"""Fixes from the second review: settings changes, resets, list tracking."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er

from custom_components.reap.const import DEFAULTS, DOMAIN
from custom_components.reap.planner import (
    Planting,
    Settings,
    is_southern,
    load_catalog,
    mmdd_to_offset,
    offset_to_mmdd,
    sowing_dates,
)
from tests.test_init import GARDEN, OWN_LIST, _call, _items, _setup
from tests.test_review_fixes import _local_list

CATALOG = load_catalog()


async def _open_settings(hass: HomeAssistant, entry) -> dict:
    result = await hass.config_entries.options.async_init(entry.entry_id)
    return await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "settings"}
    )


# ----- N1: settings changes that break plantings -----


@pytest.mark.freeze_time("2027-03-01 12:00:00")
async def test_settings_warn_before_breaking_plantings(hass: HomeAssistant) -> None:
    entry = await _setup(hass)  # cool_spring
    manager = entry.runtime_data
    await _call(hass, "add_planting", {"crop": "kohlrabi", "method": "direct_bed", "year": 2027})
    await _call(hass, "add_planting", {
        "crop": "garlic", "method": "direct_bed", "year": 2027, "season": "spring",
    })
    await hass.async_block_till_done()
    items = len(await _items(hass, OWN_LIST))
    assert items

    result = await _open_settings(hass, entry)
    user = {**DEFAULTS, **GARDEN, "profile": "continental"}
    result = await hass.config_entries.options.async_configure(result["flow_id"], user)
    # First save: told which plantings would break.
    assert result["type"] == "form"
    assert result["errors"] == {"base": "plantings_break"}
    assert "Kohlrabi" in result["description_placeholders"]["plantings"]
    assert "Garlic" in result["description_placeholders"]["plantings"]
    # Saving again keeps the change.
    result = await hass.config_entries.options.async_configure(result["flow_id"], user)
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()

    manager = entry.runtime_data
    assert len(manager.problems) == 2
    state = hass.states.get("sensor.reap_plantings")
    assert len(state.attributes["problems"]) == 2
    assert all(p["problem"] for p in state.attributes["plantings"])
    # Their items stay on the list until the plantings are fixed.
    await _call(hass, "sync", {})
    assert len(await _items(hass, OWN_LIST)) == items

    # Fixing one (kohlrabi is started indoors on this profile) clears it.
    kohlrabi = next(p for p in manager.plantings() if p.crop == "kohlrabi")
    await _call(hass, "update_planting", {"planting_id": kohlrabi.id, "method": "indoor_bed"})
    assert kohlrabi.id not in manager.problems


async def test_settings_save_straight_away_when_nothing_breaks(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    await _call(hass, "add_planting", {"crop": "tomato", "method": "indoor_bed", "year": 2027})
    result = await _open_settings(hass, entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**DEFAULTS, **GARDEN, "harden_off_days": 10}
    )
    assert result["type"] == "create_entry"


# ----- N2: reset_crop -----


async def test_reset_crop_refuses_to_break_a_planting(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    manager = entry.runtime_data
    await _call(hass, "add_crop", {"key": "carrot", "windows": [
        {"season": "spring", "direct": ["03-01", "04-01"]},
        {"season": "summer", "direct": ["07-01", "07-20"]},
    ]})
    await _call(hass, "add_planting", {
        "crop": "carrot", "method": "direct_bed", "year": 2027, "season": "summer",
    })
    count = len(manager.tasks)
    with pytest.raises(ServiceValidationError, match="summer planting of Carrot"):
        await _call(hass, "reset_crop", {"key": "carrot"})
    assert len(manager.tasks) == count
    assert "carrot" in manager.data["custom_crops"]


# ----- N3: recovering after a failed read-back -----


@pytest.mark.freeze_time("2027-03-01 12:00:00")
async def test_failed_read_back_is_recovered(hass: HomeAssistant, tmp_path) -> None:
    target = await _local_list(hass, tmp_path)
    entry = await _setup(hass, todo_entity=target)
    manager = entry.runtime_data
    real = manager._async_get_items
    calls = {"n": 0}

    async def flaky(entity_id):
        calls["n"] += 1
        if calls["n"] == 2:  # the read-back after adding
            raise HomeAssistantError("timeout")
        return await real(entity_id)

    with patch.object(manager, "_async_get_items", flaky):
        await _call(hass, "add_planting", {"crop": "pea", "method": "direct_bed", "year": 2027})
    assert manager.data["unmatched"]
    await _call(hass, "sync", {})
    assert manager.data["unmatched"] == []
    items = await _items(hass, target)
    assert len(items) == len(manager.data["pushed"])  # nothing added twice
    pea = next(i for i in items if i["summary"].startswith("Sow Pea"))
    await hass.services.async_call(
        "todo", "update_item", {"entity_id": target, "item": pea["uid"], "status": "completed"},
        blocking=True,
    )
    await _call(hass, "sync", {})
    assert manager.data["actuals"]


# ----- N4: copies keep frost tender -----


async def test_configure_copy_keeps_frost_tender(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    manager = entry.runtime_data
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "add_crop"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"name": "Sungold", "category": "vegetable", "based_on": "tomato"}
    )
    assert result["type"] == "create_entry"
    assert manager.crop("sungold").frost_tender


# ----- N5, N6, N7: Reap's own list -----


async def test_renaming_own_list_keeps_its_items(hass: HomeAssistant) -> None:
    await _setup(hass)
    await _call(hass, "add_planting", {
        "crop": "pea", "method": "direct_bed", "start_date": date.today().isoformat(),
    })
    await hass.async_block_till_done()
    before = {i["uid"] for i in await _items(hass, OWN_LIST)}
    er.async_get(hass).async_update_entity(OWN_LIST, new_entity_id="todo.garden")
    await hass.async_block_till_done()
    await _call(hass, "sync", {})
    await hass.async_block_till_done()
    assert {i["uid"] for i in await _items(hass, "todo.garden")} == before


async def test_deleting_from_own_list_dismisses_at_once(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    manager = entry.runtime_data
    await _call(hass, "add_planting", {
        "crop": "radish", "method": "direct_bed", "start_date": date.today().isoformat(),
    })
    await hass.async_block_till_done()
    item = (await _items(hass, OWN_LIST))[0]
    # Deleting it starts one sync, and that one sync is enough.
    await hass.services.async_call(
        "todo", "remove_item", {"entity_id": OWN_LIST, "item": [item["uid"]]}, blocking=True
    )
    await hass.async_block_till_done()
    assert len(manager.data["dismissed"]) == 1
    assert manager.data["missing"] == []


async def test_own_notes_on_an_item_are_kept(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    manager = entry.runtime_data
    resp = await _call(hass, "add_planting", {
        "crop": "pea", "method": "direct_bed", "start_date": date.today().isoformat(),
        "quantity": "1 row",
    }, True)
    await hass.async_block_till_done()
    item = next(i for i in await _items(hass, OWN_LIST) if i["summary"].startswith("Sow"))
    await hass.services.async_call("todo", "update_item", {
        "entity_id": OWN_LIST, "item": item["uid"],
        "description": f"{item['description']}\nUsed the old seed packet.",
    }, blocking=True)
    await hass.async_block_till_done()
    await _call(hass, "update_planting", {"planting_id": resp["planting_id"], "quantity": "2 rows"})
    await hass.async_block_till_done()
    desc = next(i for i in await _items(hass, OWN_LIST) if i["uid"] == item["uid"])["description"]
    assert "Quantity: 2 rows" in desc
    assert desc.endswith("Used the old seed packet.")
    # An idle sync doesn't touch it again.
    with patch.object(manager, "_async_call", wraps=manager._async_call) as call:
        await manager.async_sync()
    assert not call.called


# ----- N8: seasons in calendar order -----


async def test_seasons_in_calendar_order(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    manager = entry.runtime_data
    info = manager.crop_info(manager.crop("pea"))
    assert info["seasons"] == [s for s in ("spring", "summer", "fall") if s in info["seasons"]]
    assert info["seasons"][0] == "spring"
    assert CATALOG["kohlrabi"].seasons("cool_spring")[0] == "spring"


# ----- N9: hemisphere from Home Assistant -----


def test_january_first_frost_in_the_north() -> None:
    # Frost-free most of the year, northern hemisphere: last 02-15, first 01-10.
    north = Settings(last_frost="02-15", first_frost="01-10", southern=False)
    assert not is_southern(north)
    assert mmdd_to_offset("03-01", "02-15", "01-10", southern=False) == "L+14"
    nov = mmdd_to_offset("11-01", "02-15", "01-10", southern=False)
    assert nov == "F-70"
    crop = CATALOG["lettuce"]
    assert offset_to_mmdd(nov, crop, north) == "11-01"
    sched = sowing_dates(
        Planting(id="p", crop="lettuce", method="direct_bed", year=2027), crop, north
    )
    assert sched.window_start.year == 2027


async def test_hemisphere_follows_home_location(hass: HomeAssistant) -> None:
    hass.config.latitude = -41.3
    entry = await _setup(hass, last_frost="09-20", first_frost="05-10", warm_last_frost="")
    assert entry.runtime_data.settings.southern is True
    assert hass.config_entries.async_entries(DOMAIN)
