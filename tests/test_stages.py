"""Indoor starts move from their start location to where they're planted out."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from custom_components.reap.planner import Planting, Settings, generate_tasks, load_catalog
from tests.test_init import _call, _setup


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

    assert where() == ("Seedling tray 1", 1, 0)
    # Ticking off sowing indoors doesn't move it.
    sow = next(t for t in manager.tasks if t.planting_id == planting_id and t.kind == "sow_indoors")
    manager.data["actuals"][sow.uid] = "2027-02-10"
    manager.rebuild()
    await hass.async_block_till_done()
    assert where()[0] == "Seedling tray 1"
    # Transplanting does.
    out = next(t for t in manager.tasks if t.planting_id == planting_id and t.kind == "transplant")
    manager.data["actuals"][out.uid] = "2027-04-10"
    manager.rebuild()
    await hass.async_block_till_done()
    assert where() == ("Bed 3", 0, 1)

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
