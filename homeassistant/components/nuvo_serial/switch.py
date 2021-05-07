"""Support for interfacing with Nuvo multi-zone amplifier."""
import logging
from typing import Any

from homeassistant import core
from homeassistant.components.switch import SwitchEntity
from homeassistant.const import CONF_TYPE

from .const import CONF_ZONES, DOMAIN, FIRST_RUN, NUVO_OBJECT

# from typing import Any, Awaitable, Dict, Iterable, List, Optional


# from serial import SerialException


_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1


@core.callback
def _get_zones(config_entry):
    if CONF_ZONES in config_entry.options:
        data = config_entry.options
    else:
        data = config_entry.data

    return data[CONF_ZONES]


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up the Switch entities associated with each Nuvo multi-zone amplifier zone."""
    model = config_entry.data[CONF_TYPE]

    nuvo = hass.data[DOMAIN][config_entry.entry_id][NUVO_OBJECT]
    zones = _get_zones(config_entry)
    entities = []

    for zone_id, zone_name in zones.items():
        zone_id = int(zone_id)
        entities.append(
            LoudnessCompensation(nuvo, model, config_entry.entry_id, zone_id, zone_name)
        )

    # only call update before add if it's the first run so we can try to detect zones
    first_run = hass.data[DOMAIN][config_entry.entry_id][FIRST_RUN]
    async_add_entities(entities, first_run)


class LoudnessCompensation(SwitchEntity):
    """Loudness Compensation control for Nuvo amplifier zone."""

    def __init__(self, nuvo, model, namespace, zone_id, zone_name):
        """Init this entity."""
        self._nuvo = nuvo
        self._model = model
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._name = f"{self._zone_name} Loudness Compensation"
        self._namespace = namespace
        self._unique_id = f"{self._namespace}_zone_{self._zone_id}_loudcmp"
        self._loudness_compensation = None

    @property
    def value(self) -> bool:
        """Return the entity value to represent the entity state."""
        return self._loudness_compensation

    def set_value(self, value: bool) -> None:
        """Set new value."""
        self._nuvo.set_loudness_comp(self._zone_id, value)

    @property
    def is_on(self) -> bool:
        """Return True if entity is on."""
        return self._loudness_compensation

    def turn_on(self, **kwargs: Any) -> None:
        """Turn the entity on."""
        self._nuvo.set_loudness_comp(self._zone_id, True)

    def turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        self._nuvo.set_loudness_comp(self._zone_id, False)

    def update(self):
        """Retrieve latest state."""

        eq = self._nuvo.zone_eq_status(self._zone_id)
        if not eq:
            _LOGGER.error("NO EQ STATE RETURNED")
            return False

        self._loudness_compensation = eq.loudcmp
        return True

    @property
    def device_info(self):
        """Return device info for this device."""
        return {
            "identifiers": {(DOMAIN, self._namespace)},
            "name": f"{' '.join(self._model.split('_'))}",
            "manufacturer": "Nuvo",
            "model": self._model,
        }

    @property
    def unique_id(self):
        """Return unique ID for this device."""
        return self._unique_id

    @property
    def name(self):
        """Return the name of the control."""
        return self._name
