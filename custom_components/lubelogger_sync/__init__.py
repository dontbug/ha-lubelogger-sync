"""LubeLogger Sync: push odometer readings to LubeLogger and expose reminders."""

from __future__ import annotations

from datetime import datetime
import logging

from homeassistant.const import CONF_API_KEY, CONF_URL, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

from .api import LubeLoggerApi
from .const import (
    CONF_SCHEDULE,
    CONF_TIME,
    DEFAULT_SCHEDULE,
    DEFAULT_TIME,
    DOMAIN,
    SCHEDULE_DAILY,
    SCHEDULE_OFF,
    WEEKDAYS,
)
from .coordinator import LubeLoggerConfigEntry, LubeLoggerCoordinator
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the integration services."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: LubeLoggerConfigEntry) -> bool:
    """Set up LubeLogger Sync from a config entry."""
    api = LubeLoggerApi(
        async_get_clientsession(hass), entry.data[CONF_URL], entry.data[CONF_API_KEY]
    )
    coordinator = LubeLoggerCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _async_setup_schedule(hass, entry, coordinator)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


@callback
def _async_setup_schedule(
    hass: HomeAssistant, entry: LubeLoggerConfigEntry, coordinator: LubeLoggerCoordinator
) -> None:
    """Schedule the automatic odometer sync (weekly on a weekday, or daily)."""
    schedule = entry.options.get(CONF_SCHEDULE, DEFAULT_SCHEDULE)
    if schedule == SCHEDULE_OFF:
        return
    at = dt_util.parse_time(entry.options.get(CONF_TIME, DEFAULT_TIME))
    if at is None:
        at = dt_util.parse_time(DEFAULT_TIME)
    assert at is not None

    async def _scheduled_sync(now: datetime) -> None:
        if schedule != SCHEDULE_DAILY and WEEKDAYS[now.weekday()] != schedule:
            return
        _LOGGER.debug("Running scheduled odometer sync")
        await coordinator.async_sync()

    entry.async_on_unload(
        async_track_time_change(
            hass, _scheduled_sync, hour=at.hour, minute=at.minute, second=0
        )
    )


async def _async_reload_entry(hass: HomeAssistant, entry: LubeLoggerConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: LubeLoggerConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
