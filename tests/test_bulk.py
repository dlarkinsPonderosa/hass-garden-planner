"""Adding several plantings at once, and planning a year again."""

from __future__ import annotations

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from tests.test_init import _call, _setup


async def test_add_several_crops_with_their_defaults(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    manager = entry.runtime_data
    await _call(hass, "set_crop_defaults", {"crop": "lettuce", "quantity": "1 row", "location": "Garden"})
    resp = await _call(hass, "add_plantings", {"plantings": [
        {"crop": "lettuce", "year": 2027},
        {"crop": "tomato", "year": 2027, "location": "Greenhouse"},
        {"crop": "carrot", "year": 2027},
    ]}, True)
    assert len(resp["planting_ids"]) == 3
    by_crop = {p.crop: p for p in manager.plantings()}
    # Each crop's saved defaults apply; what's given wins.
    assert by_crop["lettuce"].quantity == "1 row"
    assert by_crop["lettuce"].location == "Garden"
    assert by_crop["lettuce"].succession_days == 14  # built-in default
    assert by_crop["tomato"].location == "Greenhouse"
    assert by_crop["tomato"].method == "indoor_bed"


async def test_add_several_is_all_or_nothing(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    manager = entry.runtime_data
    with pytest.raises(ServiceValidationError, match="garlic"):
        await _call(hass, "add_plantings", {"plantings": [
            {"crop": "lettuce", "year": 2027},
            {"crop": "garlic", "year": 2027, "method": "indoor_bed"},
        ]})
    assert manager.plantings() == []


async def test_several_varieties_at_once(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    manager = entry.runtime_data
    base = {"crop": "tomato", "method": "indoor_bed", "year": 2027, "location": "Greenhouse"}
    await _call(hass, "add_plantings", {"use_defaults": False, "plantings": [
        {**base, "variety": "Sungold", "quantity": "4"},
        {**base, "variety": "Brandywine", "quantity": "2"},
        {**base, "variety": "San Marzano"},
    ]})
    varieties = {p.variety: p for p in manager.plantings()}
    assert set(varieties) == {"Sungold", "Brandywine", "San Marzano"}
    assert varieties["Sungold"].quantity == "4"
    assert varieties["San Marzano"].quantity is None
    summaries = {t.summary for t in manager.tasks if t.kind == "sow_indoors"}
    assert "Sow Tomato (Brandywine) indoors" in summaries


async def test_plan_a_year_again(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    manager = entry.runtime_data
    await _call(hass, "add_planting", {
        "crop": "pea", "method": "direct_bed", "year": 2026, "start_date": "2026-02-10",
        "succession_days": 14, "succession_until": "2026-04-01", "variety": "Sugar Snap",
        "quantity": "2 rows", "location": "Garden",
    })
    await _call(hass, "add_planting", {
        "crop": "garlic", "method": "direct_bed", "year": 2026, "season": "fall",
    })
    # Already planned for 2027, so it's skipped.
    await _call(hass, "add_planting", {"crop": "garlic", "method": "direct_bed", "year": 2027, "season": "fall"})
    await _call(hass, "add_planting", {"crop": "tomato", "method": "indoor_bed", "year": 2025})

    resp = await _call(hass, "copy_plantings", {"from_year": 2026}, True)
    assert len(resp["planting_ids"]) == 1
    assert [s["name"] for s in resp["skipped"]] == ["Garlic"]
    copy = next(p for p in manager.plantings() if p.id == resp["planting_ids"][0])
    assert (copy.crop, copy.year, copy.variety, copy.quantity, copy.location) == (
        "pea", 2027, "Sugar Snap", "2 rows", "Garden",
    )
    assert copy.start_date == "2027-02-10"
    assert copy.succession_until == "2027-04-01"
    assert copy.succession_days == 14
    assert len(manager.plantings()) == 5

    # Picking by id copies even what's already planned, to any year.
    garlic = next(p for p in manager.plantings() if p.crop == "garlic" and p.year == 2026)
    resp = await _call(hass, "copy_plantings", {
        "from_year": 2026, "to_year": 2027, "planting_ids": [garlic.id],
    }, True)
    assert len(resp["planting_ids"]) == 1


async def test_copy_moves_a_leap_day(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    manager = entry.runtime_data
    await _call(hass, "add_planting", {
        "crop": "pea", "method": "direct_bed", "year": 2028, "start_date": "2028-02-29",
    })
    resp = await _call(hass, "copy_plantings", {"from_year": 2028}, True)
    copy = next(p for p in manager.plantings() if p.id == resp["planting_ids"][0])
    assert copy.start_date == "2029-02-28"


async def test_copy_to_the_same_year_is_refused(hass: HomeAssistant) -> None:
    await _setup(hass)
    with pytest.raises(ServiceValidationError):
        await _call(hass, "copy_plantings", {"from_year": 2026, "to_year": 2026})
