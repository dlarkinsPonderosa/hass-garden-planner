"""Reap date engine.

Turns plantings into dated tasks. This module has no Home Assistant imports so
it can be unit tested on its own.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from datetime import date, timedelta
import json
import re
from pathlib import Path
from typing import Any

METHOD_INDOOR_BED = "indoor_bed"
METHOD_INDOOR_GREENHOUSE = "indoor_greenhouse"
METHOD_DIRECT_BED = "direct_bed"
METHOD_DIRECT_GREENHOUSE = "direct_greenhouse"
METHODS = (
    METHOD_INDOOR_BED,
    METHOD_INDOOR_GREENHOUSE,
    METHOD_DIRECT_BED,
    METHOD_DIRECT_GREENHOUSE,
)
INDOOR_METHODS = (METHOD_INDOOR_BED, METHOD_INDOOR_GREENHOUSE)
GREENHOUSE_METHODS = (METHOD_INDOOR_GREENHOUSE, METHOD_DIRECT_GREENHOUSE)

TASK_SOW_INDOORS = "sow_indoors"
TASK_POT_UP = "pot_up"
TASK_HARDEN_OFF = "harden_off"
TASK_TRANSPLANT = "transplant"
TASK_SOW = "sow"
TASK_COVER = "cover"
TASK_HARVEST = "harvest"
# Indoor tasks done before planting out: they happen at the start location.
BEFORE_PLANT_OUT = (TASK_SOW_INDOORS, TASK_POT_UP, TASK_HARDEN_OFF)

TASK_ICONS = {
    TASK_SOW_INDOORS: "mdi:seed-outline",
    TASK_POT_UP: "mdi:pot-mix",
    TASK_HARDEN_OFF: "mdi:weather-sunny",
    TASK_TRANSPLANT: "mdi:shovel",
    TASK_SOW: "mdi:seed",
    TASK_COVER: "mdi:umbrella-outline",
    TASK_HARVEST: "mdi:basket",
}

SEASON_ORDER = ("spring", "summer", "fall", "winter")

CATALOG_PATH = Path(__file__).parent / "data" / "crops.json"
OFFSET_RE = re.compile(r"^([LF])([+-]\d+)$")


class PlannerError(ValueError):
    """A planting can't be scheduled as asked."""


def month_day(year: int, mmdd: str) -> date:
    """Turn "MM-DD" into a date in the given year."""
    month, day = (int(part) for part in mmdd.split("-"))
    return date(year, month, day)


def parse_date(value: str | date | None) -> date | None:
    """Accept an ISO date string, a date, or None."""
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


@dataclass
class Settings:
    """Location and greenhouse settings."""

    last_frost: str = "03-06"
    first_frost: str = "11-16"
    # Last frost date used for frost-tender crops. Warm crops need warm soil
    # and nights, so where the last frost is unusually early
    # this can be set later than last_frost. Empty means the same date.
    warm_last_frost: str | None = None
    # Moves every date earlier (negative) or later (positive).
    offset_days: int = 0
    # Climate profile: cool_spring, continental or atlantic.
    profile: str = "cool_spring"
    greenhouse_spring_weeks: int = 4
    greenhouse_fall_weeks: int = 4
    harden_off_days: int = 7
    greenhouse_harden_off_days: int = 3
    # Southern hemisphere, from Home Assistant's latitude. None guesses from
    # the frost dates.
    southern: bool | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Settings:
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class Window:
    """One growing window of a crop.

    Each range is a pair of frost offsets such as ("L-31", "L+14"): days from
    the last spring frost (L) or the first fall frost (F).
    """

    season: str
    indoor: tuple[str, str] | None = None
    direct: tuple[str, str] | None = None
    transplant: tuple[str, str] | None = None
    cover: tuple[str, str] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Window:
        def rng(key: str) -> tuple[str, str] | None:
            value = data.get(key)
            return (value[0], value[1]) if value else None

        return cls(
            season=data.get("season", "spring"),
            indoor=rng("indoor"),
            direct=rng("direct"),
            transplant=rng("transplant"),
            cover=rng("cover"),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"season": self.season}
        for key in ("indoor", "direct", "transplant", "cover"):
            value = getattr(self, key)
            if value:
                out[key] = list(value)
        return out


@dataclass
class Crop:
    """A crop in the catalog."""

    key: str
    name: str
    windows: list[Window]
    weeks_indoor: int | None = None
    days_to_harvest: int = 60
    harvest_weeks: int = 4
    frost_tender: bool = False
    pot_up: bool = False
    perennial: bool = False
    source: str = "custom"
    category: str = "vegetable"
    notes: str | None = None
    icon: str = "mdi:sprout"
    # Windows for other climate profiles. "windows" is the cool_spring set and
    # the fallback for any profile not listed (custom crops have only that).
    profiles: dict[str, list[Window]] = field(default_factory=dict)
    # Profiles whose windows were estimated rather than read off a chart.
    estimated_profiles: list[str] = field(default_factory=list)
    # What a new planting starts with: method, succession_days, ...
    defaults: dict[str, Any] = field(default_factory=dict)
    # For crops that overwinter (summer or fall plantings): days after the
    # next spring's warm last frost when harvest starts. Not tied to sowing.
    overwinter_harvest: int | None = None
    # Grown from cloves, sets, tubers or slips: tasks say "Plant", not "Sow".
    planted: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Crop:
        return cls(
            key=data["key"],
            name=data["name"],
            windows=[Window.from_dict(w) for w in data.get("windows", [])],
            icon=data.get("icon") or "mdi:sprout",
            profiles={
                name: [Window.from_dict(w) for w in windows]
                for name, windows in (data.get("profiles") or {}).items()
            },
            estimated_profiles=list(data.get("estimated_profiles") or []),
            defaults=dict(data.get("defaults") or {}),
            weeks_indoor=data.get("weeks_indoor"),
            days_to_harvest=int(data.get("days_to_harvest", 60)),
            harvest_weeks=int(data.get("harvest_weeks", 4)),
            frost_tender=bool(data.get("frost_tender", False)),
            pot_up=bool(data.get("pot_up", False)),
            perennial=bool(data.get("perennial", False)),
            source=data.get("source", "custom"),
            category=data.get("category") or "vegetable",
            notes=data.get("notes"),
            planted=bool(data.get("planted", data["key"] in ("garlic", "potato"))),
            overwinter_harvest=(
                int(data["overwinter_harvest"])
                if data.get("overwinter_harvest") is not None
                else None
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["windows"] = [w.to_dict() for w in self.windows]
        out["profiles"] = {
            name: [w.to_dict() for w in windows]
            for name, windows in self.profiles.items()
        }
        return out

    def windows_for(self, profile: str | None) -> list[Window]:
        if profile and profile in self.profiles:
            return self.profiles[profile]
        return self.windows

    def supports(self, method: str, profile: str | None = None) -> bool:
        return any(_window_supports(w, method) for w in self.windows_for(profile))

    def seasons(self, profile: str | None = None) -> list[str]:
        """The crop's seasons in calendar order: spring, summer, fall, winter."""
        found = {w.season for w in self.windows_for(profile)}
        return sorted(found, key=lambda s: (SEASON_ORDER.index(s) if s in SEASON_ORDER else 9, s))

    def methods(self, profile: str | None = None) -> list[str]:
        return [m for m in METHODS if self.supports(m, profile)]


def load_catalog(path: Path = CATALOG_PATH) -> dict[str, Crop]:
    """Load the built-in crop catalog."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return {c["key"]: Crop.from_dict(c) for c in data["crops"]}


@dataclass
class Planting:
    """One crop, grown one way, in one season."""

    id: str
    crop: str
    method: str
    year: int
    season: str | None = None
    # Transplant date for indoor methods, first sowing date for direct methods.
    # Empty means the start of the crop's window.
    start_date: str | None = None
    succession_days: int = 0
    succession_count: int | None = None
    succession_until: str | None = None
    variety: str | None = None
    quantity: str | None = None
    # Where it's planted out, or grown for direct sowing.
    location: str | None = None
    notes: str | None = None
    # Indoor methods: where it starts (seedling tray...) until it's planted out.
    start_location: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Planting:
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def location_for(self, kind: str) -> str | None:
        """Where the planting is for a task of this kind."""
        if kind in BEFORE_PLANT_OUT and self.method in INDOOR_METHODS:
            return self.start_location or self.location
        return self.location


@dataclass
class Task:
    """A dated task made from a planting."""

    uid: str
    planting_id: str
    succession: int
    kind: str
    due: date
    planned: date
    summary: str
    description: str = ""
    done_on: date | None = None
    icon: str = "mdi:sprout"
    crop_icon: str = "mdi:sprout"
    # Fixed tasks keep their date when earlier tasks are done early or late.
    fixed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "uid": self.uid,
            "planting_id": self.planting_id,
            "succession": self.succession,
            "kind": self.kind,
            "due": self.due.isoformat(),
            "planned": self.planned.isoformat(),
            "summary": self.summary,
            "description": self.description,
            "done_on": self.done_on.isoformat() if self.done_on else None,
            "icon": self.icon,
            "crop_icon": self.crop_icon,
        }


@dataclass
class Schedule:
    """Where a planting's dates came from, for display."""

    window_start: date
    window_end: date
    dates: list[date] = field(default_factory=list)


def _window_supports(window: Window, method: str) -> bool:
    if method in INDOOR_METHODS:
        return window.transplant is not None
    return window.direct is not None


def parse_offset(token: str) -> tuple[str, int]:
    """Split "L-26" into ("L", -26). L is last frost, F is first frost."""
    match = OFFSET_RE.match(token)
    if not match:
        raise PlannerError(f"Bad date offset {token!r}; use L-14 or F+7 style")
    return match.group(1), int(match.group(2))


def format_offset(anchor: str, days: int) -> str:
    return f"{anchor}{days:+d}"


def frost_wraps(last_frost: str, first_frost: str) -> bool:
    """True when the first frost comes earlier in the calendar than the last
    frost. The first frost of a season is then in the next calendar year."""
    return month_day(2001, first_frost) < month_day(2001, last_frost)


def is_southern(
    settings_or_last: Settings | str,
    first_frost: str | None = None,
    southern: bool | None = None,
) -> bool:
    """Whether the garden is in the southern hemisphere.

    Uses the hemisphere when it's known (from Home Assistant's latitude), and
    otherwise guesses from the frost dates: a first frost earlier in the
    calendar than the last frost. The growing year then starts in July, and a
    planting's year is the one its spring falls in.
    """
    if isinstance(settings_or_last, Settings):
        if settings_or_last.southern is not None:
            return settings_or_last.southern
        last, first = settings_or_last.last_frost, settings_or_last.first_frost
    else:
        if southern is not None:
            return southern
        last, first = settings_or_last, first_frost or ""
    return frost_wraps(last, first)


def _season_order(mmdd: str, southern: bool) -> tuple[int, int]:
    """Sort key of a date within the growing year (January or July first)."""
    month, day = (int(part) for part in mmdd.split("-"))
    return ((month - 7) % 12 if southern else month - 1, day)


def mmdd_to_offset(
    mmdd: str, last_frost: str, first_frost: str, southern: bool | None = None
) -> str:
    """Turn a calendar date into an offset from that location's frost dates.

    Dates in the first half of the growing year (January to June, or July to
    December in the southern hemisphere) are measured from the last frost,
    later ones from the first frost.
    """
    southern = is_southern(last_frost, first_frost, southern)
    month = int(mmdd.split("-")[0])
    if (month >= 7) == southern:
        return format_offset(
            "L", (month_day(2001, mmdd) - month_day(2001, last_frost)).days
        )
    # Second-half dates are in the next calendar year down south; so is the
    # first frost when it comes earlier in the calendar than the last.
    day = month_day(2002 if southern else 2001, mmdd)
    frost = month_day(
        2002 if frost_wraps(last_frost, first_frost) else 2001, first_frost
    )
    return format_offset("F", (day - frost).days)


MAX_RANGE_DAYS = 240


def range_to_offsets(
    start: str, end: str, last_frost: str, first_frost: str,
    southern: bool | None = None,
) -> tuple[str, str]:
    """A calendar range (MM-DD to MM-DD) as frost offsets.

    A range whose end comes before its start, such as Nov 1 to Jan 15, runs
    into the next year; its end is then measured from the same frost date as
    its start so it stays after it.
    """
    southern = is_southern(last_frost, first_frost, southern)
    first = mmdd_to_offset(start, last_frost, first_frost, southern)
    if _season_order(end, southern) >= _season_order(start, southern):
        return first, mmdd_to_offset(end, last_frost, first_frost, southern)
    span = (month_day(2001, end) - month_day(2001, start)).days % 365
    if span > MAX_RANGE_DAYS:
        raise PlannerError(
            f"The range {start} to {end} ends before it starts; "
            "check the from and to dates"
        )
    anchor, days = parse_offset(first)
    return first, format_offset(anchor, days + span)


def _anchor_date(anchor: str, year: int, crop: Crop, settings: Settings) -> date:
    if anchor == "L":
        mmdd = settings.last_frost
        if crop.frost_tender and settings.warm_last_frost:
            mmdd = settings.warm_last_frost
        return month_day(year, mmdd)
    # The first frost follows the last one: in the next calendar year when it
    # comes earlier in the calendar (southern gardens, or a January frost).
    wraps = frost_wraps(settings.last_frost, settings.first_frost)
    return month_day(year + (1 if wraps else 0), settings.first_frost)


def offset_to_mmdd(token: str, crop: Crop, settings: Settings) -> str:
    """The calendar date (MM-DD) of a frost offset, ignoring the date shift."""
    anchor, days = parse_offset(token)
    return f"{_anchor_date(anchor, 2001, crop, settings) + timedelta(days=days):%m-%d}"


def resolve(token: str, year: int, crop: Crop, settings: Settings) -> date:
    """The calendar date of a frost offset for this location."""
    anchor, days = parse_offset(token)
    return _anchor_date(anchor, year, crop, settings) + timedelta(
        days=days + settings.offset_days
    )


def effective_range(
    crop: Crop,
    rng: tuple[str, str],
    year: int,
    settings: Settings,
    greenhouse: bool,
) -> tuple[date, date]:
    """A crop range as calendar dates for this location and growing place."""
    start = resolve(rng[0], year, crop, settings)
    # A range that mixes frost dates (L+75 to F-124) can end before it starts
    # where the season is short; it then shrinks to its start.
    end = max(start, resolve(rng[1], year, crop, settings))
    if greenhouse:
        start -= timedelta(weeks=settings.greenhouse_spring_weeks)
        end += timedelta(weeks=settings.greenhouse_fall_weeks)
    return start, end


def choose_window(
    crop: Crop, method: str, season: str | None, profile: str | None = None
) -> Window:
    """Pick the crop window a planting uses."""
    options = [w for w in crop.windows_for(profile) if _window_supports(w, method)]
    if not options:
        raise PlannerError(
            f"{crop.name} can't be grown with method {method}. "
            f"Supported: {', '.join(crop.methods(profile)) or 'none'}"
        )
    if season:
        for window in options:
            if window.season == season:
                return window
        raise PlannerError(
            f"{crop.name} has no {season} window for {method}. "
            f"Seasons: {', '.join(w.season for w in options)}"
        )
    return options[0]


def _weeks_indoor(crop: Crop, window: Window) -> int:
    if crop.weeks_indoor:
        return int(crop.weeks_indoor)
    if window.indoor and window.transplant:
        a_anchor, a_days = parse_offset(window.indoor[0])
        b_anchor, b_days = parse_offset(window.transplant[0])
        if a_anchor == b_anchor:
            return max(1, round((b_days - a_days) / 7))
    return 6


def sowing_dates(
    planting: Planting, crop: Crop, settings: Settings
) -> Schedule:
    """The anchor date of each succession: transplant for indoor, sowing for direct."""
    window = choose_window(crop, planting.method, planting.season, settings.profile)
    greenhouse = planting.method in GREENHOUSE_METHODS
    rng = window.transplant if planting.method in INDOOR_METHODS else window.direct
    assert rng is not None
    start, end = effective_range(crop, rng, planting.year, settings, greenhouse)

    first = parse_date(planting.start_date) or start
    until = parse_date(planting.succession_until) or end
    schedule = Schedule(window_start=start, window_end=end)

    interval = int(planting.succession_days or 0)
    if interval <= 0:
        schedule.dates.append(first)
        return schedule

    count = int(planting.succession_count) if planting.succession_count else None
    current = first
    while (count is None or len(schedule.dates) < count) and (
        current <= until or not schedule.dates
    ):
        schedule.dates.append(current)
        current += timedelta(days=interval)
        if len(schedule.dates) >= 200:
            break
    return schedule


def generate_tasks(
    planting: Planting, crop: Crop, settings: Settings
) -> list[Task]:
    """All tasks for a planting, in date order, before any actual dates."""
    window = choose_window(crop, planting.method, planting.season, settings.profile)
    schedule = sowing_dates(planting, crop, settings)
    greenhouse = planting.method in GREENHOUSE_METHODS
    indoor = planting.method in INDOOR_METHODS
    place = "greenhouse" if greenhouse else "beds"
    label = f"{crop.name} ({planting.variety})" if planting.variety else crop.name
    total = len(schedule.dates)
    tasks: list[Task] = []

    def add(
        idx: int, kind: str, due: date, summary: str, extra: str = "",
        fixed: bool = False,
    ) -> None:
        suffix = f" (sowing {idx + 1} of {total})" if total > 1 else ""
        parts = [p for p in (extra, planting.quantity and f"Quantity: {planting.quantity}",
                             planting.location_for(kind)
                             and f"Location: {planting.location_for(kind)}",
                             planting.notes) if p]
        tasks.append(
            Task(
                uid=f"{planting.id}:{idx}:{kind}",
                planting_id=planting.id,
                succession=idx,
                kind=kind,
                due=due,
                planned=due,
                summary=summary + suffix,
                description="\n".join(parts),
                icon=TASK_ICONS.get(kind, "mdi:sprout"),
                crop_icon=crop.icon,
                fixed=fixed,
            )
        )

    for idx, anchor in enumerate(schedule.dates):
        if indoor:
            # Where it's planted out, when the planting says.
            out_to = planting.location or place
            weeks = _weeks_indoor(crop, window)
            sow = anchor - timedelta(weeks=weeks)
            add(idx, TASK_SOW_INDOORS, sow, f"Sow {label} indoors",
                f"Transplant to {out_to} about {anchor:%b %-d}.")
            if crop.pot_up and weeks >= 5:
                add(idx, TASK_POT_UP, sow + timedelta(days=weeks * 7 // 2),
                    f"Pot up {label}")
            harden = (
                settings.greenhouse_harden_off_days
                if greenhouse
                else settings.harden_off_days
            )
            if harden > 0:
                add(idx, TASK_HARDEN_OFF, anchor - timedelta(days=harden),
                    f"Start hardening off {label}",
                    f"{harden} days before transplanting to {out_to}.")
            add(idx, TASK_TRANSPLANT, anchor, f"Transplant {label} to {out_to}")
            seeded = sow
        else:
            verb = "Plant" if crop.planted else "Sow"
            add(idx, TASK_SOW, anchor, f"{verb} {label} in {place}")
            seeded = anchor

        if not greenhouse and window.cover and idx == 0:
            cover_start, _ = effective_range(
                crop, window.cover, planting.year, settings, False
            )
            if cover_start >= anchor:
                add(idx, TASK_COVER, cover_start, f"Cover {label}",
                    "Row cover or cloche to extend the season.")

        overwinter = crop.overwinter_harvest is not None and window.season != "spring"
        if overwinter:
            spring = month_day(
                planting.year + 1, settings.warm_last_frost or settings.last_frost
            )
            harvest = spring + timedelta(
                days=crop.overwinter_harvest + settings.offset_days
            )
        else:
            harvest = seeded + timedelta(days=crop.days_to_harvest)
        harvest_end = harvest + timedelta(weeks=crop.harvest_weeks)
        add(idx, TASK_HARVEST, harvest, f"Harvest {label}",
            f"Expected harvest window: {harvest:%b %-d, %Y} to {harvest_end:%b %-d, %Y}."
            + (f" {crop.notes}" if crop.notes else ""),
            fixed=overwinter)

    tasks.sort(key=lambda t: (t.due, t.succession))
    return tasks


def planting_timeline(tasks: list[Task], crop: Crop) -> dict[str, Any] | None:
    """A planting's phases as date ranges, for drawing it on a season chart.

    Each phase spans every sowing: from the first to the last. Harvest runs
    to the last harvest's end. "grow" joins going in the ground (planting out,
    or sowing outside) to the first harvest. Dates already follow what was
    done early or late.
    """
    if not tasks:
        return None
    by_kind: dict[str, list[Task]] = {}
    for task in tasks:
        by_kind.setdefault(task.kind, []).append(task)

    def span(kind: str, extra_days: int = 0) -> dict[str, Any] | None:
        group = by_kind.get(kind)
        if not group:
            return None
        start = min(t.due for t in group)
        end = max(t.due for t in group) + timedelta(days=extra_days)
        return {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "done": all(t.done_on for t in group),
        }

    phases = {
        "indoor": span(TASK_SOW_INDOORS),
        "out": span(TASK_TRANSPLANT),
        "sow": span(TASK_SOW),
        "harvest": span(TASK_HARVEST, crop.harvest_weeks * 7),
    }
    begin = phases["out"] or phases["sow"]
    if begin and phases["harvest"] and phases["harvest"]["start"] > begin["start"]:
        phases["grow"] = {"start": begin["start"], "end": phases["harvest"]["start"]}
    return {key: value for key, value in phases.items() if value}


def apply_actuals(tasks: list[Task], actuals: dict[str, str | date]) -> list[Task]:
    """Mark tasks done and shift later tasks in the same chain to match.

    If a task was done 4 days late, every later task for that planting and
    sowing moves 4 days later too.
    """
    chains: dict[tuple[str, int], list[Task]] = {}
    for task in tasks:
        chains.setdefault((task.planting_id, task.succession), []).append(task)
    for chain in chains.values():
        chain.sort(key=lambda t: t.planned)
        delta = timedelta(0)
        for task in chain:
            task.due = task.planned if task.fixed else task.planned + delta
            done = parse_date(actuals.get(task.uid)) if task.uid in actuals else None
            if done:
                task.done_on = done
                task.due = done
                delta = done - task.planned
    tasks.sort(key=lambda t: (t.due, t.succession))
    return tasks
