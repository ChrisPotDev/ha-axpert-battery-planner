"""Config and options flow for Axpert Battery Planner.

Steps (identical in the config and options flows):
  1. Source entities from the existing Axpert integration.
  2. Mode mapping: which option label of the inverter's select entities
     means SBU / USB / OSO / SNU (labels differ between integrations).
  3. Tuning: deadband, hysteresis, update interval and write protection.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from .const import (
    CHARGER_GRID_CANDIDATES,
    CHARGER_NO_GRID_CANDIDATES,
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
    DEFAULT_TITLE,
    DEFAULT_UPDATE_INTERVAL,
    DEFAULT_VOLTAGE_EMPTY,
    DEFAULT_VOLTAGE_FULL,
    DOMAIN,
    ENTITY_KEYS,
    OUTPUT_DISCHARGE_CANDIDATES,
    OUTPUT_HOLD_CANDIDATES,
)
from .planner import guess_option, normalize_option, resolve_option

REQUIRED_ENTITY_KEYS = (
    CONF_SOC_ENTITY,
    CONF_OUTPUT_PRIORITY_ENTITY,
    CONF_CHARGER_PRIORITY_ENTITY,
)

# (mode option key, entity key it belongs to, auto-detect candidates)
MODE_FIELDS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (CONF_OUTPUT_DISCHARGE_OPTION, CONF_OUTPUT_PRIORITY_ENTITY, OUTPUT_DISCHARGE_CANDIDATES),
    (CONF_OUTPUT_HOLD_OPTION, CONF_OUTPUT_PRIORITY_ENTITY, OUTPUT_HOLD_CANDIDATES),
    (CONF_CHARGER_NO_GRID_OPTION, CONF_CHARGER_PRIORITY_ENTITY, CHARGER_NO_GRID_CANDIDATES),
    (CONF_CHARGER_GRID_OPTION, CONF_CHARGER_PRIORITY_ENTITY, CHARGER_GRID_CANDIDATES),
)

INT_SETTINGS = (CONF_UPDATE_INTERVAL, CONF_MIN_DWELL_TIME, CONF_MAX_WRITES_PER_DAY)


# ---------------------------------------------------------------------------
# Step 1: entities
# ---------------------------------------------------------------------------
def _entities_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_SOC_ENTITY): EntitySelector(
                EntitySelectorConfig(domain=["sensor", "number", "input_number"])
            ),
            vol.Optional(CONF_VOLTAGE_ENTITY): EntitySelector(
                EntitySelectorConfig(domain=["sensor", "input_number"])
            ),
            vol.Required(CONF_OUTPUT_PRIORITY_ENTITY): EntitySelector(
                EntitySelectorConfig(domain=["select", "input_select"])
            ),
            vol.Required(CONF_CHARGER_PRIORITY_ENTITY): EntitySelector(
                EntitySelectorConfig(domain=["select", "input_select"])
            ),
            vol.Optional(CONF_CHARGE_CURRENT_ENTITY): EntitySelector(
                EntitySelectorConfig(domain=["number", "input_number"])
            ),
        }
    )


def _validate_entities(hass: HomeAssistant, user_input: Mapping[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    for key in ENTITY_KEYS:
        entity_id = user_input.get(key)
        if key in REQUIRED_ENTITY_KEYS and not entity_id:
            errors[key] = "entity_required"
        elif entity_id and hass.states.get(entity_id) is None:
            errors[key] = "entity_not_found"
    output = user_input.get(CONF_OUTPUT_PRIORITY_ENTITY)
    if output and output == user_input.get(CONF_CHARGER_PRIORITY_ENTITY):
        errors[CONF_CHARGER_PRIORITY_ENTITY] = "same_entity"
    return errors


def _clean_entities(user_input: Mapping[str, Any]) -> dict[str, Any]:
    """Store every entity key; cleared optional entities become None explicitly
    so they also override older values when saved as options."""
    return {key: user_input.get(key) or None for key in ENTITY_KEYS}


def _entity_suggestions(conf: Mapping[str, Any]) -> dict[str, Any]:
    return {key: conf[key] for key in ENTITY_KEYS if conf.get(key)}


# ---------------------------------------------------------------------------
# Step 2: mode mapping
# ---------------------------------------------------------------------------
def _entity_options(hass: HomeAssistant, entity_id: str | None) -> list[str]:
    if not entity_id:
        return []
    state = hass.states.get(entity_id)
    if state is None:
        return []
    options = state.attributes.get("options")
    if isinstance(options, (list, tuple)):
        return [str(option) for option in options]
    return []


def _modes_schema(hass: HomeAssistant, conf: Mapping[str, Any]) -> vol.Schema:
    schema: dict[vol.Marker, Any] = {}
    for key, entity_key, candidates in MODE_FIELDS:
        options = _entity_options(hass, conf.get(entity_key))
        default = (
            conf.get(key)
            or guess_option(options, candidates)
            or (options[0] if options else candidates[0])
        )
        selector: SelectSelector | TextSelector
        if options:
            selector = SelectSelector(
                SelectSelectorConfig(
                    options=options,
                    custom_value=True,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            )
        else:
            selector = TextSelector()
        schema[vol.Required(key, default=default)] = selector
    return vol.Schema(schema)


def _modes_placeholders(hass: HomeAssistant, conf: Mapping[str, Any]) -> dict[str, str]:
    def describe(entity_key: str) -> str:
        options = _entity_options(hass, conf.get(entity_key))
        return ", ".join(options) if options else "none reported (type the exact label)"

    return {
        "output_entity": str(conf.get(CONF_OUTPUT_PRIORITY_ENTITY)),
        "output_options": describe(CONF_OUTPUT_PRIORITY_ENTITY),
        "charger_entity": str(conf.get(CONF_CHARGER_PRIORITY_ENTITY)),
        "charger_options": describe(CONF_CHARGER_PRIORITY_ENTITY),
    }


def _validate_modes(
    hass: HomeAssistant, conf: Mapping[str, Any], user_input: Mapping[str, Any]
) -> tuple[dict[str, str], dict[str, str]]:
    """Return (errors, resolved option labels)."""
    errors: dict[str, str] = {}
    resolved: dict[str, str] = {}
    for key, entity_key, _candidates in MODE_FIELDS:
        value = str(user_input.get(key, "")).strip()
        match = resolve_option(_entity_options(hass, conf.get(entity_key)), value) if value else None
        if match is None:
            errors[key] = "invalid_option"
        else:
            resolved[key] = match

    if not errors:
        if normalize_option(resolved[CONF_OUTPUT_DISCHARGE_OPTION]) == normalize_option(
            resolved[CONF_OUTPUT_HOLD_OPTION]
        ):
            errors[CONF_OUTPUT_HOLD_OPTION] = "same_option"
        if normalize_option(resolved[CONF_CHARGER_NO_GRID_OPTION]) == normalize_option(
            resolved[CONF_CHARGER_GRID_OPTION]
        ):
            errors[CONF_CHARGER_GRID_OPTION] = "same_option"
    return errors, resolved


# ---------------------------------------------------------------------------
# Step 3: tuning
# ---------------------------------------------------------------------------
def _number(
    minimum: float, maximum: float, step: float, unit: str | None = None
) -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=step,
            unit_of_measurement=unit,
            mode=NumberSelectorMode.BOX,
        )
    )


def _settings_schema(conf: Mapping[str, Any]) -> vol.Schema:
    def default(key: str, fallback: float) -> float:
        value = conf.get(key)
        return fallback if value is None else value

    return vol.Schema(
        {
            vol.Required(
                CONF_DEADBAND, default=default(CONF_DEADBAND, DEFAULT_DEADBAND)
            ): _number(0.5, 10, 0.5, PERCENTAGE),
            vol.Required(
                CONF_CHARGE_HYSTERESIS,
                default=default(CONF_CHARGE_HYSTERESIS, DEFAULT_CHARGE_HYSTERESIS),
            ): _number(0, 10, 0.5, PERCENTAGE),
            vol.Required(
                CONF_UPDATE_INTERVAL,
                default=default(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
            ): _number(10, 600, 5, UnitOfTime.SECONDS),
            vol.Required(
                CONF_MIN_DWELL_TIME,
                default=default(CONF_MIN_DWELL_TIME, DEFAULT_MIN_DWELL_TIME),
            ): _number(0, 3600, 30, UnitOfTime.SECONDS),
            vol.Required(
                CONF_MAX_WRITES_PER_DAY,
                default=default(CONF_MAX_WRITES_PER_DAY, DEFAULT_MAX_WRITES_PER_DAY),
            ): _number(1, 500, 1),
            vol.Required(
                CONF_GRID_CHARGE_CURRENT,
                default=default(CONF_GRID_CHARGE_CURRENT, DEFAULT_GRID_CHARGE_CURRENT),
            ): _number(0, 200, 1, UnitOfElectricCurrent.AMPERE),
            vol.Required(
                CONF_VOLTAGE_EMPTY,
                default=default(CONF_VOLTAGE_EMPTY, DEFAULT_VOLTAGE_EMPTY),
            ): _number(10, 70, 0.1, UnitOfElectricPotential.VOLT),
            vol.Required(
                CONF_VOLTAGE_FULL,
                default=default(CONF_VOLTAGE_FULL, DEFAULT_VOLTAGE_FULL),
            ): _number(10, 70, 0.1, UnitOfElectricPotential.VOLT),
        }
    )


def _validate_settings(user_input: Mapping[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    if float(user_input[CONF_VOLTAGE_FULL]) <= float(user_input[CONF_VOLTAGE_EMPTY]):
        errors[CONF_VOLTAGE_FULL] = "voltage_range"
    return errors


def _clean_settings(user_input: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: int(value) if key in INT_SETTINGS else float(value)
        for key, value in user_input.items()
    }


# ---------------------------------------------------------------------------
# Flows
# ---------------------------------------------------------------------------
class AxpertBatteryPlannerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Initial setup flow."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialise the flow."""
        self._conf: dict[str, Any] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> AxpertBatteryPlannerOptionsFlow:
        """Return the options flow."""
        return AxpertBatteryPlannerOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 1: choose the inverter entities."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate_entities(self.hass, user_input)
            if not errors:
                await self.async_set_unique_id(user_input[CONF_SOC_ENTITY])
                self._abort_if_unique_id_configured()
                self._conf.update(_clean_entities(user_input))
                return await self.async_step_modes()

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                _entities_schema(), user_input or {}
            ),
            errors=errors,
        )

    async def async_step_modes(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 2: map plan states to the inverter's option labels."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors, resolved = _validate_modes(self.hass, self._conf, user_input)
            if not errors:
                self._conf.update(resolved)
                return await self.async_step_settings()

        return self.async_show_form(
            step_id="modes",
            data_schema=_modes_schema(self.hass, {**self._conf, **(user_input or {})}),
            errors=errors,
            description_placeholders=_modes_placeholders(self.hass, self._conf),
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 3: tuning and protection settings."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate_settings(user_input)
            if not errors:
                return self.async_create_entry(
                    title=DEFAULT_TITLE,
                    data=self._conf,
                    options=_clean_settings(user_input),
                )

        return self.async_show_form(
            step_id="settings",
            data_schema=_settings_schema(user_input or {}),
            errors=errors,
        )


class AxpertBatteryPlannerOptionsFlow(OptionsFlow):
    """Re-run all three steps; everything is saved as options."""

    def __init__(self) -> None:
        """Initialise the flow."""
        self._conf: dict[str, Any] = {}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 1: inverter entities."""
        if not self._conf:
            self._conf = {**self.config_entry.data, **self.config_entry.options}

        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate_entities(self.hass, user_input)
            if not errors:
                self._conf.update(_clean_entities(user_input))
                return await self.async_step_modes()

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                _entities_schema(),
                user_input if user_input is not None else _entity_suggestions(self._conf),
            ),
            errors=errors,
        )

    async def async_step_modes(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 2: mode mapping."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors, resolved = _validate_modes(self.hass, self._conf, user_input)
            if not errors:
                self._conf.update(resolved)
                return await self.async_step_settings()

        return self.async_show_form(
            step_id="modes",
            data_schema=_modes_schema(self.hass, {**self._conf, **(user_input or {})}),
            errors=errors,
            description_placeholders=_modes_placeholders(self.hass, self._conf),
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 3: tuning."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate_settings(user_input)
            if not errors:
                self._conf.update(_clean_settings(user_input))
                return self.async_create_entry(data=self._conf)

        return self.async_show_form(
            step_id="settings",
            data_schema=_settings_schema({**self._conf, **(user_input or {})}),
            errors=errors,
        )
