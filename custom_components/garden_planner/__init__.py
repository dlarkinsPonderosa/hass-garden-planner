"""Garden Planner: seed starting and planting schedules as Home Assistant tasks."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .manager import GardenManager, default_year
from .planner import METHODS, OFFSET_RE, Crop, PlannerError, mmdd_to_offset

PLATFORMS = [Platform.SENSOR, Platform.TODO]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLANTING_FIELDS = {
    vol.Required("crop"): cv.string,
    vol.Required("method"): vol.In(METHODS),
    vol.Optional("year"): vol.All(vol.Coerce(int), vol.Range(min=2000, max=2100)),
    vol.Optional("season"): cv.string,
    vol.Optional("start_date"): cv.date,
    vol.Optional("succession_days"): vol.All(vol.Coerce(int), vol.Range(min=0, max=365)),
    vol.Optional("succession_count"): vol.All(vol.Coerce(int), vol.Range(min=1, max=200)),
    vol.Optional("succession_until"): cv.date,
    vol.Optional("variety"): cv.string,
    vol.Optional("quantity"): cv.string,
    vol.Optional("location"): cv.string,
    vol.Optional("notes"): cv.string,
}

RANGE = vol.All(
    cv.ensure_list,
    [cv.matches_regex(r"^(\d{1,2}-\d{1,2}|[LF][+-]\d+)$")],
    vol.Length(2, 2),
)
WINDOW_SCHEMA = vol.Schema(
    {
        vol.Optional("season", default="spring"): cv.string,
        vol.Optional("indoor"): RANGE,
        vol.Optional("direct"): RANGE,
        vol.Optional("transplant"): RANGE,
        vol.Optional("cover"): RANGE,
    }
)
CROP_FIELDS = {
    vol.Required("key"): cv.matches_regex(r"^[a-z0-9_]+$"),
    vol.Optional("name"): cv.string,
    vol.Optional("based_on"): cv.string,
    vol.Optional("windows"): vol.All(cv.ensure_list, [WINDOW_SCHEMA]),
    vol.Optional("weeks_indoor"): vol.All(vol.Coerce(int), vol.Range(min=1, max=30)),
    vol.Optional("days_to_harvest"): vol.All(vol.Coerce(int), vol.Range(min=1, max=1100)),
    vol.Optional("harvest_weeks"): vol.All(vol.Coerce(int), vol.Range(min=1, max=52)),
    vol.Optional("frost_tender"): cv.boolean,
    vol.Optional("pot_up"): cv.boolean,
    vol.Optional("perennial"): cv.boolean,
    vol.Optional("notes"): cv.string,
}


def _manager(hass: HomeAssistant) -> GardenManager:
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        raise ServiceValidationError("Garden Planner is not set up")
    return entries[0].runtime_data


def _mmdd(value: str) -> str:
    month, day = (int(p) for p in value.split("-"))
    return f"{month:02d}-{day:02d}"


def _planting_fields(call: ServiceCall) -> dict[str, Any]:
    fields = dict(call.data)
    fields.setdefault("year", default_year())
    for key in ("start_date", "succession_until"):
        if key in fields and fields[key] is not None:
            fields[key] = fields[key].isoformat()
    return fields


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the services."""

    async def add_planting(call: ServiceCall) -> ServiceResponse:
        manager = _manager(hass)
        try:
            planting, tasks = await manager.async_add_planting(_planting_fields(call))
        except PlannerError as err:
            raise ServiceValidationError(str(err)) from err
        return {"planting_id": planting.id, "tasks": [t.to_dict() for t in tasks]}

    async def preview_planting(call: ServiceCall) -> ServiceResponse:
        manager = _manager(hass)
        try:
            _, tasks = manager.preview(_planting_fields(call))
        except PlannerError as err:
            raise ServiceValidationError(str(err)) from err
        return {"tasks": [t.to_dict() for t in tasks]}

    async def remove_planting(call: ServiceCall) -> None:
        try:
            await _manager(hass).async_remove_planting(call.data["planting_id"])
        except PlannerError as err:
            raise ServiceValidationError(str(err)) from err

    async def add_crop(call: ServiceCall) -> None:
        manager = _manager(hass)
        data = dict(call.data)
        base: dict[str, Any] = {}
        if based_on := data.pop("based_on", None):
            try:
                base = manager.crop(based_on).to_dict()
            except PlannerError as err:
                raise ServiceValidationError(str(err)) from err
        merged = {**base, **data, "source": "custom"}
        if "name" not in merged:
            raise ServiceValidationError("A new crop needs a name")
        if not merged.get("windows"):
            raise ServiceValidationError("A new crop needs windows or based_on")
        if "windows" in data:
            # Calendar dates (MM-DD) are this garden's dates; store them as
            # offsets from its frost dates so they follow later changes.
            settings = manager.settings
            last_frost = settings.last_frost
            if merged.get("frost_tender") and settings.warm_last_frost:
                last_frost = settings.warm_last_frost
            windows = []
            for window in data["windows"]:
                converted = dict(window)
                for key in ("indoor", "direct", "transplant", "cover"):
                    if key in window:
                        converted[key] = [
                            value if OFFSET_RE.match(value) else mmdd_to_offset(
                                _mmdd(value), last_frost, settings.first_frost
                            )
                            for value in window[key]
                        ]
                windows.append(converted)
            merged["windows"] = windows
        crop = Crop.from_dict(merged)
        await manager.async_add_crop(crop)

    async def remove_crop(call: ServiceCall) -> None:
        try:
            await _manager(hass).async_remove_crop(call.data["key"])
        except PlannerError as err:
            raise ServiceValidationError(str(err)) from err

    async def list_crops(call: ServiceCall) -> ServiceResponse:
        manager = _manager(hass)
        return {
            "crops": [
                {**crop.to_dict(), "methods": crop.methods()}
                for crop in sorted(manager.crops.values(), key=lambda c: c.name)
            ]
        }

    async def sync(call: ServiceCall) -> None:
        await _manager(hass).async_sync()

    hass.services.async_register(
        DOMAIN, "add_planting", add_planting, vol.Schema(PLANTING_FIELDS),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, "preview_planting", preview_planting, vol.Schema(PLANTING_FIELDS),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, "remove_planting", remove_planting,
        vol.Schema({vol.Required("planting_id"): cv.string}),
    )
    hass.services.async_register(
        DOMAIN, "add_crop", add_crop, vol.Schema(CROP_FIELDS)
    )
    hass.services.async_register(
        DOMAIN, "remove_crop", remove_crop,
        vol.Schema({vol.Required("key"): cv.string}),
    )
    hass.services.async_register(
        DOMAIN, "list_crops", list_crops, vol.Schema({}),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(DOMAIN, "sync", sync, vol.Schema({}))
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Garden Planner from a config entry."""
    manager = GardenManager(hass, entry)
    await manager.async_setup()
    entry.runtime_data = manager
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    if not manager.uses_own_list:
        hass.async_create_task(manager.async_sync())
    return True


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_unload()
    return unloaded
