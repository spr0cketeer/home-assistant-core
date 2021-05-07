"""Support for interfacing with Nuvo multi-zone amplifier."""
from decimal import ROUND_HALF_EVEN, Decimal
import logging

from homeassistant import core
from homeassistant.components.media_player import MediaPlayerEntity
from homeassistant.components.media_player.const import (
    SUPPORT_SELECT_SOURCE,
    SUPPORT_TURN_OFF,
    SUPPORT_TURN_ON,
    SUPPORT_VOLUME_MUTE,
    SUPPORT_VOLUME_SET,
    SUPPORT_VOLUME_STEP,
)
from homeassistant.const import CONF_TYPE, STATE_OFF, STATE_ON
from homeassistant.helpers import config_validation as cv, entity_platform, service

from .const import (
    CONF_SOURCES,
    CONF_ZONES,
    DOMAIN,
    FIRST_RUN,
    NUVO_OBJECT,
    SERVICE_RESTORE,
    SERVICE_SNAPSHOT,
)

# from serial import SerialException


_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1

SUPPORT_NUVO_SERIAL = (
    SUPPORT_VOLUME_MUTE
    | SUPPORT_VOLUME_SET
    | SUPPORT_VOLUME_STEP
    | SUPPORT_TURN_ON
    | SUPPORT_TURN_OFF
    | SUPPORT_SELECT_SOURCE
)

ATTR_LOUDNESS_COMPENSATION = "loudness_compensation"
ATTR_BASS_LEVEL = "bass_level"
ATTR_BASS_LEVEL_NATIVE = "bass_level_native"
ATTR_TREBLE_LEVEL = "treble_level"

LEVELS = {
    "Grand_Concerto": {
        "volume": {"max": 0, "min": 79, "step": 1},
        "bass": {"max": 18, "min": -18, "step": 2},
        "treble": {"max": 18, "min": -18, "step": 2},
    }
}


@core.callback
def _get_sources_from_dict(data):
    sources_config = data[CONF_SOURCES]

    source_id_name = {int(index): name for index, name in sources_config.items()}

    source_name_id = {v: k for k, v in source_id_name.items()}

    source_names = sorted(source_name_id.keys(), key=lambda v: source_name_id[v])

    return [source_id_name, source_name_id, source_names]


@core.callback
def _get_sources(config_entry):
    if CONF_SOURCES in config_entry.options:
        data = config_entry.options
    else:
        data = config_entry.data
    return _get_sources_from_dict(data)


@core.callback
def _get_zones(config_entry):
    if CONF_ZONES in config_entry.options:
        data = config_entry.options
    else:
        data = config_entry.data

    return data[CONF_ZONES]


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up the Nuvo multi-zone amplifier platform."""
    model = config_entry.data[CONF_TYPE]

    nuvo = hass.data[DOMAIN][config_entry.entry_id][NUVO_OBJECT]

    sources = _get_sources(config_entry)
    zones = _get_zones(config_entry)
    volume_step = 1
    entities = []

    for zone_id, zone_name in zones.items():
        zone_id = int(zone_id)
        entities.append(
            NuvoZone(
                nuvo,
                model,
                sources,
                config_entry.entry_id,
                zone_id,
                zone_name,
                volume_step,
            )
        )

    # only call update before add if it's the first run so we can try to detect zones
    first_run = hass.data[DOMAIN][config_entry.entry_id][FIRST_RUN]
    async_add_entities(entities, first_run)

    platform = entity_platform.current_platform.get()

    def _call_service(entities, service_call):
        for entity in entities:
            if service_call.service == SERVICE_SNAPSHOT:
                entity.snapshot()
            elif service_call.service == SERVICE_RESTORE:
                entity.restore()

    @service.verify_domain_control(hass, DOMAIN)
    async def async_service_handle(service_call):
        """Handle for services."""
        entities = await platform.async_extract_from_service(service_call)

        if not entities:
            return

        hass.async_add_executor_job(_call_service, entities, service_call)

    hass.services.async_register(
        DOMAIN,
        SERVICE_SNAPSHOT,
        async_service_handle,
        schema=cv.make_entity_service_schema({}),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_RESTORE,
        async_service_handle,
        schema=cv.make_entity_service_schema({}),
    )


class NuvoZone(MediaPlayerEntity):
    """Representation of a Nuvo amplifier zone."""

    def __init__(
        self, nuvo, model, sources, namespace, zone_id, zone_name, volume_step
    ):
        """Initialize new zone."""
        self._nuvo = nuvo
        self._model = model
        # dict source_id -> source name
        self._source_id_name = sources[0]
        # dict source name -> source_id
        self._source_name_id = sources[1]
        # ordered list of all source names
        self._source_names = sources[2]

        self._zone_id = zone_id
        self._name = zone_name
        self._namespace = namespace
        self._unique_id = f"{self._namespace}_zone_{self._zone_id}_zone"
        self._volume_step = volume_step

        self._snapshot = None
        self._state = None
        self._volume = None
        self._source = None
        self._mute = None

        self._bass = None
        self._bass_native = None
        self._treble = None
        self._loudness_compensation = None
        self._balance = None

    def update(self):
        """Retrieve latest state."""
        state = self._nuvo.zone_status(self._zone_id)

        if not state:
            _LOGGER.error("NO STATE RETURNED")
            return False

        if not state.power:
            self._state = STATE_OFF
            return True

        self._state = STATE_ON
        self._mute = state.mute

        if not self._mute:
            self._volume = self.nuvo_to_hass_vol(state.volume)

        self._source = self._source_id_name.get(state.source, None)

        """
        Update zone's permitted sources.
        A permitted source may not appear in the list of system-wide enabled sources.
        """
        z_cfg = self._nuvo.zone_configuration(self._zone_id)
        if not z_cfg:
            _LOGGER.error("NO ZONE CONFIGURATION RETURNED")
            return False

        self._source_names = list(
            filter(
                None,
                [
                    self._source_id_name.get(id, None)
                    for id in [int(src.split("SOURCE")[1]) for src in z_cfg.sources]
                ],
            )
        )

        eq = self._nuvo.zone_eq_status(self._zone_id)
        if not eq:
            _LOGGER.error("NO EQ STATE RETURNED")
            return False

        self._bass = self.nuvo_to_hass_eq("bass", eq.bass)
        self._bass_native = eq.bass
        self._treble = self.nuvo_to_hass_eq("treble", eq.treble)
        self._treble_native = eq.treble
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
        """Return the name of the zone."""
        return self._name

    @property
    def state(self):
        """Return the state of the zone."""
        return self._state

    @property
    def volume_level(self):
        """Volume level of the media player (0..1)."""
        return self._volume

    @property
    def is_volume_muted(self):
        """Boolean if volume is currently muted."""
        return self._mute

    @property
    def supported_features(self):
        """Return flag of media commands that are supported."""
        return SUPPORT_NUVO_SERIAL

    @property
    def media_title(self):
        """Return the current source as medial title."""
        return self._source

    @property
    def source(self):
        """Return the current input source of the device."""
        return self._source

    @property
    def source_list(self):
        """List of available input sources."""
        return self._source_names

    # @property
    # def bass_level(self):
    #     """Bass level of the media player (0..1)."""
    #     return self._bass

    # @property
    # def loudness_compensation(self):
    #     """Boolean if loudness compensation is enabled."""
    #     return self._loudness_compensation

    @property
    def device_state_attributes(self):
        """Return device specific state attributes."""
        attributes = {}
        attributes[ATTR_LOUDNESS_COMPENSATION] = self._loudness_compensation
        attributes[ATTR_BASS_LEVEL] = self._bass
        attributes[ATTR_BASS_LEVEL_NATIVE] = self._bass_native
        attributes[ATTR_TREBLE_LEVEL] = self._treble
        return attributes

    def snapshot(self):
        """Save zone's current state."""
        self._snapshot = self._nuvo.zone_status(self._zone_id)

    def restore(self):
        """Restore saved state."""
        if self._snapshot:
            self._nuvo.restore_zone(self._snapshot)
            self.schedule_update_ha_state(True)

    def select_source(self, source):
        """Set input source."""
        if source not in self._source_name_id:
            return
        idx = self._source_name_id[source]
        self._nuvo.set_source(self._zone_id, idx)

    def turn_on(self):
        """Turn the media player on."""
        self._nuvo.set_power(self._zone_id, True)

    def turn_off(self):
        """Turn the media player off."""
        self._nuvo.set_power(self._zone_id, False)

    def mute_volume(self, mute):
        """Mute (true) or unmute (false) media player."""
        self._nuvo.set_mute(self._zone_id, mute)

    def set_volume_level(self, volume):
        """Set volume level, range 0..1."""
        calculated_volume = self.hass_to_nuvo_vol(volume)
        # _LOGGER.debug(f"Current Hass volume {self._volume}/ Calculated Nuvo volume {calculated_volume} {type(calculated_volume)}")
        self._nuvo.set_volume(self._zone_id, calculated_volume)
        # _LOGGER.debug(f"New Current volume {self._volume}")

    def volume_up(self):
        """Volume up the media player."""
        if self._volume is None:
            return
        self._nuvo.set_volume(
            self._zone_id,
            max(self.hass_to_nuvo_vol(self._volume) - self._volume_step, 0),
        )
        # self._nuvo.set_volume(self._zone_id, max(self.hass_to_nuvo_vol(self._volume) - 1, 0))

    def volume_down(self):
        """Volume down media player."""
        if self._volume is None:
            return
        self._nuvo.set_volume(
            self._zone_id,
            min(self.hass_to_nuvo_vol(self._volume) + self._volume_step, 79),
        )
        # self._nuvo.set_volume(self._zone_id, min(self.hass_to_nuvo_vol(self._volume) + 1, 79))

    def nuvo_to_hass_vol(self, volume):
        """Convert from nuvo to hass volume."""
        return 1 - (volume / 79)

    def hass_to_nuvo_vol(self, volume):
        """Convert from hass to nuvo volume."""
        return int(
            Decimal(79 - (volume * 79)).to_integral_exact(rounding=ROUND_HALF_EVEN)
        )

    def nuvo_to_hass_eq(self, eq_type, eq_value):
        """Convert from nvuo to hass eq."""
        nuvo_max = LEVELS[self._model][eq_type]["max"]
        nuvo_min = LEVELS[self._model][eq_type]["min"]
        # hass_eq = ( (eq_value - nuvo_min) / (nuvo_max - nuvo_min) * (HASS_MAX - HASS_MIN) + HASS_MIN )
        hass_eq = (eq_value - nuvo_min) / (nuvo_max - nuvo_min)
        # _LOGGER.debug(f"Nuvo {eq_type} {eq_value} converted to hass {eq_type} {hass_eq}")
        return hass_eq

    def hass_to_nuvo_eq(self, eq_type, eq_value):
        """Convert from hass to nuvo eq."""
        nuvo_max = (
            LEVELS[self._model][eq_type]["max"] / LEVELS[self._model][eq_type]["step"]
        )
        nuvo_min = (
            LEVELS[self._model][eq_type]["min"] / LEVELS[self._model][eq_type]["step"]
        )
        # nuvo_eq = Decimal(( (eq_value - HASS_MIN) / (HASS_MAX - HASS_MIN) * (nuvo_max - nuvo_min) + nuvo_min )).to_integral_exact(rounding=ROUND_HALF_EVEN) * 2
        nuvo_eq = (
            int(
                Decimal(
                    (eq_value * (nuvo_max - nuvo_min)) + nuvo_min
                ).to_integral_exact(rounding=ROUND_HALF_EVEN)
            )
            * 2
        )
        # _LOGGER.debug(f"Hass {eq_type} {eq_value} converted to nuvo {eq_type} {nuvo_eq}")
        return nuvo_eq

    def page_on(self):
        """Turn Page On."""
        self._nuvo.set_page_on()

    def page_off(self):
        """Turn Page Off."""
        self._nuvo.set_page_off()

    def eq_request(self):
        """Request a zone's EQ status."""
        return self._nuvo.request_eq(self._zone_id)

    def set_bass(self, bass, native_scale):
        """Set a zone's bass level."""
        if native_scale:
            return self._nuvo.set_bass(self._zone_id, bass)
        else:
            return self._nuvo.set_bass(
                self._zone_id, self.hass_to_nuvo_eq("bass", bass)
            )

    def set_treble(self, treble):
        """Set a zone's treble level."""
        return self._nuvo.set_treble(
            self._zone_id, self.hass_to_nuvo_eq("treble", treble)
        )

    def set_loudness_comp(self, loudness_comp):
        """Set a zone's loudness compensation."""
        _LOGGER.info(
            f"Loudness_comp = {loudness_comp} {type(loudness_comp)} {bool(loudness_comp)}"
        )
        return self._nuvo.set_loudness_comp(self._zone_id, bool(loudness_comp))

    def toggle_loudness_comp(self):
        """Toggle a zone's loudness compensation."""
        _LOGGER.info(
            f"Toggling loudness compensation for zone {self._zone_id} from {self._loudness_compensation} to {not self._loudness_compensation}"
        )
        return self._nuvo.set_loudness_comp(
            self._zone_id, not self._loudness_compensation
        )
