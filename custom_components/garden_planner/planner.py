"""Garden Planner date engine.

Turns plantings into dated tasks. This module has no Home Assistant imports so
it can be unit tested on its own.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from datetime import date, timedelta
import json
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

CATALOG_PATH = Path(__file__).parent / "data" / "crops.json"


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
    # The chart covers all of South Coastal BC. Shifting moves spring dates by
    # (last_frost - baseline_last_frost) and fall dates by
    # (first_frost - baseline_first_frost).
    shift_windows: bool = True
    # Warm-season crops depend on soil and night temperature more than on the
    # last frost, so by default their bed dates are not moved earlier.
    shift_frost_tender: bool = False
    baseline_last_frost: str = "04-01"
    baseline_first_frost: str = "11-16"
    greenhouse_spring_weeks: int = 4
    greenhouse_fall_weeks: int = 4
    harden_off_days: int = 7
    greenhouse_harden_off_days: int = 3

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Settings:
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class Window:
    """One growing window of a crop, with "MM-DD" ranges."""

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
    notes: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Crop:
        return cls(
            key=data["key"],
            name=data["name"],
            windows=[Window.from_dict(w) for w in data.get("windows", [])],
            weeks_indoor=data.get("weeks_indoor"),
            days_to_harvest=int(data.get("days_to_harvest", 60)),
            harvest_weeks=int(data.get("harvest_weeks", 4)),
            frost_tender=bool(data.get("frost_tender", False)),
            pot_up=bool(data.get("pot_up", False)),
            perennial=bool(data.get("perennial", False)),
            source=data.get("source", "custom"),
            notes=data.get("notes"),
        )

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["windows"] = [w.to_dict() for w in self.windows]
        return out

    def supports(self, method: str) -> bool:
        return any(_window_supports(w, method) for w in self.windows)

    def methods(self) -> list[str]:
        return [m for m in METHODS if self.supports(m)]


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
    location: str | None = None
    notes: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Planting:
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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


def _shift_days(settings: Settings, crop: Crop, day: date) -> int:
    if not settings.shift_windows:
        return 0
    if crop.frost_tender and not settings.shift_frost_tender:
        return 0
    year = day.year
    if day.month < 7:
        return (
            month_day(year, settings.last_frost)
            - month_day(year, settings.baseline_last_frost)
        ).days
    return (
        month_day(year, settings.first_frost)
        - month_day(year, settings.baseline_first_frost)
    ).days


def effective_range(
    crop: Crop,
    rng: tuple[str, str],
    year: int,
    settings: Settings,
    greenhouse: bool,
) -> tuple[date, date]:
    """A chart range for this location and growing place."""
    start = month_day(year, rng[0])
    end = month_day(year, rng[1])
    start += timedelta(days=_shift_days(settings, crop, start))
    end += timedelta(days=_shift_days(settings, crop, end))
    if greenhouse:
        start -= timedelta(weeks=settings.greenhouse_spring_weeks)
        end += timedelta(weeks=settings.greenhouse_fall_weeks)
    return start, end


def choose_window(crop: Crop, method: str, season: str | None) -> Window:
    """Pick the crop window a planting uses."""
    options = [w for w in crop.windows if _window_supports(w, method)]
    if not options:
        raise PlannerError(
            f"{crop.name} can't be grown with method {method}. "
            f"Supported: {', '.join(crop.methods()) or 'none'}"
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
        gap = month_day(2000, window.transplant[0]) - month_day(2000, window.indoor[0])
        return max(1, round(gap.days / 7))
    return 6


def sowing_dates(
    planting: Planting, crop: Crop, settings: Settings
) -> Schedule:
    """The anchor date of each succession: transplant for indoor, sowing for direct."""
    window = choose_window(crop, planting.method, planting.season)
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
    window = choose_window(crop, planting.method, planting.season)
    schedule = sowing_dates(planting, crop, settings)
    greenhouse = planting.method in GREENHOUSE_METHODS
    indoor = planting.method in INDOOR_METHODS
    place = "greenhouse" if greenhouse else "beds"
    label = f"{crop.name} ({planting.variety})" if planting.variety else crop.name
    total = len(schedule.dates)
    tasks: list[Task] = []

    def add(idx: int, kind: str, due: date, summary: str, extra: str = "") -> None:
        suffix = f" (sowing {idx + 1} of {total})" if total > 1 else ""
        parts = [p for p in (extra, planting.quantity and f"Quantity: {planting.quantity}",
                             planting.location and f"Location: {planting.location}",
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
            )
        )

    for idx, anchor in enumerate(schedule.dates):
        if indoor:
            weeks = _weeks_indoor(crop, window)
            sow = anchor - timedelta(weeks=weeks)
            add(idx, TASK_SOW_INDOORS, sow, f"Sow {label} indoors",
                f"Transplant to {place} about {anchor:%b %-d}.")
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
                    f"{harden} days before transplanting to {place}.")
            add(idx, TASK_TRANSPLANT, anchor, f"Transplant {label} to {place}")
            seeded = sow
        else:
            verb = "Plant" if crop.key in ("garlic", "potato") else "Sow"
            add(idx, TASK_SOW, anchor, f"{verb} {label} in {place}")
            seeded = anchor

        if not greenhouse and window.cover and idx == 0:
            cover_start, _ = effective_range(
                crop, window.cover, planting.year, settings, False
            )
            if cover_start >= anchor:
                add(idx, TASK_COVER, cover_start, f"Cover {label}",
                    "Row cover or cloche to extend the season.")

        harvest = seeded + timedelta(days=crop.days_to_harvest)
        harvest_end = harvest + timedelta(weeks=crop.harvest_weeks)
        add(idx, TASK_HARVEST, harvest, f"Harvest {label}",
            f"Expected harvest window: {harvest:%b %-d, %Y} to {harvest_end:%b %-d, %Y}."
            + (f" {crop.notes}" if crop.notes else ""))

    tasks.sort(key=lambda t: (t.due, t.succession))
    return tasks


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
            task.due = task.planned + delta
            done = parse_date(actuals.get(task.uid)) if task.uid in actuals else None
            if done:
                task.done_on = done
                task.due = done
                delta = done - task.planned
    tasks.sort(key=lambda t: (t.due, t.succession))
    return tasks
