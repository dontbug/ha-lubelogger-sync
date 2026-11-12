"""Constants for the LubeLogger Sync integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "lubelogger_sync"

UPDATE_INTERVAL: Final = timedelta(minutes=15)
REQUEST_TIMEOUT: Final = 20

# Options
CONF_VEHICLES: Final = "vehicles"
CONF_VEHICLE: Final = "vehicle"
CONF_ENTITY_ID: Final = "entity_id"
CONF_ATTRIBUTE: Final = "attribute"
CONF_TEMPLATE: Final = "template"
CONF_MULTIPLIER: Final = "multiplier"
CONF_OFFSET: Final = "offset"
CONF_SCHEDULE: Final = "schedule"
CONF_TIME: Final = "time"
CONF_NOTES: Final = "notes"
CONF_MAX_INCREASE: Final = "max_increase"
CONF_UNIT: Final = "unit"

SCHEDULE_OFF: Final = "off"
SCHEDULE_DAILY: Final = "daily"
WEEKDAYS: Final = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
SCHEDULES: Final = [SCHEDULE_OFF, SCHEDULE_DAILY, *WEEKDAYS]

DEFAULT_SCHEDULE: Final = "mon"
DEFAULT_TIME: Final = "08:00:00"
DEFAULT_NOTES: Final = "Auto-sync from Home Assistant"
DEFAULT_MAX_INCREASE: Final = 10000

# Attribute exposed by the Traccar integrations (metres).
TRACCAR_DISTANCE_ATTRIBUTE: Final = "totalDistance"

# Urgency levels, most urgent first. Keys are the values returned by LubeLogger.
URGENCY_MAP: Final = {
    "PastDue": "past_due",
    "VeryUrgent": "very_urgent",
    "Urgent": "urgent",
    "NotUrgent": "not_urgent",
}
URGENCIES: Final = list(URGENCY_MAP.values())
DUE_URGENCIES: Final = ["past_due", "very_urgent", "urgent"]

# Sync result statuses
STATUS_SYNCED: Final = "synced"
STATUS_UP_TO_DATE: Final = "up_to_date"
STATUS_NOT_CONFIGURED: Final = "not_configured"
STATUS_SOURCE_UNAVAILABLE: Final = "source_unavailable"
STATUS_REJECTED: Final = "rejected_increase_too_large"
STATUS_ERROR: Final = "error"

SERVICE_SYNC_ODOMETER: Final = "sync_odometer"
SERVICE_ADD_ODOMETER: Final = "add_odometer"
SERVICE_GET_REMINDERS: Final = "get_reminders"
