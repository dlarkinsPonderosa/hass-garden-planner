"""Integration tests with a running Home Assistant."""

from __future__ import annotations

from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.reap.const import (
    CONF_TODO_ENTITY,
    DEFAULTS,
    DOMAIN,
    NEW_LIST,
)

OWN_LIST = "todo.reap_garden_tasks"


async def _items(hass: HomeAssistant, entity_id: str) -> list[dict[str, Any]]:
    resp = await hass.services.async_call(
        "todo", "get_items", {"entity_id": entity_id}, blocking=True, return_response=True
    )
    return resp[entity_id]["items"]


# Test garden: early last frost, with warm crops timed from Apr 1, cool spring.
GARDEN = {
    "last_frost": "03-06", "first_frost": "11-16",
    "warm_last_frost": "04-01", "profile": "cool_spring",
}


async def _setup(hass: HomeAssistant, **data: Any) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data={**DEFAULTS, **GARDEN, **data}, unique_id=DOMAIN)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


LOCATION = {k: v for k, v in DEFAULTS.items() if k != CONF_TODO_ENTITY}


async def _start_flow(hass: HomeAssistant, zone: str) -> dict[str, Any]:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == "form"
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_TODO_ENTITY: NEW_LIST, "zone": zone}
    )


async def test_config_flow_own_dates(hass: HomeAssistant) -> None:
    result = await _start_flow(hass, "custom")
    assert result["step_id"] == "location"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**LOCATION, **GARDEN, "last_frost": "3-6"}
    )
    assert result["type"] == "create_entry"
    assert result["data"]["last_frost"] == "03-06"
    assert result["data"]["warm_last_frost"] == "04-01"
    assert result["data"][CONF_TODO_ENTITY] == NEW_LIST


async def test_config_flow_zone_suggests_frost_dates(hass: HomeAssistant) -> None:
    result = await _start_flow(hass, "5")
    schema = result["data_schema"].schema
    defaults = {str(k): k.default() for k in schema if callable(getattr(k, "default", None))}
    assert defaults["last_frost"] == "04-30"
    assert defaults["first_frost"] == "10-10"
    assert defaults["profile"] == "continental"
    user = {**LOCATION, "last_frost": "04-30", "first_frost": "10-10", "offset_days": -7}
    user.pop("warm_last_frost")
    user["profile"] = "continental"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], user)
    assert result["type"] == "create_entry"
    assert result["data"]["warm_last_frost"] == ""
    assert result["data"]["offset_days"] == -7
    assert result["data"]["profile"] == "continental"


async def test_config_flow_bad_date(hass: HomeAssistant) -> None:
    result = await _start_flow(hass, "custom")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**LOCATION, "first_frost": "13-40"}
    )
    assert result["errors"] == {"first_frost": "invalid_month_day"}


@pytest.mark.freeze_time("2027-02-20 12:00:00")
async def test_own_list_planting_flow(hass: HomeAssistant) -> None:
    await _setup(hass)
    assert hass.states.get(OWN_LIST) is not None

    preview = await hass.services.async_call(
        DOMAIN, "preview_planting",
        {"crop": "tomato", "method": "indoor_greenhouse", "year": 2027},
        blocking=True, return_response=True,
    )
    assert preview["tasks"][0]["summary"] == "Sow Tomato indoors"
    assert await _items(hass, OWN_LIST) == []

    resp = await hass.services.async_call(
        DOMAIN, "add_planting",
        {"crop": "tomato", "method": "indoor_greenhouse", "year": 2027, "quantity": "6 cells"},
        blocking=True, return_response=True,
    )
    await hass.async_block_till_done()
    planting_id = resp["planting_id"]

    # Lookahead is 30 days from Feb 20: sowing (Feb 13, overdue) and pot up
    # (Mar 9) are on the list, transplant (Apr 3) is not yet.
    items = await _items(hass, OWN_LIST)
    summaries = [i["summary"] for i in items]
    assert summaries == ["Sow Tomato indoors", "Pot up Tomato"]
    assert items[0]["due"] == "2027-02-13"
    assert "6 cells" in items[0]["description"]

    assert hass.states.get("sensor.reap_overdue_tasks").state == "1"
    assert hass.states.get("sensor.reap_next_task").state == "Sow Tomato indoors"
    plantings = hass.states.get("sensor.reap_plantings")
    assert plantings.state == "1"
    assert plantings.attributes["plantings"][0]["crop_name"] == "Tomato"

    # Tick off the sowing: it's recorded as done today (7 days late) and the
    # rest of the chain moves 7 days later.
    await hass.services.async_call(
        "todo", "update_item",
        {"entity_id": OWN_LIST, "item": items[0]["uid"], "status": "completed"},
        blocking=True,
    )
    await hass.async_block_till_done()
    items = {i["summary"]: i for i in await _items(hass, OWN_LIST)}
    assert items["Pot up Tomato"]["due"] == "2027-03-16"
    assert hass.states.get("sensor.reap_overdue_tasks").state == "0"

    # Removing the planting clears its open tasks but leaves completed ones.
    await hass.services.async_call(
        DOMAIN, "remove_planting", {"planting_id": planting_id}, blocking=True
    )
    await hass.async_block_till_done()
    left = await _items(hass, OWN_LIST)
    assert [i["status"] for i in left] == ["completed"]


@pytest.mark.freeze_time("2027-03-01 12:00:00")
async def test_deleted_task_is_not_re_added(hass: HomeAssistant) -> None:
    await _setup(hass)
    await hass.services.async_call(
        DOMAIN, "add_planting",
        {"crop": "radish", "method": "direct_bed", "year": 2027},
        blocking=True,
    )
    await hass.async_block_till_done()
    items = await _items(hass, OWN_LIST)
    # Radish: sow Feb 3 (shifted), harvest from Mar 3.
    assert [i["summary"] for i in items] == ["Sow Radish in beds", "Harvest Radish"]
    await hass.services.async_call(
        "todo", "remove_item", {"entity_id": OWN_LIST, "item": [items[0]["uid"]]},
        blocking=True,
    )
    await hass.async_block_till_done()
    await hass.services.async_call(DOMAIN, "sync", {}, blocking=True)
    await hass.async_block_till_done()
    assert [i["summary"] for i in await _items(hass, OWN_LIST)] == ["Harvest Radish"]


@pytest.mark.freeze_time("2027-03-01 12:00:00")
async def test_existing_list(hass: HomeAssistant, tmp_path) -> None:
    """Tasks go onto an existing Local To-do list."""
    local = MockConfigEntry(
        domain="local_todo",
        data={"todo_list_name": "Family List", "storage_key": "family_list"},
    )
    local.add_to_hass(hass)
    hass.config.config_dir = str(tmp_path)
    (tmp_path / ".storage").mkdir()
    assert await hass.config_entries.async_setup(local.entry_id)
    await hass.async_block_till_done()
    target = "todo.family_list"
    assert hass.states.get(target) is not None
    await hass.services.async_call(
        "todo", "add_item", {"entity_id": target, "item": "Buy milk"}, blocking=True
    )

    await _setup(hass, todo_entity=target)
    assert hass.states.get(OWN_LIST) is None

    await hass.services.async_call(
        DOMAIN, "add_planting",
        {"crop": "pea", "method": "direct_bed", "year": 2027, "succession_days": 14},
        blocking=True,
    )
    await hass.async_block_till_done()
    items = await _items(hass, target)
    summaries = [i["summary"] for i in items]
    assert "Buy milk" in summaries
    peas = [i for i in items if i["summary"].startswith("Sow Pea")]
    # Peas: chart Feb 15 shifted 26 days earlier = Jan 20, then every 14 days.
    # Within 30 days of Mar 1: Jan 20, Feb 3, Feb 17, Mar 3, Mar 17, Mar 31.
    assert [p["due"] for p in peas] == [
        "2027-01-20", "2027-02-03", "2027-02-17", "2027-03-03", "2027-03-17", "2027-03-31",
    ]

    # Ticking it off on the shared list is picked up.
    await hass.services.async_call(
        "todo", "update_item",
        {"entity_id": target, "item": peas[0]["uid"], "status": "completed"},
        blocking=True,
    )
    await hass.async_block_till_done()
    await hass.services.async_call(DOMAIN, "sync", {}, blocking=True)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    actuals = entry.runtime_data.data["actuals"]
    assert list(actuals.values()) == ["2027-03-01"]


async def test_options_flow(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == "menu"
    assert result["menu_options"] == ["add_planting", "add_crop", "settings"]
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "settings"}
    )
    assert result["type"] == "form"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**DEFAULTS, "greenhouse_spring_weeks": 6}
    )
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()
    assert entry.runtime_data.settings.greenhouse_spring_weeks == 6


async def test_add_crop_with_calendar_dates(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    await hass.services.async_call(
        DOMAIN, "add_crop",
        {
            "key": "sweet_potato", "name": "Sweet potato", "frost_tender": True,
            "windows": [{"season": "spring", "transplant": ["05-15", "06-15"]}],
            "days_to_harvest": 110,
        },
        blocking=True,
    )
    crop = entry.runtime_data.crop("sweet_potato")
    # Stored relative to the warm-crop frost date (Apr 1), so May 15 = L+44.
    assert crop.windows[0].transplant == ("L+44", "L+75")
    _, tasks = entry.runtime_data.preview(
        {"crop": "sweet_potato", "method": "indoor_bed", "year": 2027}
    )
    assert any(t.kind == "transplant" and t.due.isoformat() == "2027-05-15" for t in tasks)

    tomato_variety = {"key": "tomato_sungold", "name": "Tomato, Sungold", "based_on": "tomato", "days_to_harvest": 105}
    await hass.services.async_call(DOMAIN, "add_crop", tomato_variety, blocking=True)
    assert entry.runtime_data.crop("tomato_sungold").windows == entry.runtime_data.crop("tomato").windows


@pytest.mark.freeze_time("2027-02-20 12:00:00")
async def test_add_and_remove_planting_from_configure(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"next_step_id": "add_planting"}
    )
    assert result["step_id"] == "add_planting"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"crop": "carrot"}
    )
    assert result["step_id"] == "planting_details"
    # Carrots can only be direct sown.
    methods = [o["value"] for o in result["data_schema"].schema["method"].config["options"]]
    assert methods == ["direct_bed", "direct_greenhouse"]
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"method": "direct_bed", "year": 2027, "succession_days": 7,
         "succession_count": 3, "location": "Bed 3"},
    )
    assert result["step_id"] == "planting_confirm"
    assert "Sow Carrot in beds (sowing 1 of 3)" in result["description_placeholders"]["tasks"]
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()
    manager = entry.runtime_data
    assert [p.crop for p in manager.plantings()] == ["carrot"]
    assert manager.plantings()[0].location == "Bed 3"

    # The integration wasn't reloaded, so the planting is still there.
    assert entry.runtime_data is manager

    flow = await hass.config_entries.options.async_init(entry.entry_id)
    assert "remove_planting" in flow["menu_options"]
    result = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"next_step_id": "remove_planting"}
    )
    planting_id = manager.plantings()[0].id
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"plantings": [planting_id]}
    )
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()
    assert manager.plantings() == []



@pytest.mark.freeze_time("2027-02-20 12:00:00")
async def test_update_planting(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    resp = await hass.services.async_call(
        DOMAIN, "add_planting",
        {"crop": "carrot", "method": "direct_bed", "year": 2027,
         "succession_days": 7, "location": "Bed 3"},
        blocking=True, return_response=True,
    )
    planting_id = resp["planting_id"]
    resp = await hass.services.async_call(
        DOMAIN, "update_planting",
        {"planting_id": planting_id, "succession_days": 14, "succession_count": 2, "location": ""},
        blocking=True, return_response=True,
    )
    planting = entry.runtime_data.plantings()[0]
    assert planting.succession_days == 14
    assert planting.succession_count == 2
    assert planting.location is None
    sows = [t for t in resp["tasks"] if t["kind"] == "sow"]
    assert [t["due"] for t in sows] == ["2027-03-06", "2027-03-20"]


async def test_crop_defaults(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    manager = entry.runtime_data
    # Built-in: carrots are sown every 3 weeks, tomatoes started indoors.
    assert manager.crop_defaults("carrot") == {"method": "direct_bed", "succession_days": 21}
    assert manager.crop_defaults("tomato") == {"method": "indoor_bed"}

    await hass.services.async_call(
        DOMAIN, "set_crop_defaults",
        {"crop": "tomato", "method": "indoor_greenhouse", "quantity": "6 cells"},
        blocking=True,
    )
    assert manager.crop_defaults("tomato") == {"method": "indoor_greenhouse", "quantity": "6 cells"}
    crops = await hass.services.async_call(
        DOMAIN, "list_crops", {}, blocking=True, return_response=True
    )
    tomato = next(c for c in crops["crops"] if c["key"] == "tomato")
    assert tomato["defaults"]["method"] == "indoor_greenhouse"
    assert tomato["icon"] == "mdi:fruit-cherries"

    # add_planting without a method uses the crop's default.
    resp = await hass.services.async_call(
        DOMAIN, "add_planting", {"crop": "tomato", "year": 2027},
        blocking=True, return_response=True,
    )
    assert any("greenhouse" in t["summary"] for t in resp["tasks"])

    await hass.services.async_call(
        DOMAIN, "set_crop_defaults", {"crop": "tomato", "clear": True}, blocking=True
    )
    assert manager.crop_defaults("tomato") == {"method": "indoor_bed"}


async def test_configure_prefills_crop_defaults(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"next_step_id": "add_planting"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"crop": "radish"}
    )
    schema = result["data_schema"].schema
    suggested = {
        str(k): (k.description or {}).get("suggested_value")
        for k in schema
    }
    assert suggested["succession_days"] == 14
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"method": "direct_bed", "year": 2027, "succession_days": 10,
         "quantity": "1 row", "save_defaults": True},
    )
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["type"] == "create_entry"
    assert entry.runtime_data.crop_defaults("radish") == {
        "method": "direct_bed", "succession_days": 10, "quantity": "1 row",
    }


async def test_card_resource_added_and_updated(hass) -> None:
    """The card is added once as a dashboard resource and kept on the current version."""
    from types import SimpleNamespace

    from custom_components.reap import CARD_URL, _async_ensure_resource

    class FakeResources:
        loaded = True

        def __init__(self, items):
            self.items = items

        def async_items(self):
            return self.items

        async def async_create_item(self, data):
            self.items.append({"id": "new", "type": data["res_type"], "url": data["url"]})

        async def async_update_item(self, item_id, updates):
            for item in self.items:
                if item["id"] == item_id:
                    item.update(updates)

    res = FakeResources([{"id": "a", "type": "module", "url": "/other/card.js"}])
    hass.data["lovelace"] = SimpleNamespace(resource_mode="storage", resources=res)
    await _async_ensure_resource(hass, f"{CARD_URL}?v=1")
    await _async_ensure_resource(hass, f"{CARD_URL}?v=1")
    assert [i["url"] for i in res.items] == ["/other/card.js", f"{CARD_URL}?v=1"]

    # A manually added resource without a version is reused and updated.
    res.items = [{"id": "m", "type": "module", "url": CARD_URL}]
    await _async_ensure_resource(hass, f"{CARD_URL}?v=2")
    assert res.items == [{"id": "m", "type": "module", "url": f"{CARD_URL}?v=2"}]

    # YAML-mode resources are left alone.
    yaml_res = FakeResources([])
    hass.data["lovelace"] = SimpleNamespace(resource_mode="yaml", resources=yaml_res)
    await _async_ensure_resource(hass, f"{CARD_URL}?v=2")
    assert yaml_res.items == []


async def _call(hass: HomeAssistant, service: str, data: dict[str, Any], response: bool = False):
    return await hass.services.async_call(
        DOMAIN, service, data, blocking=True, return_response=response
    )


async def test_locations(hass: HomeAssistant) -> None:
    """Default locations, add/rename/remove, and plantings following a rename."""
    from homeassistant.exceptions import ServiceValidationError

    entry = await _setup(hass)
    manager = entry.runtime_data
    resp = await _call(hass, "list_locations", {}, True)
    assert [loc["name"] for loc in resp["locations"]] == ["Seedling Tray", "Garden", "Greenhouse"]

    resp = await _call(hass, "add_location", {"name": "Bed 3", "soil_sensor": "sensor.bed_3_moisture"}, True)
    bed = resp["location"]
    assert bed["soil_sensor"] == "sensor.bed_3_moisture" and bed["light"] is None
    with pytest.raises(ServiceValidationError):
        await _call(hass, "add_location", {"name": "bed 3"})

    # Plantings use a location by name, matched without case.
    await _call(hass, "add_planting", {"crop": "carrot", "method": "direct_bed", "year": 2027, "location": "BED 3"}, True)
    assert manager.plantings()[0].location == "Bed 3"
    with pytest.raises(ServiceValidationError):
        await _call(hass, "remove_location", {"location_id": bed["id"]})

    await _call(hass, "update_location", {"location_id": bed["id"], "name": "North bed", "light": "switch.grow_lights", "soil_sensor": ""})
    assert manager.plantings()[0].location == "North bed"
    loc = next(l for l in manager.locations() if l["id"] == bed["id"])
    assert loc == {**loc, "name": "North bed", "light": "switch.grow_lights", "soil_sensor": None, "plantings": 1}
    attrs = hass.states.get("sensor.reap_plantings").attributes
    assert any(l["name"] == "North bed" for l in attrs["locations"])

    # A new name on a planting creates the location.
    await _call(hass, "add_planting", {"crop": "pea", "method": "direct_bed", "year": 2027, "location": "Trellis"}, True)
    assert "Trellis" in [l["name"] for l in manager.locations()]

    garden = next(l for l in manager.locations() if l["name"] == "Garden")
    await _call(hass, "remove_location", {"location_id": garden["id"]})
    assert "Garden" not in [l["name"] for l in manager.locations()]


async def test_existing_free_text_locations_are_migrated(hass: HomeAssistant, hass_storage) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data=dict(DEFAULTS), unique_id=DOMAIN)
    hass_storage[f"{DOMAIN}.{entry.entry_id}"] = {
        "version": 1, "key": f"{DOMAIN}.{entry.entry_id}",
        "data": {"plantings": {"a1": {"id": "a1", "crop": "onion", "method": "indoor_bed", "year": 2027, "location": "Seed tray 1"}}},
    }
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    names = [l["name"] for l in entry.runtime_data.locations()]
    assert names == ["Seedling Tray", "Garden", "Greenhouse", "Seed tray 1"]


async def test_custom_crop_round_trip(hass: HomeAssistant) -> None:
    """A crop added with garden dates lists those dates back for editing."""
    from homeassistant.exceptions import ServiceValidationError

    entry = await _setup(hass, profile="continental")
    await _call(hass, "add_crop", {
        "key": "okra", "name": "Okra", "based_on": "tomato", "icon": "mdi:chili-mild",
        "category": "vegetable", "days_to_harvest": 60,
        "windows": [{"season": "spring", "indoor": ["2027-03-01", "03-20"], "transplant": ["05-15", "06-01"]}],
    })
    crop = entry.runtime_data.crop("okra")
    # Its own dates win over the base crop's climate profiles.
    assert crop.profiles == {}
    resp = await _call(hass, "list_crops", {}, True)
    okra = next(c for c in resp["crops"] if c["key"] == "okra")
    assert okra["custom"] and not okra["in_use"]
    assert okra["icon"] == "mdi:chili-mild"
    assert okra["windows"] == [{"season": "spring", "indoor": ["03-01", "03-20"], "transplant": ["05-15", "06-01"]}]
    tomato = next(c for c in resp["crops"] if c["key"] == "tomato")
    assert not tomato["custom"] and "windows" not in tomato

    with pytest.raises(ServiceValidationError):
        await _call(hass, "add_crop", {"key": "nothing", "name": "Nothing"})
    with pytest.raises(ServiceValidationError):
        await _call(hass, "add_crop", {"key": "bad", "name": "Bad", "windows": [{"indoor": ["03-01", "03-20"]}]})


async def test_add_crop_from_configure(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    assert "add_crop" in flow["menu_options"]
    result = await hass.config_entries.options.async_configure(flow["flow_id"], {"next_step_id": "add_crop"})
    assert result["step_id"] == "add_crop"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"name": "Tulsi", "category": "herb", "spring_direct_from": "2026-04-15"}
    )
    assert result["errors"] == {"base": "crop_error"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"name": "Tulsi", "category": "herb", "icon": "mdi:leaf",
         "spring_direct_from": "2026-04-15", "spring_direct_to": "2026-05-31", "days_to_harvest": 60},
    )
    assert result["type"] == "create_entry"
    crop = entry.runtime_data.crop("tulsi")
    assert crop.category == "herb" and crop.icon == "mdi:leaf"
    assert crop.windows[0].direct == ("L+40", "L+86")
    # Adding the same name again makes a second key instead of overwriting.
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(flow["flow_id"], {"next_step_id": "add_crop"})
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"name": "Tomato", "category": "vegetable", "based_on": "tomato"}
    )
    assert result["type"] == "create_entry"
    assert entry.runtime_data.crop("tomato_2").name == "Tomato"
