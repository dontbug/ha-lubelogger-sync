"""Binary sensors for LubeLogger Sync."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import UnitOfLength
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .config_flow import default_unit
from .const import CONF_UNIT, DUE_URGENCIES
from .coordinator import LubeLoggerConfigEntry, LubeLoggerCoordinator
from .entity import LubeLoggerEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LubeLoggerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create one 'maintenance due' sensor per vehicle."""
    coordinator = entry.runtime_data
    unit = entry.options.get(
        CONF_UNIT,
        default_unit(hass.config.units.length_unit == UnitOfLength.KILOMETERS),
    )
    async_add_entities(
        MaintenanceDueSensor(coordinator, vehicle_id, unit)
        for vehicle_id in coordinator.data
    )


class MaintenanceDueSensor(LubeLoggerEntity, BinarySensorEntity):
    """On when any reminder is past due, very urgent or urgent."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(
        self, coordinator: LubeLoggerCoordinator, vehicle_id: int, unit: str
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, vehicle_id, "maintenance_due")
        self._unit = unit

    @property
    def is_on(self) -> bool | None:
        """Return True if something needs attention."""
        return bool(self.vehicle.due) if self.vehicle else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return what needs attention, as readable text and as full lists."""
        if (vehicle := self.vehicle) is None:
            return None
        lines = []
        for reminder in vehicle.due:
            remaining = []
            if reminder["due_distance"] is not None:
                remaining.append(f"{reminder['due_distance']} {self._unit}")
            if reminder["due_days"] is not None:
                remaining.append(f"{reminder['due_days']} d")
            lines.append(
                reminder["description"]
                + (f" ({', '.join(remaining)})" if remaining else "")
            )
        return {
            "summary": "\n".join(lines),
            "items": lines,
            **{urgency: vehicle.by_urgency(urgency) for urgency in DUE_URGENCIES},
            "url": vehicle.url,
        }
