"""Indoor starts move from their start location to where they're planted out."""

from __future__ import annotations

import pytest

from homeassistant.core import HomeAssistant

from custom_components.reap.planner import Planting, Settings, generate_tasks, load_catalog
from tests.test_init import OWN_LIST, _call, _items, _setup


def test_tasks_name_the_right_place() -> None:
    crop = load_catalog()["tomato"]
    planting = Planting(
        id="t", crop="tomato", method="indoor_bed", year=2027,
        location="Bed 3", start_location="Seedling tray 1",
    )
    tasks = {t.kind: t for t in generate_tasks(planting, crop, Settings())}
    assert "Location: Seedling tray 1" in tasks["sow_indoors"].description
    assert "Transplant to Bed 3 about" in tasks["sow_indoors"].description
    assert "Location: Seedling tray 1" in tasks["harden_off"].description
    assert "Location: Bed 3" in tasks["transplant"].description
    assert "Location: Bed 3" in tasks["harvest"].description


@pytest.mark.freeze_time("2027-06-01 12:00:00")
async def test_planting_moves_when_planted_out(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    manager = entry.runtime_data
    resp = await _call(hass, "add_planting", {
        "crop": "tomato", "method": "indoor_bed", "year": 2027,
        "location": "Bed 3", "start_location": "Seedling tray 1",
    }, True)
    await hass.async_block_till_done()
    planting_id = resp["planting_id"]

    def where() -> tuple[str, int, int]:
        state = hass.states.get("sensor.reap_plantings")
        planting = next(p for p in state.attributes["plantings"] if p["id"] == planting_id)
        counts = {x["name"]: x["plantings"] for x in manager.locations()}
        return planting["current_location"], counts.get("Seedling tray 1", 0), counts.get("Bed 3", 0)

    async def tick(start: str, status: str = "completed") -> None:
        item = next(i for i in await _items(hass, OWN_LIST) if i["summary"].startswith(start))
        await hass.services.async_call(
            "todo", "update_item", {"entity_id": OWN_LIST, "item": item["uid"], "status": status},
            blocking=True,
        )
        await hass.async_block_till_done()

    assert where() == ("Seedling tray 1", 1, 0)
    # Ticking off sowing indoors doesn't move it.
    await tick("Sow Tomato indoors")
    assert where()[0] == "Seedling tray 1"
    # Transplanting does, and the task names the bed.
    await tick("Transplant Tomato to Bed 3")
    assert where() == ("Bed 3", 0, 1)
    # Un-ticking moves it back.
    await tick("Transplant Tomato to Bed 3", "needs_action")
    assert where()[0] == "Seedling tray 1"
    await tick("Transplant Tomato to Bed 3")

    # Changing where it went is just an edit.
    await _call(hass, "update_planting", {"planting_id": planting_id, "location": "Greenhouse"})
    await hass.async_block_till_done()
    assert where()[0] == "Greenhouse"


async def test_start_location_only_for_indoor_starts(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    manager = entry.runtime_data
    resp = await _call(hass, "add_planting", {
        "crop": "lettuce", "method": "indoor_bed", "year": 2027,
        "start_location": "Shelf",
    }, True)
    planting_id = resp["planting_id"]
    assert manager.data["plantings"][planting_id]["start_location"] == "Shelf"
    # Without a plant-out location it shows where it starts.
    planting = next(p for p in manager.plantings() if p.id == planting_id)
    assert manager.current_location(planting) == "Shelf"
    # Switching to direct sowing drops it.
    await _call(hass, "update_planting", {"planting_id": planting_id, "method": "direct_bed"})
    assert manager.data["plantings"][planting_id]["start_location"] is None


async def test_locations_in_use_rename_and_remove(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    manager = entry.runtime_data
    await _call(hass, "add_planting", {
        "crop": "pepper", "method": "indoor_greenhouse", "year": 2027,
        "location": "Greenhouse", "start_location": "Heat mat",
    })
    mat = next(x for x in manager.locations() if x["name"] == "Heat mat")
    # A start location in use can't be removed.
    try:
        await _call(hass, "remove_location", {"location_id": mat["id"]})
    except Exception as err:  # noqa: BLE001
        assert "used by 1" in str(err)
    else:
        raise AssertionError("removed a location in use")
    await _call(hass, "update_location", {"location_id": mat["id"], "name": "Heat mat 2"})
    planting = manager.plantings()[0]
    assert planting.start_location == "Heat mat 2"


async def test_crop_defaults_keep_start_location(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    manager = entry.runtime_data
    await _call(hass, "set_crop_defaults", {
        "crop": "onion", "location": "Bed 1", "start_location": "Seedling tray",
    })
    assert manager.crop_defaults("onion")["start_location"] == "Seedling Tray"
    await _call(hass, "add_plantings", {"plantings": [{"crop": "onion", "method": "indoor_bed"}]})
    planting = manager.plantings()[0]
    assert (planting.location, planting.start_location) == ("Bed 1", "Seedling Tray")


@pytest.mark.freeze_time("2027-05-10 12:00:00")
async def test_repeat_sowings_can_be_in_both_places(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    manager = entry.runtime_data
    resp = await _call(hass, "add_planting", {
        "crop": "lettuce", "method": "indoor_bed", "year": 2027, "start_date": "2027-04-01",
        "succession_days": 14, "succession_count": 2, "succession_until": "2027-06-01",
        "location": "Garden", "start_location": "Seedling Tray",
    }, True)
    planting_id = resp["planting_id"]
    first = next(t for t in manager.tasks
                 if t.planting_id == planting_id and t.kind == "transplant" and t.succession == 0)
    manager.data["actuals"][first.uid] = "2027-04-01"
    manager.rebuild()
    state = manager.where_now()[planting_id]
    # The second sowing is still in the tray.
    assert state["current_location"] == "Seedling Tray"
    assert state["current_locations"] == ["Seedling Tray", "Garden"]
    counts = {x["name"]: x["plantings"] for x in manager.locations()}
    assert counts["Seedling Tray"] == counts["Garden"] == 1


@pytest.mark.freeze_time("2027-06-15 12:00:00")
async def test_deleted_transplant_counts_once_due(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    manager = entry.runtime_data
    resp = await _call(hass, "add_planting", {
        "crop": "tomato", "method": "indoor_bed", "year": 2027,
        "location": "Garden", "start_location": "Seedling Tray",
    }, True)
    planting_id = resp["planting_id"]
    out = next(t for t in manager.tasks if t.planting_id == planting_id and t.kind == "transplant")
    assert out.due.isoformat() < "2027-06-15"
    manager.data["dismissed"].append(out.uid)
    assert manager.where_now()[planting_id]["current_location"] == "Garden"


async def test_plans_and_finished_plantings_arent_there(hass: HomeAssistant, freezer) -> None:
    freezer.move_to("2026-11-21 12:00:00")
    entry = await _setup(hass)
    manager = entry.runtime_data
    resp = await _call(hass, "add_planting", {
        "crop": "carrot", "method": "direct_bed", "year": 2027, "location": "Garden",
    }, True)
    planting_id = resp["planting_id"]
    garden = lambda: next(x for x in manager.locations() if x["name"] == "Garden")  # noqa: E731
    # Next year's plan: in use (can't be removed) but nothing there yet.
    assert manager.where_now()[planting_id]["active"] is False
    assert (garden()["plantings"], garden()["in_use"]) == (0, 1)
    freezer.move_to("2027-04-01 12:00:00")
    assert manager.where_now()[planting_id]["active"] is True
    assert garden()["plantings"] == 1
    # Long after the last harvest window, it's gone from the bed.
    freezer.move_to("2028-03-01 12:00:00")
    assert manager.where_now()[planting_id]["active"] is False
    assert garden()["plantings"] == 0


def test_bought_starts_skip_sowing() -> None:
    crop = load_catalog()["tomato"]
    sown = Planting(id="s", crop="tomato", method="indoor_bed", year=2027, location="Bed 3")
    bought = Planting(id="b", crop="tomato", method="indoor_bed", year=2027, location="Bed 3",
                      bought_starts=True)
    sown_tasks = {t.kind: t for t in generate_tasks(sown, crop, Settings())}
    tasks = {t.kind: t for t in generate_tasks(bought, crop, Settings())}
    assert "sow_indoors" not in tasks and "pot_up" not in tasks
    assert tasks["buy_starts"].summary == "Buy Tomato starts"
    assert (tasks["transplant"].due - tasks["buy_starts"].due).days == 7
    assert (tasks["transplant"].due - tasks["harden_off"].due).days <= 3
    # Planting out and harvest land on the same days as growing from seed.
    assert tasks["transplant"].due == sown_tasks["transplant"].due
    assert tasks["harvest"].due == sown_tasks["harvest"].due


async def test_bought_starts_only_for_indoor_methods(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    manager = entry.runtime_data
    resp = await _call(hass, "add_planting", {
        "crop": "tomato", "method": "indoor_bed", "year": 2027, "bought_starts": True,
    }, True)
    planting_id = resp["planting_id"]
    assert manager.data["plantings"][planting_id]["bought_starts"] is True
    assert any(t.kind == "buy_starts" for t in manager.tasks if t.planting_id == planting_id)
    await _call(hass, "update_planting", {"planting_id": planting_id, "method": "direct_bed",
                                          "crop": "lettuce"})
    assert not manager.data["plantings"][planting_id].get("bought_starts")
    # A crop can default to bought starts.
    await _call(hass, "set_crop_defaults", {"crop": "pepper", "bought_starts": True})
    await _call(hass, "add_plantings", {"plantings": [{"crop": "pepper", "method": "indoor_bed"}]})
    pepper = next(p for p in manager.plantings() if p.crop == "pepper")
    assert pepper.bought_starts is True
