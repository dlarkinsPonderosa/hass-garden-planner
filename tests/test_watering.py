"""Cameras and watering on locations, and when each was last watered."""

from __future__ import annotations

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
import pytest

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from tests.test_init import _call, _setup


async def test_location_keeps_camera_and_watering(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    manager = entry.runtime_data
    resp = await _call(hass, "add_location", {
        "name": "Bed 4", "camera": "camera.garden", "water": "valve.bed_4",
    }, True)
    loc = resp["location"]
    assert (loc["camera"], loc["water"]) == ("camera.garden", "valve.bed_4")
    await _call(hass, "update_location", {"location_id": loc["id"], "camera": ""})
    listed = next(x for x in manager.locations() if x["id"] == loc["id"])
    assert listed["camera"] is None
    assert listed["water"] == "valve.bed_4"
    # Older locations list every entity key too.
    assert all("camera" in x and "water" in x for x in manager.locations())


@pytest.mark.freeze_time("2027-05-01 07:00:00")
async def test_valve_run_is_remembered(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    hass.states.async_set("valve.bed_4", "closed")
    entry = await _setup(hass)
    manager = entry.runtime_data
    await _call(hass, "add_location", {"name": "Bed 4", "water": "valve.bed_4"})
    hass.states.async_set("valve.bed_4", "open")
    await hass.async_block_till_done()
    bed = next(x for x in manager.locations() if x["name"] == "Bed 4")
    assert bed["last_watered"].startswith("2027-05-01")
    assert bed["watered_minutes"] is None  # still running
    freezer.tick(timedelta(minutes=12))
    hass.states.async_set("valve.bed_4", "closed")
    await hass.async_block_till_done()
    bed = next(x for x in manager.locations() if x["name"] == "Bed 4")
    assert bed["watered_minutes"] == 12
    assert bed["watered_by_hand"] is False
    state = hass.states.get("sensor.reap_plantings")
    shown = next(x for x in state.attributes["locations"] if x["name"] == "Bed 4")
    assert shown["watered_minutes"] == 12
    # Going unavailable isn't a watering.
    hass.states.async_set("valve.bed_4", "unavailable")
    await hass.async_block_till_done()
    assert next(x for x in manager.locations() if x["name"] == "Bed 4")["watered_minutes"] == 12


async def test_switch_added_later_is_followed(hass: HomeAssistant) -> None:
    hass.states.async_set("switch.drip", "off")
    entry = await _setup(hass)
    manager = entry.runtime_data
    garden = next(x for x in manager.locations() if x["name"] == "Garden")
    await _call(hass, "update_location", {"location_id": garden["id"], "water": "switch.drip"})
    hass.states.async_set("switch.drip", "on")
    await hass.async_block_till_done()
    assert next(x for x in manager.locations() if x["name"] == "Garden")["last_watered"]


async def test_watered_by_hand(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    manager = entry.runtime_data
    resp = await _call(hass, "log_watering", {"location": "greenhouse"}, True)
    assert resp["location"]["watered_by_hand"] is True
    assert resp["location"]["last_watered"]
    with pytest.raises(ServiceValidationError):
        await _call(hass, "log_watering", {"location": "Nowhere"})
    assert manager.data["watering"]


@pytest.mark.freeze_time("2027-05-01 07:00:00")
async def test_valve_dropping_off_mid_run(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    hass.states.async_set("valve.bed_5", "closed")
    entry = await _setup(hass)
    manager = entry.runtime_data
    await _call(hass, "add_location", {"name": "Bed 5", "water": "valve.bed_5"})
    hass.states.async_set("valve.bed_5", "open")
    await hass.async_block_till_done()
    freezer.tick(timedelta(minutes=5))
    hass.states.async_set("valve.bed_5", "unavailable")
    await hass.async_block_till_done()
    freezer.tick(timedelta(minutes=10))
    hass.states.async_set("valve.bed_5", "closed")
    await hass.async_block_till_done()
    bed = next(x for x in manager.locations() if x["name"] == "Bed 5")
    assert bed["watered_minutes"] == 15
