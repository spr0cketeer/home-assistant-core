"""Support for interfacing with Nuvo multi-zone amplifier."""
from __future__ import annotations

import logging
from typing import Any, Callable, Iterable

from nuvo_serial.configuration import config
from nuvo_serial.const import (
    SOURCE_CONFIGURATION,
    ZONE_EQ_STATUS,
    ZONE_VOLUME_CONFIGURATION,
)

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_TYPE
from homeassistant.helpers.entity import DeviceInfo, Entity
from homeassistant.helpers.typing import HomeAssistantType

from .const import (
    CONTROL_EQ_BALANCE,
    CONTROL_EQ_BASS,
    CONTROL_EQ_TREBLE,
    CONTROL_SOURCE_GAIN,
    CONTROL_VOLUME,
    CONTROL_VOLUME_INI,
    CONTROL_VOLUME_MAX,
    CONTROL_VOLUME_PAGE,
    CONTROL_VOLUME_PARTY,
    DOMAIN,
    NUVO_OBJECT,
    SOURCE,
    ZONE,
)
from .helpers import get_sources, get_zones
from .nuvo_control import NuvoControl

_LOGGER = logging.getLogger(__name__)

VOLUME_CONTROLS = [
    CONTROL_VOLUME_MAX,
    CONTROL_VOLUME_INI,
    CONTROL_VOLUME_PAGE,
    CONTROL_VOLUME_PARTY,
]


async def async_setup_entry(
    hass: HomeAssistantType,
    config_entry: ConfigEntry,
    async_add_entities: Callable[[Iterable[Entity], bool], None],
) -> None:
    """Set up the Number entities associated with each Nuvo multi-zone amplifier zone."""

    model = config_entry.data[CONF_TYPE]
    nuvo = hass.data[DOMAIN][config_entry.entry_id][NUVO_OBJECT]
    zones = get_zones(config_entry)
    sources = get_sources(config_entry)[0]
    entities: list[Entity] = []

    for zone_id, zone_name in zones.items():
        z_id = int(zone_id)
        entities.append(
            Bass(
                nuvo,
                model,
                config_entry.entry_id,
                z_id,
                ZONE,
                zone_name,
                CONTROL_EQ_BASS,
                CONTROL_EQ_BASS,
                ZONE_EQ_STATUS,
            )
        )
        entities.append(
            Treble(
                nuvo,
                model,
                config_entry.entry_id,
                z_id,
                ZONE,
                zone_name,
                CONTROL_EQ_TREBLE,
                CONTROL_EQ_TREBLE,
                ZONE_EQ_STATUS,
            )
        )
        entities.append(
            Balance(
                nuvo,
                model,
                config_entry.entry_id,
                z_id,
                ZONE,
                zone_name,
                CONTROL_EQ_BALANCE,
                CONTROL_EQ_BALANCE,
                ZONE_EQ_STATUS,
            )
        )
        entities.append(
            VolumeMaxControl(
                nuvo,
                model,
                config_entry.entry_id,
                z_id,
                ZONE,
                zone_name,
                CONTROL_VOLUME_MAX,
                CONTROL_VOLUME,
                ZONE_VOLUME_CONFIGURATION,
            )
        )
        entities.append(
            VolumeIniControl(
                nuvo,
                model,
                config_entry.entry_id,
                z_id,
                ZONE,
                zone_name,
                CONTROL_VOLUME_INI,
                CONTROL_VOLUME,
                ZONE_VOLUME_CONFIGURATION,
            )
        )
        entities.append(
            VolumePageControl(
                nuvo,
                model,
                config_entry.entry_id,
                z_id,
                ZONE,
                zone_name,
                CONTROL_VOLUME_PAGE,
                CONTROL_VOLUME,
                ZONE_VOLUME_CONFIGURATION,
            )
        )
        entities.append(
            VolumePartyControl(
                nuvo,
                model,
                config_entry.entry_id,
                z_id,
                ZONE,
                zone_name,
                CONTROL_VOLUME_PARTY,
                CONTROL_VOLUME,
                ZONE_VOLUME_CONFIGURATION,
            )
        )

    for source_id, source_name in sources.items():
        s_id = int(source_id)
        entities.append(
            GainControl(
                nuvo,
                model,
                config_entry.entry_id,
                s_id,
                SOURCE,
                source_name,
                CONTROL_SOURCE_GAIN,
                CONTROL_SOURCE_GAIN,
                SOURCE_CONFIGURATION,
            )
        )

    async_add_entities(entities, False)


class NuvoNumberControl(NuvoControl, NumberEntity):
    """Nuvo Number based control."""

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return device info for this device."""
        return {
            "identifiers": {(DOMAIN, self._namespace)},
            "name": f"{' '.join(self._model.split('_'))}",
            "manufacturer": "Nuvo",
            "model": self._model,
        }

    @property
    def min_value(self) -> float:
        """Return the minimum value."""
        return float(config[self._model][self._nuvo_config_key]["min"])

    @property
    def max_value(self) -> float:
        """Return the maximum value."""
        return float(config[self._model][self._nuvo_config_key]["max"])

    @property
    def step(self) -> float:
        """Return the increment/decrement step."""
        return float(config[self._model][self._nuvo_config_key]["step"])

    @property
    def value(self) -> float:
        """Return the entity value to represent the entity state."""
        return self._control_value

    async def async_set_value(self, value: float) -> None:
        """Set new value."""

        return await self._nuvo_set_control_value(value)

    async def async_added_to_hass(self) -> None:
        """Run when entity is added to register.

        Subscribe callback to handle updates from the Nuvo.
        Request initial entity state, letting the update callback handle setting it.
        """
        self._nuvo.add_subscriber(self._update_callback, self._nuvo_msg_class)
        await self._nuvo_get_control_value()

    async def async_will_remove_from_hass(self) -> None:
        """Run when entity is removed to register.

        Remove Nuvo update callback.
        """
        self._nuvo.remove_subscriber(self._update_callback, self._nuvo_msg_class)
        self._nuvo = None

    async def _update_callback(self, message: dict[str, Any]) -> None:
        """Update entity state callback.

        Nuvo lib calls this when it receives new messages.
        """
        try:
            msg = message["event"]
            originating_id = getattr(msg, self._nuvo_entity_type)
            if originating_id != self._nuvo_id:
                return
            self._control_value = float(getattr(msg, self._control_name))
            if self._control_name == "balance" and msg.balance_position == "L":
                self._control_value = -self._control_value
            elif self._control_name in VOLUME_CONTROLS:
                self._control_value = -self._control_value
            self._available = True
        except (KeyError, AttributeError):
            _LOGGER.debug(
                "%s %d %s: invalid %s message received",
                self._nuvo_entity_type,
                self._nuvo_id,
                self.entity_id,
                self._control_name,
            )
            return
        else:
            self.async_schedule_update_ha_state()

    async def _nuvo_get_control_value(self) -> None:
        """Get value."""
        raise NotImplementedError

    async def _nuvo_set_control_value(self, value: float) -> None:
        """Set new value."""
        raise NotImplementedError


class EQ(NuvoNumberControl):
    """Nuvo EQ based control."""

    async def _nuvo_get_control_value(self) -> None:
        """Get value."""
        await self._nuvo.zone_eq_status(self._nuvo_id)


class Bass(EQ):
    """Bass control for Nuvo amplifier zone."""

    async def _nuvo_set_control_value(self, value: float) -> None:
        """Set new value."""
        await self._nuvo.set_bass(self._nuvo_id, int(value))


class Treble(EQ):
    """Treble control for Nuvo amplifier zone."""

    async def _nuvo_set_control_value(self, value: float) -> None:
        """Set new value."""
        await self._nuvo.set_treble(self._nuvo_id, int(value))


class Balance(EQ):
    """Balance control for Nuvo amplifier zone.

    In order to control the balance from one frontend UI slider control, represent R
    balance with positive values and L balance with negative values.
    """

    @property
    def min_value(self) -> float:
        """Return the minimum value."""
        max = float(config[self._model][CONTROL_EQ_BALANCE]["max"])
        return -max

    async def _nuvo_set_control_value(self, value: float) -> None:
        """Set new value."""
        balance_position = "C"

        if value < 0:
            balance_position = "L"
            value = -value
        elif value > 0:
            balance_position = "R"

        await self._nuvo.set_balance(self._nuvo_id, balance_position, int(value))


class GainControl(NuvoNumberControl, NuvoControl):
    """Gain control for Nuvo amplifier source."""

    async def _nuvo_get_control_value(self) -> None:
        """Get value."""
        await self._nuvo.source_configuration(self._nuvo_id)

    async def _nuvo_set_control_value(self, value: float) -> None:
        """Set new value."""
        await self._nuvo.set_source_gain(self._nuvo_id, int(value))


class VolumeControl(NuvoNumberControl, NuvoControl):
    """Nuvo Volume based control."""

    @property
    def unit_of_measurement(self) -> str:
        """Return the unity of measurement."""
        return "dB"

    @property
    def min_value(self) -> float:
        """Return the minimum value."""
        min = float(config[self._model][CONTROL_VOLUME]["min"])
        return -min

    async def _nuvo_get_control_value(self) -> None:
        """Get value."""
        await self._nuvo.zone_volume_configuration(self._nuvo_id)


class VolumeMaxControl(VolumeControl):
    """Max volume control for Nuvo amplifier zone."""

    async def _nuvo_set_control_value(self, value: float) -> None:
        """Set new value."""
        await self._nuvo.zone_volume_max(self._nuvo_id, int(-value))

    @property
    def name(self) -> str:
        """Return the name of the control."""
        return f"{self._nuvo_entity_name} Volume Max"


class VolumeIniControl(VolumeControl):
    """Initial volume control for Nuvo amplifier zone."""

    async def _nuvo_set_control_value(self, value: float) -> None:
        """Set new value."""
        await self._nuvo.zone_volume_initial(self._nuvo_id, int(-value))

    @property
    def name(self) -> str:
        """Return the name of the control."""
        return f"{self._nuvo_entity_name} Volume Initial"


class VolumePageControl(VolumeControl):
    """Page volume control for Nuvo amplifier zone."""

    async def _nuvo_set_control_value(self, value: float) -> None:
        """Set new value."""
        await self._nuvo.zone_volume_page(self._nuvo_id, int(-value))

    @property
    def name(self) -> str:
        """Return the name of the control."""
        return f"{self._nuvo_entity_name} Volume Page"


class VolumePartyControl(VolumeControl):
    """Party volume control for Nuvo amplifier zone."""

    async def _nuvo_set_control_value(self, value: float) -> None:
        """Set new value."""
        await self._nuvo.zone_volume_party(self._nuvo_id, int(-value))

    @property
    def name(self) -> str:
        """Return the name of the control."""
        return f"{self._nuvo_entity_name} Volume Party"
