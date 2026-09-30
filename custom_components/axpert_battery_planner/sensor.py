"""Status sensors for Axpert Battery Planner."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    ATTR_BATTERY_LOAD,
    ATTR_BATTERY_LOAD_TRIPPED,
    ATTR_CHARGE_CURRENT,
    ATTR_DESIRED_CHARGER,
    ATTR_DESIRED_OUTPUT,
    ATTR_ERRORS,
    ATTR_GRID_AVAILABLE,
    ATTR_GRID_CHARGE,
    ATTR_LAST_COMMAND,
    ATTR_LAST_COMMAND_TIME,
    ATTR_MAX_WRITES_PER_DAY,
    ATTR_NEXT_CHANGE,
    ATTR_OVERRIDES,
    ATTR_PENDING_STATE,
    ATTR_SLOT_END,
    ATTR_SLOT_START,
    ATTR_SOC,
    ATTR_SOC_SOURCE,
    ATTR_SOLAR_FORECAST,
    ATTR_STATE_SINCE,
    ATTR_TARGET_SOC,
    ATTR_WRITES_TODAY,
)
from .coordinator import AxpertPlannerConfigEntry, AxpertPlannerCoordinator
from .entity import AxpertPlannerEntity
from .planner import PlanStatus

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AxpertPlannerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the plan sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            ActiveSlotSensor(coordinator),
            PlanStatusSensor(coordinator),
            PlanTargetSocSensor(coordinator),
        ]
    )


class ActiveSlotSensor(AxpertPlannerEntity, SensorEntity):
    """Number (1-6) of the slot currently in force."""

    _attr_translation_key = "active_slot"

    def __init__(self, coordinator: AxpertPlannerCoordinator) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, "active_slot")

    @property
    def native_value(self) -> int | None:
        """Return the active slot number."""
        return self.coordinator.data.active_slot

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return details of the active slot."""
        data = self.coordinator.data
        return {
            ATTR_SLOT_START: data.slot_start.isoformat() if data.slot_start else None,
            ATTR_SLOT_END: data.slot_end.isoformat() if data.slot_end else None,
            ATTR_NEXT_CHANGE: data.next_change.isoformat() if data.next_change else None,
            ATTR_TARGET_SOC: data.target_soc,
            ATTR_GRID_CHARGE: data.grid_charge,
            ATTR_CHARGE_CURRENT: data.charge_current,
        }


class PlanStatusSensor(AxpertPlannerEntity, SensorEntity):
    """What the plan is doing right now."""

    _attr_translation_key = "plan_status"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [status.value for status in PlanStatus]

    def __init__(self, coordinator: AxpertPlannerCoordinator) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, "plan_status")

    @property
    def native_value(self) -> str:
        """Return the plan execution status."""
        return self.coordinator.data.status.value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return evaluation and dispatch diagnostics."""
        data = self.coordinator.data
        return {
            ATTR_SOC: data.soc,
            ATTR_SOC_SOURCE: data.soc_source,
            ATTR_TARGET_SOC: data.target_soc,
            ATTR_DESIRED_OUTPUT: data.desired_output,
            ATTR_DESIRED_CHARGER: data.desired_charger,
            ATTR_PENDING_STATE: data.pending_state.value if data.pending_state else None,
            ATTR_STATE_SINCE: data.state_since.isoformat() if data.state_since else None,
            ATTR_OVERRIDES: list(data.overrides),
            ATTR_GRID_AVAILABLE: data.grid_available,
            ATTR_SOLAR_FORECAST: data.solar_forecast,
            ATTR_BATTERY_LOAD: data.battery_load,
            ATTR_BATTERY_LOAD_TRIPPED: data.battery_load_tripped,
            ATTR_LAST_COMMAND: data.last_command,
            ATTR_LAST_COMMAND_TIME: (
                data.last_command_time.isoformat() if data.last_command_time else None
            ),
            ATTR_ERRORS: list(data.errors),
            ATTR_WRITES_TODAY: data.writes_today,
            ATTR_MAX_WRITES_PER_DAY: data.max_writes_per_day,
        }


class PlanTargetSocSensor(AxpertPlannerEntity, SensorEntity):
    """Target SOC of the slot currently in force."""

    _attr_translation_key = "target_soc"
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(self, coordinator: AxpertPlannerCoordinator) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, "target_soc")

    @property
    def native_value(self) -> int | None:
        """Return the active target SOC."""
        return self.coordinator.data.target_soc
