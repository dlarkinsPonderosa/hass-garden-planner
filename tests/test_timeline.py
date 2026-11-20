"""The season chart data on the plantings sensor."""

from __future__ import annotations

import json
import os

import pytest

from homeassistant.core import HomeAssistant

from custom_components.reap.planner import (
    Planting,
    Settings,
    generate_tasks,
    load_catalog,
    planting_timeline,
)
from tests.test_init import _call, _setup

CATALOG = load_catalog()


def test_timeline_of_an_indoor_planting() -> None:
    crop = CATALOG["tomato"]
    settings = Settings(last_frost="04-01", first_frost="10-20")
    tasks = generate_tasks(
        Planting(id="t", crop="tomato", method="indoor_bed", year=2027), crop, settings
    )
    t = planting_timeline(tasks, crop)
    assert set(t) == {"indoor", "out", "harvest", "grow"}
    assert t["indoor"]["start"] < t["out"]["start"] == t["grow"]["start"]
    assert t["grow"]["end"] == t["harvest"]["start"]
    harvest = next(x for x in tasks if x.kind == "harvest")
    assert t["harvest"]["end"] > harvest.due.isoformat()
    assert t["indoor"]["done"] is False


def test_timeline_spans_every_sowing() -> None:
    crop = CATALOG["lettuce"]
    settings = Settings(last_frost="04-01", first_frost="10-20")
    planting = Planting(
        id="l", crop="lettuce", method="direct_bed", year=2027,
        start_date="2027-04-01", succession_days=14, succession_until="2027-05-15",
    )
    t = planting_timeline(generate_tasks(planting, crop, settings), crop)
    assert t["sow"]["start"] == "2027-04-01"
    assert t["sow"]["end"] == "2027-05-13"
    assert "indoor" not in t and "out" not in t


def test_no_tasks_no_timeline() -> None:
    assert planting_timeline([], CATALOG["pea"]) is None


@pytest.mark.freeze_time("2026-11-20 12:00:00")
async def test_sensor_carries_timeline_and_hemisphere(hass: HomeAssistant) -> None:
    await _setup(hass)
    await _call(hass, "add_planting", {"crop": "garlic", "method": "direct_bed", "year": 2026, "season": "fall"})
    await _call(hass, "add_planting", {"crop": "tomato", "method": "indoor_bed", "year": 2027, "variety": "Sungold"})
    await hass.async_block_till_done()
    state = hass.states.get("sensor.reap_plantings")
    assert state.attributes["southern"] is False
    garlic = next(p for p in state.attributes["plantings"] if p["crop"] == "garlic")
    # Fall garlic is harvested the summer after.
    assert garlic["timeline"]["sow"]["start"].startswith("2026-")
    assert garlic["timeline"]["harvest"]["start"].startswith("2027-")
    dump = os.environ.get("REAP_DUMP_TIMELINE")
    if dump:
        with open(dump, "w", encoding="utf-8") as fh:
            json.dump(dict(state.attributes), fh, default=str)


async def test_deleted_tasks_leave_the_timeline(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    manager = entry.runtime_data
    resp = await _call(hass, "add_planting", {"crop": "tomato", "method": "indoor_bed", "year": 2027}, True)
    await hass.async_block_till_done()
    sow = next(t for t in manager.tasks if t.planting_id == resp["planting_id"] and t.kind == "sow_indoors")
    manager.data["dismissed"].append(sow.uid)
    manager._notify()
    await hass.async_block_till_done()
    state = hass.states.get("sensor.reap_plantings")
    timeline = state.attributes["plantings"][0]["timeline"]
    assert "indoor" not in timeline
    assert "out" in timeline
