"""Aggregate 'cheapest nearby' sensors for the Queensland Fuel integration.

One sensor per selected fuel type, reporting the lowest price currently
found among stations within radius of this entry's origin — the actual
"highlight the lowest price" feature. Station-level detail lives in the
geo_location platform instead of here.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_FUELTYPES, DOMAIN
from .origin_manager import OriginManager

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up one 'cheapest nearby' sensor per selected fuel type."""
    manager: OriginManager = hass.data[DOMAIN][entry.entry_id]["manager"]
    fueltypes = entry.options.get(CONF_FUELTYPES, entry.data[CONF_FUELTYPES])

    device_info = DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        entry_type=DeviceEntryType.SERVICE,
        name=entry.title,
    )

    async_add_entities(
        QldFuelCheapestSensor(manager, entry.entry_id, fueltype, device_info)
        for fueltype in fueltypes
    )


class QldFuelCheapestSensor(SensorEntity):
    """The lowest price for one fuel type among stations currently in radius."""

    _attr_should_poll = False
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "AUD/L"
    _attr_icon = "mdi:gas-station"

    def __init__(
        self,
        manager: OriginManager,
        entry_id: str,
        fueltype: str,
        device_info: DeviceInfo,
    ) -> None:
        self._manager = manager
        self._fueltype = fueltype
        self._attr_unique_id = f"{entry_id}_cheapest_{fueltype}"
        self._attr_name = f"Cheapest {fueltype} nearby"
        self._attr_device_info = device_info

    async def async_added_to_hass(self) -> None:
        """Subscribe to origin-manager recomputes."""
        self.async_on_remove(self._manager.async_add_listener(self._handle_update))

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    def _cheapest_station(self) -> tuple[Any, dict[str, Any]] | None:
        candidates = [
            (site_id, station)
            for site_id, station in self._manager.stations.items()
            if self._fueltype in station["prices"]
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda item: item[1]["prices"][self._fueltype]["price"])

    @property
    def native_value(self) -> float | None:
        """Return the lowest current price, or None if no station is in range."""
        cheapest = self._cheapest_station()
        if cheapest is None:
            return None
        _, station = cheapest
        return station["prices"][self._fueltype]["price"]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return details of the winning station."""
        cheapest = self._cheapest_station()
        if cheapest is None:
            return {}
        _, station = cheapest
        return {
            "name": station["name"],
            "address": station["address"],
            "brand": station["brand"],
            "distance_km": station["distance_km"],
            "latitude": station["latitude"],
            "longitude": station["longitude"],
        }
