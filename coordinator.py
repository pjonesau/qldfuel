"""Shared price/site data coordinator.

One instance is created per API key and reused across every config entry
that shares that key (e.g. one entry per tracked phone), so adding another
origin never multiplies polling against the upstream API. Lifecycle is
managed in __init__.py via reference counting, so the coordinator is
deliberately not bound to any one config entry: HA shuts an entry-bound
coordinator down when that entry unloads, which would stop polling for every
other entry still sharing it.
"""
from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .qldfuel_api import ApiAuthError, ApiError, QldFuelAPI

_LOGGER = logging.getLogger(__name__)


class QldFuelDataCoordinator(DataUpdateCoordinator):
    """Fetches the statewide fuel price/site dataset, shared by API key."""

    def __init__(self, hass: HomeAssistant, api: QldFuelAPI, update_interval_minutes: float) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=None,
            name="Queensland Fuel Price Coordinator",
            update_interval=timedelta(minutes=update_interval_minutes),
        )
        self.api = api
        self.ref_count = 0
        # entry_id -> that entry's requested poll interval (minutes). The
        # coordinator's actual update_interval tracks the fastest of these —
        # see _async_get_shared_coordinator in __init__.py.
        self.entry_intervals: dict[str, float] = {}

    async def _async_update_data(self) -> dict:
        try:
            await self.hass.async_add_executor_job(self.api.refresh_data)
        except ApiAuthError as err:
            # UpdateFailed rather than ConfigEntryAuthFailed: HA returns early
            # on the latter without notifying listeners, which would leave
            # entities showing stale prices as available. Reauth is started
            # here since HA can't start it for an unbound coordinator.
            self._async_start_reauth()
            raise UpdateFailed(f"API key rejected: {err}") from err
        except ApiError as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err

        return self.api.get_data()

    @callback
    def _async_start_reauth(self) -> None:
        """Ask for a new API key on behalf of every entry sharing this one.

        Not being bound to a config entry, the coordinator can't rely on HA
        to start reauth. One flow is enough: completing it updates every
        entry that uses the rejected key (see config_flow.py).
        """
        for entry_id in self.entry_intervals:
            entry = self.hass.config_entries.async_get_entry(entry_id)
            if entry is not None:
                entry.async_start_reauth(self.hass)
                return
