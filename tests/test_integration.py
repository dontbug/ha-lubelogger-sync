"""Tests for LubeLogger Sync, using responses captured from LubeLogger 1.7.4."""

from __future__ import annotations

from datetime import timedelta
import json

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util

from custom_components.lubelogger_sync.const import DOMAIN

URL = "http://lube.test:8080"
HEADERS = {"x-api-key": "key", "culture-invariant": "true"}


def _vehicle(vid, year, make, model, odo, past_due=0):
    return {
        "vehicleData": {
            "id": vid,
            "year": year,
            "make": make,
            "model": model,
            "licensePlate": f"PLATE{vid}",
        },
        "pastDueReminderCount": past_due,
        "lastReportedOdometer": odo,
    }


def _reminder(vid, rid, desc, urgency, metric, **kw):
    return {
        "vehicleId": vid,
        "id": rid,
        "description": desc,
        "urgency": urgency,
        "metric": metric,
        "userMetric": metric,
        "notes": None,
        "dueDate": kw.get("date", "2026-08-09"),
        "dueOdometer": kw.get("odo", 0),
        "dueDays": kw.get("days", 0),
        "dueDistance": kw.get("dist", 0),
        "tags": "",
    }


REMINDERS = [
    _reminder(1, 5, "Oil change", "NotUrgent", "Odometer", odo=130000, dist=9500),
    _reminder(1, 7, "Insurance", "Urgent", "Date", date="2026-12-01", days=19),
    _reminder(1, 2, "Timing belt", "PastDue", "Odometer", odo=110000, dist=-10500),
    _reminder(2, 9, "Brake pads", "NotUrgent", "Odometer", odo=50000, dist=4800),
]


class FakeLubeLogger:
    """In-memory LubeLogger behind aioclient_mock."""

    def __init__(self, mock) -> None:
        self.odometers = {1: 120500, 2: 45200}
        self.added: list[tuple[int, dict]] = []
        mock.get(f"{URL}/api/vehicle/info", side_effect=self._info)
        mock.get(f"{URL}/api/vehicle/reminders/all", json=REMINDERS)
        mock.get(f"{URL}/api/vehicle/odometerrecords/latest", side_effect=self._latest)
        mock.post(f"{URL}/api/vehicle/odometerrecords/add", side_effect=self._add)

    async def _info(self, method, url, data):
        from pytest_homeassistant_custom_component.test_util.aiohttp import (
            AiohttpClientMockResponse,
        )

        body = [
            _vehicle(1, 2019, "Honda", "Civic", self.odometers[1], 1),
            _vehicle(2, 2021, "Skoda", "Octavia", self.odometers[2]),
        ]
        return AiohttpClientMockResponse(method, url, json=body)

    async def _latest(self, method, url, data):
        from pytest_homeassistant_custom_component.test_util.aiohttp import (
            AiohttpClientMockResponse,
        )

        vid = int(url.query["vehicleId"])
        return AiohttpClientMockResponse(method, url, text=str(self.odometers[vid]))

    async def _add(self, method, url, data):
        from pytest_homeassistant_custom_component.test_util.aiohttp import (
            AiohttpClientMockResponse,
        )

        vid = int(url.query["vehicleId"])
        self.added.append((vid, data))
        self.odometers[vid] = data["odometer"]
        return AiohttpClientMockResponse(
            method, url, json={"success": True, "message": "Odometer Record Added"}
        )


@pytest.fixture
def lube(aioclient_mock) -> FakeLubeLogger:
    return FakeLubeLogger(aioclient_mock)


async def _setup(hass: HomeAssistant, options: dict | None = None) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"url": URL, "api_key": "key"},
        options={"schedule": "off", **(options or {})},
        unique_id=URL,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


CAR_ONE = {
    "entity_id": "device_tracker.car_one",
    "attribute": "totalDistance",
    "multiplier": 0.001,
    "offset": 0,
}
CAR_TWO = {
    "template": "{{ (state_attr('device_tracker.car_two', 'totalDistance') / 1000)"
    " | round(0) }}"
}


def _set_trackers(hass: HomeAssistant, car_one=120671400.0, car_two=45314100.0) -> None:
    hass.states.async_set("device_tracker.car_one", "home", {"totalDistance": car_one})
    hass.states.async_set("device_tracker.car_two", "home", {"totalDistance": car_two})


async def test_config_flow(hass: HomeAssistant, lube, aioclient_mock) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"url": URL + "/", "api_key": " key "}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"url": URL, "api_key": "key"}
    assert result["title"] == "LubeLogger (lube.test)"
    assert aioclient_mock.mock_calls[0][3]["x-api-key"] == "key"


async def test_config_flow_invalid_key(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(f"{URL}/api/vehicle/info", status=401, text="<html>")
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"url": URL, "api_key": "bad"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_sensors(hass: HomeAssistant, lube) -> None:
    await _setup(hass, {"unit": "km"})
    odo = hass.states.get("sensor.2019_honda_civic_odometer")
    assert odo.state == "120500"
    assert odo.attributes["unit_of_measurement"] == "km"

    due = hass.states.get("sensor.2019_honda_civic_reminders_due")
    assert due.state == "2"
    past = due.attributes["past_due"]
    assert [r["description"] for r in past] == ["Timing belt"]
    # Odometer reminder: placeholder date dropped, distance kept.
    assert past[0]["due_distance"] == -10500
    assert past[0]["due_odometer"] == 110000
    assert past[0]["due_date"] is None
    urgent = due.attributes["urgent"][0]
    assert urgent["due_date"] == "2026-12-01"
    assert urgent["due_days"] == 19
    assert urgent["due_odometer"] is None
    assert due.attributes["very_urgent"] == []
    assert due.attributes["url"] == f"{URL}/Vehicle/Index?vehicleId=1"

    assert hass.states.get("sensor.2019_honda_civic_past_due_reminders").state == "1"
    problem = hass.states.get("binary_sensor.2019_honda_civic_maintenance_due")
    assert problem.state == "on"
    assert problem.attributes["items"] == ["Timing belt (-10500 km)", "Insurance (19 d)"]
    assert problem.attributes["summary"] == "Timing belt (-10500 km)\nInsurance (19 d)"
    assert [r["description"] for r in problem.attributes["past_due"]] == ["Timing belt"]
    assert hass.states.get("binary_sensor.2021_skoda_octavia_maintenance_due").state == "off"
    assert hass.states.get("sensor.2021_skoda_octavia_reminders_due").state == "0"


async def test_sync_attribute_and_template(hass: HomeAssistant, lube) -> None:
    _set_trackers(hass)
    await _setup(hass, {"vehicles": {"1": CAR_ONE, "2": CAR_TWO}, "notes": "From tracker"})

    response = await hass.services.async_call(
        DOMAIN, "sync_odometer", {}, blocking=True, return_response=True
    )
    by_id = {r["vehicle_id"]: r for r in response["results"]}
    assert by_id[1]["status"] == "synced"
    assert by_id[1] | {"odometer": 120671, "previous": 120500, "distance": 171} == by_id[1]
    assert by_id[2]["status"] == "synced"
    assert by_id[2]["odometer"] == 45314

    today = dt_util.now().date().isoformat()
    assert lube.added[0] == (
        1,
        {
            "date": today,
            "initialOdometer": 120500,
            "odometer": 120671,
            "notes": "From tracker",
        },
    )
    # Sensors reflect the new value straight away.
    assert hass.states.get("sensor.2019_honda_civic_odometer").state == "120671"

    # A second run adds nothing.
    response = await hass.services.async_call(
        DOMAIN, "sync_odometer", {}, blocking=True, return_response=True
    )
    assert {r["status"] for r in response["results"]} == {"up_to_date"}
    assert len(lube.added) == 2


async def test_sync_guards(hass: HomeAssistant, lube) -> None:
    # Car one: forgot the multiplier -> absurd jump. Car two: tracker missing.
    hass.states.async_set("device_tracker.car_one", "home", {"totalDistance": 120671400})
    await _setup(
        hass,
        {"vehicles": {"1": {**CAR_ONE, "multiplier": 1}, "2": CAR_TWO}},
    )
    response = await hass.services.async_call(
        DOMAIN, "sync_odometer", {}, blocking=True, return_response=True
    )
    by_id = {r["vehicle_id"]: r for r in response["results"]}
    assert by_id[1]["status"] == "rejected_increase_too_large"
    assert by_id[2]["status"] == "source_unavailable"
    assert lube.added == []

    # Unavailable tracker without attributes.
    hass.states.async_set("device_tracker.car_one", "unavailable", {})
    response = await hass.services.async_call(
        DOMAIN, "sync_odometer", {}, blocking=True, return_response=True
    )
    assert {r["status"] for r in response["results"]} == {"source_unavailable"}
    assert lube.added == []


async def test_sync_selected_device_and_button(hass: HomeAssistant, lube) -> None:
    _set_trackers(hass)
    entry = await _setup(hass, {"vehicles": {"1": CAR_ONE, "2": CAR_TWO}})
    device = dr.async_get(hass).async_get_device(
        identifiers={(DOMAIN, f"{entry.entry_id}_2")}
    )
    await hass.services.async_call(
        DOMAIN, "sync_odometer", {"device_id": [device.id]}, blocking=True
    )
    assert [vid for vid, _ in lube.added] == [2]

    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": "button.2019_honda_civic_sync_odometer"},
        blocking=True,
    )
    assert [vid for vid, _ in lube.added] == [2, 1]
    last = hass.states.get("sensor.2019_honda_civic_last_odometer_sync")
    assert last.attributes["status"] == "synced"


async def test_get_reminders(hass: HomeAssistant, lube) -> None:
    await _setup(hass)
    response = await hass.services.async_call(
        DOMAIN, "get_reminders", {}, blocking=True, return_response=True
    )
    json.dumps(response)  # must be serialisable for automations
    assert response["count"] == 2
    assert [r["description"] for r in response["reminders"]] == ["Timing belt", "Insurance"]
    first, second = response["vehicles"]
    assert first["vehicle"] == "2019 Honda Civic"
    assert first["count"] == 2 and second["count"] == 0
    assert "not_urgent" not in first

    response = await hass.services.async_call(
        DOMAIN,
        "get_reminders",
        {"urgencies": ["not_urgent"]},
        blocking=True,
        return_response=True,
    )
    assert response["count"] == 2


async def test_add_odometer(hass: HomeAssistant, lube) -> None:
    entry = await _setup(hass)
    device = dr.async_get(hass).async_get_device(
        identifiers={(DOMAIN, f"{entry.entry_id}_1")}
    )
    await hass.services.async_call(
        DOMAIN,
        "add_odometer",
        {"device_id": device.id, "odometer": 121000, "date": "2026-11-10"},
        blocking=True,
    )
    assert lube.added == [
        (
            1,
            {
                "date": "2026-11-10",
                "initialOdometer": 120500,
                "odometer": 121000,
                "notes": "Auto-sync from Home Assistant",
            },
        )
    ]


async def test_weekly_schedule(hass: HomeAssistant, lube, freezer) -> None:
    # Thursday 2026-11-12; schedule Monday 08:00 local time.
    freezer.move_to(dt_util.as_utc(dt_util.parse_datetime("2026-11-12T07:59:00").replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)))
    _set_trackers(hass)
    await _setup(
        hass, {"vehicles": {"1": CAR_ONE}, "schedule": "mon", "time": "08:00:00"}
    )
    for day in ("2026-11-12", "2026-11-13"):
        when = dt_util.parse_datetime(f"{day}T08:00:00").replace(
            tzinfo=dt_util.DEFAULT_TIME_ZONE
        )
        freezer.move_to(when)
        async_fire_time_changed(hass, when)
        await hass.async_block_till_done()
    assert lube.added == []

    monday = dt_util.parse_datetime("2026-11-16T08:00:00").replace(
        tzinfo=dt_util.DEFAULT_TIME_ZONE
    )
    freezer.move_to(monday)
    async_fire_time_changed(hass, monday)
    await hass.async_block_till_done()
    assert [vid for vid, _ in lube.added] == [1]


async def test_options_flow_traccar_defaults(hass: HomeAssistant, lube) -> None:
    _set_trackers(hass)
    entry = await _setup(hass)
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    assert flow["type"] is FlowResultType.MENU
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"next_step_id": "vehicle"}
    )
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"vehicle": "1"}
    )
    assert flow["step_id"] == "source"
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"entity_id": "device_tracker.car_one"}
    )
    assert flow["step_id"] == "entity"
    # Traccar attribute and metre->km multiplier are pre-filled; preview is shown.
    assert flow["description_placeholders"]["preview"] == "120671"
    assert flow["description_placeholders"]["odometer"] == "120500"
    suggested = {
        str(k): k.description["suggested_value"] for k in flow["data_schema"].schema
    }
    assert suggested == {"attribute": "totalDistance", "multiplier": 0.001, "offset": 0}
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], suggested)
    assert flow["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["vehicles"] == {"1": CAR_ONE}
    assert entry.options["schedule"] == "off"  # untouched


async def test_options_flow_template(hass: HomeAssistant, lube) -> None:
    entry = await _setup(hass)
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"next_step_id": "vehicle"}
    )
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"vehicle": "2"}
    )
    # Tracker does not exist yet -> template cannot render a number.
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"template": CAR_TWO["template"]}
    )
    assert flow["errors"] == {"template": "template_not_number"}
    _set_trackers(hass)
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"template": CAR_TWO["template"]}
    )
    assert flow["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["vehicles"] == {"2": CAR_TWO}
