"""Support for interfacing with Nuvo multi-zone amplifier."""
import logging
from typing import Any, Callable, Dict, Iterable

from nuvo_serial.grand_concerto_essentia_g import NuvoAsync

from homeassistant.components.switch import SwitchEntity
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
    """Set up the Switch entities associated with each Nuvo multi-zone amplifier zone."""

    model = config_entry.data[CONF_TYPE]
    nuvo = hass.data[DOMAIN][config_entry.entry_id][NUVO_OBJECT]
    zones = get_zones(config_entry)
    entities = []

    for zone_id, zone_name in zones.items():
        z_id = int(zone_id)
        entities.append(
            LoudnessCompensation(nuvo, model, config_entry.entry_id, z_id, zone_name)
        )

    async_add_entities(entities, False)


class LoudnessCompensation(SwitchEntity):
    """Loudness Compensation control for Nuvo amplifier zone."""

    def __init__(
        self, nuvo: NuvoAsync, model: str, namespace: str, zone_id: int, zone_name: str
    ):
        """Init this entity."""
        self._nuvo = nuvo
        self._model = model
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._name = f"{self._zone_name} Loudcmp"
        self._namespace = namespace
        self._unique_id = f"{self._namespace}_zone_{self._zone_id}_loudcmp"
        self._loudness_compensation: bool = False

    @property
    def value(self) -> bool:
        """Return the entity value to represent the entity state."""
        return self._loudness_compensation

    @property
    def is_on(self) -> bool:
        """Return True if entity is on."""
        return self._loudness_compensation

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the entity on."""
        await self._nuvo.set_loudness_comp(self._zone_id, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        await self._nuvo.set_loudness_comp(self._zone_id, False)

    async def async_toggle(self, **kwargs: Any) -> None:
        """Toggle the entity."""
        await self._nuvo.set_loudness_comp(self._zone_id, not (self.value))

    @property
    def device_info(self) -> Dict[str, Any]:
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
    def device_state_attributes(self) -> Dict[str, int]:
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

    async def _update_callback(self, message: Dict[str, Any]) -> None:
        """Update entity state callback.

        Nuvo lib calls this when it receives new messages.
        """
        try:
            eq = message["event"]
            zone = eq.zone
            if zone != self._zone_id:
                return
            self._loudness_compensation = eq.loudcmp
        except (KeyError, AttributeError):
            _LOGGER.debug(
                "Zone %d %s: invalid %s EQ config received",
                self._zone_id,
                self.entity_id,
                "loudcmp",
            )
            return
        else:
            self.async_schedule_update_ha_state()
