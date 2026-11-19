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


async def _setup(hass: HomeAssistant, **data: Any) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data={**DEFAULTS, **data}, unique_id=DOMAIN)
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


async def test_config_flow_victoria(hass: HomeAssistant) -> None:
    result = await _start_flow(hass, "victoria")
    assert result["step_id"] == "location"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**LOCATION, "last_frost": "3-6"}
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
    """Tasks go onto an existing Local To-do list, like Darren's List."""
    local = MockConfigEntry(
        domain="local_todo",
        data={"todo_list_name": "Darren's List", "storage_key": "darrens_list"},
    )
    local.add_to_hass(hass)
    hass.config.config_dir = str(tmp_path)
    (tmp_path / ".storage").mkdir()
    assert await hass.config_entries.async_setup(local.entry_id)
    await hass.async_block_till_done()
    target = "todo.darren_s_list"
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
    assert result["menu_options"] == ["add_planting", "settings"]
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
