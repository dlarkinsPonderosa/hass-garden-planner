"""Config flow for Reap."""

from __future__ import annotations

from datetime import date
import re
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
)
from .planner import PlannerError


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


CROP_DATE_FIELDS = (
    ("spring_indoor", "spring", "indoor"),
    ("spring_transplant", "spring", "transplant"),
    ("spring_direct", "spring", "direct"),
    ("fall_direct", "fall", "direct"),
)


def _crop_key(manager: Any, name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "crop"
    key, n = base, 2
    while key in manager.crops or key in manager.builtin_crops:
        key, n = f"{base}_{n}", n + 1
    return key


def _crop_from_form(manager: Any, user_input: dict[str, Any]) -> dict[str, Any]:
    """The add_crop fields for what was entered in the Configure form."""
    name = (user_input.get("name") or "").strip()
    data: dict[str, Any] = {
        "key": _crop_key(manager, name),
        "name": name,
        "category": user_input.get("category") or "vegetable",
        "frost_tender": bool(user_input.get("frost_tender")),
        "perennial": bool(user_input.get("perennial")),
    }
    for key in ("icon", "based_on", "notes"):
        if user_input.get(key):
            data[key] = user_input[key]
    for key in ("days_to_harvest", "harvest_weeks", "weeks_indoor"):
        if user_input.get(key) not in (None, ""):
            data[key] = int(user_input[key])
    windows: dict[str, dict[str, Any]] = {}
    for field, season, kind in CROP_DATE_FIELDS:
        start, end = user_input.get(f"{field}_from"), user_input.get(f"{field}_to")
        if not start and not end:
            continue
        if not start or not end:
            raise PlannerError("Give both a from and a to date for each range you use")
        windows.setdefault(season, {"season": season})[kind] = [str(start), str(end)]
    if windows:
        data["windows"] = list(windows.values())
    elif not data.get("based_on"):
        raise PlannerError("Give at least one date range, or copy timing from a crop")
    return data


class ReapConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up Reap."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick the task list and a starting point for frost dates."""
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
                    vol.Required(CONF_ZONE, default=ZONE_CUSTOM): _zone_selector(),
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
                    title="Reap",
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
        return ReapOptionsFlow()


METHOD_LABELS = {
    "indoor_bed": "Start indoors, transplant to beds",
    "indoor_greenhouse": "Start indoors, transplant to greenhouse",
    "direct_bed": "Direct sow in beds",
    "direct_greenhouse": "Direct sow in greenhouse",
}
PLANTING_KEYS = (
    "method", "season", "year", "start_date", "succession_days",
    "succession_count", "succession_until", "variety", "quantity",
    "location", "notes",
)


def _box(minimum: int, maximum: int, unit: str | None = None) -> selector.NumberSelector:
    config = selector.NumberSelectorConfig(
        min=minimum, max=maximum, step=1, mode=selector.NumberSelectorMode.BOX
    )
    if unit:
        config["unit_of_measurement"] = unit
    return selector.NumberSelector(config)


class ReapOptionsFlow(OptionsFlow):
    """Add or remove plantings, or change Reap settings."""

    def __init__(self) -> None:
        self._crop: str | None = None
        self._planting: dict[str, Any] = {}
        self._save_defaults = False

    @property
    def _manager(self) -> Any:
        return self.config_entry.runtime_data

    def _done(self) -> ConfigFlowResult:
        # Keep the options as they are, so the integration isn't reloaded.
        return self.async_create_entry(data=dict(self.config_entry.options))

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        options = ["add_planting", "add_crop", "settings"]
        if self._manager.plantings():
            options.insert(1, "remove_planting")
        return self.async_show_menu(step_id="init", menu_options=options)

    # ----- add a crop -----

    async def async_step_add_crop(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add a crop or variety with this garden's dates."""
        manager = self._manager
        errors: dict[str, str] = {}
        placeholders = {"error": ""}
        if user_input is not None:
            try:
                await manager.async_save_crop(_crop_from_form(manager, user_input))
            except PlannerError as err:
                errors["base"] = "crop_error"
                placeholders["error"] = str(err)
            else:
                return self._done()
        crops = sorted(manager.crops.values(), key=lambda c: c.name)
        date = selector.TextSelector(selector.TextSelectorConfig())
        fields: dict[Any, Any] = {
            vol.Required("name"): str,
            vol.Required("category", default="vegetable"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=["vegetable", "herb", "fruit", "flower"],
                    translation_key="category",
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("icon"): selector.IconSelector(),
            vol.Optional("based_on"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(value=c.key, label=c.name)
                        for c in crops
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                    sort=False,
                )
            ),
        }
        for field, _season, _kind in CROP_DATE_FIELDS:
            fields[vol.Optional(f"{field}_from")] = date
            fields[vol.Optional(f"{field}_to")] = date
        fields.update(
            {
                vol.Optional("days_to_harvest"): _box(1, 1100, "days"),
                vol.Optional("harvest_weeks"): _box(1, 52, "weeks"),
                vol.Optional("weeks_indoor"): _box(1, 30, "weeks"),
                vol.Optional("frost_tender", default=False): bool,
                vol.Optional("perennial", default=False): bool,
                vol.Optional("notes"): str,
            }
        )
        schema = vol.Schema(fields)
        if user_input:
            schema = self.add_suggested_values_to_schema(schema, user_input)
        return self.async_show_form(
            step_id="add_crop",
            data_schema=schema,
            errors=errors,
            description_placeholders=placeholders,
        )

    # ----- add a planting -----

    async def async_step_add_planting(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 1: pick the crop."""
        if user_input is not None:
            self._crop = user_input["crop"]
            return await self.async_step_planting_details()
        crops = sorted(self._manager.crops.values(), key=lambda c: c.name)
        return self.async_show_form(
            step_id="add_planting",
            data_schema=vol.Schema(
                {
                    vol.Required("crop"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                selector.SelectOptionDict(value=c.key, label=c.name)
                                for c in crops
                            ],
                            mode=selector.SelectSelectorMode.DROPDOWN,
                            sort=False,
                        )
                    )
                }
            ),
        )

    async def async_step_planting_details(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 2: how and when it's grown."""
        manager = self._manager
        crop = manager.crop(self._crop)
        profile = manager.settings.profile
        errors: dict[str, str] = {}
        problem = ""
        if user_input is not None:
            fields = {"crop": crop.key}
            for key in PLANTING_KEYS:
                value = user_input.get(key)
                if value in (None, ""):
                    continue
                if key in ("year", "succession_days", "succession_count"):
                    value = int(value)
                fields[key] = value
            if fields.get("succession_days") == 0:
                fields.pop("succession_days")
            self._save_defaults = bool(user_input.get("save_defaults"))
            try:
                manager.preview(fields)
            except PlannerError as err:
                errors["base"] = "crop_error"
                problem = str(err)
            else:
                self._planting = fields
                return await self.async_step_planting_confirm()

        methods = crop.methods(profile)
        seasons = sorted({w.season for w in crop.windows_for(profile)})
        defaults = manager.crop_defaults(crop.key)
        fields: dict[Any, Any] = {
            vol.Required("method", default=defaults.get("method", methods[0])): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(value=m, label=METHOD_LABELS[m])
                        for m in methods
                    ],
                    mode=selector.SelectSelectorMode.LIST,
                )
            ),
        }
        if len(seasons) > 1:
            fields[vol.Required("season", default=seasons[0])] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=seasons, mode=selector.SelectSelectorMode.LIST
                )
            )
        fields.update(
            {
                vol.Required("year", default=manager.pick_year({
                    "crop": crop.key,
                    "method": defaults.get("method", methods[0]),
                    "season": seasons[0] if len(seasons) > 1 else None,
                })): _box(2000, 2100),
                vol.Optional("start_date"): selector.DateSelector(),
                vol.Optional("succession_days", default=0): _box(0, 365, "days"),
                vol.Optional("succession_count"): _box(1, 200),
                vol.Optional("succession_until"): selector.DateSelector(),
                vol.Optional("variety"): str,
                vol.Optional("quantity"): str,
                vol.Optional("location"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[loc["name"] for loc in manager.locations()],
                        custom_value=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional("notes"): str,
                vol.Optional("save_defaults", default=False): bool,
            }
        )
        suggested = user_input or {
            k: v for k, v in defaults.items() if k != "method"
        }
        schema = self.add_suggested_values_to_schema(vol.Schema(fields), suggested)
        return self.async_show_form(
            step_id="planting_details",
            data_schema=schema,
            errors=errors,
            description_placeholders={"crop": crop.name, "error": problem},
        )

    async def async_step_planting_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 3: show the dates, then save."""
        manager = self._manager
        if user_input is not None:
            await manager.async_add_planting(self._planting)
            if self._save_defaults:
                await manager.async_set_crop_defaults(
                    self._planting["crop"],
                    {
                        k: v for k, v in self._planting.items()
                        if k in ("method", "succession_days", "succession_count", "quantity", "location")
                    },
                )
            return self._done()
        _, tasks = manager.preview(self._planting)
        lines = [f"- {t.due:%a %b %-d, %Y}: {t.summary}" for t in tasks[:40]]
        if len(tasks) > 40:
            lines.append(f"- ...and {len(tasks) - 40} more")
        return self.async_show_form(
            step_id="planting_confirm",
            data_schema=vol.Schema({}),
            description_placeholders={
                "crop": manager.crop(self._planting["crop"]).name,
                "tasks": "\n".join(lines),
            },
        )

    # ----- remove plantings -----

    async def async_step_remove_planting(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        manager = self._manager
        if user_input is not None:
            for planting_id in user_input.get("plantings", []):
                await manager.async_remove_planting(planting_id)
            return self._done()
        crops = manager.crops
        options = []
        for planting in sorted(manager.plantings(), key=lambda p: (p.year, p.crop)):
            crop = crops.get(planting.crop)
            name = crop.name if crop else planting.crop
            if planting.variety:
                name = f"{name} ({planting.variety})"
            extra = f", every {planting.succession_days} days" if planting.succession_days else ""
            where = f", {planting.location}" if planting.location else ""
            options.append(
                selector.SelectOptionDict(
                    value=planting.id,
                    label=f"{name}: {METHOD_LABELS.get(planting.method, planting.method).lower()}, {planting.year}{extra}{where}",
                )
            )
        return self.async_show_form(
            step_id="remove_planting",
            data_schema=vol.Schema(
                {
                    vol.Required("plantings"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=options, multiple=True,
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
        )

    # ----- settings -----

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate(user_input)
            if not errors:
                return self.async_create_entry(data=_clean(user_input))
        current = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id="settings",
            data_schema=_schema(self.hass, user_input or current),
            errors=errors,
        )
