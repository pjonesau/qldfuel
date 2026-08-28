"""Geolocation entities for fuel stations within radius of an origin.

Entities are created/updated/removed dynamically as OriginManager recomputes
which stations are in range (following the same add/update/remove-via-
dispatcher pattern HA core uses for other radius-bound feeds, e.g.
usgs_earthquakes_feed), rather than being created once at startup.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.geo_location import GeolocationEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfLength
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SIGNAL_DELETE_STATION, SIGNAL_UPDATE_STATION
from .origin_manager import OriginManager

_LOGGER = logging.getLogger(__name__)

SOURCE = DOMAIN


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the geolocation platform for a config entry."""
    manager: OriginManager = hass.data[DOMAIN][entry.entry_id]["manager"]
    station_manager = QldFuelStationEntityManager(hass, entry, manager, async_add_entities)
    station_manager.async_setup()


class QldFuelStationEntityManager:
    """Diffs OriginManager.stations against the entities currently shown."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        manager: OriginManager,
        async_add_entities: AddEntitiesCallback,
    ) -> None:
        self._hass = hass
        self._entry = entry
        self._manager = manager
        self._async_add_entities = async_add_entities
        self._known_site_ids: set[Any] = set()

    def async_setup(self) -> None:
        """Connect to the origin manager and create the initial entities."""
        self._entry.async_on_unload(self._manager.async_add_listener(self._handle_update))
        self._handle_update()

    @callback
    def _handle_update(self) -> None:
        current_ids = set(self._manager.stations)
        new_ids = current_ids - self._known_site_ids
        stale_ids = self._known_site_ids - current_ids
        existing_ids = current_ids & self._known_site_ids

        if new_ids:
            self._async_add_entities(
                QldFuelStationEvent(self._manager, self._entry.entry_id, site_id)
                for site_id in new_ids
            )
        for site_id in existing_ids:
            async_dispatcher_send(
                self._hass, SIGNAL_UPDATE_STATION.format(self._entry.entry_id, site_id)
            )
        for site_id in stale_ids:
            async_dispatcher_send(
                self._hass, SIGNAL_DELETE_STATION.format(self._entry.entry_id, site_id)
            )

        self._known_site_ids = current_ids


class QldFuelStationEvent(GeolocationEvent):
    """A single fuel station currently within radius of the configured origin."""

    _attr_should_poll = False
    _attr_source = SOURCE
    _attr_unit_of_measurement = UnitOfLength.KILOMETERS
    _attr_icon = "mdi:gas-station"

    def __init__(self, manager: OriginManager, entry_id: str, site_id: Any) -> None:
        self._manager = manager
        self._entry_id = entry_id
        self._site_id = site_id
        self._attr_unique_id = f"{entry_id}_{site_id}"
        self._update_from_station()

    async def async_added_to_hass(self) -> None:
        """Subscribe to this station's update/delete signals."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_UPDATE_STATION.format(self._entry_id, self._site_id),
                self._handle_update,
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_DELETE_STATION.format(self._entry_id, self._site_id),
                self._handle_delete,
            )
        )

    @callback
    def _handle_update(self) -> None:
        self._update_from_station()
        self.async_write_ha_state()

    @callback
    def _handle_delete(self) -> None:
        self.hass.async_create_task(self.async_remove(force_remove=True))

    def _update_from_station(self) -> None:
        station = self._manager.stations.get(self._site_id)
        if station is None:
            return
        prices = {fuel: price["price"] for fuel, price in station["prices"].items()}
        cheapest_fuel = min(prices, key=prices.get)

        self._attr_name = station["name"]
        self._attr_distance = station["distance_km"]
        self._attr_latitude = station["latitude"]
        self._attr_longitude = station["longitude"]
        self._attr_extra_state_attributes = {
            "address": station["address"],
            "brand": station["brand"],
            "postcode": station["postcode"],
            "prices": prices,
            "cheapest_fuel": cheapest_fuel,
            "cheapest_price": prices[cheapest_fuel],
        }
