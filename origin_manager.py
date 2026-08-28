"""Per-config-entry origin tracking.

Filters the shared coordinator's statewide station data down to whatever is
within radius of a configurable origin — either a fixed HA zone or a tracked
entity such as a phone's device_tracker. Recomputes both when the shared
price data refreshes and when the tracked entity moves, ignoring movement
smaller than MOVEMENT_THRESHOLD_KM so GPS jitter doesn't churn entities.
"""
from __future__ import annotations

from collections.abc import Callable
import logging
from math import asin, cos, radians, sin, sqrt
from typing import Any

from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    CONF_FUELTYPES,
    CONF_ORIGIN_TYPE,
    CONF_RADIUS_KM,
    CONF_TRACKED_ENTITY,
    CONF_ZONE_ENTITY,
    MOVEMENT_THRESHOLD_KM,
    ORIGIN_TYPE_TRACKED,
)
from .coordinator import QldFuelDataCoordinator

_LOGGER = logging.getLogger(__name__)

EARTH_RADIUS_KM = 6371


def haversine_km(origin: tuple[float, float], point: tuple[float, float]) -> float:
    """Great-circle distance between two lat/long points, in kilometres."""
    lat1, lon1 = radians(origin[0]), radians(origin[1])
    lat2, lon2 = radians(point[0]), radians(point[1])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * asin(sqrt(a))


class OriginManager:
    """Maintains the set of stations currently within radius of one origin."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: QldFuelDataCoordinator,
        config: dict[str, Any],
    ) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self._config = config
        self.stations: dict[Any, dict[str, Any]] = {}
        self._origin: tuple[float, float] | None = None
        self._listeners: list[Callable[[], None]] = []
        self._unsub_coordinator: Callable[[], None] | None = None
        self._unsub_track_entity: Callable[[], None] | None = None

    def async_add_listener(self, update_callback: Callable[[], None]) -> Callable[[], None]:
        """Register a callback fired whenever `stations` is recomputed."""
        self._listeners.append(update_callback)

        def remove_listener() -> None:
            self._listeners.remove(update_callback)

        return remove_listener

    async def async_setup(self) -> None:
        """Register data sources and compute the initial station set."""
        self._unsub_coordinator = self.coordinator.async_add_listener(
            self._handle_coordinator_update
        )
        if self._config[CONF_ORIGIN_TYPE] == ORIGIN_TYPE_TRACKED:
            self._unsub_track_entity = async_track_state_change_event(
                self.hass,
                [self._config[CONF_TRACKED_ENTITY]],
                self._handle_entity_moved,
            )
        self._recompute(force=True)

    async def async_unload(self) -> None:
        """Cancel everything this manager registered."""
        if self._unsub_coordinator is not None:
            self._unsub_coordinator()
        if self._unsub_track_entity is not None:
            self._unsub_track_entity()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._recompute(force=False)

    @callback
    def _handle_entity_moved(self, event: Event[EventStateChangedData]) -> None:
        self._recompute(force=False)

    def _origin_entity_id(self) -> str:
        if self._config[CONF_ORIGIN_TYPE] == ORIGIN_TYPE_TRACKED:
            return self._config[CONF_TRACKED_ENTITY]
        return self._config[CONF_ZONE_ENTITY]

    def _get_origin_coords(self) -> tuple[float, float] | None:
        state = self.hass.states.get(self._origin_entity_id())
        if state is None:
            return None
        latitude = state.attributes.get("latitude")
        longitude = state.attributes.get("longitude")
        if latitude is None or longitude is None:
            return None
        return (latitude, longitude)

    def _recompute(self, *, force: bool) -> None:
        new_origin = self._get_origin_coords()
        if new_origin is None:
            _LOGGER.debug(
                "Origin %s has no known position, keeping last known stations",
                self._origin_entity_id(),
            )
            return

        if not force and self._origin is not None:
            if haversine_km(self._origin, new_origin) < MOVEMENT_THRESHOLD_KM:
                return

        self._origin = new_origin
        radius_km = self._config[CONF_RADIUS_KM]
        wanted_fueltypes = set(self._config[CONF_FUELTYPES])

        all_sites = self.coordinator.data["sites"] if self.coordinator.data else {}
        stations: dict[Any, dict[str, Any]] = {}
        for site_id, site in all_sites.items():
            prices = {
                fuel: price
                for fuel, price in site["prices"].items()
                if fuel in wanted_fueltypes
            }
            if not prices:
                continue

            distance = haversine_km(new_origin, (site["latitude"], site["longitude"]))
            if distance > radius_km:
                continue

            stations[site_id] = {**site, "prices": prices, "distance_km": round(distance, 1)}

        self.stations = stations
        for update_callback in list(self._listeners):
            update_callback()
