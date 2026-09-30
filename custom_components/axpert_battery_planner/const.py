"""Constants for the Axpert Battery Planner integration."""

from __future__ import annotations

from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "axpert_battery_planner"
DEFAULT_TITLE: Final = "Axpert Battery Planner"
MANUFACTURER: Final = "Axpert Battery Planner"
MODEL: Final = "Battery plan scheduler"

PLATFORMS: Final[list[Platform]] = [
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TIME,
]

NUM_SLOTS: Final = 6

# Persistent storage of the plan (slot values and master switch).
STORAGE_VERSION: Final = 1
STORE_SAVE_DELAY: Final = 2  # seconds


def storage_key(entry_id: str) -> str:
    """Return the storage key for a config entry's plan."""
    return f"{DOMAIN}.{entry_id}"


# --- Config entry keys: source entities -------------------------------------
CONF_SOC_ENTITY: Final = "soc_entity"
CONF_VOLTAGE_ENTITY: Final = "voltage_entity"
CONF_OUTPUT_PRIORITY_ENTITY: Final = "output_priority_entity"
CONF_CHARGER_PRIORITY_ENTITY: Final = "charger_priority_entity"
CONF_CHARGE_CURRENT_ENTITY: Final = "charge_current_entity"

ENTITY_KEYS: Final = (
    CONF_SOC_ENTITY,
    CONF_VOLTAGE_ENTITY,
    CONF_OUTPUT_PRIORITY_ENTITY,
    CONF_CHARGER_PRIORITY_ENTITY,
    CONF_CHARGE_CURRENT_ENTITY,
)

# --- Config entry keys: mode mapping ----------------------------------------
# Option labels of the inverter's select entities to use for each plan state.
CONF_OUTPUT_DISCHARGE_OPTION: Final = "output_discharge_option"
CONF_OUTPUT_HOLD_OPTION: Final = "output_hold_option"
CONF_CHARGER_NO_GRID_OPTION: Final = "charger_no_grid_option"
CONF_CHARGER_GRID_OPTION: Final = "charger_grid_option"

# --- Config entry keys: tuning ----------------------------------------------
CONF_DEADBAND: Final = "deadband"
CONF_CHARGE_HYSTERESIS: Final = "charge_hysteresis"
CONF_UPDATE_INTERVAL: Final = "update_interval"
CONF_MIN_DWELL_TIME: Final = "min_dwell_time"
CONF_MAX_WRITES_PER_DAY: Final = "max_writes_per_day"
CONF_GRID_CHARGE_CURRENT: Final = "grid_charge_current"
CONF_VOLTAGE_EMPTY: Final = "voltage_empty"
CONF_VOLTAGE_FULL: Final = "voltage_full"

DEFAULT_DEADBAND: Final = 2.0
DEFAULT_CHARGE_HYSTERESIS: Final = 2.0
DEFAULT_UPDATE_INTERVAL: Final = 30
DEFAULT_MIN_DWELL_TIME: Final = 300
DEFAULT_MAX_WRITES_PER_DAY: Final = 60
DEFAULT_GRID_CHARGE_CURRENT: Final = 0
DEFAULT_VOLTAGE_EMPTY: Final = 46.0
DEFAULT_VOLTAGE_FULL: Final = 53.6

# --- Command dispatch safeguards --------------------------------------------
# Wait this long for the inverter entity to report a written value before
# writing again. Doubles on each unconfirmed attempt up to the maximum.
WRITE_RETRY_INTERVAL: Final = 90
WRITE_RETRY_MAX_BACKOFF: Final = 1800
# Report an error once a value is still unconfirmed after this many writes.
WRITE_CONFIRM_WARN_ATTEMPTS: Final = 3
# Pause between successive writes so serial-based inverter links keep up.
COMMAND_SPACING: Final = 2.0
# Numeric (charge current) values within this tolerance count as equal.
NUMERIC_TOLERANCE: Final = 0.5

# --- Default plan (hour, minute, target SOC, grid charge) --------------------
DEFAULT_SLOTS: Final[tuple[tuple[int, int, int, bool], ...]] = (
    (0, 0, 30, False),
    (5, 0, 30, False),
    (9, 0, 20, False),
    (16, 0, 40, False),
    (21, 0, 30, False),
    (23, 0, 30, False),
)

# --- Mode mapping candidates ------------------------------------------------
# Different Axpert/Voltronic integrations label the same inverter setting
# differently (e.g. "SBU", "SBU priority", "Solar-Battery-Utility"). These
# ordered lists pre-fill the mapping step; the user confirms the final choice.
OUTPUT_DISCHARGE_CANDIDATES: Final = (
    "SBU",
    "SBU priority",
    "SBU first",
    "Solar Battery Utility",
    "SOL",
    "Solar first",
)
OUTPUT_HOLD_CANDIDATES: Final = (
    "USB",
    "Utility first",
    "Utility Solar Battery",
    "SUB",
    "Solar Utility Battery",
    "UTI",
    "Utility",
)
CHARGER_NO_GRID_CANDIDATES: Final = (
    "OSO",
    "Only solar",
    "Solar only",
    "Only solar charging",
    "CSO",
    "Solar first",
)
CHARGER_GRID_CANDIDATES: Final = (
    "SNU",
    "Solar and utility",
    "Solar + Utility",
    "Solar & Utility",
    "Solar Utility",
    "UTI",
    "Utility first",
    "Utility",
)

# --- SOC sources --------------------------------------------------------------
SOC_SOURCE_SENSOR: Final = "soc_sensor"
SOC_SOURCE_VOLTAGE: Final = "voltage_estimate"

# --- Extra state attributes -------------------------------------------------
ATTR_SOC: Final = "soc"
ATTR_SOC_SOURCE: Final = "soc_source"
ATTR_TARGET_SOC: Final = "target_soc"
ATTR_GRID_CHARGE: Final = "grid_charge"
ATTR_SLOT_START: Final = "slot_start"
ATTR_SLOT_END: Final = "slot_end"
ATTR_NEXT_CHANGE: Final = "next_slot_change"
ATTR_DESIRED_OUTPUT: Final = "desired_output_priority"
ATTR_DESIRED_CHARGER: Final = "desired_charger_priority"
ATTR_PENDING_STATE: Final = "pending_state"
ATTR_STATE_SINCE: Final = "state_since"
ATTR_LAST_COMMAND: Final = "last_command"
ATTR_LAST_COMMAND_TIME: Final = "last_command_time"
ATTR_ERRORS: Final = "errors"
ATTR_WRITES_TODAY: Final = "writes_today"
ATTR_MAX_WRITES_PER_DAY: Final = "max_writes_per_day"
