"""Config flow for the Queensland Fuel integration."""
from __future__ import annotations

import hashlib
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .const import (
    CONF_APIKEY,
    CONF_FUELTYPES,
    CONF_ORIGIN_TYPE,
    CONF_RADIUS_KM,
    CONF_TRACKED_ENTITY,
    CONF_ZONE_ENTITY,
    DEFAULT_RADIUS_KM,
    DOMAIN,
    ORIGIN_TYPE_TRACKED,
    ORIGIN_TYPE_ZONE,
)
from .qldfuel_api import ApiAuthError, ApiError, QldFuelAPI

_LOGGER = logging.getLogger(__name__)


def _user_schema(default_apikey: str | None) -> vol.Schema:
    return vol.Schema(
        {vol.Required(CONF_APIKEY, default=default_apikey or vol.UNDEFINED): str}
    )


def _radius_field(default: float) -> dict[vol.Marker, NumberSelector]:
    return {
        vol.Required(CONF_RADIUS_KM, default=default): NumberSelector(
            NumberSelectorConfig(
                min=1, max=100, step=1, mode=NumberSelectorMode.BOX, unit_of_measurement="km"
            )
        )
    }


def _zone_schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_ZONE_ENTITY, default=defaults.get(CONF_ZONE_ENTITY, vol.UNDEFINED)
            ): EntitySelector(EntitySelectorConfig(filter={"domain": "zone"})),
            **_radius_field(defaults.get(CONF_RADIUS_KM, DEFAULT_RADIUS_KM)),
        }
    )


def _tracked_schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_TRACKED_ENTITY, default=defaults.get(CONF_TRACKED_ENTITY, vol.UNDEFINED)
            ): EntitySelector(
                EntitySelectorConfig(filter={"domain": ["device_tracker", "person"]})
            ),
            **_radius_field(defaults.get(CONF_RADIUS_KM, DEFAULT_RADIUS_KM)),
        }
    )


def _fueltype_schema(fuelnames: list[str], defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_FUELTYPES, default=defaults.get(CONF_FUELTYPES, [])
            ): cv.multi_select(fuelnames)
        }
    )


async def _validate_api_key(hass: HomeAssistant, apikey: str) -> QldFuelAPI:
    """Check the API key works and return a client with fuel types loaded."""
    api = QldFuelAPI(apikey)
    try:
        await hass.async_add_executor_job(api.refresh_fueltype)
    except ApiAuthError as err:
        raise InvalidAuth from err
    except ApiError as err:
        raise CannotConnect from err
    return api


class QldFuelConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Queensland Fuel Prices."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._api: QldFuelAPI | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle API key entry."""
        existing_entries = self.hass.config_entries.async_entries(DOMAIN)
        default_apikey = existing_entries[0].data[CONF_APIKEY] if existing_entries else None

        if user_input is None:
            return self.async_show_form(
                step_id="user", data_schema=_user_schema(default_apikey)
            )

        errors: dict[str, str] = {}
        try:
            self._api = await _validate_api_key(self.hass, user_input[CONF_APIKEY])
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidAuth:
            errors["base"] = "invalid_auth"
        except Exception:
            _LOGGER.exception("Unexpected exception validating API key")
            errors["base"] = "unknown"

        if errors:
            return self.async_show_form(
                step_id="user", data_schema=_user_schema(default_apikey), errors=errors
            )

        self._data[CONF_APIKEY] = user_input[CONF_APIKEY]
        return await self.async_step_origin()

    async def async_step_origin(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Choose what the radius is measured from."""
        return self.async_show_menu(step_id="origin", menu_options=["origin_zone", "origin_tracked"])

    async def async_step_origin_zone(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Configure a fixed-zone origin."""
        if user_input is None:
            return self.async_show_form(
                step_id="origin_zone", data_schema=_zone_schema(self._data)
            )
        return await self._finish_origin(
            ORIGIN_TYPE_ZONE, user_input[CONF_ZONE_ENTITY], user_input[CONF_RADIUS_KM]
        )

    async def async_step_origin_tracked(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure a tracked-entity origin."""
        if user_input is None:
            return self.async_show_form(
                step_id="origin_tracked", data_schema=_tracked_schema(self._data)
            )
        return await self._finish_origin(
            ORIGIN_TYPE_TRACKED, user_input[CONF_TRACKED_ENTITY], user_input[CONF_RADIUS_KM]
        )

    async def _finish_origin(
        self, origin_type: str, entity_id: str, radius_km: float
    ) -> FlowResult:
        """Record the chosen origin, enforce uniqueness, and move on."""
        self._data[CONF_ORIGIN_TYPE] = origin_type
        self._data[CONF_ZONE_ENTITY] = entity_id if origin_type == ORIGIN_TYPE_ZONE else None
        self._data[CONF_TRACKED_ENTITY] = (
            entity_id if origin_type == ORIGIN_TYPE_TRACKED else None
        )
        self._data[CONF_RADIUS_KM] = radius_km

        # Fingerprint rather than embed the raw API key, so it isn't carried
        # into unique_id (which isn't covered by the usual data[] redaction
        # if diagnostics support is ever added).
        key_fingerprint = hashlib.sha256(self._data[CONF_APIKEY].encode()).hexdigest()[:12]
        await self.async_set_unique_id(f"{key_fingerprint}:{entity_id}")
        self._abort_if_unique_id_configured()

        return await self.async_step_fueltype()

    async def async_step_fueltype(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Choose which fuel types to track."""
        fuelnames = sorted(set(self._api.get_fueltype().values()))

        if user_input is None:
            return self.async_show_form(
                step_id="fueltype", data_schema=_fueltype_schema(fuelnames, self._data)
            )

        self._data[CONF_FUELTYPES] = user_input[CONF_FUELTYPES]
        return self.async_create_entry(title="Queensland Fuel Prices", data=self._data)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> QldFuelOptionsFlow:
        return QldFuelOptionsFlow()


class QldFuelOptionsFlow(config_entries.OptionsFlow):
    """Edit radius, origin and fuel types without recreating the entry."""

    def __init__(self) -> None:
        self._options: dict[str, Any] = {}

    @property
    def _current(self) -> dict[str, Any]:
        return {**self.config_entry.data, **self.config_entry.options}

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Edit the origin and radius."""
        return self.async_show_menu(step_id="init", menu_options=["origin_zone", "origin_tracked"])

    async def async_step_origin_zone(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Configure a fixed-zone origin."""
        if user_input is None:
            return self.async_show_form(
                step_id="origin_zone", data_schema=_zone_schema(self._current)
            )
        self._options = {
            CONF_ORIGIN_TYPE: ORIGIN_TYPE_ZONE,
            CONF_ZONE_ENTITY: user_input[CONF_ZONE_ENTITY],
            CONF_TRACKED_ENTITY: None,
            CONF_RADIUS_KM: user_input[CONF_RADIUS_KM],
        }
        return await self.async_step_fueltype()

    async def async_step_origin_tracked(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure a tracked-entity origin."""
        if user_input is None:
            return self.async_show_form(
                step_id="origin_tracked", data_schema=_tracked_schema(self._current)
            )
        self._options = {
            CONF_ORIGIN_TYPE: ORIGIN_TYPE_TRACKED,
            CONF_ZONE_ENTITY: None,
            CONF_TRACKED_ENTITY: user_input[CONF_TRACKED_ENTITY],
            CONF_RADIUS_KM: user_input[CONF_RADIUS_KM],
        }
        return await self.async_step_fueltype()

    async def async_step_fueltype(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Edit which fuel types to track."""
        # Read from the already-polled shared coordinator instead of firing
        # another request — its API client's fuel-type lookup is refreshed
        # on every poll cycle regardless of how many entries share it.
        coordinator = self.hass.data[DOMAIN][self.config_entry.entry_id]["coordinator"]
        fuelnames = sorted(set(coordinator.api.get_fueltype().values()))
        if not fuelnames:
            fuelnames = self._current[CONF_FUELTYPES]

        if user_input is None:
            return self.async_show_form(
                step_id="fueltype",
                data_schema=_fueltype_schema(fuelnames, self._current),
            )

        self._options[CONF_FUELTYPES] = user_input[CONF_FUELTYPES]
        return self.async_create_entry(title="", data=self._options)


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate the API key was rejected."""
