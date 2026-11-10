"""The Queensland Fuel integration."""
from __future__ import annotations

import asyncio
from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import (
    CONF_APIKEY,
    CONF_FUELTYPES,
    CONF_ORIGIN_TYPE,
    CONF_RADIUS_KM,
    CONF_SCAN_INTERVAL,
    CONF_TRACKED_ENTITY,
    CONF_ZONE_ENTITY,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DOMAIN,
)
from .coordinator import QldFuelDataCoordinator
from .origin_manager import OriginManager
from .qldfuel_api import QldFuelAPI

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.GEO_LOCATION]


def _entry_config(entry: ConfigEntry) -> dict:
    """The effective config for this entry — options override initial data."""
    return {
        CONF_ORIGIN_TYPE: entry.options.get(CONF_ORIGIN_TYPE, entry.data[CONF_ORIGIN_TYPE]),
        CONF_ZONE_ENTITY: entry.options.get(CONF_ZONE_ENTITY, entry.data.get(CONF_ZONE_ENTITY)),
        CONF_TRACKED_ENTITY: entry.options.get(
            CONF_TRACKED_ENTITY, entry.data.get(CONF_TRACKED_ENTITY)
        ),
        CONF_RADIUS_KM: entry.options.get(CONF_RADIUS_KM, entry.data[CONF_RADIUS_KM]),
        CONF_FUELTYPES: entry.options.get(CONF_FUELTYPES, entry.data[CONF_FUELTYPES]),
        CONF_SCAN_INTERVAL: entry.options.get(
            CONF_SCAN_INTERVAL, entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MINUTES)
        ),
    }


async def _async_get_shared_coordinator(
    hass: HomeAssistant, apikey: str, entry_id: str, scan_interval_minutes: float
) -> QldFuelDataCoordinator:
    """Return the coordinator for this API key, creating it on first use.

    Shared across every config entry using the same key so adding another
    tracked origin never multiplies polling against the upstream API. A
    coordinator is only published for reuse once its first refresh has
    actually succeeded — otherwise a transient failure (e.g. a DNS blip)
    would leave a permanently-empty coordinator cached, and every later
    setup retry would skip re-fetching entirely instead of trying again.

    Entries sharing a key can each request their own poll interval; the
    coordinator polls at the fastest of whatever's currently registered. A
    slower join doesn't take effect until the current interval elapses, but
    a faster join does — since it lowers the minimum immediately.
    """
    locks = hass.data[DOMAIN].setdefault("_shared_coordinator_locks", {})
    lock = locks.setdefault(apikey, asyncio.Lock())

    async with lock:
        shared = hass.data[DOMAIN].setdefault("_shared_coordinators", {})
        coordinator = shared.get(apikey)
        if coordinator is None:
            coordinator = QldFuelDataCoordinator(hass, QldFuelAPI(apikey), scan_interval_minutes)
            await coordinator.async_config_entry_first_refresh()
            shared[apikey] = coordinator

        coordinator.ref_count += 1
        coordinator.entry_intervals[entry_id] = scan_interval_minutes
        coordinator.update_interval = timedelta(
            minutes=min(coordinator.entry_intervals.values())
        )
        return coordinator


async def _async_release_shared_coordinator(
    hass: HomeAssistant, apikey: str, entry_id: str
) -> None:
    """Drop this entry's reference, shutting the coordinator down if unused."""
    shared = hass.data[DOMAIN]["_shared_coordinators"]
    coordinator = shared[apikey]
    coordinator.ref_count -= 1
    coordinator.entry_intervals.pop(entry_id, None)
    if coordinator.ref_count <= 0:
        await coordinator.async_shutdown()
        del shared[apikey]
    else:
        coordinator.update_interval = timedelta(
            minutes=min(coordinator.entry_intervals.values())
        )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Queensland Fuel from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    config = _entry_config(entry)
    coordinator = await _async_get_shared_coordinator(
        hass, entry.data[CONF_APIKEY], entry.entry_id, config[CONF_SCAN_INTERVAL]
    )

    manager = OriginManager(hass, coordinator, config)
    await manager.async_setup()

    hass.data[DOMAIN][entry.entry_id] = {"coordinator": coordinator, "manager": manager}

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        entry_data = hass.data[DOMAIN].pop(entry.entry_id)
        await entry_data["manager"].async_unload()
        await _async_release_shared_coordinator(hass, entry.data[CONF_APIKEY], entry.entry_id)

    return unload_ok
