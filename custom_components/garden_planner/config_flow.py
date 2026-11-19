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
    CONF_OFFSET_DAYS,
    CONF_PROFILE,
    CONF_TASK_EMOJI,
    CONF_TODO_ENTITY,
    CONF_WARM_LAST_FROST,
    CONF_ZONE,
    DEFAULTS,
    DOMAIN,
    NEW_LIST,
    PROFILE_CONTINENTAL,
    PROFILES,
    ZONE_CUSTOM,
    ZONE_FROST_DATES,
    ZONE_VICTORIA,
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


def _zone_selector() -> selector.SelectSelector:
    options = [
        selector.SelectOptionDict(value=ZONE_VICTORIA, label="Victoria, BC (planting guide dates)"),
        selector.SelectOptionDict(value=ZONE_CUSTOM, label="I'll enter my own frost dates"),
    ]
    for zone, (last, first) in ZONE_FROST_DATES.items():
        options.append(
            selector.SelectOptionDict(
                value=zone,
                label=f"USDA zone {zone} (about {last} to {first})",
            )
        )
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options, mode=selector.SelectSelectorMode.DROPDOWN
        )
    )


def _zone_defaults(zone: str) -> dict[str, Any]:
    """Suggested frost dates for the chosen starting point."""
    if zone in ZONE_FROST_DATES:
        last, first = ZONE_FROST_DATES[zone]
        return {
            CONF_LAST_FROST: last,
            CONF_FIRST_FROST: first,
            CONF_WARM_LAST_FROST: "",
            CONF_PROFILE: PROFILE_CONTINENTAL,
        }
    if zone == ZONE_CUSTOM:
        return {CONF_WARM_LAST_FROST: "", CONF_PROFILE: PROFILE_CONTINENTAL}
    return {}


def _number(minimum: int, maximum: int, unit: str) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=minimum, max=maximum, step=1, unit_of_measurement=unit,
            mode=selector.NumberSelectorMode.BOX,
        )
    )


def _schema(
    hass: HomeAssistant, current: dict[str, Any], include_list: bool = True
) -> vol.Schema:
    def default(key: str) -> Any:
        return current.get(key, DEFAULTS[key])

    fields: dict[Any, Any] = {}
    if include_list:
        fields[vol.Required(CONF_TODO_ENTITY, default=default(CONF_TODO_ENTITY))] = _list_selector(hass)
    return vol.Schema(
        {
            **fields,
            vol.Required(CONF_LAST_FROST, default=default(CONF_LAST_FROST)): str,
            vol.Required(CONF_FIRST_FROST, default=default(CONF_FIRST_FROST)): str,
            vol.Optional(CONF_WARM_LAST_FROST, description={"suggested_value": default(CONF_WARM_LAST_FROST)}): str,
            vol.Required(CONF_OFFSET_DAYS, default=default(CONF_OFFSET_DAYS)): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=-60, max=60, step=1, unit_of_measurement="days",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Required(CONF_PROFILE, default=default(CONF_PROFILE)): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=list(PROFILES),
                    translation_key=CONF_PROFILE,
                    mode=selector.SelectSelectorMode.LIST,
                )
            ),
            vol.Required(CONF_GREENHOUSE_SPRING_WEEKS, default=default(CONF_GREENHOUSE_SPRING_WEEKS)): _number(0, 16, "weeks"),
            vol.Required(CONF_GREENHOUSE_FALL_WEEKS, default=default(CONF_GREENHOUSE_FALL_WEEKS)): _number(0, 16, "weeks"),
            vol.Required(CONF_HARDEN_OFF_DAYS, default=default(CONF_HARDEN_OFF_DAYS)): _number(0, 21, "days"),
            vol.Required(CONF_GREENHOUSE_HARDEN_OFF_DAYS, default=default(CONF_GREENHOUSE_HARDEN_OFF_DAYS)): _number(0, 21, "days"),
            vol.Required(CONF_LOOKAHEAD_DAYS, default=default(CONF_LOOKAHEAD_DAYS)): _number(1, 400, "days"),
            vol.Required(CONF_TASK_EMOJI, default=default(CONF_TASK_EMOJI)): bool,
        }
    )


def _validate(user_input: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    for key in (CONF_LAST_FROST, CONF_FIRST_FROST, CONF_WARM_LAST_FROST):
        if key == CONF_WARM_LAST_FROST and not user_input.get(key):
            continue
        try:
            month, day = (int(p) for p in str(user_input[key]).split("-"))
            date(2001, month, day)
        except ValueError:
            errors[key] = "invalid_month_day"
    return errors


def _clean(user_input: dict[str, Any]) -> dict[str, Any]:
    out = dict(user_input)
    out.setdefault(CONF_WARM_LAST_FROST, "")
    for key in (CONF_LAST_FROST, CONF_FIRST_FROST, CONF_WARM_LAST_FROST):
        if not out[key]:
            continue
        month, day = (int(p) for p in str(out[key]).split("-"))
        out[key] = f"{month:02d}-{day:02d}"
    for key in (
        CONF_GREENHOUSE_SPRING_WEEKS,
        CONF_GREENHOUSE_FALL_WEEKS,
        CONF_HARDEN_OFF_DAYS,
        CONF_GREENHOUSE_HARDEN_OFF_DAYS,
        CONF_LOOKAHEAD_DAYS,
        CONF_OFFSET_DAYS,
    ):
        out[key] = int(out[key])
    return out


class GardenPlannerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up Garden Planner."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick the task list and a starting point for frost dates."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            self._data = {
                CONF_TODO_ENTITY: user_input[CONF_TODO_ENTITY],
                **_zone_defaults(user_input[CONF_ZONE]),
            }
            return await self.async_step_location()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_TODO_ENTITY, default=NEW_LIST): _list_selector(self.hass),
                    vol.Required(CONF_ZONE, default=ZONE_VICTORIA): _zone_selector(),
                }
            ),
        )

    async def async_step_location(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Frost dates, offset and greenhouse settings."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate(user_input)
            if not errors:
                return self.async_create_entry(
                    title="Garden Planner",
                    data=_clean({**self._data, **user_input}),
                )
        return self.async_show_form(
            step_id="location",
            data_schema=_schema(self.hass, user_input or self._data, include_list=False),
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
