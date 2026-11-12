# LubeLogger Sync for Home Assistant

A Home Assistant integration for [LubeLogger](https://lubelogger.com) that does two things:

1. **Pushes the odometer to LubeLogger** from any Home Assistant source – a Traccar device tracker attribute, a sensor, or a template – on a weekly/daily schedule or on demand.
2. **Exposes LubeLogger reminders by urgency** (Past Due, Very Urgent, Urgent) as sensors and as a service, so you can build your own notifications (Telegram, mobile app, …).

Tested with LubeLogger 1.7.4. Requires Home Assistant 2025.1 or newer.

## Installation

### HACS

1. HACS → ⋮ → **Custom repositories**.
2. Add `https://github.com/dontbug/ha-lubelogger-sync`, type **Integration**.
3. Install **LubeLogger Sync** and restart Home Assistant.

### Manual

Copy `custom_components/lubelogger_sync` into the `custom_components` folder of your Home Assistant configuration and restart.

## Setup

### 1. Create an API key in LubeLogger

In LubeLogger open **Settings → API Keys** and create a key with the **Editor** role.
A Viewer key can read reminders but cannot add odometer records.

### 2. Add the integration

**Settings → Devices & services → Add integration → LubeLogger Sync**, then enter:

| Field | Example |
| --- | --- |
| LubeLogger URL | `http://192.168.1.10:8080` |
| API key | the key created above |

Every vehicle in your garage becomes a device.

### 3. Choose the odometer source of each vehicle

Open the integration and press **Configure → Odometer source of a vehicle**. Pick the vehicle, then choose one of:

| Source | How |
| --- | --- |
| **Attribute of an entity** (Traccar) | Select the device tracker, e.g. `device_tracker.my_car`. On the next step the `totalDistance` attribute and the multiplier `0.001` (metres → km) are pre-filled. |
| **State of a sensor** | Select the sensor and leave the attribute empty. Multiplier `0.001` is pre-filled when the sensor reports metres, otherwise `1`. |
| **Template** | Write a template that renders the final number. It overrides the entity; multiplier and offset are not applied. |

Template example:

```jinja
{{ (state_attr('device_tracker.my_car', 'totalDistance') / 1000) | round(0) }}
```

For entity sources the value sent is `value × multiplier + offset`. The form shows the value it would send next to the odometer LubeLogger currently has, so you can check it before saving. Use **offset** to correct the difference between the GPS distance and the real dashboard odometer.

Repeat for each vehicle. Leave both the entity and the template empty to stop syncing a vehicle.

### 4. Schedule and settings

**Configure → Sync schedule and settings**:

| Setting | Default | Meaning |
| --- | --- | --- |
| Automatic sync | Every Monday | Off, every day, or one weekday. |
| Time | 08:00 | Local time of the automatic sync. |
| Note | `Auto-sync from Home Assistant` | Text written in the Notes column of each odometer record. |
| Maximum increase per sync | 10000 | A larger jump is rejected (wrong multiplier, faulty source). `0` disables the check. |
| Odometer unit | km or mi, from your HA unit system | Unit shown on the odometer sensor. |

## How the sync behaves

- A record is added **only when the source value is higher** than the latest odometer in LubeLogger. Otherwise the result is `up_to_date` and nothing is written.
- If the source is missing, unavailable or not a number, nothing is written (`source_unavailable`).
- A jump larger than the configured maximum is rejected (`rejected_increase_too_large`). A vehicle with no odometer records yet accepts its first value freely.
- After writing, reminders are re-read, because LubeLogger calculates urgency from the latest odometer.

## Entities (per vehicle)

| Entity | Description |
| --- | --- |
| `sensor.<vehicle>_odometer` | Latest odometer in LubeLogger. Attributes: `source`, `source_value`. |
| `sensor.<vehicle>_reminders_due` | Number of Past Due + Very Urgent + Urgent reminders. Attributes: `past_due`, `very_urgent`, `urgent` (lists), `url`. |
| `sensor.<vehicle>_past_due_reminders` | Count; attribute `reminders` holds the list. |
| `sensor.<vehicle>_very_urgent_reminders` | Count; attribute `reminders` holds the list. |
| `sensor.<vehicle>_urgent_reminders` | Count; attribute `reminders` holds the list. |
| `sensor.<vehicle>_not_urgent_reminders` | Same, disabled by default. |
| `binary_sensor.<vehicle>_maintenance_due` | On when anything is Past Due, Very Urgent or Urgent. Attributes: `summary` (readable text, one reminder per line), `items` (the same lines as a list), `past_due`, `very_urgent`, `urgent`, `url`. |
| `button.<vehicle>_sync_odometer` | Sync this vehicle now. |
| `sensor.<vehicle>_last_odometer_sync` | Time and result of the last sync attempt (reset when Home Assistant restarts). |

Each reminder in the lists looks like this:

```yaml
id: 2
description: "Timing belt"
urgency: past_due          # past_due | very_urgent | urgent | not_urgent
metric: odometer           # odometer | date | both
due_odometer: 110000       # null for date-only reminders
due_distance: -10500       # negative = overdue; null for date-only reminders
due_date: null             # e.g. "2027-09-08"; null for odometer-only reminders
due_days: null             # null for odometer-only reminders
notes: ""
tags: ""
```

Data is refreshed every 15 minutes. Vehicles added to LubeLogger later appear after reloading the integration.

## Actions (services)

### `lubelogger_sync.sync_odometer`

Syncs all vehicles that have a source, or only the selected ones (`device_id`). Returns one result per vehicle:

```yaml
results:
  - vehicle_id: 1
    vehicle: 2019 Honda Civic
    status: synced            # synced | up_to_date | source_unavailable |
                              # rejected_increase_too_large | not_configured | error
    odometer: 120671
    previous: 120500
    distance: 171
```

### `lubelogger_sync.get_reminders`

Returns reminders for notifications. Fields: `device_id` (optional), `urgencies` (default `past_due`, `very_urgent`, `urgent`), `refresh` (default `true`).

```yaml
count: 1
vehicles:
  - vehicle_id: 1
    vehicle: 2019 Honda Civic
    license_plate: ABC123
    odometer: 120671
    url: http://192.168.1.10:8080/Vehicle/Index?vehicleId=1
    count: 1
    past_due: [ {...} ]
    very_urgent: []
    urgent: []
reminders:                    # the same reminders as one flat list
  - vehicle_id: 1
    vehicle: 2019 Honda Civic
    description: "Timing belt"
    urgency: past_due
    ...
```

### `lubelogger_sync.add_odometer`

Adds a record with an explicit value: `device_id`, `odometer`, optional `notes` and `date`.

## Example: weekly Telegram report

Syncs the odometer, then sends a message only when something needs attention. Adjust the notify action and chat ID to your setup. If you use this automation you can set **Automatic sync** to *Off*; leaving it on is harmless, the second sync simply reports `up_to_date`.

```yaml
alias: LubeLogger weekly report
triggers:
  - trigger: time
    at: "08:00:00"
conditions:
  - condition: time
    weekday: [mon]
actions:
  - action: lubelogger_sync.sync_odometer
    response_variable: sync
  - action: lubelogger_sync.get_reminders
    response_variable: lube
  - condition: template
    value_template: "{{ lube.count > 0 }}"
  - action: telegram_bot.send_message
    data:
      target: -1001234567890
      parse_mode: plain_text
      message: |-
        🚗 LubeLogger: {{ lube.count }} reminder(s) need attention
        {%- for v in lube.vehicles if v.count > 0 %}

        {{ v.vehicle }} ({{ v.odometer }} km)
        {%- for r in lube.reminders if r.vehicle_id == v.vehicle_id %}
        {{ {'past_due': '⚫ Past due', 'very_urgent': '🔴 Very urgent', 'urgent': '🟡 Urgent'}[r.urgency] }}: {{ r.description }}
        {%- if r.due_distance is not none %} ({{ r.due_distance }} km){% endif %}
        {%- if r.due_days is not none %} ({{ r.due_days }} days){% endif %}
        {%- endfor %}
        {{ v.url }}
        {%- endfor %}
```

Result:

```text
🚗 LubeLogger: 1 reminder(s) need attention

2019 Honda Civic (120671 km)
⚫ Past due: Timing belt (-10671 km)
http://192.168.1.10:8080/Vehicle/Index?vehicleId=1
```

A simpler trigger without the service: use `binary_sensor.<vehicle>_maintenance_due` turning on, and read the lists from the attributes of `sensor.<vehicle>_reminders_due`.

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| "LubeLogger rejected the API key" | Wrong key, or the key was deleted. |
| Sync result `error` with HTTP 401/403 | The key has the Viewer role; create an Editor key. |
| `source_unavailable` | The entity is unavailable, the attribute is missing, or the template does not render a number. |
| `rejected_increase_too_large` | Check the multiplier (Traccar needs `0.001`), or raise the limit in the settings. |
| Odometer drifts from the dashboard | GPS distance is an estimate; set an offset, or correct `totalDistance` in Traccar. |

## Development

```bash
pip install pytest-homeassistant-custom-component
pytest
```

## License

MIT. Not affiliated with LubeLogger or Hargata Softworks.
