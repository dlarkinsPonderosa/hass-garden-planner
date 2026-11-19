"""Reap: seed starting and planting schedules as Home Assistant tasks."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
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
from homeassistant.loader import async_get_integration

from .const import DOMAIN
from .manager import GardenManager, default_year
from .planner import METHODS, OFFSET_RE, PlannerError

PLATFORMS = [Platform.SENSOR, Platform.TODO]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLANTING_FIELDS = {
    vol.Required("crop"): cv.string,
    vol.Optional("method"): vol.In(METHODS),
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

def _clearable(validator: Any) -> Any:
    """Accept a value, or an empty string / None to clear it."""
    return vol.Any(None, vol.All(str, vol.Length(max=0)), validator)


UPDATE_FIELDS = {
    vol.Required("planting_id"): cv.string,
    vol.Optional("crop"): cv.string,
    vol.Optional("method"): vol.In(METHODS),
    vol.Optional("year"): vol.All(vol.Coerce(int), vol.Range(min=2000, max=2100)),
    vol.Optional("season"): _clearable(cv.string),
    vol.Optional("start_date"): _clearable(cv.date),
    vol.Optional("succession_days"): _clearable(vol.All(vol.Coerce(int), vol.Range(min=0, max=365))),
    vol.Optional("succession_count"): _clearable(vol.All(vol.Coerce(int), vol.Range(min=1, max=200))),
    vol.Optional("succession_until"): _clearable(cv.date),
    vol.Optional("variety"): _clearable(cv.string),
    vol.Optional("quantity"): _clearable(cv.string),
    vol.Optional("location"): _clearable(cv.string),
    vol.Optional("notes"): _clearable(cv.string),
}

RANGE = vol.All(
    cv.ensure_list,
    [cv.matches_regex(r"^((\d{4}-)?\d{1,2}-\d{1,2}|[LF][+-]\d+)$")],
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
    vol.Optional("icon"): cv.icon,
    vol.Optional("category"): vol.In(["vegetable", "herb", "fruit", "flower"]),
}


def _manager(hass: HomeAssistant) -> GardenManager:
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        raise ServiceValidationError("Reap is not set up")
    return entries[0].runtime_data


def _planting_fields(call: ServiceCall) -> dict[str, Any]:
    fields = dict(call.data)
    fields.setdefault("year", default_year())
    for key in ("start_date", "succession_until"):
        if key in fields and fields[key] is not None:
            fields[key] = fields[key].isoformat()
    return fields


_LOGGER = logging.getLogger(__name__)

CARD_URL = "/reap/reap-card.js"
CARD_PATH = Path(__file__).parent / "frontend" / "reap-card.js"


async def _async_register_card(hass: HomeAssistant) -> None:
    """Serve the dashboard card and load it on every dashboard."""
    if hass.http is None or "frontend" not in hass.config.components:
        return  # no web UI, such as some test setups
    version = (await async_get_integration(hass, DOMAIN)).version
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(CARD_PATH), cache_headers=False)]
    )
    url = f"{CARD_URL}?v={version}"
    add_extra_js_url(hass, url)
    try:
        await _async_ensure_resource(hass, url)
    except Exception:  # noqa: BLE001 - never block setup over the card
        _LOGGER.warning(
            "Could not add the Reap card to dashboard resources; add %s as a "
            "JavaScript module under Settings > Dashboards > Resources",
            CARD_URL,
            exc_info=True,
        )


async def _async_ensure_resource(hass: HomeAssistant, url: str) -> None:
    """Add (or update) the card as a dashboard resource in storage mode.

    Some frontends do not load extra module URLs reliably, while dashboard
    resources always load. Only storage-mode resources can be edited.
    """
    lovelace = hass.data.get("lovelace")
    resources = getattr(lovelace, "resources", None)
    if resources is None or getattr(lovelace, "resource_mode", "storage") != "storage":
        return
    if not getattr(resources, "loaded", True):
        await resources.async_load()
        resources.loaded = True
    for item in resources.async_items():
        if str(item.get("url", "")).split("?")[0] == CARD_URL:
            if item["url"] != url:
                await resources.async_update_item(item["id"], {"url": url})
            return
    await resources.async_create_item({"res_type": "module", "url": url})


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the services and the dashboard card."""
    await _async_register_card(hass)

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

    async def update_planting(call: ServiceCall) -> ServiceResponse:
        manager = _manager(hass)
        changes = dict(call.data)
        planting_id = changes.pop("planting_id")
        for key in ("start_date", "succession_until"):
            if changes.get(key) not in (None, ""):
                changes[key] = changes[key].isoformat()
        try:
            planting, tasks = await manager.async_update_planting(planting_id, changes)
        except PlannerError as err:
            raise ServiceValidationError(str(err)) from err
        return {"planting_id": planting.id, "tasks": [t.to_dict() for t in tasks]}

    async def remove_planting(call: ServiceCall) -> None:
        try:
            await _manager(hass).async_remove_planting(call.data["planting_id"])
        except PlannerError as err:
            raise ServiceValidationError(str(err)) from err

    async def add_crop(call: ServiceCall) -> None:
        try:
            await _manager(hass).async_save_crop(dict(call.data))
        except PlannerError as err:
            raise ServiceValidationError(str(err)) from err

    async def remove_crop(call: ServiceCall) -> None:
        try:
            await _manager(hass).async_remove_crop(call.data["key"])
        except PlannerError as err:
            raise ServiceValidationError(str(err)) from err

    async def list_crops(call: ServiceCall) -> ServiceResponse:
        manager = _manager(hass)
        return {
            "crops": [
                manager.crop_info(crop)
                for crop in sorted(manager.crops.values(), key=lambda c: c.name)
            ]
        }

    async def set_crop_defaults(call: ServiceCall) -> None:
        manager = _manager(hass)
        data = dict(call.data)
        key = data.pop("crop")
        clear = data.pop("clear", False)
        try:
            await manager.async_set_crop_defaults(key, None if clear else data)
        except PlannerError as err:
            raise ServiceValidationError(str(err)) from err

    async def add_location(call: ServiceCall) -> ServiceResponse:
        try:
            location = await _manager(hass).async_add_location(
                call.data["name"], call.data.get("soil_sensor"), call.data.get("light")
            )
        except PlannerError as err:
            raise ServiceValidationError(str(err)) from err
        return {"location": location}

    async def update_location(call: ServiceCall) -> ServiceResponse:
        changes = dict(call.data)
        location_id = changes.pop("location_id")
        try:
            location = await _manager(hass).async_update_location(location_id, changes)
        except PlannerError as err:
            raise ServiceValidationError(str(err)) from err
        return {"location": location}

    async def remove_location(call: ServiceCall) -> None:
        try:
            await _manager(hass).async_remove_location(call.data["location_id"])
        except PlannerError as err:
            raise ServiceValidationError(str(err)) from err

    async def list_locations(call: ServiceCall) -> ServiceResponse:
        return {"locations": _manager(hass).locations()}

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
        DOMAIN, "update_planting", update_planting, vol.Schema(UPDATE_FIELDS),
        supports_response=SupportsResponse.OPTIONAL,
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
    hass.services.async_register(
        DOMAIN, "set_crop_defaults", set_crop_defaults,
        vol.Schema(
            {
                vol.Required("crop"): cv.string,
                vol.Optional("method"): vol.In(METHODS),
                vol.Optional("succession_days"): vol.All(vol.Coerce(int), vol.Range(min=0, max=365)),
                vol.Optional("succession_count"): vol.All(vol.Coerce(int), vol.Range(min=1, max=200)),
                vol.Optional("quantity"): cv.string,
                vol.Optional("location"): cv.string,
                vol.Optional("clear", default=False): cv.boolean,
            }
        ),
    )
    entity_or_empty = vol.Any(cv.entity_id, "", None)
    hass.services.async_register(
        DOMAIN, "add_location", add_location,
        vol.Schema(
            {
                vol.Required("name"): cv.string,
                vol.Optional("soil_sensor"): entity_or_empty,
                vol.Optional("light"): entity_or_empty,
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, "update_location", update_location,
        vol.Schema(
            {
                vol.Required("location_id"): cv.string,
                vol.Optional("name"): cv.string,
                vol.Optional("soil_sensor"): entity_or_empty,
                vol.Optional("light"): entity_or_empty,
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, "remove_location", remove_location,
        vol.Schema({vol.Required("location_id"): cv.string}),
    )
    hass.services.async_register(
        DOMAIN, "list_locations", list_locations, vol.Schema({}),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(DOMAIN, "sync", sync, vol.Schema({}))
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Reap from a config entry."""
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
