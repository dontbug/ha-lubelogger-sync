"""Buttons for LubeLogger Sync."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import STATUS_SYNCED, STATUS_UP_TO_DATE
from .coordinator import LubeLoggerConfigEntry, LubeLoggerCoordinator
from .entity import LubeLoggerEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LubeLoggerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create one 'sync odometer' button per vehicle."""
    coordinator = entry.runtime_data
    async_add_entities(
        SyncOdometerButton(coordinator, vehicle_id) for vehicle_id in coordinator.data
    )


class SyncOdometerButton(LubeLoggerEntity, ButtonEntity):
    """Push the mapped odometer value to LubeLogger now."""

    def __init__(self, coordinator: LubeLoggerCoordinator, vehicle_id: int) -> None:
        """Initialize the button."""
        super().__init__(coordinator, vehicle_id, "sync_odometer")

    async def async_press(self) -> None:
        """Sync this vehicle and surface failures in the UI."""
        result = (await self.coordinator.async_sync([self.vehicle_id]))[0]
        if result["status"] not in (STATUS_SYNCED, STATUS_UP_TO_DATE):
            raise HomeAssistantError(
                f"Odometer not synced: {result['status']}"
                + (f" ({result['error']})" if "error" in result else "")
            )
