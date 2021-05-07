"""Support for interfacing with Nuvo multi-zone amplifier."""
from __future__ import annotations

import logging
from typing import Any, Callable, Iterable

from nuvo_serial.const import ranges
from nuvo_serial.grand_concerto_essentia_g import NuvoAsync

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_TYPE
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.typing import HomeAssistantType

from .const import DOMAIN, NUVO_OBJECT
from .helpers import get_zones

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistantType,
    config_entry: ConfigEntry,
    async_add_entities: Callable[[Iterable[Entity], bool], None],
) -> None:
    """Set up the Number entities associated with each Nuvo multi-zone amplifier zone."""

    model = config_entry.data[CONF_TYPE]
    nuvo = hass.data[DOMAIN][config_entry.entry_id][NUVO_OBJECT]
    zones = get_zones(config_entry)
    entities: list[EQ] = []

    for zone_id, zone_name in zones.items():
        z_id = int(zone_id)
        entities.append(
            Bass(nuvo, model, config_entry.entry_id, z_id, zone_name, "bass")
        )
        entities.append(
            Treble(nuvo, model, config_entry.entry_id, z_id, zone_name, "treble")
        )
        entities.append(
            Balance(nuvo, model, config_entry.entry_id, z_id, zone_name, "balance")
        )

    async_add_entities(entities, False)


class EQ(NumberEntity):
    """EQ base class for Nuvo amplifier zone."""

    def __init__(
        self,
        nuvo: NuvoAsync,
        model: str,
        namespace: str,
        zone_id: int,
        zone_name: str,
        eq_name: str,
    ):
        """Init this entity."""
        self._nuvo = nuvo
        self._model = model
        self._namespace = namespace
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._eq_name = eq_name
        self._name = f"{self._zone_name} {self._eq_name.capitalize()}"
        self._unique_id = f"{self._namespace}_zone_{self._zone_id}_{self._eq_name}"
        self._eq_value: float = 0

    @property
    def min_value(self) -> float:
        """Return the minimum value."""
        return float(ranges[self._model][self._eq_name]["min"])

    @property
    def max_value(self) -> float:
        """Return the maximum value."""
        return float(ranges[self._model][self._eq_name]["max"])

    @property
    def step(self) -> float:
        """Return the increment/decrement step."""
        return float(ranges[self._model][self._eq_name]["step"])

    @property
    def value(self) -> float:
        """Return the entity value to represent the entity state."""
        return self._eq_value

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device info for this device."""
        return {
            "identifiers": {(DOMAIN, self._namespace)},
            "name": f"{' '.join(self._model.split('_'))}",
            "manufacturer": "Nuvo",
            "model": self._model,
        }

    @property
    def unique_id(self) -> str:
        """Return unique ID for this device."""
        return self._unique_id

    @property
    def name(self) -> str:
        """Return the name of the control."""
        return self._name

    @property
    def device_state_attributes(self) -> dict[str, int]:
        """Return the name of the control."""
        return {"zone_id": self._zone_id}

    @property
    def should_poll(self) -> bool:
        """State updates are handled through subscription so turn polling off."""
        return False

    async def async_added_to_hass(self) -> None:
        """Run when entity is added to register.

        Subscribe callback to handle updates from the Nuvo.
        Request initial entity state, letting the update callback handle setting it.
        """
        self._nuvo.add_subscriber(self._update_callback, "ZoneEQStatus")
        await self._nuvo.zone_eq_status(self._zone_id)

    async def async_will_remove_from_hass(self) -> None:
        """Run when entity is removed to register.

        Remove Nuvo update callback.
        """
        self._nuvo.remove_subscriber(self._update_callback, "ZoneEQStatus")
        self._nuvo = None

    async def _update_callback(self, message: dict[str, Any]) -> None:
        """Update entity state callback.

        Nuvo lib calls this when it receives new messages.
        """
        try:
            eq = message["event"]
            zone = eq.zone
            if zone != self._zone_id:
                return
            self._eq_value = float(getattr(eq, self._eq_name))
            if self._eq_name == "balance" and eq.balance_position == "L":
                self._eq_value = -self._eq_value
        except (KeyError, AttributeError):
            _LOGGER.debug(
                "Zone %d %s: invalid %s EQ config received",
                self._zone_id,
                self.entity_id,
                self._eq_name,
            )
            return
        else:
            self.async_schedule_update_ha_state()


class Bass(EQ):
    """Bass control for Nuvo amplifier zone."""

    async def async_set_value(self, value: float) -> None:
        """Set new value."""
        await self._nuvo.set_bass(self._zone_id, int(value))


class Treble(EQ):
    """Treble control for Nuvo amplifier zone."""

    async def async_set_value(self, value: float) -> None:
        """Set new value."""
        await self._nuvo.set_treble(self._zone_id, int(value))


class Balance(EQ):
    """Balance control for Nuvo amplifier zone."""

    @property
    def min_value(self) -> float:
        """Return the minimum value."""
        max = float(ranges[self._model]["balance"]["max"])
        return -max

    async def async_set_value(self, value: float) -> None:
        """Set new value."""
        balance_position = "C"

        if value < 0:
            balance_position = "L"
            value = -value
        elif value > 0:
            balance_position = "R"

        await self._nuvo.set_balance(self._zone_id, balance_position, int(value))


# class _Bass(NumberEntity):
#     """Bass control for Nuvo amplifier zone."""

#     def __init__(self, nuvo, model, namespace, zone_id, zone_name):
#         """Init this entity."""
#         self._nuvo = nuvo
#         self._model = model
#         self._zone_id = zone_id
#         self._zone_name = zone_name
#         self._name = f"{self._zone_name} Bass"
#         self._namespace = namespace
#         self._unique_id = f"{self._namespace}_zone_{self._zone_id}_bass"
#         self._bass = None

#     @property
#     def should_poll(self):
#         """State updates are handled through subscription so turn polling off."""
#         return False

#     async def async_added_to_hass(self) -> None:
#         """Run when entity is added to register.

#         Subscribe callback to handle updates from the Nuvo.
#         Request initial entity state, letting the update callback handle setting it.
#         """
#         self._nuvo.add_subscriber(self._update_callback, "ZoneEQStatus")
#         await self._nuvo.zone_eq_status(self._zone_id)

#     async def async_will_remove_from_hass(self) -> None:
#         """Run when entity is removed to register.

#         Remove Nuvo update callback.
#         """
#         self._nuvo.remove_subscriber(self._update_callback, "ZoneEQStatus")
#         self._nuvo = None

#     async def _update_callback(self, message):
#         """Update entity state callback.

#         Nuvo lib calls this when it receives new messages.
#         """
#         if not message:
#             _LOGGER.debug("Invalid EQ config received")
#         try:
#             event_name = message["event_name"]
#             eq = message["event"]
#             zone = eq.zone
#             bass = float(eq.bass)
#         except Exception as exc:
#             raise
#         else:
#             if zone != self._zone_id:
#                 return

#             _LOGGER.debug(
#                 "ZONE %d: Notified by nuvo that %s is available for update",
#                 self._zone_id,
#                 message,
#             )

#             self._bass = bass

#             self.async_schedule_update_ha_state()

#     @property
#     def min_value(self) -> float:
#         """Return the minimum value."""
#         return ranges[self._model]["bass"]["min"]

#     @property
#     def max_value(self) -> float:
#         """Return the maximum value."""
#         return ranges[self._model]["bass"]["max"]

#     @property
#     def step(self) -> float:
#         """Return the increment/decrement step."""
#         return ranges[self._model]["bass"]["step"]

#     @property
#     def value(self) -> float:
#         """Return the entity value to represent the entity state."""
#         return self._bass

#     async def async_set_value(self, value: float) -> None:
#         """Set new value."""
#         await self._nuvo.set_bass(self._zone_id, int(value))

#     # def update(self):
#     #     """Retrieve latest state."""

#     #     eq = self._nuvo.zone_eq_status(self._zone_id)
#     #     if not eq:
#     #         _LOGGER.error("NO EQ STATE RETURNED")
#     #         return False

#     #     self._bass = float(eq.bass)
#     #     return True

#     @property
#     def device_info(self):
#         """Return device info for this device."""
#         return {
#             "identifiers": {(DOMAIN, self._namespace)},
#             "name": f"{' '.join(self._model.split('_'))}",
#             "manufacturer": "Nuvo",
#             "model": self._model,
#         }

#     @property
#     def unique_id(self):
#         """Return unique ID for this device."""
#         return self._unique_id

#     @property
#     def name(self):
#         """Return the name of the control."""
#         return self._name


# class _Treble(NumberEntity):
#     """Treble control for Nuvo amplifier zone."""

#     def __init__(self, nuvo, model, namespace, zone_id, zone_name):
#         """Init this entity."""
#         self._nuvo = nuvo
#         self._model = model
#         self._zone_id = zone_id
#         self._zone_name = zone_name
#         self._name = f"{self._zone_name} Treble"
#         self._namespace = namespace
#         self._unique_id = f"{self._namespace}_zone_{self._zone_id}_treble"
#         self._treble = None

#     @property
#     def min_value(self) -> float:
#         """Return the minimum value."""
#         return ranges[self._model]["treble"]["min"]

#     @property
#     def max_value(self) -> float:
#         """Return the maximum value."""
#         return ranges[self._model]["treble"]["max"]

#     @property
#     def step(self) -> float:
#         """Return the increment/decrement step."""
#         return ranges[self._model]["treble"]["step"]

#     @property
#     def value(self) -> float:
#         """Return the entity value to represent the entity state."""
#         return self._treble

#     async def async_set_value(self, value: float) -> None:
#         """Set new value."""
#         await self._nuvo.set_treble(self._zone_id, int(value))

#     # def update(self):
#     #     """Retrieve latest state."""

#     #     eq = self._nuvo.zone_eq_status(self._zone_id)
#     #     if not eq:
#     #         _LOGGER.error("NO EQ STATE RETURNED")
#     #         return False

#     #     self._treble = float(eq.treble)
#     #     return True

#     @property
#     def device_info(self):
#         """Return device info for this device."""
#         return {
#             "identifiers": {(DOMAIN, self._namespace)},
#             "name": f"{' '.join(self._model.split('_'))}",
#             "manufacturer": "Nuvo",
#             "model": self._model,
#         }

#     @property
#     def unique_id(self):
#         """Return unique ID for this device."""
#         return self._unique_id

#     @property
#     def name(self):
#         """Return the name of the control."""
#         return self._name

#     @property
#     def should_poll(self):
#         """State updates are handled through subscription so turn polling off."""
#         return False

#     async def async_added_to_hass(self) -> None:
#         """Run when entity is added to register.

#         Subscribe callback to handle updates from the Nuvo.
#         Request initial entity state, letting the update callback handle setting it.
#         """
#         self._nuvo.add_subscriber(self._update_callback, "ZoneEQStatus")
#         await self._nuvo.zone_eq_status(self._zone_id)

#     async def async_will_remove_from_hass(self) -> None:
#         """Run when entity is removed to register.

#         Remove Nuvo update callback.
#         """
#         self._nuvo.remove_subscriber(self._update_callback, "ZoneEQStatus")
#         self._nuvo = None

#     async def _update_callback(self, message):
#         """Update entity state callback.

#         Nuvo lib calls this when it receives new messages.
#         """
#         if not message:
#             _LOGGER.debug("Invalid EQ config received")
#         try:
#             event_name = message["event_name"]
#             eq = message["event"]
#             zone = eq.zone
#             treble = float(eq.treble)
#         except Exception as exc:
#             raise
#         else:
#             if zone != self._zone_id:
#                 return

#             _LOGGER.debug(
#                 "ZONE %d: Notified by nuvo that %s is available for update",
#                 self._zone_id,
#                 message,
#             )

#             self._treble = treble

#             self.async_schedule_update_ha_state()


# class _Balance(NumberEntity):
#     """Balance control for Nuvo amplifier zone."""

#     def __init__(self, nuvo, model, namespace, zone_id, zone_name):
#         """Init this entity."""
#         self._nuvo = nuvo
#         self._model = model
#         self._zone_id = zone_id
#         self._zone_name = zone_name
#         self._name = f"{self._zone_name} Balance"
#         self._namespace = namespace
#         self._unique_id = f"{self._namespace}_zone_{self._zone_id}_balance"
#         self._balance = None

#     @property
#     def min_value(self) -> float:
#         """Return the minimum value."""
#         max = ranges[self._model]["balance"]["max"]
#         return -max

#     @property
#     def max_value(self) -> float:
#         """Return the maximum value."""
#         return ranges[self._model]["balance"]["max"]

#     @property
#     def step(self) -> float:
#         """Return the increment/decrement step."""
#         return ranges[self._model]["balance"]["step"]

#     @property
#     def value(self) -> float:
#         """Return the entity value to represent the entity state."""
#         return self._balance

#     async def async_set_value(self, value: float) -> None:
#         """Set new value."""
#         balance_position = "C"

#         if value < 0:
#             balance_position = "L"
#             value = -value
#         elif value > 0:
#             balance_position = "R"

#         await self._nuvo.set_balance(self._zone_id, balance_position, int(value))

#     # def update(self):
#     #     """Retrieve latest state."""

#     #     eq = self._nuvo.zone_eq_status(self._zone_id)
#     #     balance_value = None
#     #     if not eq:
#     #         _LOGGER.error("NO EQ STATE RETURNED")
#     #         return False
#     #     if eq.balance_position == "L":
#     #         balance_value = -eq.balance_value
#     #     else:
#     #         balance_value = eq.balance_value

#     #     self._balance = float(balance_value)
#     #     return True

#     @property
#     def device_info(self):
#         """Return device info for this device."""
#         return {
#             "identifiers": {(DOMAIN, self._namespace)},
#             "name": f"{' '.join(self._model.split('_'))}",
#             "manufacturer": "Nuvo",
#             "model": self._model,
#         }

#     @property
#     def unique_id(self):
#         """Return unique ID for this device."""
#         return self._unique_id

#     @property
#     def name(self):
#         """Return the name of the control."""
#         return self._name

#     @property
#     def should_poll(self):
#         """State updates are handled through subscription so turn polling off."""
#         return False

#     async def async_added_to_hass(self) -> None:
#         """Run when entity is added to register.

#         Subscribe callback to handle updates from the Nuvo.
#         Request initial entity state, letting the update callback handle setting it.
#         """
#         self._nuvo.add_subscriber(self._update_callback, "ZoneEQStatus")
#         await self._nuvo.zone_eq_status(self._zone_id)

#     async def async_will_remove_from_hass(self) -> None:
#         """Run when entity is removed to register.

#         Remove Nuvo update callback.
#         """
#         self._nuvo.remove_subscriber(self._update_callback, "ZoneEQStatus")
#         self._nuvo = None

#     async def _update_callback(self, message):
#         """Update entity state callback.

#         Nuvo lib calls this when it receives new messages.
#         """
#         try:
#             eq = message["event"]
#             if eq.zone != self._zone_id:
#                 return
#             balance_position = eq.balance_position
#             balance_value = float(eq.balance_value)
#         except (KeyError, AttributeError):
#             _LOGGER.debug("Zone %d %s: invalid EQ config received", self._zone_id, self.entity_id)
#             return
#         else:

#             if balance_position == "L":
#                 balance_value = -eq.balance_value
#             # else:
#             #     balance_value = eq.balance_value

#             self._balance = float(balance_value)

#             self.async_schedule_update_ha_state()
