"""Keeps plantings, tasks and the chosen to-do list in step."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
import logging
from typing import Any
import uuid

from homeassistant.components.todo import TodoListEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_SUPPORTED_FEATURES
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_FIRST_FROST,
    CONF_GREENHOUSE_FALL_WEEKS,
    CONF_GREENHOUSE_HARDEN_OFF_DAYS,
    CONF_GREENHOUSE_SPRING_WEEKS,
    CONF_HARDEN_OFF_DAYS,
    CONF_LAST_FROST,
    CONF_LOOKAHEAD_DAYS,
    CONF_OFFSET_DAYS,
    CONF_PROFILE,
    CONF_WARM_LAST_FROST,
    CONF_TODO_ENTITY,
    DEFAULTS,
    DOMAIN,
    MARKER_PREFIX,
    NEW_LIST,
    STORAGE_VERSION,
    SYNC_INTERVAL_MINUTES,
)
from .planner import (
    BEFORE_PLANT_OUT,
    INDOOR_METHODS,
    OFFSET_RE,
    Crop,
    Planting,
    PlannerError,
    Settings,
    Task,
    apply_actuals,
    generate_tasks,
    load_catalog,
    mmdd_to_offset,
    offset_to_mmdd,
    parse_offset,
    range_to_offsets,
    sowing_dates,
)

_LOGGER = logging.getLogger(__name__)


CROP_DEFAULT_KEYS = (
    "method", "succession_days", "succession_count", "quantity", "location",
    "start_location", "bought_starts",
)
# Planting fields that name a location.
LOCATION_FIELDS = ("location", "start_location")


def _empty_data() -> dict[str, Any]:
    return {
        "plantings": {},
        # Your own crops, and your edits of built-in ones (same key).
        "custom_crops": {},
        # Built-in crops you removed from the list.
        "hidden_crops": [],
        # task uid -> ISO date it was done
        "actuals": {},
        # task uid -> to-do item uid on the target list
        "pushed": {},
        # the list "pushed" refers to
        "pushed_entity": None,
        # tasks added to the list whose item couldn't be found afterwards
        "unmatched": [],
        # pushed tasks whose item was missing on the last sync
        "missing": [],
        # task uids the user deleted from the list; never re-added
        "dismissed": [],
        # items of the planner's own list, when it uses one
        "own_items": [],
        # crop key -> the user's planting defaults for that crop
        "crop_defaults": {},
        # location id -> {id, name, soil_sensor, soil_temperature, light, camera, water}
        "locations": {},
        # location id -> {last, minutes, manual, started}: when it was last
        # watered, for how long, by hand or not, and when the valve opened if
        # it's open now
        "watering": {},
    }


# What pushed_entity holds while Reap uses its own list.
OWN_LIST_KEY = "own"

DEFAULT_LOCATIONS = ("Seedling Tray", "Garden", "Greenhouse")
LOCATION_ENTITY_KEYS = ("soil_sensor", "soil_temperature", "light", "camera", "water")
# States of a watering valve or switch that mean water is running.
WATER_ON_STATES = ("on", "open", "opening")


class GardenManager:
    """Owns the stored plantings and syncs tasks to a to-do list."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self.data: dict[str, Any] = _empty_data()
        self.builtin_crops: dict[str, Crop] = {}
        self.tasks: list[Task] = []
        self.own_entity_id: str | None = None
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[Callable[[], None]] = []
        self._water_unsub: Callable[[], None] | None = None
        self._watched_water: tuple[str, ...] = ()
        self._syncing = False
        self._resync = False
        self._crops: dict[str, Crop] | None = None
        # planting id -> why it can't be scheduled right now
        self.problems: dict[str, str] = {}

    # ----- config -----

    def option(self, key: str) -> Any:
        if key in self.entry.options:
            return self.entry.options[key]
        return self.entry.data.get(key, DEFAULTS[key])

    @property
    def uses_own_list(self) -> bool:
        return self.option(CONF_TODO_ENTITY) in (None, "", NEW_LIST)

    @property
    def target_entity_id(self) -> str | None:
        if self.uses_own_list:
            return self.own_entity_id
        return self.option(CONF_TODO_ENTITY)

    @property
    def settings(self) -> Settings:
        return Settings(
            last_frost=self.option(CONF_LAST_FROST),
            first_frost=self.option(CONF_FIRST_FROST),
            warm_last_frost=self.option(CONF_WARM_LAST_FROST) or None,
            offset_days=int(self.option(CONF_OFFSET_DAYS)),
            profile=self.option(CONF_PROFILE),
            greenhouse_spring_weeks=int(self.option(CONF_GREENHOUSE_SPRING_WEEKS)),
            greenhouse_fall_weeks=int(self.option(CONF_GREENHOUSE_FALL_WEEKS)),
            harden_off_days=int(self.option(CONF_HARDEN_OFF_DAYS)),
            greenhouse_harden_off_days=int(
                self.option(CONF_GREENHOUSE_HARDEN_OFF_DAYS)
            ),
            southern=_southern(self.hass),
        )

    @property
    def lookahead_days(self) -> int:
        return int(self.option(CONF_LOOKAHEAD_DAYS))

    # ----- lifecycle -----

    async def async_setup(self) -> None:
        self.builtin_crops = await self.hass.async_add_executor_job(load_catalog)
        stored = await self._store.async_load()
        if stored:
            self.data = {**_empty_data(), **stored}
        if not stored or "locations" not in stored:
            self._seed_locations()
            await self._async_save()
        self.rebuild()
        self._watch_watering()

        self._unsubs.append(
            async_track_time_interval(
                self.hass,
                self._async_interval_sync,
                timedelta(minutes=SYNC_INTERVAL_MINUTES),
            )
        )
        if not self.uses_own_list and self.target_entity_id:
            self._unsubs.append(
                async_track_state_change_event(
                    self.hass, [self.target_entity_id], self._async_target_changed
                )
            )

    async def async_unload(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._water_unsub:
            self._water_unsub()
            self._water_unsub = None
        await self._store.async_save(self.data)

    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)

        def remove() -> None:
            self._listeners.remove(listener)

        return remove

    @callback
    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    async def _async_save(self) -> None:
        await self._store.async_save(self.data)

    # ----- crops and plantings -----

    @property
    def crops(self) -> dict[str, Crop]:
        """Every crop on the list: built-in ones (with your edits) and your own."""
        if self._crops is None:
            hidden = set(self.data["hidden_crops"])
            crops = {k: c for k, c in self.builtin_crops.items() if k not in hidden}
            for key, raw in self.data["custom_crops"].items():
                if key not in hidden:
                    crops[key] = Crop.from_dict(raw)
            self._crops = crops
        return self._crops

    def hidden_crops(self) -> list[Crop]:
        """Built-in crops removed from the list, which can be restored."""
        return [
            self.builtin_crops[k] for k in self.data["hidden_crops"]
            if k in self.builtin_crops
        ]

    def crop(self, key: str) -> Crop:
        try:
            return self.crops[key]
        except KeyError as err:
            raise PlannerError(f"Unknown crop: {key}") from err

    def crop_defaults(self, key: str) -> dict[str, Any]:
        """Planting defaults for a crop: built-in, then the user's own."""
        crop = self.crop(key)
        merged = {**crop.defaults, **self.data["crop_defaults"].get(key, {})}
        methods = crop.methods(self.settings.profile)
        if merged.get("method") not in methods and methods:
            merged["method"] = methods[0]
        return {k: v for k, v in merged.items() if v not in (None, "")}

    async def async_set_crop_defaults(
        self, key: str, values: dict[str, Any] | None
    ) -> None:
        """Save the user's defaults for a crop, or clear them with None."""
        self.crop(key)
        if values is None:
            self.data["crop_defaults"].pop(key, None)
        else:
            self.data["crop_defaults"][key] = {
                k: (self._location_name(v) if k in LOCATION_FIELDS else v)
                for k, v in values.items()
                if k in CROP_DEFAULT_KEYS
            }
        await self._async_save()
        self._notify()

    # ----- locations -----

    def _seed_locations(self) -> None:
        """Default locations, plus any free-text ones existing plantings use."""
        names = list(DEFAULT_LOCATIONS)
        for raw in self.data["plantings"].values():
            for field in LOCATION_FIELDS:
                name = (raw.get(field) or "").strip()
                if name and name.casefold() not in {n.casefold() for n in names}:
                    names.append(name)
        for name in names:
            self._new_location(name)

    def _new_location(self, name: str, **entities: str | None) -> dict[str, Any]:
        location_id = uuid.uuid4().hex[:8]
        location = {"id": location_id, "name": name}
        for key in LOCATION_ENTITY_KEYS:
            location[key] = entities.get(key) or None
        self.data["locations"][location_id] = location
        return location

    def locations(self) -> list[dict[str, Any]]:
        """Locations in the order they were added, with when each was last
        watered and how many plantings use it:

        - plantings: under way there now,
        - in_use: plantings that name it at all, planned ones included. A
          location in use can't be removed.
        """
        here: dict[str, int] = {}
        named: dict[str, int] = {}
        where = self.where_now()
        for planting in self.plantings():
            state = where.get(planting.id, {})
            if state.get("active"):
                for name in state.get("current_locations", []):
                    here[name.casefold()] = here.get(name.casefold(), 0) + 1
            for name in {(getattr(planting, f) or "").casefold() for f in LOCATION_FIELDS}:
                if name:
                    named[name] = named.get(name, 0) + 1
        result = []
        for loc in self.data["locations"].values():
            watering = self.data["watering"].get(loc["id"], {})
            folded = loc["name"].casefold()
            result.append({
                **{key: None for key in LOCATION_ENTITY_KEYS},
                **loc,
                "plantings": here.get(folded, 0),
                "in_use": named.get(folded, 0),
                "last_watered": watering.get("last"),
                "watered_minutes": watering.get("minutes"),
                "watered_by_hand": bool(watering.get("manual")),
            })
        return result

    # ----- watering -----

    def _watch_watering(self) -> None:
        """Follow every location's watering valve or switch."""
        entities = tuple(sorted({
            loc["water"] for loc in self.data["locations"].values() if loc.get("water")
        }))
        if entities == self._watched_water and (self._water_unsub or not entities):
            return
        if self._water_unsub:
            self._water_unsub()
            self._water_unsub = None
        self._watched_water = entities
        if entities:
            self._water_unsub = async_track_state_change_event(
                self.hass, list(entities), self._async_water_changed
            )

    async def _async_water_changed(self, event: Event) -> None:
        entity_id = event.data["entity_id"]
        old, new = event.data.get("old_state"), event.data.get("new_state")
        # Dropping off the network isn't a change: a run that was going stays
        # open, and the next real state ends or continues it.
        if new is None or new.state in ("unavailable", "unknown"):
            return
        is_on = new.state in WATER_ON_STATES
        now = dt_util.now()
        changed = False
        for loc in self.data["locations"].values():
            if loc.get("water") != entity_id:
                continue
            record = self.data["watering"].setdefault(loc["id"], {})
            running = bool(record.get("started"))
            if is_on and not running:
                changed = True
                record.update(last=now.isoformat(), minutes=None, manual=False,
                              started=now.isoformat())
            elif not is_on and running:
                changed = True
                started = dt_util.parse_datetime(record["started"])
                # Without an old state (Home Assistant just started) the run
                # ended while it was down, at a time nobody saw.
                if started and old is not None:
                    record["minutes"] = max(0, round((now - started).total_seconds() / 60))
                record["started"] = None
        if changed:
            await self._async_save()
            self._notify()

    async def async_log_watering(self, location: str) -> dict[str, Any]:
        """Record that a location was watered by hand just now."""
        loc = self.data["locations"].get(location) or self._location_named(location)
        if loc is None:
            raise PlannerError(f"Unknown location: {location}")
        self.data["watering"][loc["id"]] = {
            "last": dt_util.now().isoformat(), "minutes": None, "manual": True, "started": None,
        }
        await self._async_save()
        self._notify()
        return next(item for item in self.locations() if item["id"] == loc["id"])

    def _location_named(self, name: str) -> dict[str, Any] | None:
        folded = name.strip().casefold()
        for loc in self.data["locations"].values():
            if loc["name"].casefold() == folded:
                return loc
        return None

    def _with_locations(self, fields: dict[str, Any]) -> dict[str, Any]:
        """Planting fields with known location names (new ones are added).

        Only indoor starts have a start location.
        """
        fields = dict(fields)
        if fields.get("method") not in INDOOR_METHODS:
            fields.pop("start_location", None)
            fields.pop("bought_starts", None)
        for field in LOCATION_FIELDS:
            if fields.get(field):
                fields[field] = self._location_name(fields[field])
        return fields

    def where_now(self) -> dict[str, dict[str, Any]]:
        """Where each planting is now, and whether it's in the ground.

        - current_locations: every place it is. An indoor start is in its
          start location until a sowing is planted out, so repeat sowings can
          be in the tray and the bed at once.
        - current_location: the start location while any sowing is still
          there, then where it's planted out.
        - active: under way. Its first task is done or due, and its harvest
          isn't done and its harvest window hasn't ended.

        A sowing counts as planted out once its transplant (or a later task)
        is ticked off, or was deleted from the list after its due date.
        """
        today = dt_util.now().date()
        dismissed = set(self.data["dismissed"])
        by_planting: dict[str, list[Task]] = {}
        for task in self.tasks:
            by_planting.setdefault(task.planting_id, []).append(task)
        result: dict[str, dict[str, Any]] = {}
        for planting in self.plantings():
            tasks = by_planting.get(planting.id, [])
            places: list[str] = []
            staged = planting.method in INDOOR_METHODS and planting.start_location
            if staged:
                for idx in sorted({t.succession for t in tasks}) or [0]:
                    out = any(
                        t.succession == idx and t.kind not in BEFORE_PLANT_OUT
                        and (t.done_on or (t.uid in dismissed and t.due <= today))
                        for t in tasks
                    )
                    places.append(planting.location if out else planting.start_location)
            else:
                places.append(planting.location)
            places = [p for i, p in enumerate(places) if p and p not in places[:i]]
            if staged and planting.start_location in places:
                current = planting.start_location
            else:
                current = planting.location or (places[0] if places else None)
            # Start location first, then the bed.
            places.sort(key=lambda p: p != planting.start_location)
            result[planting.id] = {
                "current_location": current,
                "current_locations": places,
                "active": self._active(planting, tasks, today),
            }
        return result

    def _active(self, planting: Planting, tasks: list[Task], today: date) -> bool:
        if not tasks:
            return False
        started = any(t.done_on for t in tasks) or min(t.due for t in tasks) <= today
        if not started:
            return False
        harvests = [t for t in tasks if t.kind == "harvest"]
        if harvests and all(t.done_on for t in harvests):
            return False
        weeks = self.crops[planting.crop].harvest_weeks if planting.crop in self.crops else 4
        if harvests and max(t.due for t in harvests) + timedelta(weeks=weeks) < today:
            return False
        return any(not t.done_on for t in tasks)

    def current_location(self, planting: Planting) -> str | None:
        """Where a planting is now: its start location until it's planted out."""
        return self.where_now().get(planting.id, {}).get("current_location", planting.location)

    def _location_name(self, value: Any) -> Any:
        """A planting's location as a known location name, added if new."""
        if not isinstance(value, str) or not value.strip():
            return value
        loc = self._location_named(value) or self._new_location(value.strip())
        return loc["name"]

    async def async_add_location(
        self, name: str, **entities: str | None
    ) -> dict[str, Any]:
        name = name.strip()
        if not name:
            raise PlannerError("A location needs a name")
        if self._location_named(name):
            raise PlannerError(f"There is already a location called {name}")
        location = self._new_location(
            name, **{k: v for k, v in entities.items() if k in LOCATION_ENTITY_KEYS}
        )
        await self._async_save()
        self.rebuild()
        self._watch_watering()
        return location

    async def async_update_location(
        self, location_id: str, changes: dict[str, Any]
    ) -> dict[str, Any]:
        """Rename a location or change its entities. Empty values clear an entity."""
        location = self.data["locations"].get(location_id)
        if location is None:
            raise PlannerError(f"Unknown location: {location_id}")
        old_name = location["name"]
        if "name" in changes:
            new_name = (changes["name"] or "").strip()
            if not new_name:
                raise PlannerError("A location needs a name")
            other = self._location_named(new_name)
            if other and other["id"] != location_id:
                raise PlannerError(f"There is already a location called {new_name}")
            location["name"] = new_name
        for key in LOCATION_ENTITY_KEYS:
            if key in changes:
                location[key] = changes[key] or None
        if location["name"] != old_name:
            folded = old_name.casefold()
            for raw in [*self.data["plantings"].values(),
                        *self.data["crop_defaults"].values()]:
                for field in LOCATION_FIELDS:
                    if (raw.get(field) or "").casefold() == folded:
                        raw[field] = location["name"]
        await self._async_save()
        self.rebuild()
        self._watch_watering()
        await self.async_sync()
        return location

    async def async_remove_location(self, location_id: str) -> None:
        location = self.data["locations"].get(location_id)
        if location is None:
            raise PlannerError(f"Unknown location: {location_id}")
        folded = location["name"].casefold()
        in_use = [
            raw for raw in self.data["plantings"].values()
            if any((raw.get(field) or "").casefold() == folded
                   for field in LOCATION_FIELDS)
        ]
        if in_use:
            raise PlannerError(
                f"{location['name']} is used by {len(in_use)} planting(s); "
                "move or remove them first"
            )
        del self.data["locations"][location_id]
        self.data["watering"].pop(location_id, None)
        for defaults in self.data["crop_defaults"].values():
            for field in LOCATION_FIELDS:
                if (defaults.get(field) or "").casefold() == folded:
                    defaults.pop(field, None)
        await self._async_save()
        self.rebuild()
        self._watch_watering()

    # ----- plantings -----

    def plantings(self) -> list[Planting]:
        return [Planting.from_dict(p) for p in self.data["plantings"].values()]

    def _with_method(self, fields: dict[str, Any]) -> dict[str, Any]:
        if not fields.get("method"):
            fields = {**fields, "method": self.crop_defaults(fields["crop"]).get("method")}
        if not fields.get("year"):
            fields = {**fields, "year": self.pick_year(fields)}
        return fields

    def pick_year(self, fields: dict[str, Any], today: date | None = None) -> int:
        """The first year whose window for this planting hasn't ended yet."""
        today = today or dt_util.now().date()
        if start := fields.get("start_date"):
            return date.fromisoformat(str(start)).year
        try:
            crop = self.crop(fields["crop"])
            for year in (today.year - 1, today.year, today.year + 1):
                planting = Planting(
                    id="year", crop=crop.key, method=fields["method"], year=year,
                    season=fields.get("season"),
                )
                if sowing_dates(planting, crop, self.settings).window_end >= today:
                    return year
        except (KeyError, PlannerError):
            pass
        return default_year(today)

    def preview(self, fields: dict[str, Any]) -> tuple[Planting, list[Task]]:
        fields = self._with_method(fields)
        planting = Planting.from_dict({"id": "preview", **fields})
        tasks = generate_tasks(planting, self.crop(planting.crop), self.settings)
        return planting, tasks

    async def async_add_planting(
        self, fields: dict[str, Any]
    ) -> tuple[Planting, list[Task]]:
        planting_id = uuid.uuid4().hex[:8]
        fields = self._with_method(fields)
        fields = self._with_locations(fields)
        planting = Planting.from_dict({**fields, "id": planting_id})
        # Validates the planting before it is saved.
        generate_tasks(planting, self.crop(planting.crop), self.settings)
        self.data["plantings"][planting_id] = planting.to_dict()
        self.rebuild()
        await self._async_save()
        await self.async_sync()
        return planting, [t for t in self.tasks if t.planting_id == planting_id]

    async def async_add_plantings(
        self, many: list[dict[str, Any]], use_defaults: bool = True
    ) -> list[Planting]:
        """Add several plantings at once: all of them, or none if one fails.

        Each starts from its crop's saved defaults (method, repeat, quantity,
        location...) unless use_defaults is off; what's given wins.
        """
        new: list[Planting] = []
        for fields in many:
            if use_defaults and fields.get("crop"):
                fields = {**self.crop_defaults(fields["crop"]), **fields}
            fields = self._with_method(fields)
            planting = Planting.from_dict({**fields, "id": uuid.uuid4().hex[:8]})
            try:
                generate_tasks(planting, self.crop(planting.crop), self.settings)
            except PlannerError as err:
                # The message already names the crop; add the variety if any.
                if planting.variety:
                    raise PlannerError(f"{planting.variety}: {err}") from err
                raise
            new.append(planting)
        # Only now that every planting is valid: new locations get created.
        for planting in new:
            self.data["plantings"][planting.id] = self._with_locations(planting.to_dict())
        self.rebuild()
        await self._async_save()
        await self.async_sync()
        return new

    async def async_copy_plantings(
        self,
        from_year: int,
        to_year: int | None = None,
        planting_ids: list[str] | None = None,
    ) -> tuple[list[Planting], list[dict[str, str]]]:
        """Plan a year's plantings again for another year, same settings.

        Dates move by the same number of years. Plantings already planned in
        the target year (same crop, method, season, variety and location) are
        skipped unless picked by id. Returns the new plantings and the skipped
        ones with why.
        """
        to_year = to_year or from_year + 1
        shift = to_year - from_year
        if not shift:
            raise PlannerError("Pick a different year to copy to")
        today = dt_util.now().date()
        source = [p for p in self.plantings() if p.year == from_year]
        skipped: list[dict[str, str]] = []
        if planting_ids is not None:
            wanted = set(planting_ids)
            source = [p for p in source if p.id in wanted]
            for planting_id in sorted(wanted - {p.id for p in source}):
                skipped.append({"planting_id": planting_id, "name": planting_id,
                                "reason": f"not a {from_year} planting"})

        def same(p: Planting) -> tuple[Any, ...]:
            start = (p.start_date or "")[5:]  # month-day: a March and a June block differ
            return (p.crop, p.method, p.season or "", p.variety or "",
                    (p.location or "").casefold(), (p.start_location or "").casefold(),
                    start)

        # Each planting already planned covers one source planting, no more.
        planned: dict[tuple[Any, ...], int] = {}
        for p in self.plantings():
            if p.year == to_year:
                planned[same(p)] = planned.get(same(p), 0) + 1
        new: list[Planting] = []
        for old in source:
            label = self.crops[old.crop].name if old.crop in self.crops else old.crop
            if old.variety:
                label += f" ({old.variety})"
            if planting_ids is None and planned.get(same(old)):
                planned[same(old)] -= 1
                skipped.append({"planting_id": old.id, "name": label,
                                "reason": f"already planned for {to_year}"})
                continue
            raw = {**old.to_dict(), "id": uuid.uuid4().hex[:8], "year": to_year}
            for key in ("start_date", "succession_until"):
                if raw.get(key):
                    raw[key] = _add_years(raw[key], shift)
            planting = Planting.from_dict(raw)
            try:
                crop = self.crop(planting.crop)
                generate_tasks(planting, crop, self.settings)
                # Copying into a season that's over would only add overdue tasks.
                sched = sowing_dates(planting, crop, self.settings)
                if max(sched.dates[-1], sched.window_end) < today:
                    skipped.append({"planting_id": old.id, "name": label,
                                    "reason": f"its {to_year} sowing time is over"})
                    continue
            except PlannerError as err:
                skipped.append({"planting_id": old.id, "name": label, "reason": str(err)})
                continue
            new.append(planting)
        for planting in new:
            self.data["plantings"][planting.id] = planting.to_dict()
        if new:
            self.rebuild()
            await self._async_save()
            await self.async_sync()
        return new, skipped

    async def async_update_planting(
        self, planting_id: str, changes: dict[str, Any]
    ) -> tuple[Planting, list[Task]]:
        """Change a planting. Keys set to None or "" are cleared."""
        if planting_id not in self.data["plantings"]:
            raise PlannerError(f"Unknown planting: {planting_id}")
        merged = dict(self.data["plantings"][planting_id])
        for key, value in changes.items():
            if key == "id":
                continue
            merged[key] = None if value == "" else value
        merged = self._with_locations(merged)
        planting = Planting.from_dict(merged)
        generate_tasks(planting, self.crop(planting.crop), self.settings)
        self.data["plantings"][planting_id] = planting.to_dict()
        self.rebuild()
        await self._async_save()
        await self.async_sync()
        return planting, [t for t in self.tasks if t.planting_id == planting_id]

    async def async_remove_planting(self, planting_id: str) -> None:
        if planting_id not in self.data["plantings"]:
            raise PlannerError(f"Unknown planting: {planting_id}")
        del self.data["plantings"][planting_id]
        prefix = f"{planting_id}:"
        for key in ("actuals",):
            self.data[key] = {
                k: v for k, v in self.data[key].items() if not k.startswith(prefix)
            }
        self.data["dismissed"] = [
            uid for uid in self.data["dismissed"] if not uid.startswith(prefix)
        ]
        self.rebuild()
        await self._async_save()
        await self.async_sync()

    async def async_save_crop(self, data: dict[str, Any]) -> Crop:
        """Add or replace a custom crop.

        based_on copies another crop first. Window ranges can be calendar
        dates (MM-DD) for this garden, stored as offsets from its frost dates
        so they follow later changes, or offsets (L-14, F+7) directly.
        """
        data = dict(data)
        base: dict[str, Any] = {}
        if based_on := data.pop("based_on", None):
            base = self.crop(based_on).to_dict()
        elif data.get("key") in self.crops:
            # Editing: keep what the change doesn't mention.
            base = self.crops[data["key"]].to_dict()
        merged = {**base, **data, "source": "custom"}
        if not merged.get("name"):
            raise PlannerError("A new crop needs a name")
        if "windows" in data:
            # Its own dates replace every climate profile of the base crop.
            merged["profiles"] = {}
            merged["estimated_profiles"] = []
            settings = self.settings
            last_frost = settings.last_frost
            if merged.get("frost_tender") and settings.warm_last_frost:
                last_frost = settings.warm_last_frost
            old_cover = {
                w.get("season"): w.get("cover")
                for w in base.get("windows") or [] if w.get("cover")
            }
            windows = []
            for window in data["windows"]:
                converted = {"season": window.get("season") or "spring"}
                if "cover" not in window and old_cover.get(converted["season"]):
                    converted["cover"] = old_cover[converted["season"]]
                for key in ("indoor", "direct", "transplant", "cover"):
                    if window.get(key):
                        start, end = window[key]
                        if OFFSET_RE.match(start) or OFFSET_RE.match(end):
                            converted[key] = [
                                v if OFFSET_RE.match(v) else mmdd_to_offset(
                                    _mmdd(v), last_frost, settings.first_frost,
                                    settings.southern,
                                )
                                for v in (start, end)
                            ]
                        else:
                            converted[key] = list(range_to_offsets(
                                _mmdd(start), _mmdd(end), last_frost,
                                settings.first_frost, settings.southern,
                            ))
                windows.append(converted)
            merged["windows"] = windows
        elif bool(merged.get("frost_tender")) != bool(base.get("frost_tender")):
            # Frost-tender crops count from the warm-crop frost date. Keep the
            # calendar dates the same when only that box changes.
            settings = self.settings
            if settings.warm_last_frost:
                gap = (
                    date.fromisoformat(f"2001-{settings.warm_last_frost}")
                    - date.fromisoformat(f"2001-{settings.last_frost}")
                ).days
                shift = -gap if merged.get("frost_tender") else gap
                merged["windows"] = _shift_l(merged.get("windows") or [], shift)
                merged["profiles"] = {
                    name: _shift_l(ws, shift)
                    for name, ws in (merged.get("profiles") or {}).items()
                }
        if not any(
            w.get("indoor") or w.get("direct") or w.get("transplant")
            for w in merged.get("windows") or []
        ):
            raise PlannerError("A new crop needs sowing dates or a crop to copy")
        crop = Crop.from_dict(merged)
        if not crop.methods(self.settings.profile):
            raise PlannerError(
                "Give a direct sowing range, or both an indoor start and a transplant range"
            )
        # Plantings of this crop must still fit its new dates.
        if problems := self.unschedulable(crops={crop.key: crop}):
            raise PlannerError(f"{problems[0]}. Change or remove that planting first")
        await self.async_add_crop(crop)
        return crop

    def crop_info(self, crop: Crop) -> dict[str, Any]:
        """What the card needs to list, add with and edit a crop."""
        profile = self.settings.profile
        info: dict[str, Any] = {
            "key": crop.key,
            "name": crop.name,
            "icon": crop.icon,
            "category": crop.category,
            "frost_tender": crop.frost_tender,
            "planted": crop.planted,
            "perennial": crop.perennial,
            "source": crop.source,
            "custom": crop.key not in self.builtin_crops,
            "builtin": crop.key in self.builtin_crops,
            "edited": crop.key in self.builtin_crops
            and crop.key in self.data["custom_crops"],
            "notes": crop.notes,
            # A built-in crop edited before details existed keeps the built-in ones.
            "details": crop.details or (
                self.builtin_crops[crop.key].details if crop.key in self.builtin_crops else {}
            ),
            "methods": crop.methods(profile),
            "seasons": crop.seasons(profile),
            "defaults": self.crop_defaults(crop.key),
        }
        settings = self.settings
        info.update(
            days_to_harvest=crop.days_to_harvest,
            harvest_weeks=crop.harvest_weeks,
            weeks_indoor=crop.weeks_indoor,
            in_use=any(p.crop == crop.key for p in self.plantings()),
            windows=[
                {
                    "season": w.season,
                    **{
                        key: [offset_to_mmdd(v, crop, settings) for v in rng]
                        for key in ("indoor", "direct", "transplant")
                        if (rng := getattr(w, key))
                    },
                }
                for w in crop.windows_for(profile)
            ],
        )
        return info

    async def async_add_crop(self, crop: Crop) -> None:
        self.data["custom_crops"][crop.key] = crop.to_dict()
        self.data["hidden_crops"] = [k for k in self.data["hidden_crops"] if k != crop.key]
        self.rebuild()
        await self._async_save()
        await self.async_sync()

    async def async_remove_crop(self, key: str) -> None:
        """Remove a crop. A built-in one is hidden and can be restored."""
        if key not in self.crops:
            raise PlannerError(f"Unknown crop: {key}")
        in_use = [p.id for p in self.plantings() if p.crop == key]
        if in_use:
            raise PlannerError(
                f"{self.crops[key].name} is used by {len(in_use)} planting(s); "
                "remove them first"
            )
        self.data["custom_crops"].pop(key, None)
        if key in self.builtin_crops:
            self.data["hidden_crops"].append(key)
        self.data["crop_defaults"].pop(key, None)
        self.rebuild()
        await self._async_save()

    async def async_reset_crop(self, key: str) -> None:
        """Undo edits to a built-in crop, or bring a removed one back."""
        if key not in self.builtin_crops:
            raise PlannerError(f"{key} is not a built-in crop")
        if problems := self.unschedulable(crops={key: self.builtin_crops[key]}):
            raise PlannerError(
                f"{problems[0]} once its edits are undone. "
                "Change or remove that planting first"
            )
        self.data["custom_crops"].pop(key, None)
        self.data["hidden_crops"] = [k for k in self.data["hidden_crops"] if k != key]
        self.rebuild()
        await self._async_save()
        await self.async_sync()

    def rebuild(self) -> None:
        """Regenerate every task from the plantings and recorded actual dates."""
        self._crops = None  # crops may have changed
        tasks: list[Task] = []
        problems: dict[str, str] = {}
        settings = self.settings
        for planting in self.plantings():
            try:
                tasks.extend(
                    generate_tasks(planting, self.crop(planting.crop), settings)
                )
            except PlannerError as err:
                # Shown on the card; its items stay on the list until it's fixed.
                _LOGGER.warning("Can't schedule planting %s: %s", planting.id, err)
                problems[planting.id] = str(err)
        self.problems = problems
        self.tasks = apply_actuals(tasks, self.data["actuals"])
        self._notify()

    def unschedulable(
        self,
        settings: Settings | None = None,
        crops: dict[str, Crop] | None = None,
    ) -> list[str]:
        """Plantings that couldn't be scheduled with these settings or crops.

        Each is described for the person. Plantings already broken now aren't
        listed, so a change is only blamed for what it breaks.
        """
        settings = settings or self.settings
        out = []
        for planting in self.plantings():
            if planting.id in self.problems:
                continue
            crop = (crops or {}).get(planting.crop) or self.crops.get(planting.crop)
            if crop is None:
                continue
            try:
                generate_tasks(planting, crop, settings)
            except PlannerError as err:
                where = f" {planting.season}" if planting.season else ""
                out.append(
                    f"The {planting.year}{where} planting of {crop.name} "
                    f"can't be scheduled ({err})"
                )
        return out

    def settings_with(self, options: dict[str, Any]) -> Settings:
        """The settings these Configure options would give."""
        current = self.settings
        merged = {**self.entry.data, **self.entry.options, **options}
        return Settings(
            last_frost=merged.get(CONF_LAST_FROST, current.last_frost),
            first_frost=merged.get(CONF_FIRST_FROST, current.first_frost),
            warm_last_frost=merged.get(CONF_WARM_LAST_FROST) or None,
            offset_days=int(merged.get(CONF_OFFSET_DAYS, current.offset_days)),
            profile=merged.get(CONF_PROFILE, current.profile),
            greenhouse_spring_weeks=int(merged.get(
                CONF_GREENHOUSE_SPRING_WEEKS, current.greenhouse_spring_weeks)),
            greenhouse_fall_weeks=int(merged.get(
                CONF_GREENHOUSE_FALL_WEEKS, current.greenhouse_fall_weeks)),
            harden_off_days=int(merged.get(CONF_HARDEN_OFF_DAYS, current.harden_off_days)),
            greenhouse_harden_off_days=int(merged.get(
                CONF_GREENHOUSE_HARDEN_OFF_DAYS, current.greenhouse_harden_off_days)),
            southern=current.southern,
        )

    def open_tasks(self) -> list[Task]:
        dismissed = set(self.data["dismissed"])
        return [t for t in self.tasks if not t.done_on and t.uid not in dismissed]

    # ----- own list -----

    @property
    def own_items(self) -> list[dict[str, Any]]:
        return self.data["own_items"]

    async def async_save_own_items(self) -> None:
        await self._async_save()

    # ----- syncing with the to-do list -----

    async def _async_interval_sync(self, _now: Any) -> None:
        await self.async_sync()

    async def _async_target_changed(self, _event: Event) -> None:
        if not self._syncing:
            await self.async_sync()

    async def async_sync(self) -> None:
        """Bring the to-do list and the planner into step."""
        if self._syncing:
            self._resync = True
            return
        self._syncing = True
        try:
            while True:
                self._resync = False
                await self._async_sync_once()
                if not self._resync:
                    break
        finally:
            self._syncing = False

    def _features(self, entity_id: str) -> TodoListEntityFeature:
        state = self.hass.states.get(entity_id)
        if state is None:
            return TodoListEntityFeature(0)
        return TodoListEntityFeature(state.attributes.get(ATTR_SUPPORTED_FEATURES, 0))

    async def _async_get_items(self, entity_id: str) -> list[dict[str, Any]]:
        response = await self.hass.services.async_call(
            "todo",
            "get_items",
            {"entity_id": entity_id},
            blocking=True,
            return_response=True,
        )
        return list(response.get(entity_id, {}).get("items", []))

    async def _async_call(self, service: str, data: dict[str, Any]) -> None:
        await self.hass.services.async_call("todo", service, data, blocking=True)

    async def _async_sync_once(self) -> None:
        entity_id = self.target_entity_id
        if not entity_id or self.hass.states.get(entity_id) is None:
            _LOGGER.debug("To-do list %s not available yet", entity_id)
            return
        features = self._features(entity_id)
        has_due = bool(features & TodoListEntityFeature.SET_DUE_DATE_ON_ITEM)
        has_desc = bool(features & TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM)

        try:
            items = await self._async_get_items(entity_id)
        except HomeAssistantError as err:
            _LOGGER.warning("Could not read %s: %s", entity_id, err)
            return
        changed = False
        # Reap's own list is known by "own", so renaming its entity isn't
        # mistaken for a switch to another list.
        list_key = OWN_LIST_KEY if self.uses_own_list else entity_id
        stored = self.data.get("pushed_entity")
        if stored == entity_id and list_key == OWN_LIST_KEY:
            stored = self.data["pushed_entity"] = OWN_LIST_KEY  # older installs
            changed = True
        if stored != list_key:
            if stored and self.data["pushed"]:
                await self._async_leave_list(stored)
            self.data["pushed_entity"] = list_key
            self.data["unmatched"] = []
            self.data["missing"] = []
            changed = True
        by_uid = {item.get("uid"): item for item in items if item.get("uid")}
        pushed: dict[str, str] = self.data["pushed"]
        actuals: dict[str, str] = self.data["actuals"]
        dismissed: set[str] = set(self.data["dismissed"])
        unmatched: set[str] = set(self.data["unmatched"])
        was_missing: set[str] = set(self.data["missing"])
        missing: set[str] = set()
        today = dt_util.now().date()

        # 0. Find items added earlier whose uid wasn't learned then (the
        # read-back failed), by their marker or summary.
        if unmatched:
            claimed = set(pushed.values())
            by_task = {t.uid: t for t in self.tasks}
            for task_uid in sorted(unmatched):
                task = by_task.get(task_uid)
                summary = _item_summary(task, has_due) if task else ""
                if match := _find_new_item(items, task_uid, summary, claimed):
                    pushed[task_uid] = match
                    claimed.add(match)
                    unmatched.discard(task_uid)
                    changed = True

        # 1. Read back what happened on the list.
        for task_uid, item_uid in list(pushed.items()):
            item = by_uid.get(item_uid)
            if item is None:
                if task_uid not in was_missing and not self.uses_own_list:
                    # Missing once could be a list that hasn't loaded yet.
                    # Wait for the next sync before treating it as deleted.
                    # (Reap's own list is always loaded.)
                    missing.add(task_uid)
                    continue
                # Deleted from the list by hand: don't add it again.
                del pushed[task_uid]
                if task_uid not in actuals:
                    dismissed.add(task_uid)
                changed = True
                continue
            done = item.get("status") == "completed"
            if done and task_uid not in actuals:
                actuals[task_uid] = today.isoformat()
                changed = True
            elif not done and task_uid in actuals:
                del actuals[task_uid]
                changed = True

        if sorted(missing) != self.data["missing"]:
            self.data["missing"] = sorted(missing)
            changed = True
        if changed:
            self.data["dismissed"] = sorted(dismissed)
            self.rebuild()

        # 2. Remove open items whose planting is gone.
        current = {t.uid for t in self.tasks}
        if unmatched - current:
            unmatched &= current
            changed = True
        # Keep the items of a planting that can't be scheduled right now (after
        # a profile change, say); they come back in step once it's fixed.
        stale = [
            uid for uid in pushed
            if uid not in current and uid.split(":")[0] not in self.problems
        ]
        for task_uid in stale:
            item_uid = pushed.pop(task_uid)
            item = by_uid.get(item_uid)
            if item and item.get("status") != "completed":
                try:
                    await self._async_call(
                        "remove_item", {"entity_id": entity_id, "item": [item_uid]}
                    )
                except HomeAssistantError as err:
                    _LOGGER.warning("Could not remove %s: %s", item_uid, err)
            changed = True

        # 3. Add tasks coming into view, and move ones whose dates changed.
        horizon = today + timedelta(days=self.lookahead_days)
        added: list[Task] = []
        for task in self.open_tasks():
            if task.uid in unmatched or task.uid in missing:
                continue  # added before, but not on the list now; don't add again
            summary = _item_summary(task, has_due)
            description = _item_description(task)
            item_uid = pushed.get(task.uid)
            if item_uid:
                item = by_uid.get(item_uid, {})
                update: dict[str, Any] = {}
                if item.get("summary") != summary:
                    update["rename"] = summary
                if has_due and item.get("due") != task.due.isoformat():
                    update["due_date"] = task.due
                if has_desc:
                    # Keep anything the person wrote after Reap's marker.
                    merged = _merge_description(item.get("description"), description)
                    if (item.get("description") or "").strip() != merged.strip():
                        update["description"] = merged
                if update:
                    try:
                        await self._async_call(
                            "update_item",
                            {"entity_id": entity_id, "item": item_uid, **update},
                        )
                    except HomeAssistantError as err:
                        _LOGGER.warning("Could not update %s: %s", item_uid, err)
                continue
            if task.due > horizon:
                continue
            data: dict[str, Any] = {"entity_id": entity_id, "item": summary}
            if has_due:
                data["due_date"] = task.due
            if has_desc:
                data["description"] = description
            try:
                await self._async_call("add_item", data)
            except HomeAssistantError as err:
                _LOGGER.warning("Could not add %s: %s", summary, err)
                continue
            added.append(task)

        # 4. Learn the uids of the items just added.
        if added:
            try:
                items = await self._async_get_items(entity_id)
            except HomeAssistantError as err:
                _LOGGER.warning("Could not read %s: %s", entity_id, err)
                items = []
            claimed = set(pushed.values())
            for task in added:
                match = _find_new_item(
                    items, task.uid, _item_summary(task, has_due), claimed
                )
                if match:
                    pushed[task.uid] = match
                    claimed.add(match)
                else:
                    _LOGGER.warning(
                        "Added %r to %s but couldn't find it again; "
                        "it won't be added a second time",
                        task.summary, entity_id,
                    )
                    unmatched.add(task.uid)
            changed = True

        if sorted(unmatched) != self.data["unmatched"]:
            self.data["unmatched"] = sorted(unmatched)
            changed = True
        if changed:
            await self._async_save()
        self._notify()

    async def _async_leave_list(self, old_entity_id: str) -> None:
        """The target list changed: take open items off the old list.

        Done items stay where they are. The tasks themselves aren't dismissed,
        so they are added to the new list on this sync.
        """
        pushed: dict[str, str] = self.data["pushed"]
        if self.hass.states.get(old_entity_id) is not None:
            try:
                items = await self._async_get_items(old_entity_id)
            except HomeAssistantError as err:
                _LOGGER.warning("Could not read %s: %s", old_entity_id, err)
                items = []
            mine = set(pushed.values())
            open_uids = [
                item["uid"] for item in items
                if item.get("uid") in mine and item.get("status") != "completed"
            ]
            if open_uids:
                try:
                    await self._async_call(
                        "remove_item", {"entity_id": old_entity_id, "item": open_uids}
                    )
                except HomeAssistantError as err:
                    _LOGGER.warning("Could not tidy %s: %s", old_entity_id, err)
        else:
            # Reap's own list isn't loaded once another list is chosen.
            mine = set(pushed.values())
            self.data["own_items"] = [
                raw for raw in self.data["own_items"]
                if raw.get("uid") not in mine or raw.get("status") == "completed"
            ]
        pushed.clear()


def _item_summary(task: Task, has_due: bool) -> str:
    return task.summary if has_due else f"{task.summary} ({task.due:%b %-d})"


def _merge_description(existing: str | None, ours: str) -> str:
    """Reap's description, followed by the person's own text, if any.

    Reap owns everything up to and including its marker line; text after it
    is the person's and is kept.
    """
    marker = ours.rsplit("\n", 1)[-1]
    if existing and marker in existing:
        tail = existing.split(marker, 1)[1]
        if tail.strip():
            return f"{ours}{tail}"
    return ours


def _item_description(task: Task) -> str:
    desc = f"{task.description}\n\n" if task.description else ""
    return f"{desc}{MARKER_PREFIX}{task.uid}"


def _shift_l(windows: list[dict[str, Any]], shift: int) -> list[dict[str, Any]]:
    """Windows with every last-frost (L) offset moved by shift days."""
    out = []
    for window in windows:
        moved = dict(window)
        for key in ("indoor", "direct", "transplant", "cover"):
            if window.get(key):
                moved[key] = [
                    f"L{days + shift:+d}" if anchor == "L" else value
                    for value in window[key]
                    for anchor, days in [parse_offset(value)]
                ]
        out.append(moved)
    return out


def _add_years(iso: str, years: int) -> str:
    """An ISO date the given number of years later (Feb 29 becomes Feb 28)."""
    day = date.fromisoformat(str(iso))
    try:
        return day.replace(year=day.year + years).isoformat()
    except ValueError:
        return day.replace(year=day.year + years, day=28).isoformat()


def _southern(hass: HomeAssistant) -> bool | None:
    """The hemisphere from Home Assistant's home location, if it's set."""
    latitude = hass.config.latitude
    return None if not latitude else latitude < 0


def _find_new_item(
    items: list[dict[str, Any]], task_uid: str, summary: str, claimed: set[str]
) -> str | None:
    marker = f"{MARKER_PREFIX}{task_uid}"
    for item in items:
        if item.get("uid") not in claimed and marker in (item.get("description") or ""):
            return item["uid"]
    for item in reversed(items):
        if item.get("uid") not in claimed and item.get("summary") == summary:
            return item["uid"]
    return None


def _mmdd(value: str) -> str:
    """ "03-15" or "2026-03-15" as "03-15"; the year is ignored."""
    try:
        month, day = (int(p) for p in str(value).strip().split("-")[-2:])
        if (month, day) == (2, 29):
            day = 28  # dates repeat every year, so skip the leap day
        date(2001, month, day)
    except ValueError as err:
        raise PlannerError(f"Bad date {value!r}; use month-day, such as 03-15") from err
    return f"{month:02d}-{day:02d}"


def default_year(today: date | None = None) -> int:
    """Plan for next year once the main season is over."""
    today = today or dt_util.now().date()
    return today.year if today.month < 9 else today.year + 1
