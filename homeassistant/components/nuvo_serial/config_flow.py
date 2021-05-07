"""Config flow for Nuvo multi-zone amplifier integration."""
import logging

from nuvo_serial import get_nuvo
from nuvo_serial.const import ranges
from serial import SerialException
import voluptuous as vol

from homeassistant import config_entries, core, exceptions
from homeassistant.const import CONF_PORT, CONF_TYPE

from .const import CONF_SOURCES, CONF_ZONES
from .const import DOMAIN  # pylint:disable=unused-import

_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA = vol.Schema({vol.Required(CONF_PORT): str, vol.Required(CONF_TYPE): str})


@core.callback
def _idx_from_config(data):
    modded = {}

    for k, v in data.items():
        modded[int(k.split("_")[1])] = v.strip()

    return modded


@core.callback
def _get_source_schema(sources):
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


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Nuvo Amplifier."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    @staticmethod
    @core.callback
    def async_get_options_flow(config_entry):
        """Define the config flow to handle options."""
        return NuvoOptionsFlowHandler(config_entry)

    async def async_step_init(self, user_input=None):
        """Handle the initial step."""
        self._data = {}
        errors = {}
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

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        return await self.async_step_init(user_input)

    async def async_step_sources(self, user_input=None):
        """Handle Nuvo sources."""
        errors = {}
        if user_input is not None:
            """process sources"""
            self._data[CONF_SOURCES] = _idx_from_config(user_input)
            return await self.async_step_zones()

        try:
            sources = await self._get_nuvo_sources()
        except SerialException as err:
            _LOGGER.error("Error retrieving zone data from Nuvo controller")
            raise CannotConnect from err
        source_schema = self._get_source_schema(sources)
        return self.async_show_form(
            step_id="sources",
            data_schema=source_schema,
            errors=errors,
        )

    async def async_step_zones(self, user_input=None):
        """Handle Nuvo zones."""
        errors = {}
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

    async def _create_entry(self):
        """Create device and entities."""
        return self.async_create_entry(title=self._data[CONF_PORT], data=self._data)

    @core.callback
    def _get_source_schema(self, sources):
        """Create schema for source validation."""
        data_schema = vol.Schema(
            {
                vol.Optional(f"source_{source.source}", default=source.name): str
                for source in sources
            }
        )
        return data_schema

    @core.callback
    def _get_zone_schema(self, zones):
        """Create schema for zone validation."""
        data_schema = vol.Schema(
            {
                vol.Optional(f"zone_{zone.zone}", default=zone.name): str
                for zone in zones
            }
        )
        return data_schema

    async def _get_nuvo_sources(self):
        """Retrieve enabled sources from Nuvo."""
        source_count = ranges[self._data[CONF_TYPE]]["sources"]
        sources = []
        try:
            for source_num in range(1, source_count + 1):
                source = await self.hass.async_add_executor_job(
                    self._nuvo.source_status, source_num
                )
                if source.enabled:
                    sources.append(source)
        except SerialException as err:
            _LOGGER.error("Error retrieving source data from Nuvo controller")
            raise CannotConnect from err

        return sources

    async def _get_nuvo_zones(self):
        """Retrieve enabled zones from Nuvo."""
        zone_count = ranges[self._data[CONF_TYPE]]["zones"]["physical"]
        zones = []
        try:
            for zone_num in range(1, zone_count + 1):
                zone = await self.hass.async_add_executor_job(
                    self._nuvo.zone_configuration, zone_num
                )
                if zone.enabled:
                    zones.append(zone)
        except SerialException as err:
            _LOGGER.error("Error retrieving source data from Nuvo controller")
            raise CannotConnect from err

        return zones

    async def _async_get_nuvo(self, data):
        """Connect to the amplifier and return the handler."""
        try:
            nuvo = await self.hass.async_add_executor_job(
                get_nuvo, data[CONF_PORT], data[CONF_TYPE]
            )

        except SerialException as err:
            _LOGGER.error("Error connecting to Nuvo controller")
            raise CannotConnect from err

        return nuvo


# @core.callback
# def _key_for_source(index, source, previous_sources):
#     if str(index) in previous_sources:
#         key = vol.Optional(
#             source, description={"suggested_value": previous_sources[str(index)]}
#         )
#     else:
#         key = vol.Optional(source)

#     return key


class NuvoOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle a Nuvo options flow."""

    def __init__(self, config_entry):
        """Initialize."""
        self.config_entry = config_entry

    @core.callback
    def _previous_sources(self):
        """Get current sources."""
        if CONF_SOURCES in self.config_entry.options:
            previous = self.config_entry.options[CONF_SOURCES]
        else:
            previous = self.config_entry.data[CONF_SOURCES]

        return previous

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(
                title="", data={CONF_SOURCES: _idx_from_config(user_input)}
            )

        previous_sources = self._previous_sources()

        source_schema = _get_source_schema(previous_sources)

        return self.async_show_form(step_id="init", data_schema=source_schema)

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


class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""
