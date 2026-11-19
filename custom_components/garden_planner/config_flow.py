"""Config flow for Garden Planner."""

from __future__ import annotations

from datetime import date
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from .const import (
    CONF_FIRST_FROST,
    CONF_GREENHOUSE_FALL_WEEKS,
    CONF_GREENHOUSE_HARDEN_OFF_DAYS,
    CONF_GREENHOUSE_SPRING_WEEKS,
    CONF_HARDEN_OFF_DAYS,
    CONF_LAST_FROST,
    CONF_LOOKAHEAD_DAYS,
    CONF_SHIFT_FROST_TENDER,
    CONF_SHIFT_WINDOWS,
    CONF_TODO_ENTITY,
    DEFAULTS,
    DOMAIN,
    NEW_LIST,
)


def _list_selector(hass: HomeAssistant) -> selector.SelectSelector:
    options = [selector.SelectOptionDict(value=NEW_LIST, label="Create a new Garden Tasks list")]
    for state in sorted(hass.states.async_all("todo"), key=lambda s: s.name):
        if state.entity_id.startswith(f"todo.{DOMAIN}"):
            continue
        options.append(
            selector.SelectOptionDict(value=state.entity_id, label=state.name)
        )
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options, mode=selector.SelectSelectorMode.DROPDOWN
        )
    )


def _number(minimum: int, maximum: int, unit: str) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=minimum, max=maximum, step=1, unit_of_measurement=unit,
            mode=selector.NumberSelectorMode.BOX,
        )
    )


def _schema(hass: HomeAssistant, current: dict[str, Any]) -> vol.Schema:
    def default(key: str) -> Any:
        return current.get(key, DEFAULTS[key])

    return vol.Schema(
        {
            vol.Required(CONF_TODO_ENTITY, default=default(CONF_TODO_ENTITY)): _list_selector(hass),
            vol.Required(CONF_LAST_FROST, default=default(CONF_LAST_FROST)): str,
            vol.Required(CONF_FIRST_FROST, default=default(CONF_FIRST_FROST)): str,
            vol.Required(CONF_SHIFT_WINDOWS, default=default(CONF_SHIFT_WINDOWS)): bool,
            vol.Required(CONF_SHIFT_FROST_TENDER, default=default(CONF_SHIFT_FROST_TENDER)): bool,
            vol.Required(CONF_GREENHOUSE_SPRING_WEEKS, default=default(CONF_GREENHOUSE_SPRING_WEEKS)): _number(0, 16, "weeks"),
            vol.Required(CONF_GREENHOUSE_FALL_WEEKS, default=default(CONF_GREENHOUSE_FALL_WEEKS)): _number(0, 16, "weeks"),
            vol.Required(CONF_HARDEN_OFF_DAYS, default=default(CONF_HARDEN_OFF_DAYS)): _number(0, 21, "days"),
            vol.Required(CONF_GREENHOUSE_HARDEN_OFF_DAYS, default=default(CONF_GREENHOUSE_HARDEN_OFF_DAYS)): _number(0, 21, "days"),
            vol.Required(CONF_LOOKAHEAD_DAYS, default=default(CONF_LOOKAHEAD_DAYS)): _number(1, 400, "days"),
        }
    )


def _validate(user_input: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    for key in (CONF_LAST_FROST, CONF_FIRST_FROST):
        try:
            month, day = (int(p) for p in str(user_input[key]).split("-"))
            date(2001, month, day)
        except ValueError:
            errors[key] = "invalid_month_day"
    return errors


def _clean(user_input: dict[str, Any]) -> dict[str, Any]:
    out = dict(user_input)
    for key in (CONF_LAST_FROST, CONF_FIRST_FROST):
        month, day = (int(p) for p in str(out[key]).split("-"))
        out[key] = f"{month:02d}-{day:02d}"
    for key in (
        CONF_GREENHOUSE_SPRING_WEEKS,
        CONF_GREENHOUSE_FALL_WEEKS,
        CONF_HARDEN_OFF_DAYS,
        CONF_GREENHOUSE_HARDEN_OFF_DAYS,
        CONF_LOOKAHEAD_DAYS,
    ):
        out[key] = int(out[key])
    return out


class GardenPlannerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up Garden Planner."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate(user_input)
            if not errors:
                return self.async_create_entry(
                    title="Garden Planner", data=_clean(user_input)
                )
        return self.async_show_form(
            step_id="user",
            data_schema=_schema(self.hass, user_input or {}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return GardenPlannerOptionsFlow()


class GardenPlannerOptionsFlow(OptionsFlow):
    """Change Garden Planner settings."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate(user_input)
            if not errors:
                return self.async_create_entry(data=_clean(user_input))
        current = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id="init",
            data_schema=_schema(self.hass, user_input or current),
            errors=errors,
        )
