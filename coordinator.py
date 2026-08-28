"""Shared price/site data coordinator.

One instance is created per API key and reused across every config entry
that shares that key (e.g. one entry per tracked phone), so adding another
origin never multiplies polling against the upstream API. Lifecycle is
managed in __init__.py via reference counting.
"""
from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import SCAN_INTERVAL
from .qldfuel_api import ApiAuthError, ApiError, QldFuelAPI

_LOGGER = logging.getLogger(__name__)


class QldFuelDataCoordinator(DataUpdateCoordinator):
    """Fetches the statewide fuel price/site dataset, shared by API key."""

    def __init__(self, hass: HomeAssistant, api: QldFuelAPI) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="Queensland Fuel Price Coordinator",
            update_interval=timedelta(seconds=SCAN_INTERVAL),
        )
        self.api = api
        self.ref_count = 0

    async def _async_update_data(self) -> dict:
        try:
            await self.hass.async_add_executor_job(self.api.refresh_data)
        except ApiAuthError as err:
            raise ConfigEntryAuthFailed from err
        except ApiError as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err

        return self.api.get_data()
