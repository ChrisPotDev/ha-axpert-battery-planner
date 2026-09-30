# Axpert Battery Planner

Sunsynk/Deye-style **System Work Mode / battery plan** scheduling for Axpert, Voltronic, MPP Solar and other PI30-family inverters in Home Assistant.

These inverters have no time-of-use or SOC-target scheduling of their own. This integration adds six time slots, each with a start time, a target SOC and a grid-charge flag. It then controls the inverter's **output source priority** and **charger source priority** through the entities your existing Axpert integration already provides.

## Installation

### HACS (custom repository)
1. HACS → Integrations → ⋮ → *Custom repositories* → add this repository, category *Integration*.
2. Install **Axpert Battery Planner** and restart Home Assistant.

### Manual
Copy `custom_components/axpert_battery_planner` into `<config>/custom_components/` and restart.

Requires Home Assistant 2024.11 or newer.

## Setup

*Settings → Devices & services → Add integration → Axpert Battery Planner*

| Step | What you choose |
|---|---|
| 1. Inverter entities | Battery SOC sensor, optional battery voltage sensor, output source priority select, charger source priority select, optional max AC charge current number |
| 2. Mode mapping | The exact option labels your integration uses for SBU/SOL (discharge), USB/SUB (hold), OSO (grid charging blocked) and SNU/UTI (grid charging). Pre-filled by auto-detection. |
| 3. Tuning | Deadband, grid-charge overshoot, evaluation interval, minimum dwell time, daily write cap, default grid charge current, voltage range for the fallback SOC estimate |
| 4. Overrides (optional) | Force-hold entities, solar forecast sensor and threshold, battery load protection, grid availability entity. See [Overrides](#overrides). |

You can change all of these later under *Configure*. The integration reloads when you save.

> **Use OSO, not CSO, as the "grid charging blocked" option.** On Axpert inverters, CSO (solar first) still charges from the utility whenever solar is not available, for example at night.

## How the plan works

### Active slot
A slot runs from its start time until the start time of the next **enabled** slot, wrapping past midnight. Disabled slots are skipped, and the previous slot stays in force through them. Before the earliest start time of the day, the last slot of the previous day is still active.

### States
T = slot target SOC, D = deadband (default 2%), H = grid-charge overshoot (default 2%).

| Status | Output priority | Charger priority | Entered when | Left when |
|---|---|---|---|---|
| **Discharging to target** | SBU / SOL | OSO | SOC > T + D (SOC > T at startup) | SOC ≤ T |
| **Holding at target** | USB / SUB | OSO | SOC ≤ T | SOC > T + D, or grid charge on and SOC < T − D |
| **Grid charging to target** | USB / SUB | SNU / UTI | Grid charge on and SOC < T − D (SOC < T at startup) | SOC ≥ min(T + H, 100%), or the slot's grid charge is off |

When grid charging finishes, the plan goes to **Holding**, not straight to discharging. That stops a charge/discharge loop through the grid. The master switch **Battery plan enabled** off means *bypass*: the integration stops sending commands and leaves the inverter as it is.

Other statuses: **Holding (override)** (see below), **Grid down (paused)**, **Plan disabled (bypass)**, **Waiting for SOC** (SOC sensor and voltage fallback both unavailable; nothing is sent), **No active slot** (all slots disabled).

### Per-slot charge current
Each slot has its own **charge current** (A). It is applied to the max AC charge current entity when that slot starts grid charging. 0 means use the default grid charge current from the Tuning step.

## Overrides

Overrides sit on top of the slot plan. All of them are optional.

| Override | Configure | Effect |
|---|---|---|
| **Force-hold entities** | Any `binary_sensor`, `input_boolean` or `switch` entities | Hold while any of them is on. Use a template binary sensor for your own conditions, e.g. poor solar. |
| **Solar forecast** | A numeric forecast sensor plus a threshold (kWh) | Hold while the forecast is below the threshold. Use an "energy production today" style sensor, not "remaining today", which drops below any threshold every evening. |
| **Battery load protection** | A load sensor (% or W), trip and release levels, and how long each must be sustained | Hold once the load has stayed at or above the trip level for the trip delay. Release once it has stayed at or below the release level for the release delay. Short spikes are ignored. |
| **Grid availability** | An on/off entity (on = grid present) or a grid voltage sensor plus a minimum voltage | While the grid is down, the plan pauses and sends nothing. The inverter runs from battery by itself. |

How the hold overrides behave:
- **They only stop discharge.** If the slot would discharge, the plan holds instead. Grid charging is never interrupted by a hold override.
- **Starting a hold is immediate**, because it protects the battery. **Releasing one respects the minimum dwell time**, and discharge resumes only once SOC is above target + deadband.
- **They're visible.** While an override is what stops discharge, the status is **Holding (override)** and the `overrides` attribute gives the reason, e.g. `battery load above 80 (releases at 60)`.

A note on battery load protection: if your sensor measures *battery discharge*, it falls as soon as the load moves to the grid. The release delay then effectively sets how long the hold lasts. If it measures *inverter output load*, it follows your actual consumption.

Unavailable override entities never block the plan. They're listed in the status sensor's `errors` attribute instead.

### Inverter (EEPROM) protection
Axpert inverters store these settings in non-volatile memory, so writes are kept to a minimum:

- **Write only on change.** Each target entity's current state is compared with the desired option (case- and punctuation-insensitive). A service call is made only when they differ.
- **Minimum dwell time** (default 5 min) between mode changes. Three things skip it: stopping discharge at the target (it protects the battery), a slot boundary, and your own edits to the plan.
- **Confirmation backoff.** After a write, the integration waits for the inverter entity to report the new value. If it doesn't, the next write waits 90 s, then 180 s, and so on, up to 30 min. The status sensor shows an error after 3 unconfirmed attempts.
- **Daily write cap** (default 60). When reached, commands stop until local midnight and the status sensor reports it.
- **Ordered, spaced commands.** The charge current is set first, then the charger priority, then the output priority, 2 s apart. Grid charging is therefore always blocked before the battery is allowed to discharge.

### SOC fallback
If the SOC sensor is unavailable and a battery voltage sensor is configured, SOC is estimated linearly between the configured 0% and 100% voltages. Voltage under load is only a rough guide, so use this as a safety net and not as the main SOC source.

## Entities

Entity IDs below assume the default entry title *Axpert Battery Planner*.

| Entity | Purpose |
|---|---|
| `switch.axpert_battery_planner_battery_plan_enabled` | Master switch (off = bypass) |
| `sensor.axpert_battery_planner_plan_execution_status` | Current status; the attributes hold SOC, SOC source, desired modes, pending state, active overrides, grid availability, solar forecast, battery load, last command, errors and writes today |
| `sensor.axpert_battery_planner_active_plan_slot` | Active slot number; the attributes hold the slot's start, end, next change, target, grid charge and effective charge current |
| `sensor.axpert_battery_planner_plan_target_soc` | Target SOC of the active slot |
| `time.axpert_battery_planner_slot_N_start_time` | Slot N start time |
| `number.axpert_battery_planner_slot_N_target_soc` | Slot N target SOC (0–100%) |
| `number.axpert_battery_planner_slot_N_charge_current` | Slot N grid charge current in A (0 = use default) |
| `switch.axpert_battery_planner_slot_N_grid_charge` | Slot N grid charging allowed |
| `switch.axpert_battery_planner_slot_N_enabled` | Slot N part of the schedule |

The plan is stored in `.storage/axpert_battery_planner.<entry_id>` and survives restarts. Nothing is sent to the inverter until Home Assistant has finished starting.

## Dashboard

Two ready-made layouts using only core cards:

- [`dashboards/battery_plan_entities.yaml`](dashboards/battery_plan_entities.yaml): status tiles, an entities card with one section per slot, and a diagnostics card.
- [`dashboards/battery_plan_grid.yaml`](dashboards/battery_plan_grid.yaml): a compact Sunsynk-style table, one row of five tiles per slot (Enabled · Start · SOC · Grid · Amps).

Paste either into *Edit dashboard → Add card → Manual*.

## Example plan

| Slot | Start | Target | Grid charge | Effect |
|---|---|---|---|---|
| 1 | 00:00 | 30% | off | Night: run from battery down to 30% |
| 2 | 04:00 | 60% | **on** | Cheap-rate window: top up to 60% from the grid |
| 3 | 06:00 | 20% | off | Morning: battery covers load, solar refills |
| 4 | 17:00 | 40% | off | Evening peak from battery, keep 40% reserve |
| 5 | 21:00 | 30% | off | Late evening |
| 6 | 23:00 | 30% | off | (disable if unused) |
