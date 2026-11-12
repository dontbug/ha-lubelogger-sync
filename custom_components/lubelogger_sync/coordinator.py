"""Data coordinator and odometer sync logic for LubeLogger Sync."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import TemplateError
from homeassistant.helpers.template import Template
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import LubeLoggerApi, LubeLoggerError
from .const import (
    CONF_ATTRIBUTE,
    CONF_ENTITY_ID,
    CONF_MAX_INCREASE,
    CONF_MULTIPLIER,
    CONF_NOTES,
    CONF_OFFSET,
    CONF_TEMPLATE,
    CONF_VEHICLES,
    DEFAULT_MAX_INCREASE,
    DEFAULT_NOTES,
    DOMAIN,
    DUE_URGENCIES,
    STATUS_ERROR,
    STATUS_NOT_CONFIGURED,
    STATUS_REJECTED,
    STATUS_SOURCE_UNAVAILABLE,
    STATUS_SYNCED,
    STATUS_UP_TO_DATE,
    UPDATE_INTERVAL,
    URGENCIES,
    URGENCY_MAP,
)

_LOGGER = logging.getLogger(__name__)

type LubeLoggerConfigEntry = ConfigEntry[LubeLoggerCoordinator]


@dataclass(slots=True)
class VehicleData:
    """State of one LubeLogger vehicle."""

    id: int
    name: str
    license_plate: str | None
    odometer: int | None
    url: str
    reminders: list[dict[str, Any]] = field(default_factory=list)

    def by_urgency(self, urgency: str) -> list[dict[str, Any]]:
        """Return the reminders with the given urgency."""
        return [r for r in self.reminders if r["urgency"] == urgency]

    @property
    def due(self) -> list[dict[str, Any]]:
        """Return reminders that are past due, very urgent or urgent."""
        return [r for r in self.reminders if r["urgency"] in DUE_URGENCIES]


def _as_int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def normalize_reminder(raw: dict[str, Any]) -> dict[str, Any]:
    """Convert a LubeLogger reminder into a flat, automation-friendly dict.

    LubeLogger fills the unused metric with placeholder values (a date for
    odometer-only reminders, 0 for date-only ones), so those are blanked out.
    """
    metric = str(raw.get("metric") or "").lower()
    by_date = metric in ("date", "both")
    by_odometer = metric in ("odometer", "both")
    return {
        "id": _as_int(raw.get("id")),
        "description": raw.get("description") or "",
        "urgency": URGENCY_MAP.get(str(raw.get("urgency")), "not_urgent"),
        "metric": metric,
        "due_date": (raw.get("dueDate") or None) if by_date else None,
        "due_days": _as_int(raw.get("dueDays")) if by_date else None,
        "due_odometer": _as_int(raw.get("dueOdometer")) if by_odometer else None,
        "due_distance": _as_int(raw.get("dueDistance")) if by_odometer else None,
        "notes": raw.get("notes") or "",
        "tags": raw.get("tags") or "",
    }


def _reminder_sort_key(reminder: dict[str, Any]) -> tuple[int, float]:
    remaining = [
        v for v in (reminder["due_days"], reminder["due_distance"]) if v is not None
    ]
    return (URGENCIES.index(reminder["urgency"]), min(remaining, default=0))


def vehicle_name(data: dict[str, Any]) -> str:
    """Build a display name the same way LubeLogger does (year make model)."""
    parts = [data.get("year"), data.get("make"), data.get("model")]
    name = " ".join(str(p) for p in parts if p)
    return name or f"Vehicle {data.get('id')}"


class LubeLoggerCoordinator(DataUpdateCoordinator[dict[int, VehicleData]]):
    """Fetch vehicles and reminders, and push odometer readings."""

    config_entry: LubeLoggerConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: LubeLoggerConfigEntry, api: LubeLoggerApi
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.api = api
        self.last_sync: dict[int, dict[str, Any]] = {}

    async def _async_update_data(self) -> dict[int, VehicleData]:
        try:
            info = await self.api.vehicle_info()
            reminders = await self.api.reminders()
        except LubeLoggerError as err:
            raise UpdateFailed(str(err)) from err

        vehicles: dict[int, VehicleData] = {}
        for item in info:
            data = item.get("vehicleData") or {}
            vehicle_id = _as_int(data.get("id"))
            if vehicle_id is None:
                continue
            vehicles[vehicle_id] = VehicleData(
                id=vehicle_id,
                name=vehicle_name(data),
                license_plate=data.get("licensePlate") or None,
                odometer=_as_int(item.get("lastReportedOdometer")),
                url=f"{self.api.url}/Vehicle/Index?vehicleId={vehicle_id}",
            )

        for raw in reminders:
            vehicle = vehicles.get(_as_int(raw.get("vehicleId")) or -1)
            if vehicle is not None:
                vehicle.reminders.append(normalize_reminder(raw))
        for vehicle in vehicles.values():
            vehicle.reminders.sort(key=_reminder_sort_key)
        return vehicles

    # ----------------------------------------------------------------- sync

    def mapping(self, vehicle_id: int) -> dict[str, Any] | None:
        """Return the odometer source mapping of a vehicle, if configured."""
        mapping = self.config_entry.options.get(CONF_VEHICLES, {}).get(str(vehicle_id))
        if mapping and (mapping.get(CONF_ENTITY_ID) or mapping.get(CONF_TEMPLATE)):
            return mapping
        return None

    @staticmethod
    def source_label(mapping: dict[str, Any]) -> str:
        """Describe where the odometer value of a mapping comes from."""
        if mapping.get(CONF_TEMPLATE):
            return "template"
        if attribute := mapping.get(CONF_ATTRIBUTE):
            return f"{mapping[CONF_ENTITY_ID]}[{attribute}]"
        return mapping[CONF_ENTITY_ID]

    def read_source(self, mapping: dict[str, Any]) -> int | None:
        """Read the odometer value from the mapped template or entity.

        A template takes precedence and its result is used as-is; multiplier
        and offset only apply to entity/attribute sources.
        """
        if template := mapping.get(CONF_TEMPLATE):
            try:
                rendered = Template(template, self.hass).async_render(
                    parse_result=False
                )
                return round(float(str(rendered).strip()))
            except (TemplateError, TypeError, ValueError, OverflowError) as err:
                _LOGGER.debug("Odometer template did not yield a number: %s", err)
                return None
        state = self.hass.states.get(mapping[CONF_ENTITY_ID])
        if state is None:
            return None
        if attribute := mapping.get(CONF_ATTRIBUTE):
            raw = state.attributes.get(attribute)
        elif state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return None
        else:
            raw = state.state
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None
        value = value * float(mapping.get(CONF_MULTIPLIER, 1)) + float(
            mapping.get(CONF_OFFSET, 0)
        )
        try:
            return round(value)
        except (ValueError, OverflowError):  # nan / inf
            return None

    async def async_sync_vehicle(self, vehicle_id: int) -> dict[str, Any]:
        """Push the mapped odometer value of one vehicle to LubeLogger."""
        result = await self._async_sync_vehicle(vehicle_id)
        vehicle = (self.data or {}).get(vehicle_id)
        result = {
            "vehicle_id": vehicle_id,
            "vehicle": vehicle.name if vehicle else None,
            **result,
        }
        self.last_sync[vehicle_id] = {**result, "time": dt_util.utcnow()}
        if result["status"] == STATUS_SYNCED:
            _LOGGER.info("Odometer synced to LubeLogger: %s", result)
        elif result["status"] != STATUS_UP_TO_DATE:
            _LOGGER.warning("Odometer not synced to LubeLogger: %s", result)
        return result

    async def _async_sync_vehicle(self, vehicle_id: int) -> dict[str, Any]:
        mapping = self.mapping(vehicle_id)
        if mapping is None:
            return {"status": STATUS_NOT_CONFIGURED}
        value = self.read_source(mapping)
        if value is None:
            return {
                "status": STATUS_SOURCE_UNAVAILABLE,
                "source": self.source_label(mapping),
            }
        try:
            previous = await self.api.latest_odometer(vehicle_id)
            result: dict[str, Any] = {"odometer": value, "previous": previous}
            if value <= previous:
                return {"status": STATUS_UP_TO_DATE, **result}
            max_increase = self.config_entry.options.get(
                CONF_MAX_INCREASE, DEFAULT_MAX_INCREASE
            )
            # A vehicle without any odometer record (0) gets its first value freely.
            if previous > 0 and max_increase and value - previous > max_increase:
                return {"status": STATUS_REJECTED, **result}
            await self.api.add_odometer(
                vehicle_id,
                date=dt_util.now().date().isoformat(),
                odometer=value,
                initial_odometer=previous,
                notes=self.config_entry.options.get(CONF_NOTES, DEFAULT_NOTES),
            )
        except LubeLoggerError as err:
            return {"status": STATUS_ERROR, "error": str(err)}
        return {"status": STATUS_SYNCED, "distance": value - previous, **result}

    async def async_sync(
        self, vehicle_ids: list[int] | None = None
    ) -> list[dict[str, Any]]:
        """Sync the given vehicles (default: all mapped ones), then refresh."""
        if vehicle_ids is None:
            vehicle_ids = [v for v in (self.data or {}) if self.mapping(v)]
        results = [await self.async_sync_vehicle(v) for v in vehicle_ids]
        # LubeLogger derives reminder urgency from the latest odometer, so the
        # reminders must be re-read after writing.
        await self.async_refresh()
        return results

    async def async_add_odometer(
        self, vehicle_id: int, odometer: int, notes: str, date: str | None = None
    ) -> dict[str, Any]:
        """Add an explicit odometer record (ISO date, default today), then refresh."""
        previous = await self.api.latest_odometer(vehicle_id)
        day = date or dt_util.now().date().isoformat()
        await self.api.add_odometer(
            vehicle_id,
            date=day,
            odometer=odometer,
            initial_odometer=previous,
            notes=notes,
        )
        await self.async_refresh()
        return {
            "vehicle_id": vehicle_id,
            "status": STATUS_SYNCED,
            "odometer": odometer,
            "previous": previous,
            "date": day,
        }
