"""Integration tests with a running Home Assistant."""

from __future__ import annotations

from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.garden_planner.const import (
    CONF_TODO_ENTITY,
    DEFAULTS,
    DOMAIN,
    NEW_LIST,
)

OWN_LIST = "todo.garden_planner_garden_tasks"


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


async def test_config_flow_defaults(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == "form"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**DEFAULTS, "last_frost": "3-6"}
    )
    assert result["type"] == "create_entry"
    assert result["data"]["last_frost"] == "03-06"
    assert result["data"][CONF_TODO_ENTITY] == NEW_LIST


async def test_config_flow_bad_date(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**DEFAULTS, "first_frost": "13-40"}
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

    assert hass.states.get("sensor.garden_planner_overdue_tasks").state == "1"
    assert hass.states.get("sensor.garden_planner_next_task").state == "Sow Tomato indoors"
    plantings = hass.states.get("sensor.garden_planner_plantings")
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
    assert hass.states.get("sensor.garden_planner_overdue_tasks").state == "0"

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
    assert result["type"] == "form"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**DEFAULTS, "greenhouse_spring_weeks": 6}
    )
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()
    assert entry.runtime_data.settings.greenhouse_spring_weeks == 6
