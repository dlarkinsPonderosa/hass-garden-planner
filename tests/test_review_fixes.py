"""Fixes from the November 2026 review: list switching, crop edits, dates."""

from __future__ import annotations

from datetime import date
from pathlib import Path
import subprocess
import sys

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er

from custom_components.reap.const import DOMAIN, ZONE_FROST_DATES
from custom_components.reap.planner import (
    METHODS,
    Crop,
    Planting,
    PlannerError,
    Settings,
    Window,
    choose_window,
    effective_range,
    generate_tasks,
    load_catalog,
    range_to_offsets,
    sowing_dates,
)
from tests.test_init import OWN_LIST, _call, _items, _setup

CATALOG = load_catalog()
ROOT = Path(__file__).resolve().parent.parent


async def _local_list(hass: HomeAssistant, tmp_path, name: str = "Family") -> str:
    local = MockConfigEntry(
        domain="local_todo",
        data={"todo_list_name": name, "storage_key": name.lower()},
    )
    local.add_to_hass(hass)
    hass.config.config_dir = str(tmp_path)
    (tmp_path / ".storage").mkdir(exist_ok=True)
    assert await hass.config_entries.async_setup(local.entry_id)
    await hass.async_block_till_done()
    return f"todo.{name.lower()}"


# ----- H1, L1, L7: changing the target list -----


@pytest.mark.freeze_time("2027-03-01 12:00:00")
async def test_switching_list_moves_open_tasks(hass: HomeAssistant, tmp_path) -> None:
    target = await _local_list(hass, tmp_path)
    entry = await _setup(hass)
    manager = entry.runtime_data
    await _call(hass, "add_planting", {
        "crop": "pea", "method": "direct_bed", "year": 2027, "succession_days": 14,
    })
    await hass.async_block_till_done()
    own = await _items(hass, OWN_LIST)
    assert len(own) > 2
    # Tick one off before switching; it stays done.
    await hass.services.async_call(
        "todo", "update_item",
        {"entity_id": OWN_LIST, "item": own[0]["uid"], "status": "completed"},
        blocking=True,
    )
    await hass.async_block_till_done()

    hass.config_entries.async_update_entry(
        entry, options={**entry.data, "todo_entity": target}
    )
    await hass.async_block_till_done()
    manager = entry.runtime_data
    await _call(hass, "sync", {})
    await hass.async_block_till_done()

    assert manager.data["dismissed"] == []
    moved = await _items(hass, target)
    # The open sowings move across. The done one doesn't, and its harvest moved
    # out of the look-ahead window when it was ticked off late.
    assert [i["summary"] for i in moved] == [i["summary"] for i in own[1:] if "Sow" in i["summary"]]
    assert manager.data["pushed_entity"] == target
    # Only the done item is left in Reap's own list, and that list is gone.
    assert [i["status"] for i in manager.data["own_items"]] == ["completed"]
    assert er.async_get(hass).async_get_entity_id(
        "todo", DOMAIN, f"{entry.entry_id}_tasks"
    ) is None


@pytest.mark.freeze_time("2027-03-01 12:00:00")
async def test_list_briefly_empty_dismisses_nothing(hass: HomeAssistant, tmp_path) -> None:
    target = await _local_list(hass, tmp_path)
    entry = await _setup(hass, todo_entity=target)
    manager = entry.runtime_data
    await _call(hass, "add_planting", {"crop": "radish", "method": "direct_bed", "year": 2027})
    await hass.async_block_till_done()
    count = len(await _items(hass, target))
    assert count
    real_get = manager._async_get_items

    async def empty(entity_id):
        return []

    # One sync where the list comes back empty (not loaded yet, say).
    manager._async_get_items = empty
    await manager.async_sync()
    assert manager.data["dismissed"] == []
    assert manager.data["missing"]
    # The list is back: nothing was lost and nothing was added twice.
    manager._async_get_items = real_get
    await manager.async_sync()
    assert manager.data["missing"] == []
    assert manager.data["dismissed"] == []
    assert len(await _items(hass, target)) == count


# ----- H2: editing a crop that has summer windows -----


async def test_editing_crop_keeps_plantings_schedulable(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    manager = entry.runtime_data
    await _call(hass, "add_planting", {
        "crop": "kohlrabi", "method": "direct_bed", "year": 2027, "season": "summer",
    })
    before = len(manager.tasks)
    crops = (await _call(hass, "list_crops", {}, True))["crops"]
    info = next(c for c in crops if c["key"] == "kohlrabi")
    spring = next(w for w in info["windows"] if w["season"] == "spring")
    # Dropping the summer window would orphan the planting: refused.
    with pytest.raises(ServiceValidationError, match="summer"):
        await _call(hass, "add_crop", {
            "key": "kohlrabi", "name": "Kohlrabi",
            "windows": [{"season": "spring", "direct": spring["direct"]}],
        })
    assert len(manager.tasks) == before
    # What the card now sends: every season it shows, so summer survives.
    await _call(hass, "add_crop", {
        "key": "kohlrabi", "name": "Kohlrabi", "windows": info["windows"],
    })
    assert {w.season for w in manager.crop("kohlrabi").windows} == set(info["seasons"])
    assert len(manager.tasks) == before


# ----- M1: item descriptions follow planting changes -----


async def test_description_updates_on_the_list(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    resp = await _call(hass, "add_planting", {
        "crop": "pea", "method": "direct_bed", "start_date": date.today().isoformat(),
        "quantity": "1 row",
    }, True)
    await hass.async_block_till_done()
    assert any("Quantity: 1 row" in (i.get("description") or "") for i in await _items(hass, OWN_LIST))
    await _call(hass, "update_planting", {"planting_id": resp["planting_id"], "quantity": "3 rows"})
    await hass.async_block_till_done()
    descriptions = [i.get("description") or "" for i in await _items(hass, OWN_LIST)]
    assert any("Quantity: 3 rows" in d for d in descriptions)
    assert not any("1 row" in d for d in descriptions)


# ----- M2: southern hemisphere -----


def test_southern_hemisphere_season_crosses_new_year() -> None:
    south = Settings(last_frost="09-15", first_frost="05-01", profile="continental")
    tasks = generate_tasks(
        Planting(id="p", crop="tomato", method="indoor_bed", year=2027), CATALOG["tomato"], south
    )
    transplant = next(t for t in tasks if t.kind == "transplant")
    harvest = next(t for t in tasks if t.kind == "harvest")
    # Transplanted in the southern spring, after the Sep 15 last frost...
    assert date(2027, 9, 15) <= transplant.due <= date(2027, 12, 31)
    # ...and harvested before the first frost of May 2028.
    assert transplant.due < harvest.due < date(2028, 5, 1)
    # A fall window is anchored to the next year's first frost.
    garlic = generate_tasks(
        Planting(id="g", crop="garlic", method="direct_bed", year=2027, season="fall"),
        CATALOG["garlic"], south,
    )
    assert next(t for t in garlic if t.kind == "sow").due.year == 2028


async def test_southern_custom_crop_dates(hass: HomeAssistant) -> None:
    hass.config.latitude = -36.8  # Auckland
    entry = await _setup(hass, last_frost="09-15", first_frost="05-01", warm_last_frost="")
    manager = entry.runtime_data
    await _call(hass, "add_crop", {
        "key": "kumara", "name": "Kumara",
        "windows": [{"season": "spring", "direct": ["10-15", "12-15"]}],
    })
    info = manager.crop_info(manager.crop("kumara"))
    assert info["windows"][0]["direct"] == ["10-15", "12-15"]
    sched = sowing_dates(
        Planting(id="k", crop="kumara", method="direct_bed", year=2027),
        manager.crop("kumara"), manager.settings,
    )
    assert (sched.window_start, sched.window_end) == (date(2027, 10, 15), date(2027, 12, 15))


# ----- M3: ranges across the new year -----


def test_range_across_new_year() -> None:
    settings = Settings(last_frost="04-20", first_frost="10-20")
    start, end = range_to_offsets("11-01", "01-15", settings.last_frost, settings.first_frost)
    assert (start, end) == ("F+12", "F+87")
    crop = Crop(key="x", name="X", windows=[Window(season="fall", direct=(start, end))])
    sched = sowing_dates(
        Planting(id="p", crop="x", method="direct_bed", year=2027, succession_days=14),
        crop, settings,
    )
    assert (sched.window_start, sched.window_end) == (date(2027, 11, 1), date(2028, 1, 15))
    assert len(sched.dates) == 6
    with pytest.raises(PlannerError, match="ends before it starts"):
        range_to_offsets("06-01", "03-01", settings.last_frost, settings.first_frost)


# ----- M4: every built-in crop schedules everywhere -----


@pytest.mark.parametrize("zone", sorted(ZONE_FROST_DATES))
@pytest.mark.parametrize("profile", ["cool_spring", "continental", "atlantic"])
def test_catalog_windows_never_run_backwards(zone: str, profile: str) -> None:
    last, first = ZONE_FROST_DATES[zone][:2]
    settings = Settings(last_frost=last, first_frost=first, profile=profile)
    for crop in CATALOG.values():
        for window in crop.windows_for(profile):
            for method in METHODS:
                try:
                    choose_window(crop, method, window.season, profile)
                except PlannerError:
                    continue
                planting = Planting(
                    id="p", crop=crop.key, method=method, year=2027, season=window.season
                )
                sched = sowing_dates(planting, crop, settings)
                assert sched.window_start <= sched.window_end, (crop.key, method, window.season)
                for rng in (window.indoor, window.transplant, window.direct):
                    if rng:
                        start, end = effective_range(crop, rng, 2027, settings, False)
                        assert start <= end, (crop.key, rng)
                tasks = generate_tasks(planting, crop, settings)
                sow = [t for t in tasks if t.kind == "sow_indoors"]
                out = [t for t in tasks if t.kind == "transplant"]
                if sow and out:
                    assert sow[0].due < out[0].due


# ----- M5: catalog matches its script -----


def test_catalog_matches_build_script() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build_catalog.py"), "--check"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


# ----- M6: frost tender toggle keeps the dates -----


async def test_frost_tender_toggle_keeps_dates(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    manager = entry.runtime_data
    await _call(hass, "add_crop", {
        "key": "x1", "name": "X1", "frost_tender": False,
        "windows": [{"direct": ["05-01", "05-20"]}],
    })
    await _call(hass, "add_crop", {"key": "x1", "frost_tender": True})
    info = manager.crop_info(manager.crop("x1"))
    assert info["frost_tender"] is True
    assert info["windows"][0]["direct"] == ["05-01", "05-20"]
    await _call(hass, "add_crop", {"key": "x1", "frost_tender": False})
    assert manager.crop_info(manager.crop("x1"))["windows"][0]["direct"] == ["05-01", "05-20"]


# ----- M7: the default year follows the crop's window -----


async def test_default_year_follows_window(hass: HomeAssistant, freezer) -> None:
    entry = await _setup(hass)
    manager = entry.runtime_data
    freezer.move_to("2026-09-05 12:00:00")
    # Garlic's fall window hasn't ended yet: this year.
    assert manager.pick_year({"crop": "garlic", "method": "direct_bed", "season": "fall"}) == 2026
    # Spring peas are over: next year.
    assert manager.pick_year({"crop": "pea", "method": "direct_bed", "season": "spring"}) == 2027
    resp = await _call(hass, "preview_planting", {"crop": "garlic", "season": "fall"}, True)
    assert resp["tasks"][0]["due"].startswith("2026")


# ----- M9: a list that renames new items -----


@pytest.mark.freeze_time("2027-03-01 12:00:00")
async def test_unmatched_items_are_not_added_again(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    manager = entry.runtime_data
    real_add = manager._async_call

    async def renaming_call(service, data):
        if service == "add_item":
            data = {**data, "item": data["item"].upper()}
            data.pop("description", None)
        await real_add(service, data)

    manager._async_call = renaming_call
    await _call(hass, "add_planting", {"crop": "radish", "method": "direct_bed", "year": 2027})
    await hass.async_block_till_done()
    count = len(manager.own_items)
    assert manager.data["unmatched"]
    await _call(hass, "sync", {})
    await _call(hass, "sync", {})
    assert len(manager.own_items) == count


# ----- L8, L9, L10 -----


def test_planted_crops_say_plant() -> None:
    settings = Settings()
    tasks = generate_tasks(
        Planting(id="g", crop="garlic", method="direct_bed", year=2026, season="fall"),
        CATALOG["garlic"], settings,
    )
    assert tasks[0].summary.startswith("Plant Garlic")
    shallot = Crop.from_dict({
        "key": "shallot", "name": "Shallot", "planted": True,
        "windows": [{"season": "spring", "direct": ["L-14", "L+14"]}],
    })
    tasks = generate_tasks(
        Planting(id="s", crop="shallot", method="direct_bed", year=2027), shallot, settings
    )
    assert tasks[0].summary.startswith("Plant Shallot")


async def test_service_errors_are_translatable(hass: HomeAssistant) -> None:
    await _setup(hass)
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, "add_planting", {"crop": "nope", "method": "direct_bed", "year": 2027})
    assert err.value.translation_key == "planner_error"
    assert "nope" in str(err.value)


async def test_plantings_sensor_lists_open_tasks_only(hass: HomeAssistant) -> None:
    await _setup(hass)
    await _call(hass, "add_planting", {
        "crop": "lettuce", "method": "direct_bed", "year": 2027, "succession_days": 7,
    })
    await hass.async_block_till_done()
    planting = hass.states.get("sensor.reap_plantings").attributes["plantings"][0]
    assert planting["sowings"] > 10
    assert planting["task_count"] >= planting["sowings"] * 2
    assert len(planting["tasks"]) == 10
    assert hass.states.get("sensor.reap_plantings").attributes.get("unit_of_measurement") is None
