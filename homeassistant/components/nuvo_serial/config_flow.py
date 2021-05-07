"""Config flow for Nuvo multi-zone amplifier integration."""
from __future__ import annotations

import logging
from typing import Any

from nuvo_serial import get_nuvo_async
from nuvo_serial.const import ranges
from nuvo_serial.grand_concerto_essentia_g import (
    NuvoAsync,
    SourceConfiguration,
    ZoneConfiguration,
)
from serial import SerialException
import voluptuous as vol

from homeassistant.config_entries import (
    CONN_CLASS_LOCAL_POLL,
    ConfigEntry,
    ConfigFlow,
    OptionsFlow,
)
from homeassistant.const import CONF_PORT, CONF_TYPE
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError

from .const import CONF_SOURCES, CONF_ZONES
from .const import DOMAIN  # pylint:disable=unused-import

_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA = vol.Schema({vol.Required(CONF_PORT): str, vol.Required(CONF_TYPE): str})
# PORT_SCHEMA = vol.Schema({vol.Required(CONF_PORT): str})


@callback
def _idx_from_config(data: dict[str, str]) -> dict[int, str]:
    """Cleanse input from user."""
    modded = {}

    for k, v in data.items():
        modded[int(k.split("_")[1])] = v.strip()

    return modded


@callback
def _get_source_schema(
    sources: dict[str, str] | list[SourceConfiguration]
) -> vol.Schema:
    """Create schema for source validation."""
    if isinstance(sources, dict):
        data_schema = vol.Schema(
            {
                vol.Optional(f"source_{source}", default=name): str
                for source, name in sources.items()
            }
        )
    else:
        data_schema = vol.Schema(
            {
                vol.Optional(f"source_{source.source}", default=source.name): str
                for source in sources
            }
        )
    return data_schema


class NuvoConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Nuvo Amplifier."""

    VERSION = 1
    CONNECTION_CLASS = CONN_CLASS_LOCAL_POLL

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> NuvoOptionsFlowHandler:
        """Define the config flow to handle options."""
        return NuvoOptionsFlowHandler(config_entry)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Handle the initial step."""

        self._data: dict[str, Any] = {}
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                self._nuvo = await self._async_get_nuvo(user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

            self._data[CONF_PORT] = user_input[CONF_PORT]
            self._data[CONF_TYPE] = user_input[CONF_TYPE]
            return await self.async_step_sources()

        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Handle the initial step."""
        return await self.async_step_init(user_input)

    async def async_step_sources(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Handle Nuvo sources."""

        errors: dict[str, str] = {}

        if user_input is not None:
            """process sources"""
            self._data[CONF_SOURCES] = _idx_from_config(user_input)
            return await self.async_step_zones()

        try:
            sources = await self._get_nuvo_sources()
        except SerialException as err:
            _LOGGER.error("Error retrieving zone data from Nuvo controller")
            raise CannotConnect from err
        source_schema = _get_source_schema(sources)
        return self.async_show_form(
            step_id="sources",
            data_schema=source_schema,
            errors=errors,
        )

    async def async_step_zones(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Handle Nuvo zones."""

        errors: dict[str, str] = {}

        if user_input is not None:
            """process zones"""
            self._data[CONF_ZONES] = _idx_from_config(user_input)
            return await self._create_entry()

        zones = await self._get_nuvo_zones()
        zone_schema = self._get_zone_schema(zones)
        return self.async_show_form(
            step_id="zones",
            data_schema=zone_schema,
            errors=errors,
        )

    async def _create_entry(self) -> dict[str, Any]:
        """Create device and entities."""
        await self._nuvo.disconnect()
        self._nuvo = None
        title = " ".join(self._data[CONF_TYPE].split("_"))
        return self.async_create_entry(title=title, data=self._data)

    # @callback
    # def _get_source_schema(self, sources):
    #     """Create schema for source validation."""
    #     data_schema = vol.Schema(
    #         {
    #             vol.Optional(f"source_{source.source}", default=source.name): str
    #             for source in sources
    #         }
    #     )
    #     return data_schema

    @callback
    def _get_zone_schema(self, zones: list[ZoneConfiguration]) -> vol.Schema:
        """Create schema for zone validation."""
        data_schema = vol.Schema(
            {
                vol.Optional(f"zone_{zone.zone}", default=zone.name): str
                for zone in zones
            }
        )
        return data_schema

    async def _get_nuvo_sources(self) -> list[SourceConfiguration]:
        """Retrieve enabled sources from Nuvo."""
        source_count = ranges[self._data[CONF_TYPE]]["sources"]
        sources = []
        try:
            for source_num in range(1, source_count + 1):
                source = await self._nuvo.source_status(source_num)
                if source.enabled:
                    sources.append(source)
        except SerialException as err:
            _LOGGER.error("Error retrieving source data from Nuvo controller")
            raise CannotConnect from err

        return sources

    async def _get_nuvo_zones(self) -> list[ZoneConfiguration]:
        """Retrieve enabled zones from Nuvo."""
        zone_count = ranges[self._data[CONF_TYPE]]["zones"]["physical"]
        zones = []
        try:
            for zone_num in range(1, zone_count + 1):
                zone = await self._nuvo.zone_configuration(zone_num)
                if zone.enabled:
                    zones.append(zone)
        except SerialException as err:
            _LOGGER.error("Error retrieving source data from Nuvo controller")
            raise CannotConnect from err

        return zones

    async def _async_get_nuvo(self, data: dict[str, str]) -> NuvoAsync:
        """: dict[str, str]Connect to the amplifier and return the handler."""
        try:
            nuvo = await get_nuvo_async(data[CONF_PORT], data[CONF_TYPE])
        except SerialException as err:
            _LOGGER.error("Error connecting to Nuvo controller")
            raise CannotConnect from err

        return nuvo


class NuvoOptionsFlowHandler(OptionsFlow):
    """Handle a Nuvo options flow."""

    def __init__(self, config_entry: ConfigEntry):
        """Initialize."""
        self.config_entry = config_entry
        self._data: dict[str, Any] = {}
        self._port_changed = False

    @callback
    def _previous_sources(self) -> dict[str, str]:
        """Get current sources."""
        previous: dict[str, str]
        if CONF_SOURCES in self.config_entry.options:
            previous = self.config_entry.options[CONF_SOURCES]
        else:
            previous = self.config_entry.data[CONF_SOURCES]

        return previous

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Manage the options."""
        return await self.async_step_port()

    async def async_step_port(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Handle serial port change."""

        current_port = self.config_entry.data[CONF_PORT]
        errors: dict[str, str] = {}

        if user_input is not None:
            _LOGGER.debug(user_input[CONF_PORT])
            if user_input[CONF_PORT] != current_port:
                self._port_changed = True
            self._data[CONF_PORT] = user_input[CONF_PORT]
            return await self.async_step_sources()

        schema = vol.Schema({vol.Required(CONF_PORT, default=current_port): str})
        return self.async_show_form(step_id="port", data_schema=schema, errors=errors)

    async def async_step_sources(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Handle Source changes."""
        if user_input is not None:
            _LOGGER.debug("in aync_step_source abt to async_create_entry")
            _LOGGER.debug(self._data[CONF_PORT])
            self._data[CONF_SOURCES] = _idx_from_config(user_input)
            return self.async_create_entry(title="", data=self._data)

        # return await self.async_step_port()
        previous_sources = self._previous_sources()
        source_schema = _get_source_schema(previous_sources)
        return self.async_show_form(step_id="sources", data_schema=source_schema)

    # async def _get_nuvo_sources(self):
    #     model = self.config_entry.data[CONF_TYPE]
    #     nuvo = self.hass.data[DOMAIN][self.config_entry.entry_id][NUVO_OBJECT]
    #     source_count = ranges[model]["sources"]
    #     sources = []
    #     try:
    #         for source_num in range(1, source_count + 1):
    #             source = await self.hass.async_add_executor_job(
    #                 nuvo.source_status, source_num
    #             )
    #             if source.enabled:
    #                 sources.append(source)
    #     except SerialException as err:
    #         _LOGGER.error("Error retrieving source data from Nuvo controller")
    #         raise CannotConnect from err

    #     return sources


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""
