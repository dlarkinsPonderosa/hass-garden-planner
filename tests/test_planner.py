"""Tests for the date engine (no Home Assistant needed)."""

from datetime import date

import pytest

from custom_components.reap.planner import (
    TASK_HARDEN_OFF,
    TASK_HARVEST,
    TASK_POT_UP,
    TASK_SOW,
    TASK_SOW_INDOORS,
    TASK_TRANSPLANT,
    Planting,
    PlannerError,
    Settings,
    apply_actuals,
    generate_tasks,
    load_catalog,
)

CATALOG = load_catalog()
# A garden with an early last frost, but warm crops timed from April 1.
GARDEN = Settings(last_frost="03-06", first_frost="11-16", warm_last_frost="04-01")
# The chart as printed: April 1 last frost for everything.
AS_PRINTED = Settings(last_frost="04-01", first_frost="11-16")


def tasks_for(**kwargs):
    planting = Planting(id="p1", year=2027, **kwargs)
    return generate_tasks(planting, CATALOG[planting.crop], kwargs.pop("settings", GARDEN))


def by_kind(tasks):
    return {t.kind: t.due for t in tasks}


def test_catalog_has_vegetables_and_herbs():
    assert all(c.source == "builtin" for c in CATALOG.values())
    assert len([c for c in CATALOG.values() if c.category == "vegetable"]) == 53
    assert len([c for c in CATALOG.values() if c.category == "herb"]) == 22
    for key in ("potato", "tomatillo", "daikon", "napa_cabbage"):
        assert key in CATALOG
    for crop in CATALOG.values():
        assert crop.methods(), crop.key


def test_tomato_indoor_to_beds_is_not_shifted():
    # Frost-tender crops keep the chart's bed dates by default.
    dates = by_kind(tasks_for(crop="tomato", method="indoor_bed"))
    assert dates[TASK_TRANSPLANT] == date(2027, 5, 1)
    assert dates[TASK_SOW_INDOORS] == date(2027, 3, 13)  # 7 weeks before
    assert dates[TASK_HARDEN_OFF] == date(2027, 4, 24)
    assert TASK_POT_UP in dates


def test_tomato_greenhouse_is_four_weeks_earlier():
    dates = by_kind(tasks_for(crop="tomato", method="indoor_greenhouse"))
    assert dates[TASK_TRANSPLANT] == date(2027, 4, 3)
    assert dates[TASK_HARDEN_OFF] == date(2027, 3, 31)  # 3 day greenhouse step


def test_hardy_crop_shifted_for_early_frost():
    # Carrot window starts Apr 1 on the chart; this garden's last frost is 26 days
    # earlier than the Apr 1 baseline.
    shifted = by_kind(tasks_for(crop="carrot", method="direct_bed"))
    assert shifted[TASK_SOW] == date(2027, 3, 6)
    planting = Planting(id="p1", year=2027, crop="carrot", method="direct_bed")
    printed = by_kind(generate_tasks(planting, CATALOG["carrot"], AS_PRINTED))
    assert printed[TASK_SOW] == date(2027, 4, 1)


def test_weekly_carrot_successions_stop_at_window_end():
    tasks = tasks_for(crop="carrot", method="direct_bed", succession_days=7)
    sows = sorted(t.due for t in tasks if t.kind == TASK_SOW)
    assert sows[0] == date(2027, 3, 6)
    assert all((b - a).days == 7 for a, b in zip(sows, sows[1:]))
    assert sows[-1] <= date(2027, 7, 15)
    assert "sowing 1 of" in next(t for t in tasks if t.kind == TASK_SOW).summary


def test_succession_count_and_start_date():
    tasks = tasks_for(
        crop="lettuce", method="direct_bed", start_date="2027-05-10",
        succession_days=14, succession_count=3,
    )
    sows = sorted(t.due for t in tasks if t.kind == TASK_SOW)
    assert sows == [date(2027, 5, 10), date(2027, 5, 24), date(2027, 6, 7)]


def test_fall_garlic_harvest_next_year():
    dates = by_kind(tasks_for(crop="garlic", method="direct_bed", season="fall"))
    assert dates[TASK_SOW] == date(2027, 9, 20)
    assert dates[TASK_HARVEST].year == 2028


def test_unsupported_method_raises():
    with pytest.raises(PlannerError):
        tasks_for(crop="carrot", method="indoor_bed")
    with pytest.raises(PlannerError):
        tasks_for(crop="garlic", method="direct_bed", season="winter")


def test_late_task_shifts_rest_of_chain():
    tasks = tasks_for(crop="pepper", method="indoor_bed")
    sow = next(t for t in tasks if t.kind == TASK_SOW_INDOORS)
    transplant = next(t for t in tasks if t.kind == TASK_TRANSPLANT).due
    late = date.fromordinal(sow.due.toordinal() + 5)
    apply_actuals(tasks, {sow.uid: late.isoformat()})
    assert sow.done_on == late
    moved = next(t for t in tasks if t.kind == TASK_TRANSPLANT)
    assert (moved.due - transplant).days == 5
    assert moved.planned == transplant


def test_other_location_uses_its_frost_dates():
    # A zone 5 garden: last frost Apr 30, first frost Oct 10, one week colder.
    zone5 = Settings(last_frost="04-30", first_frost="10-10", offset_days=7)
    planting = Planting(id="p1", year=2027, crop="tomato", method="indoor_bed")
    dates = by_kind(generate_tasks(planting, CATALOG["tomato"], zone5))
    # Chart: transplant 30 days after last frost, plus the 7 day offset.
    assert dates[TASK_TRANSPLANT] == date(2027, 6, 6)
    planting = Planting(id="p2", year=2027, crop="garlic", method="direct_bed", season="fall")
    dates = by_kind(generate_tasks(planting, CATALOG["garlic"], zone5))
    # Chart: garlic from 57 days before first frost, plus 7.
    assert dates[TASK_SOW] == date(2027, 8, 21)


def test_catalog_matches_chart_when_frost_dates_match():
    # With the chart's own frost dates, the stored offsets give back the
    # calendar dates read off the chart.
    planting = Planting(id="p1", year=2027, crop="pepper", method="indoor_bed")
    dates = by_kind(generate_tasks(planting, CATALOG["pepper"], AS_PRINTED))
    assert dates[TASK_TRANSPLANT] == date(2027, 6, 1)


def test_every_crop_has_every_profile_and_an_icon():
    for crop in CATALOG.values():
        assert set(crop.profiles) == {"continental", "atlantic"}, crop.key
        assert crop.icon.startswith("mdi:")
        for profile in ("cool_spring", "continental", "atlantic"):
            assert crop.methods(profile), (crop.key, profile)


def test_continental_profile_saskatoon():
    # Saskatoon: last frost May 21, first frost Sep 15.
    sask = Settings(last_frost="05-21", first_frost="09-15", profile="continental")
    peas = Planting(id="p1", year=2027, crop="pea", method="direct_bed")
    tomato = Planting(id="p2", year=2027, crop="tomato", method="indoor_bed")
    pea_sow = by_kind(generate_tasks(peas, CATALOG["pea"], sask))[TASK_SOW]
    transplant = by_kind(generate_tasks(tomato, CATALOG["tomato"], sask))[TASK_TRANSPLANT]
    # The Prairies chart: peas from about May 1, tomatoes out from late May.
    assert date(2027, 4, 25) <= pea_sow <= date(2027, 5, 10)
    assert date(2027, 5, 25) <= transplant <= date(2027, 6, 10)
    # The coastal profile would put tomatoes out a month after last frost.
    coastal = Settings(last_frost="05-21", first_frost="09-15")
    late = by_kind(generate_tasks(tomato, CATALOG["tomato"], coastal))[TASK_TRANSPLANT]
    assert late > transplant


def test_task_icons():
    planting = Planting(id="p1", year=2027, crop="carrot", method="direct_bed")
    tasks = generate_tasks(planting, CATALOG["carrot"], GARDEN)
    sow = next(t for t in tasks if t.kind == TASK_SOW)
    assert sow.summary == "Sow Carrot in beds"
    assert sow.icon == "mdi:seed"
    assert sow.crop_icon == "mdi:carrot"


def test_fall_garlic_harvest_is_next_summer_and_stays_put() -> None:
    """Overwintered garlic is harvested the next summer, whenever it went in."""
    garlic = load_catalog()["garlic"]
    planting = Planting(id="g", crop="garlic", method="direct_bed", year=2026, season="fall")
    tasks = generate_tasks(planting, garlic, GARDEN)
    harvest = next(t for t in tasks if t.kind == TASK_HARVEST)
    assert harvest.due == date(2027, 6, 30)  # 90 days after Apr 1

    late = apply_actuals(generate_tasks(planting, garlic, GARDEN), {"g:0:sow": "2026-11-15"})
    assert next(t for t in late if t.kind == TASK_SOW).due == date(2026, 11, 15)
    assert next(t for t in late if t.kind == TASK_HARVEST).due == date(2027, 6, 30)


def test_spring_garlic_still_counts_days_from_planting() -> None:
    garlic = load_catalog()["garlic"]
    planting = Planting(id="g", crop="garlic", method="direct_bed", year=2027, season="spring")
    tasks = generate_tasks(planting, garlic, GARDEN)
    sow = next(t for t in tasks if t.kind == TASK_SOW)
    harvest = next(t for t in tasks if t.kind == TASK_HARVEST)
    assert (harvest.due - sow.due).days == garlic.days_to_harvest
