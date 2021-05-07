"""Support for interfacing with Nuvo multi-zone amplifier."""
import logging

from nuvo_serial.const import ranges

from homeassistant import core
from homeassistant.components.number import NumberEntity
from homeassistant.const import CONF_TYPE

from .const import CONF_ZONES, DOMAIN, FIRST_RUN, NUVO_OBJECT

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
    """Set up the Number entities associated with each Nuvo multi-zone amplifier zone."""
    model = config_entry.data[CONF_TYPE]

    nuvo = hass.data[DOMAIN][config_entry.entry_id][NUVO_OBJECT]
    zones = _get_zones(config_entry)
    entities = []

    for zone_id, zone_name in zones.items():
        zone_id = int(zone_id)
        entities.append(Bass(nuvo, model, config_entry.entry_id, zone_id, zone_name))
        entities.append(Treble(nuvo, model, config_entry.entry_id, zone_id, zone_name))
        entities.append(Balance(nuvo, model, config_entry.entry_id, zone_id, zone_name))

    # only call update before add if it's the first run so we can try to detect zones
    first_run = hass.data[DOMAIN][config_entry.entry_id][FIRST_RUN]
    async_add_entities(entities, first_run)


class Bass(NumberEntity):
    """Bass control for Nuvo amplifier zone."""

    def __init__(self, nuvo, model, namespace, zone_id, zone_name):
        """Init this entity."""
        self._nuvo = nuvo
        self._model = model
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._name = f"{self._zone_name} Bass"
        self._namespace = namespace
        self._unique_id = f"{self._namespace}_zone{self._zone_id}_bass"
        self._bass = None

    @property
    def min_value(self) -> float:
        """Return the minimum value."""
        return ranges[self._model]["bass"]["min"]

    @property
    def max_value(self) -> float:
        """Return the maximum value."""
        return ranges[self._model]["bass"]["max"]

    @property
    def step(self) -> float:
        """Return the increment/decrement step."""
        return ranges[self._model]["bass"]["step"]

    @property
    def value(self) -> float:
        """Return the entity value to represent the entity state."""
        return self._bass

    def set_value(self, value: float) -> None:
        """Set new value."""
        self._nuvo.set_bass(self._zone_id, int(value))

    def update(self):
        """Retrieve latest state."""

        eq = self._nuvo.zone_eq_status(self._zone_id)
        if not eq:
            _LOGGER.error("NO EQ STATE RETURNED")
            return False

        self._bass = float(eq.bass)
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
        """Return the name of the bass number."""
        return self._name


class Treble(NumberEntity):
    """Treble control for Nuvo amplifier zone."""

    def __init__(self, nuvo, model, namespace, zone_id, zone_name):
        """Init this entity."""
        self._nuvo = nuvo
        self._model = model
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._name = f"{self._zone_name} Treble"
        self._namespace = namespace
        self._unique_id = f"{self._namespace}_zone{self._zone_id}_treble"
        self._treble = None

    @property
    def min_value(self) -> float:
        """Return the minimum value."""
        return ranges[self._model]["treble"]["min"]

    @property
    def max_value(self) -> float:
        """Return the maximum value."""
        return ranges[self._model]["treble"]["max"]

    @property
    def step(self) -> float:
        """Return the increment/decrement step."""
        return ranges[self._model]["treble"]["step"]

    @property
    def value(self) -> float:
        """Return the entity value to represent the entity state."""
        return self._treble

    def set_value(self, value: float) -> None:
        """Set new value."""
        self._nuvo.set_treble(self._zone_id, int(value))

    def update(self):
        """Retrieve latest state."""

        eq = self._nuvo.zone_eq_status(self._zone_id)
        if not eq:
            _LOGGER.error("NO EQ STATE RETURNED")
            return False

        self._treble = float(eq.treble)
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
        """Return the name of the bass number."""
        return self._name


class Balance(NumberEntity):
    """Balance control for Nuvo amplifier zone."""

    def __init__(self, nuvo, model, namespace, zone_id, zone_name):
        """Init this entity."""
        self._nuvo = nuvo
        self._model = model
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._name = f"{self._zone_name} Balance"
        self._namespace = namespace
        self._unique_id = f"{self._namespace}_zone{self._zone_id}_balance"
        self._balance = None

    @property
    def min_value(self) -> float:
        """Return the minimum value."""
        max = ranges[self._model]["balance"]["max"]
        return -max

    @property
    def max_value(self) -> float:
        """Return the maximum value."""
        return ranges[self._model]["balance"]["max"]

    @property
    def step(self) -> float:
        """Return the increment/decrement step."""
        return ranges[self._model]["balance"]["step"]

    @property
    def value(self) -> float:
        """Return the entity value to represent the entity state."""
        return self._balance

    def set_value(self, value: float) -> None:
        """Set new value."""
        balance_position = "C"

        if value < 0:
            balance_position = "L"
            value = -value
        elif value > 0:
            balance_position = "R"

        self._nuvo.set_balance(self._zone_id, balance_position, int(value))

    def update(self):
        """Retrieve latest state."""

        eq = self._nuvo.zone_eq_status(self._zone_id)
        balance_value = None
        if not eq:
            _LOGGER.error("NO EQ STATE RETURNED")
            return False
        if eq.balance_position == "L":
            balance_value = -eq.balance_value
        else:
            balance_value = eq.balance_value

        self._balance = float(balance_value)
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
        """Return the name of the bass number."""
        return self._name
