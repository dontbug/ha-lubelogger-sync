"""Services of the LubeLogger Sync integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr

from .api import LubeLoggerError
from .const import (
    CONF_NOTES,
    DEFAULT_NOTES,
    DOMAIN,
    DUE_URGENCIES,
    SERVICE_ADD_ODOMETER,
    SERVICE_GET_REMINDERS,
    SERVICE_SYNC_ODOMETER,
    URGENCIES,
)
from .coordinator import LubeLoggerCoordinator

ATTR_ODOMETER = "odometer"
ATTR_NOTES = "notes"
ATTR_DATE = "date"
ATTR_URGENCIES = "urgencies"
ATTR_REFRESH = "refresh"

_DEVICES = vol.All(cv.ensure_list, [cv.string])

SYNC_SCHEMA = vol.Schema({vol.Optional(ATTR_DEVICE_ID): _DEVICES})
ADD_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.string,
        vol.Required(ATTR_ODOMETER): vol.All(vol.Coerce(int), vol.Range(min=0)),
        vol.Optional(ATTR_NOTES): cv.string,
        vol.Optional(ATTR_DATE): cv.date,
    }
)
REMINDERS_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_DEVICE_ID): _DEVICES,
        vol.Optional(ATTR_URGENCIES, default=DUE_URGENCIES): vol.All(
            cv.ensure_list, [vol.In(URGENCIES)]
        ),
        vol.Optional(ATTR_REFRESH, default=True): cv.boolean,
    }
)

Targets = dict[LubeLoggerCoordinator, list[int] | None]


def device_identifier(entry_id: str, vehicle_id: int) -> tuple[str, str]:
    """Return the device registry identifier of a vehicle."""
    return (DOMAIN, f"{entry_id}_{vehicle_id}")


def _coordinators(hass: HomeAssistant) -> dict[str, LubeLoggerCoordinator]:
    loaded = {
        entry.entry_id: entry.runtime_data
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
    }
    if not loaded:
        raise ServiceValidationError("LubeLogger Sync is not set up or not loaded")
    return loaded


def _resolve_targets(hass: HomeAssistant, device_ids: list[str] | None) -> Targets:
    """Map selected devices to vehicles; None means 'all vehicles of the entry'."""
    coordinators = _coordinators(hass)
    if not device_ids:
        return {coordinator: None for coordinator in coordinators.values()}

    registry = dr.async_get(hass)
    targets: Targets = {}
    for device_id in device_ids:
        device = registry.async_get(device_id)
        match = None
        for domain, identifier in device.identifiers if device else ():
            entry_id, _, vehicle_id = identifier.rpartition("_")
            if domain == DOMAIN and entry_id in coordinators and vehicle_id.isdigit():
                match = (coordinators[entry_id], int(vehicle_id))
        if match is None:
            raise ServiceValidationError(
                f"Device {device_id} is not a loaded LubeLogger vehicle"
            )
        targets.setdefault(match[0], [])
        targets[match[0]].append(match[1])  # type: ignore[union-attr]
    return targets


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register services."""

    async def sync_odometer(call: ServiceCall) -> ServiceResponse:
        results: list[dict[str, Any]] = []
        for coordinator, vehicle_ids in _resolve_targets(
            hass, call.data.get(ATTR_DEVICE_ID)
        ).items():
            results.extend(await coordinator.async_sync(vehicle_ids))
        return {"results": results}

    async def add_odometer(call: ServiceCall) -> ServiceResponse:
        targets = _resolve_targets(hass, [call.data[ATTR_DEVICE_ID]])
        coordinator, vehicle_ids = next(iter(targets.items()))
        assert vehicle_ids
        date = call.data.get(ATTR_DATE)
        try:
            return await coordinator.async_add_odometer(
                vehicle_ids[0],
                call.data[ATTR_ODOMETER],
                call.data.get(
                    ATTR_NOTES,
                    coordinator.config_entry.options.get(CONF_NOTES, DEFAULT_NOTES),
                ),
                date.isoformat() if date else None,
            )
        except LubeLoggerError as err:
            raise HomeAssistantError(str(err)) from err

    async def get_reminders(call: ServiceCall) -> ServiceResponse:
        urgencies = [u for u in URGENCIES if u in call.data[ATTR_URGENCIES]]
        vehicles: list[dict[str, Any]] = []
        flat: list[dict[str, Any]] = []
        for coordinator, vehicle_ids in _resolve_targets(
            hass, call.data.get(ATTR_DEVICE_ID)
        ).items():
            if call.data[ATTR_REFRESH]:
                await coordinator.async_refresh()
            for vehicle in (coordinator.data or {}).values():
                if vehicle_ids is not None and vehicle.id not in vehicle_ids:
                    continue
                grouped = {u: vehicle.by_urgency(u) for u in urgencies}
                vehicles.append(
                    {
                        "vehicle_id": vehicle.id,
                        "vehicle": vehicle.name,
                        "license_plate": vehicle.license_plate,
                        "odometer": vehicle.odometer,
                        "url": vehicle.url,
                        "count": sum(len(items) for items in grouped.values()),
                        **grouped,
                    }
                )
                flat.extend(
                    {"vehicle_id": vehicle.id, "vehicle": vehicle.name, **reminder}
                    for items in grouped.values()
                    for reminder in items
                )
        return {"count": len(flat), "vehicles": vehicles, "reminders": flat}

    hass.services.async_register(
        DOMAIN,
        SERVICE_SYNC_ODOMETER,
        sync_odometer,
        schema=SYNC_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_ADD_ODOMETER,
        add_odometer,
        schema=ADD_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_REMINDERS,
        get_reminders,
        schema=REMINDERS_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
