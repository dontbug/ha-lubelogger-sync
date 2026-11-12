"""Sensors for LubeLogger Sync."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfLength
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .config_flow import default_unit
from .const import CONF_UNIT, DUE_URGENCIES, URGENCIES
from .coordinator import LubeLoggerConfigEntry, LubeLoggerCoordinator
from .entity import LubeLoggerEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LubeLoggerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create the sensors of every vehicle."""
    coordinator = entry.runtime_data
    unit = entry.options.get(
        CONF_UNIT,
        default_unit(hass.config.units.length_unit == UnitOfLength.KILOMETERS),
    )
    entities: list[SensorEntity] = []
    for vehicle_id in coordinator.data:
        entities.append(OdometerSensor(coordinator, vehicle_id, unit))
        entities.append(DueRemindersSensor(coordinator, vehicle_id))
        entities.extend(
            UrgencySensor(coordinator, vehicle_id, urgency) for urgency in URGENCIES
        )
        entities.append(LastSyncSensor(coordinator, vehicle_id))
    async_add_entities(entities)


class OdometerSensor(LubeLoggerEntity, SensorEntity):
    """Latest odometer reading known to LubeLogger."""

    _attr_device_class = SensorDeviceClass.DISTANCE
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_suggested_display_precision = 0

    def __init__(
        self, coordinator: LubeLoggerCoordinator, vehicle_id: int, unit: str
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, vehicle_id, "odometer")
        self._attr_native_unit_of_measurement = unit

    @property
    def native_value(self) -> int | None:
        """Return the odometer reading."""
        return self.vehicle.odometer if self.vehicle else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Describe the configured source and its current value."""
        mapping = self.coordinator.mapping(self.vehicle_id)
        if mapping is None:
            return {"source": None, "source_value": None}
        return {
            "source": self.coordinator.source_label(mapping),
            "source_value": self.coordinator.read_source(mapping),
        }


class DueRemindersSensor(LubeLoggerEntity, SensorEntity):
    """Number of reminders that are past due, very urgent or urgent."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: LubeLoggerCoordinator, vehicle_id: int) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, vehicle_id, "reminders_due")

    @property
    def native_value(self) -> int | None:
        """Return the number of reminders needing attention."""
        return len(self.vehicle.due) if self.vehicle else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the reminders grouped by urgency."""
        if (vehicle := self.vehicle) is None:
            return None
        return {
            "vehicle": vehicle.name,
            "url": vehicle.url,
            **{urgency: vehicle.by_urgency(urgency) for urgency in DUE_URGENCIES},
        }


class UrgencySensor(LubeLoggerEntity, SensorEntity):
    """Number of reminders with one urgency level; the list is in attributes."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self, coordinator: LubeLoggerCoordinator, vehicle_id: int, urgency: str
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, vehicle_id, urgency)
        self._urgency = urgency
        # The full "not urgent" list is rarely needed and can be long.
        self._attr_entity_registry_enabled_default = urgency in DUE_URGENCIES

    @property
    def native_value(self) -> int | None:
        """Return the number of reminders with this urgency."""
        return len(self.vehicle.by_urgency(self._urgency)) if self.vehicle else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the reminders with this urgency."""
        if (vehicle := self.vehicle) is None:
            return None
        return {"reminders": vehicle.by_urgency(self._urgency), "url": vehicle.url}


class LastSyncSensor(LubeLoggerEntity, SensorEntity):
    """When the odometer sync last ran for this vehicle, and its outcome."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: LubeLoggerCoordinator, vehicle_id: int) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, vehicle_id, "last_sync")

    @property
    def native_value(self) -> datetime | None:
        """Return the time of the last sync attempt (since HA started)."""
        return self.coordinator.last_sync.get(self.vehicle_id, {}).get("time")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the outcome of the last sync attempt."""
        last = self.coordinator.last_sync.get(self.vehicle_id, {})
        return {k: v for k, v in last.items() if k not in ("time", "vehicle_id")}
