"""The Nuvo multi-zone amplifier integration."""
import asyncio
import logging

from nuvo_serial import get_nuvo
from serial import SerialException

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PORT, CONF_TYPE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import (
    CONF_NOT_FIRST_RUN,
    DOMAIN,
    FIRST_RUN,
    NUVO_OBJECT,
    UNDO_UPDATE_LISTENER,
)

PLATFORMS = ["media_player", "number"]

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the Nuvo multi-zone amplifier component."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up Nuvo multi-zone amplifier from a config entry."""
    # port = entry.data[CONF_PORT]
    port = entry.options.get(CONF_PORT, entry.data[CONF_PORT])
    model = entry.data[CONF_TYPE]

    try:
        nuvo = await hass.async_add_executor_job(get_nuvo, port, model)
    except SerialException as err:
        _LOGGER.error("Error connecting to Nuvo controller at %s", port)
        raise ConfigEntryNotReady from err

    # hass.async_create_task(
    #     hass.config_entries.flow.async_init(
    #         DOMAIN,
    #         context={"source": SOURCE_REAUTH},
    #         data=entry.data,
    #     )
    # )

    # double negative to handle absence of value
    first_run = not bool(entry.data.get(CONF_NOT_FIRST_RUN))

    if first_run:
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_NOT_FIRST_RUN: True}
        )

    undo_listener = entry.add_update_listener(_update_listener)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        NUVO_OBJECT: nuvo,
        UNDO_UPDATE_LISTENER: undo_listener,
        FIRST_RUN: first_run,
    }

    for component in PLATFORMS:
        hass.async_create_task(
            hass.config_entries.async_forward_entry_setup(entry, component)
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    unload_ok = all(
        await asyncio.gather(
            *[
                hass.config_entries.async_forward_entry_unload(entry, component)
                for component in PLATFORMS
            ]
        )
    )

    if unload_ok:
        hass.data[DOMAIN][entry.entry_id][UNDO_UPDATE_LISTENER]()
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def _update_listener(hass: HomeAssistant, entry: ConfigEntry):
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)
