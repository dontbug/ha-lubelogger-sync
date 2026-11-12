"""Base entity for LubeLogger Sync."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import LubeLoggerCoordinator, VehicleData
from .services import device_identifier


class LubeLoggerEntity(CoordinatorEntity[LubeLoggerCoordinator]):
    """An entity that belongs to one LubeLogger vehicle."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: LubeLoggerCoordinator, vehicle_id: int, key: str
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.vehicle_id = vehicle_id
        entry_id = coordinator.config_entry.entry_id
        vehicle = coordinator.data[vehicle_id]
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry_id}_{vehicle_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={device_identifier(entry_id, vehicle_id)},
            name=vehicle.name,
            manufacturer="LubeLogger",
            serial_number=vehicle.license_plate,
            configuration_url=vehicle.url,
        )

    @property
    def vehicle(self) -> VehicleData | None:
        """Return the current data of this entity's vehicle."""
        return self.coordinator.data.get(self.vehicle_id)

    @property
    def available(self) -> bool:
        """Return True if the vehicle still exists in LubeLogger."""
        return super().available and self.vehicle is not None
