"""Pure scheduling and state-machine logic for Axpert Battery Planner.

This module deliberately has no Home Assistant imports so the decision logic
can be reasoned about and unit tested in isolation.

State machine (T = slot target SOC, D = deadband, H = charge hysteresis):

    DISCHARGING  -> HOLDING        when SOC <= T
    HOLDING      -> DISCHARGING    when SOC >  T + D
    HOLDING      -> GRID_CHARGING  when grid charge is on and SOC < T - D
    DISCHARGING  -> GRID_CHARGING  when grid charge is on and SOC < T - D
    GRID_CHARGING-> HOLDING        when SOC >= min(T + H, 100) or grid charge is off

With no previous state (startup, plan re-enabled) the plain comparisons from
the specification are used: SOC > T discharges, SOC < T with grid charge on
charges, anything else holds.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from enum import StrEnum
import re


class PlanStatus(StrEnum):
    """Execution status of the battery plan."""

    DISABLED = "disabled"
    WAITING_FOR_SOC = "waiting_for_soc"
    NO_ACTIVE_SLOT = "no_active_slot"
    DISCHARGING = "discharging"
    HOLDING = "holding"
    GRID_CHARGING = "grid_charging"


OPERATING_STATES: frozenset[PlanStatus] = frozenset(
    {PlanStatus.DISCHARGING, PlanStatus.HOLDING, PlanStatus.GRID_CHARGING}
)


@dataclass(frozen=True, slots=True)
class PlanSlot:
    """One time slot of the battery plan (Sunsynk "System Work Mode" row)."""

    start_time: time
    target_soc: int
    grid_charge: bool
    active: bool

    def as_dict(self) -> dict[str, object]:
        """Serialise for storage."""
        return {
            "start_time": self.start_time.strftime("%H:%M:%S"),
            "target_soc": self.target_soc,
            "grid_charge": self.grid_charge,
            "active": self.active,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object], fallback: PlanSlot) -> PlanSlot:
        """Deserialise from storage, using fallback values for anything invalid."""
        start_time = fallback.start_time
        raw_start = data.get("start_time")
        if isinstance(raw_start, str):
            try:
                start_time = time.fromisoformat(raw_start).replace(
                    microsecond=0, tzinfo=None
                )
            except ValueError:
                start_time = fallback.start_time

        target_soc = fallback.target_soc
        raw_target = data.get("target_soc")
        if isinstance(raw_target, (int, float)) and not isinstance(raw_target, bool):
            target_soc = clamp_soc(raw_target)

        raw_grid = data.get("grid_charge")
        grid_charge = raw_grid if isinstance(raw_grid, bool) else fallback.grid_charge

        raw_active = data.get("active")
        active = raw_active if isinstance(raw_active, bool) else fallback.active

        return cls(
            start_time=start_time,
            target_soc=target_soc,
            grid_charge=grid_charge,
            active=active,
        )


@dataclass(frozen=True, slots=True)
class ActiveSlot:
    """The slot in force right now."""

    index: int
    slot: PlanSlot
    end_time: time

    @property
    def number(self) -> int:
        """1-based slot number as shown in the UI."""
        return self.index + 1


def clamp_soc(value: float) -> int:
    """Round and clamp a SOC value to 0..100."""
    return int(min(100, max(0, round(value))))


def resolve_active_slot(slots: Sequence[PlanSlot], now: time) -> ActiveSlot | None:
    """Return the slot active at ``now``.

    A slot runs from its start time until the start time of the next enabled
    slot, wrapping past midnight. Before the earliest start time of the day,
    the latest slot of the previous day is still in force. Disabled slots are
    skipped entirely, so the previous enabled slot keeps running through them.
    When two enabled slots share a start time, the higher-numbered one wins.
    """
    enabled = sorted(
        (slot.start_time, index) for index, slot in enumerate(slots) if slot.active
    )
    if not enabled:
        return None

    now = now.replace(tzinfo=None)
    position = len(enabled) - 1
    for candidate, (start, _index) in enumerate(enabled):
        if start <= now:
            position = candidate
        else:
            break

    index = enabled[position][1]
    end_time = enabled[(position + 1) % len(enabled)][0]
    return ActiveSlot(index=index, slot=slots[index], end_time=end_time)


def next_change_after(now: datetime, end_time: time) -> datetime:
    """Return the next datetime at which ``end_time`` occurs after ``now``."""
    candidate = now.replace(
        hour=end_time.hour,
        minute=end_time.minute,
        second=end_time.second,
        microsecond=0,
    )
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def compute_state(
    previous: PlanStatus | None,
    soc: float,
    target_soc: float,
    grid_charge: bool,
    deadband: float,
    charge_hysteresis: float,
) -> PlanStatus:
    """Compute the desired operating state with hysteresis.

    ``previous`` must be one of OPERATING_STATES or None (no memory).
    """
    if previous not in OPERATING_STATES:
        previous = None

    if grid_charge:
        if previous is PlanStatus.GRID_CHARGING:
            stop_at = min(target_soc + charge_hysteresis, 100.0)
            return PlanStatus.GRID_CHARGING if soc < stop_at else PlanStatus.HOLDING
        start_below = target_soc - deadband if previous is not None else target_soc
        if soc < start_below:
            return PlanStatus.GRID_CHARGING

    if previous is PlanStatus.DISCHARGING:
        return PlanStatus.DISCHARGING if soc > target_soc else PlanStatus.HOLDING
    if previous is PlanStatus.HOLDING:
        if soc > target_soc + deadband:
            return PlanStatus.DISCHARGING
        return PlanStatus.HOLDING

    # No usable memory (startup, plan re-enabled, or a grid-charge slot just ended).
    return PlanStatus.DISCHARGING if soc > target_soc else PlanStatus.HOLDING


def bypasses_dwell(previous: PlanStatus | None, desired: PlanStatus) -> bool:
    """Return True when a transition must not wait for the minimum dwell time.

    Leaving DISCHARGING protects the battery from going below target, so it
    always happens immediately. Every other transition is rate limited.
    """
    return previous is PlanStatus.DISCHARGING and desired is not PlanStatus.DISCHARGING


def soc_from_voltage(voltage: float, empty_voltage: float, full_voltage: float) -> float:
    """Linear SOC estimate from battery voltage, clamped to 0..100."""
    if full_voltage <= empty_voltage:
        raise ValueError("full_voltage must be greater than empty_voltage")
    fraction = (voltage - empty_voltage) / (full_voltage - empty_voltage)
    return round(min(100.0, max(0.0, fraction * 100.0)), 1)


_NON_ALNUM = re.compile(r"[^a-z0-9]")


def normalize_option(value: str) -> str:
    """Normalise an option label for tolerant comparison."""
    return _NON_ALNUM.sub("", value.lower())


def resolve_option(options: Sequence[str] | None, wanted: str) -> str | None:
    """Return the exact option label matching ``wanted``.

    If the entity does not publish an options list, ``wanted`` is returned
    unchanged. Returns None when a list exists but has no match.
    """
    if not options:
        return wanted
    if wanted in options:
        return wanted
    target = normalize_option(wanted)
    for option in options:
        if normalize_option(option) == target:
            return option
    return None


def guess_option(options: Sequence[str] | None, candidates: Sequence[str]) -> str | None:
    """Pick the option best matching an ordered list of candidate labels."""
    if not options:
        return None
    normalized = {normalize_option(option): option for option in options}
    for candidate in candidates:
        key = normalize_option(candidate)
        if key in normalized:
            return normalized[key]
    for candidate in candidates:
        key = normalize_option(candidate)
        if len(key) < 3:
            continue
        for option_key, option in normalized.items():
            if key in option_key:
                return option
    return None
