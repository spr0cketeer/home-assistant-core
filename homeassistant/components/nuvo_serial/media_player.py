"""Support for interfacing with Nuvo multi-zone amplifier."""
from decimal import ROUND_HALF_EVEN, Decimal
import logging

from nuvo_serial.const import ranges

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
    CONF_VOLUME_STEP,
    CONF_ZONES,
    DOMAIN,
    FIRST_RUN,
    NUVO_OBJECT,
    SERVICE_RESTORE,
    SERVICE_SNAPSHOT,
)

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
    volume_step = config_entry.data.get(CONF_VOLUME_STEP, 1)
    max_volume = ranges[model]["volume"]["max"]
    min_volume = ranges[model]["volume"]["min"]
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
                max_volume,
                min_volume,
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
        self,
        nuvo,
        model,
        sources,
        namespace,
        zone_id,
        zone_name,
        volume_step,
        max_volume,
        min_volume,
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
        self._max_volume = max_volume
        self._min_volume = min_volume

        self._snapshot = None
        self._state = None
        self._volume = None
        self._source = None
        self._mute = None

    @property
    def should_poll(self):
        """State updates are handled through subscription so turn polling off."""
        return False

    async def async_added_to_hass(self) -> None:
        """Run when entity is added to register.

        Subscribe callback to handle updates from the Nuvo.
        Request initial entity state, letting the update callback handle setting it.
        """
        self._nuvo.add_subscriber(self._update_callback, "ZoneStatus")
        self._nuvo.add_subscriber(self._update_callback, "ZoneConfiguration")
        _LOGGER.debug("ZONE %d: Requesting initial zone status", self._zone_id)
        await self._nuvo.zone_status(self._zone_id)
        _LOGGER.debug("ZONE %d: Requesting initial zone configuration", self._zone_id)
        await self._nuvo.zone_configuration(self._zone_id)

    async def async_will_remove_from_hass(self) -> None:
        """Run when entity is removed to register.

        Remove Nuvo update callback.
        """
        self._nuvo.remove_subscriber(self._update_callback, "ZoneStatus")
        self._nuvo.remove_subscriber(self._update_callback, "ZoneConfiguration")

    async def _update_callback(self, message):
        """Update entity state callback.

        Nuvo lib calls this when it receives new messages.
        """
        event_name = message["event_name"]
        d_class = message["event"]
        if d_class.zone != self._zone_id:
            return
        _LOGGER.debug(
            "ZONE %d: Notified by nuvo that %s is available for update",
            self._zone_id,
            message,
        )

        if event_name == "ZoneConfiguration":
            self._process_zone_configuration(d_class)
        elif event_name == "ZoneStatus":
            self._process_zone_status(d_class)
        else:
            return

        self.async_schedule_update_ha_state()
        # self.async_write_ha_state()

    # def update(self):
    #     """Retrieve latest state."""

    #     try:
    #         z_status = self._nuvo.zone_status(self._zone_id)
    #         z_cfg = self._nuvo.zone_configuration(self._zone_id)
    #     except (SerialException, ValueError) as e:
    #         _LOGGER.error(
    #             "Zone %d %s Update failed: %s",
    #             self._zone_id,
    #             self.entity_id,
    #             e,
    #         )
    #         return

    #     self._process_zone_status(z_status)

    #     self._source = self._source_id_name.get(z_status.source, None)

    #     """
    #     Update zone's permitted sources.
    #     A permitted source may not appear in the list of system-wide enabled sources.
    #     """
    #     self._source_names = list(
    #         filter(
    #             None,
    #             [
    #                 self._source_id_name.get(id, None)
    #                 for id in [int(src.split("SOURCE")[1]) for src in z_cfg.sources]
    #             ],
    #         )
    #     )

    def _process_zone_status(self, z_status):
        """Update zone's power, volume and source state.

        A permitted source may not appear in the list of system-wide enabled sources.
        """
        # _LOGGER.debug("Processing zone status %s", z_status)
        if not z_status.power:
            self._state = STATE_OFF
            return True

        self._state = STATE_ON
        self._mute = z_status.mute

        if not self._mute:
            self._volume = self._nuvo_to_hass_vol(z_status.volume)

        self._source = self._source_id_name.get(z_status.source, None)

    def _process_zone_configuration(self, z_cfg):
        """Update zone's permitted sources.

        A permitted source may not appear in the list of system-wide enabled sources so
        need to filter these out.
        """
        # _LOGGER.debug("Processing zone configuration %s", z_cfg)
        self._source_names = list(
            filter(
                None,
                [
                    self._source_id_name.get(id, None)
                    for id in [int(src.split("SOURCE")[1]) for src in z_cfg.sources]
                ],
            )
        )

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

    def snapshot(self):
        """Save zone's current state."""
        self._snapshot = self._nuvo.zone_status(self._zone_id)

    def restore(self):
        """Restore saved state."""
        if self._snapshot:
            self._nuvo.restore_zone(self._snapshot)
            self.schedule_update_ha_state(True)

    async def async_select_source(self, source):
        """Set input source."""
        if source not in self._source_name_id:
            return
        idx = self._source_name_id[source]
        await self._nuvo.set_source(self._zone_id, idx)

    async def async_turn_on(self):
        """Turn the media player on."""
        await self._nuvo.set_power(self._zone_id, True)

    async def async_turn_off(self):
        """Turn the media player off."""
        await self._nuvo.set_power(self._zone_id, False)

    async def async_mute_volume(self, mute):
        """Mute (true) or unmute (false) media player."""
        await self._nuvo.set_mute(self._zone_id, mute)

    async def async_set_volume_level(self, volume):
        """Set volume level, range 0..1.

        This has to accept HA 0..1 levels of volume
        and do the conversion to Nuvo volume format.
        """
        # _LOGGER.debug(f"Current vol hass: {self._volume} nuvo: {self._hass_to_nuvo_vol(self._volume)}")
        # _LOGGER.debug(f"Requested vol hass: {volume} nuvo: {self._hass_to_nuvo_vol(volume)}")
        nuvo_volume = self._hass_to_nuvo_vol(volume)
        await self._nuvo.set_volume(self._zone_id, nuvo_volume)

    async def async_volume_up(self):
        """Volume up the media player."""

        # If HA starts when a zone is muted _volume will be None as volume level is only
        # returned form a unmuted zone.
        if self._volume is None:
            return

        await self._nuvo.set_volume(
            self._zone_id,
            max(
                self._hass_to_nuvo_vol(self._volume) - self._volume_step,
                self._max_volume,
            ),
        )

    async def async_volume_down(self):
        """Volume down media player."""

        # If HA starts when a zone is muted _volume will be None as volume level is only
        # returned form a unmuted zone.
        if self._volume is None:
            return

        await self._nuvo.set_volume(
            self._zone_id,
            min(
                self._hass_to_nuvo_vol(self._volume) + self._volume_step,
                self._min_volume,
            ),
        )

    def _nuvo_to_hass_vol(self, volume):
        """Convert from nuvo to hass volume."""
        return 1 - (volume / self._min_volume)

    def _hass_to_nuvo_vol(self, volume):
        """Convert from hass to nuvo volume."""
        return int(
            Decimal(self._min_volume - (volume * self._min_volume)).to_integral_exact(
                rounding=ROUND_HALF_EVEN
            )
        )

    def page_on(self):
        """Turn Page On."""
        self._nuvo.set_page_on()

    def page_off(self):
        """Turn Page Off."""
        self._nuvo.set_page_off()
