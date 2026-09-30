"""Coordinator that evaluates the battery plan and drives the inverter."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, State, split_entity_id
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    COMMAND_SPACING,
    CONF_CHARGE_CURRENT_ENTITY,
    CONF_CHARGE_HYSTERESIS,
    CONF_CHARGER_GRID_OPTION,
    CONF_CHARGER_NO_GRID_OPTION,
    CONF_CHARGER_PRIORITY_ENTITY,
    CONF_DEADBAND,
    CONF_GRID_CHARGE_CURRENT,
    CONF_MAX_WRITES_PER_DAY,
    CONF_MIN_DWELL_TIME,
    CONF_OUTPUT_DISCHARGE_OPTION,
    CONF_OUTPUT_HOLD_OPTION,
    CONF_OUTPUT_PRIORITY_ENTITY,
    CONF_SOC_ENTITY,
    CONF_UPDATE_INTERVAL,
    CONF_VOLTAGE_EMPTY,
    CONF_VOLTAGE_ENTITY,
    CONF_VOLTAGE_FULL,
    DEFAULT_CHARGE_HYSTERESIS,
    DEFAULT_DEADBAND,
    DEFAULT_GRID_CHARGE_CURRENT,
    DEFAULT_MAX_WRITES_PER_DAY,
    DEFAULT_MIN_DWELL_TIME,
    DEFAULT_SLOTS,
    DEFAULT_UPDATE_INTERVAL,
    DEFAULT_VOLTAGE_EMPTY,
    DEFAULT_VOLTAGE_FULL,
    DOMAIN,
    NUMERIC_TOLERANCE,
    SOC_SOURCE_SENSOR,
    SOC_SOURCE_VOLTAGE,
    STORAGE_VERSION,
    STORE_SAVE_DELAY,
    WRITE_CONFIRM_WARN_ATTEMPTS,
    WRITE_RETRY_INTERVAL,
    WRITE_RETRY_MAX_BACKOFF,
    storage_key,
)
from .planner import (
    OPERATING_STATES,
    ActiveSlot,
    PlanSlot,
    PlanStatus,
    bypasses_dwell,
    clamp_soc,
    compute_state,
    next_change_after,
    normalize_option,
    resolve_active_slot,
    resolve_option,
    soc_from_voltage,
)

_LOGGER = logging.getLogger(__name__)

type AxpertPlannerConfigEntry = ConfigEntry[AxpertPlannerCoordinator]


@dataclass(frozen=True, slots=True)
class PlannerData:
    """Snapshot of one plan evaluation, consumed by the sensor entities."""

    status: PlanStatus
    active_slot: int | None
    target_soc: int | None
    grid_charge: bool | None
    slot_start: time | None
    slot_end: time | None
    next_change: datetime | None
    soc: float | None
    soc_source: str | None
    desired_output: str | None
    desired_charger: str | None
    pending_state: PlanStatus | None
    state_since: datetime | None
    last_command: str | None
    last_command_time: datetime | None
    errors: tuple[str, ...]
    writes_today: int
    max_writes_per_day: int


@dataclass(frozen=True, slots=True)
class _Command:
    """A desired value for one inverter entity."""

    entity_id: str
    value: str | float
    numeric: bool = False


def _default_slots() -> list[PlanSlot]:
    return [
        PlanSlot(
            start_time=time(hour, minute),
            target_soc=target,
            grid_charge=grid,
            active=True,
        )
        for hour, minute, target, grid in DEFAULT_SLOTS
    ]


def _state_to_float(state: State | None) -> float | None:
    if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN, ""):
        return None
    try:
        return float(state.state)
    except (TypeError, ValueError):
        return None


class AxpertPlannerCoordinator(DataUpdateCoordinator[PlannerData]):
    """Evaluates the plan on a fixed interval and dispatches inverter changes."""

    config_entry: AxpertPlannerConfigEntry

    def __init__(self, hass: HomeAssistant, entry: AxpertPlannerConfigEntry) -> None:
        """Initialise the coordinator."""
        self.conf: dict[str, Any] = {**entry.data, **entry.options}
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} ({entry.title})",
            update_interval=timedelta(
                seconds=int(self.conf.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL))
            ),
        )
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, storage_key(entry.entry_id)
        )
        self.slots: list[PlanSlot] = _default_slots()
        self.plan_enabled: bool = True

        # State machine memory.
        self._state: PlanStatus | None = None
        self._state_since: datetime | None = None
        self._last_slot_index: int | None = None
        self._force_evaluation = True

        # Write bookkeeping for rate limiting and confirmation tracking.
        self._last_write: dict[str, datetime] = {}
        self._write_attempts: dict[str, int] = {}
        self._pending_value: dict[str, str | float] = {}
        self._writes_today = 0
        self._writes_date: date = dt_util.now().date()
        self._last_command: str | None = None
        self._last_command_time: datetime | None = None

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------
    @property
    def deadband(self) -> float:
        """SOC deadband in percent."""
        return float(self.conf.get(CONF_DEADBAND, DEFAULT_DEADBAND))

    @property
    def charge_hysteresis(self) -> float:
        """Overshoot above target before grid charging stops, in percent."""
        return float(self.conf.get(CONF_CHARGE_HYSTERESIS, DEFAULT_CHARGE_HYSTERESIS))

    @property
    def min_dwell_time(self) -> float:
        """Minimum seconds between non-protective state transitions."""
        return float(self.conf.get(CONF_MIN_DWELL_TIME, DEFAULT_MIN_DWELL_TIME))

    @property
    def max_writes_per_day(self) -> int:
        """Maximum inverter writes per local calendar day."""
        return int(self.conf.get(CONF_MAX_WRITES_PER_DAY, DEFAULT_MAX_WRITES_PER_DAY))

    # ------------------------------------------------------------------
    # Plan persistence and mutation (called by the slot entities)
    # ------------------------------------------------------------------
    async def async_load_plan(self) -> None:
        """Load the stored plan, keeping defaults for anything missing."""
        try:
            stored = await self._store.async_load()
        except HomeAssistantError as err:
            _LOGGER.error("Could not load stored battery plan, using defaults: %s", err)
            return
        if not isinstance(stored, dict):
            return

        enabled = stored.get("plan_enabled")
        if isinstance(enabled, bool):
            self.plan_enabled = enabled

        raw_slots = stored.get("slots")
        if isinstance(raw_slots, list):
            defaults = _default_slots()
            self.slots = [
                PlanSlot.from_dict(raw_slots[index], defaults[index])
                if index < len(raw_slots) and isinstance(raw_slots[index], dict)
                else defaults[index]
                for index in range(len(defaults))
            ]

    async def async_save_plan(self) -> None:
        """Write the plan to storage immediately."""
        await self._store.async_save(self._plan_as_dict())

    def _plan_as_dict(self) -> dict[str, Any]:
        return {
            "plan_enabled": self.plan_enabled,
            "slots": [slot.as_dict() for slot in self.slots],
        }

    async def async_update_slot(
        self,
        index: int,
        *,
        start_time: time | None = None,
        target_soc: float | None = None,
        grid_charge: bool | None = None,
        active: bool | None = None,
    ) -> None:
        """Change one or more fields of a slot and re-evaluate."""
        changes: dict[str, Any] = {}
        if start_time is not None:
            changes["start_time"] = start_time.replace(microsecond=0, tzinfo=None)
        if target_soc is not None:
            changes["target_soc"] = clamp_soc(target_soc)
        if grid_charge is not None:
            changes["grid_charge"] = grid_charge
        if active is not None:
            changes["active"] = active
        if not changes:
            return
        self.slots[index] = replace(self.slots[index], **changes)
        await self._async_plan_changed()

    async def async_set_plan_enabled(self, enabled: bool) -> None:
        """Enable or bypass the whole plan."""
        self.plan_enabled = enabled
        await self._async_plan_changed()

    async def _async_plan_changed(self) -> None:
        # A deliberate user change is applied straight away, not dwell-limited.
        self._force_evaluation = True
        self._store.async_delay_save(self._plan_as_dict, STORE_SAVE_DELAY)
        self.async_update_listeners()
        await self.async_request_refresh()

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------
    async def _async_update_data(self) -> PlannerData:
        """Evaluate the plan and dispatch any needed inverter changes.

        Never raises: a failed evaluation must not make the slot entities
        unavailable. Problems are reported through the status sensor.
        """
        now = dt_util.now()
        self._roll_write_counter(now.date())
        errors: list[str] = []
        active = resolve_active_slot(self.slots, now.time())
        soc, soc_source = self._read_soc()

        if not self.plan_enabled:
            self._set_state(None, now)
            return self._snapshot(PlanStatus.DISABLED, now, active, soc, soc_source, errors)

        if active is None:
            self._set_state(None, now)
            errors.append("All slots are disabled")
            return self._snapshot(
                PlanStatus.NO_ACTIVE_SLOT, now, active, soc, soc_source, errors
            )

        if soc is None:
            # Keep the state machine memory so a brief sensor dropout does not
            # reset hysteresis, but do not touch the inverter without data.
            errors.append(f"No valid SOC from {self.conf[CONF_SOC_ENTITY]}")
            return self._snapshot(
                PlanStatus.WAITING_FOR_SOC, now, active, soc, soc_source, errors
            )

        slot = active.slot
        force = self._force_evaluation or active.index != self._last_slot_index
        desired = compute_state(
            self._state,
            soc,
            slot.target_soc,
            slot.grid_charge,
            self.deadband,
            self.charge_hysteresis,
        )

        pending: PlanStatus | None = None
        if (
            desired is not self._state
            and not force
            and self._state is not None
            and self._state_since is not None
            and not bypasses_dwell(self._state, desired)
            and (now - self._state_since).total_seconds() < self.min_dwell_time
        ):
            pending = desired
            desired = self._state

        self._force_evaluation = False
        self._last_slot_index = active.index
        self._set_state(desired, now, active, soc)

        if self.hass.is_running:
            await self._async_dispatch(desired, now, errors)
        else:
            errors.append("Waiting for Home Assistant to finish starting")

        return self._snapshot(desired, now, active, soc, soc_source, errors, pending)

    def _set_state(
        self,
        new_state: PlanStatus | None,
        now: datetime,
        active: ActiveSlot | None = None,
        soc: float | None = None,
    ) -> None:
        if new_state is self._state:
            return
        if new_state is None:
            _LOGGER.info("Battery plan idle (was %s)", self._state)
            self._last_slot_index = None
            self._force_evaluation = True
        else:
            _LOGGER.info(
                "Battery plan %s -> %s (slot %s, SOC %.1f%%, target %s%%)",
                self._state,
                new_state,
                active.number if active else "?",
                soc if soc is not None else float("nan"),
                active.slot.target_soc if active else "?",
            )
        self._state = new_state
        self._state_since = now if new_state is not None else None

    def _read_soc(self) -> tuple[float | None, str | None]:
        soc = _state_to_float(self.hass.states.get(self.conf[CONF_SOC_ENTITY]))
        if soc is not None and 0.0 <= soc <= 100.0:
            return soc, SOC_SOURCE_SENSOR

        voltage_entity: str | None = self.conf.get(CONF_VOLTAGE_ENTITY)
        if voltage_entity:
            voltage = _state_to_float(self.hass.states.get(voltage_entity))
            if voltage is not None and voltage > 0:
                empty = float(self.conf.get(CONF_VOLTAGE_EMPTY, DEFAULT_VOLTAGE_EMPTY))
                full = float(self.conf.get(CONF_VOLTAGE_FULL, DEFAULT_VOLTAGE_FULL))
                try:
                    return soc_from_voltage(voltage, empty, full), SOC_SOURCE_VOLTAGE
                except ValueError as err:
                    _LOGGER.error("Invalid voltage fallback range: %s", err)
        return None, None

    def _mode_options(self, state: PlanStatus) -> tuple[str, str]:
        """Return (output priority option, charger priority option) for a state."""
        output = (
            self.conf[CONF_OUTPUT_DISCHARGE_OPTION]
            if state is PlanStatus.DISCHARGING
            else self.conf[CONF_OUTPUT_HOLD_OPTION]
        )
        charger = (
            self.conf[CONF_CHARGER_GRID_OPTION]
            if state is PlanStatus.GRID_CHARGING
            else self.conf[CONF_CHARGER_NO_GRID_OPTION]
        )
        return output, charger

    def _snapshot(
        self,
        status: PlanStatus,
        now: datetime,
        active: ActiveSlot | None,
        soc: float | None,
        soc_source: str | None,
        errors: list[str],
        pending: PlanStatus | None = None,
    ) -> PlannerData:
        desired_output: str | None = None
        desired_charger: str | None = None
        if status in OPERATING_STATES:
            desired_output, desired_charger = self._mode_options(status)
        return PlannerData(
            status=status,
            active_slot=active.number if active else None,
            target_soc=active.slot.target_soc if active else None,
            grid_charge=active.slot.grid_charge if active else None,
            slot_start=active.slot.start_time if active else None,
            slot_end=active.end_time if active else None,
            next_change=next_change_after(now, active.end_time) if active else None,
            soc=round(soc, 1) if soc is not None else None,
            soc_source=soc_source,
            desired_output=desired_output,
            desired_charger=desired_charger,
            pending_state=pending,
            state_since=self._state_since,
            last_command=self._last_command,
            last_command_time=self._last_command_time,
            errors=tuple(errors),
            writes_today=self._writes_today,
            max_writes_per_day=self.max_writes_per_day,
        )

    # ------------------------------------------------------------------
    # Command dispatch
    # ------------------------------------------------------------------
    def _roll_write_counter(self, today: date) -> None:
        if today != self._writes_date:
            self._writes_date = today
            self._writes_today = 0

    async def _async_dispatch(
        self, state: PlanStatus, now: datetime, errors: list[str]
    ) -> None:
        """Bring the inverter entities in line with ``state``.

        Order matters: the charge current is set before grid charging is
        allowed, and the charger priority (grid charging inhibit) is always
        set before the output priority so a battery that starts discharging
        can never be recharged from the grid by a stale charger setting.
        """
        output_option, charger_option = self._mode_options(state)
        commands: list[_Command] = []

        if state is PlanStatus.GRID_CHARGING:
            current_entity: str | None = self.conf.get(CONF_CHARGE_CURRENT_ENTITY)
            amps = float(
                self.conf.get(CONF_GRID_CHARGE_CURRENT, DEFAULT_GRID_CHARGE_CURRENT)
            )
            if current_entity and amps > 0:
                commands.append(_Command(current_entity, amps, numeric=True))

        commands.append(_Command(self.conf[CONF_CHARGER_PRIORITY_ENTITY], charger_option))
        commands.append(_Command(self.conf[CONF_OUTPUT_PRIORITY_ENTITY], output_option))

        wrote = False
        for command in commands:
            if await self._async_apply(command, now, errors, space_before=wrote):
                wrote = True

    async def _async_apply(
        self,
        command: _Command,
        now: datetime,
        errors: list[str],
        *,
        space_before: bool,
    ) -> bool:
        """Write one value if it differs from the entity. Returns True if written."""
        entity_id = command.entity_id
        state = self.hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            errors.append(f"{entity_id} is unavailable")
            return False

        if command.numeric:
            current = _state_to_float(state)
            value: str | float = float(command.value)
            minimum = state.attributes.get("min")
            maximum = state.attributes.get("max")
            if isinstance(minimum, (int, float)):
                value = max(float(minimum), value)
            if isinstance(maximum, (int, float)):
                value = min(float(maximum), value)
            in_sync = current is not None and abs(current - value) < NUMERIC_TOLERANCE
        else:
            options = state.attributes.get("options")
            option_list = [str(o) for o in options] if isinstance(options, list) else None
            resolved = resolve_option(option_list, str(command.value))
            if resolved is None:
                errors.append(
                    f"'{command.value}' is not an option of {entity_id}; "
                    "re-run the integration options to fix the mode mapping"
                )
                return False
            value = resolved
            in_sync = normalize_option(state.state) == normalize_option(resolved)

        if in_sync:
            self._clear_write_tracking(entity_id)
            return False

        # A different value than the one awaiting confirmation resets the backoff.
        if self._pending_value.get(entity_id) != value:
            self._clear_write_tracking(entity_id)

        attempts = self._write_attempts.get(entity_id, 0)
        last_write = self._last_write.get(entity_id)
        if attempts and last_write is not None:
            backoff = min(
                WRITE_RETRY_INTERVAL * 2 ** (attempts - 1), WRITE_RETRY_MAX_BACKOFF
            )
            if (now - last_write).total_seconds() < backoff:
                if attempts >= WRITE_CONFIRM_WARN_ATTEMPTS:
                    errors.append(
                        f"{entity_id} has not confirmed '{value}' after "
                        f"{attempts} attempts"
                    )
                return False

        if self._writes_today >= self.max_writes_per_day:
            errors.append(
                f"Daily write limit ({self.max_writes_per_day}) reached; "
                f"not setting {entity_id} to '{value}'"
            )
            return False

        domain = split_entity_id(entity_id)[0]
        if command.numeric:
            service = "set_value"
            service_data: dict[str, Any] = {ATTR_ENTITY_ID: entity_id, "value": value}
        else:
            service = "select_option"
            service_data = {ATTR_ENTITY_ID: entity_id, "option": value}

        if space_before:
            await asyncio.sleep(COMMAND_SPACING)

        self._pending_value[entity_id] = value
        self._write_attempts[entity_id] = attempts + 1
        self._last_write[entity_id] = now
        try:
            await self.hass.services.async_call(
                domain, service, service_data, blocking=True
            )
        except (HomeAssistantError, vol.Invalid) as err:
            _LOGGER.warning("Failed to set %s to %s: %s", entity_id, value, err)
            errors.append(f"Failed to set {entity_id} to '{value}': {err}")
            return False

        self._writes_today += 1
        self._last_command = f"{entity_id} -> {value}"
        self._last_command_time = now
        _LOGGER.info(
            "Set %s from '%s' to '%s' (write %s today)",
            entity_id,
            state.state,
            value,
            self._writes_today,
        )
        return True

    def _clear_write_tracking(self, entity_id: str) -> None:
        self._write_attempts.pop(entity_id, None)
        self._last_write.pop(entity_id, None)
        self._pending_value.pop(entity_id, None)
