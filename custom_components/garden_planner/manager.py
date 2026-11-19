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
    Crop,
    Planting,
    PlannerError,
    Settings,
    Task,
    apply_actuals,
    generate_tasks,
    load_catalog,
)

_LOGGER = logging.getLogger(__name__)


CROP_DEFAULT_KEYS = (
    "method", "succession_days", "succession_count", "quantity", "location",
)


def _empty_data() -> dict[str, Any]:
    return {
        "plantings": {},
        "custom_crops": {},
        # task uid -> ISO date it was done
        "actuals": {},
        # task uid -> to-do item uid on the target list
        "pushed": {},
        # task uids the user deleted from the list; never re-added
        "dismissed": [],
        # items of the planner's own list, when it uses one
        "own_items": [],
        # crop key -> the user's planting defaults for that crop
        "crop_defaults": {},
    }


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
        self._syncing = False
        self._resync = False

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
        self.rebuild()

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
        crops = dict(self.builtin_crops)
        for key, raw in self.data["custom_crops"].items():
            crops[key] = Crop.from_dict(raw)
        return crops

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
                k: v for k, v in values.items() if k in CROP_DEFAULT_KEYS
            }
        await self._async_save()
        self._notify()

    def plantings(self) -> list[Planting]:
        return [Planting.from_dict(p) for p in self.data["plantings"].values()]

    def _with_method(self, fields: dict[str, Any]) -> dict[str, Any]:
        if not fields.get("method"):
            fields = {**fields, "method": self.crop_defaults(fields["crop"]).get("method")}
        return fields

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
        planting = Planting.from_dict({**fields, "id": planting_id})
        # Validates the planting before it is saved.
        generate_tasks(planting, self.crop(planting.crop), self.settings)
        self.data["plantings"][planting_id] = planting.to_dict()
        self.rebuild()
        await self._async_save()
        await self.async_sync()
        return planting, [t for t in self.tasks if t.planting_id == planting_id]

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

    async def async_add_crop(self, crop: Crop) -> None:
        self.data["custom_crops"][crop.key] = crop.to_dict()
        self.rebuild()
        await self._async_save()
        await self.async_sync()

    async def async_remove_crop(self, key: str) -> None:
        if key not in self.data["custom_crops"]:
            raise PlannerError(f"{key} is not a custom crop")
        in_use = [p.id for p in self.plantings() if p.crop == key]
        if in_use:
            raise PlannerError(
                f"{key} is used by plantings {', '.join(in_use)}; remove them first"
            )
        del self.data["custom_crops"][key]
        self.rebuild()
        await self._async_save()
        self._notify()

    def rebuild(self) -> None:
        """Regenerate every task from the plantings and recorded actual dates."""
        tasks: list[Task] = []
        settings = self.settings
        for planting in self.plantings():
            try:
                tasks.extend(
                    generate_tasks(planting, self.crop(planting.crop), settings)
                )
            except PlannerError as err:
                _LOGGER.warning("Skipping planting %s: %s", planting.id, err)
        self.tasks = apply_actuals(tasks, self.data["actuals"])
        self._notify()

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
        by_uid = {item.get("uid"): item for item in items if item.get("uid")}
        pushed: dict[str, str] = self.data["pushed"]
        actuals: dict[str, str] = self.data["actuals"]
        dismissed: set[str] = set(self.data["dismissed"])
        today = dt_util.now().date()
        changed = False

        # 1. Read back what happened on the list.
        for task_uid, item_uid in list(pushed.items()):
            item = by_uid.get(item_uid)
            if item is None:
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

        if changed:
            self.data["dismissed"] = sorted(dismissed)
            self.rebuild()

        # 2. Remove open items whose planting is gone.
        current = {t.uid for t in self.tasks}
        stale = [uid for uid in pushed if uid not in current]
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
            summary = task.summary if has_due else f"{task.summary} ({task.due:%b %-d})"
            item_uid = pushed.get(task.uid)
            if item_uid:
                item = by_uid.get(item_uid, {})
                update: dict[str, Any] = {}
                if item.get("summary") != summary:
                    update["rename"] = summary
                if has_due and item.get("due") != task.due.isoformat():
                    update["due_date"] = task.due
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
                desc = f"{task.description}\n\n" if task.description else ""
                data["description"] = f"{desc}{MARKER_PREFIX}{task.uid}"
            try:
                await self._async_call("add_item", data)
            except HomeAssistantError as err:
                _LOGGER.warning("Could not add %s: %s", summary, err)
                continue
            added.append(task)

        # 4. Learn the uids of the items just added.
        if added:
            items = await self._async_get_items(entity_id)
            claimed = set(pushed.values())
            for task in added:
                summary = (
                    task.summary if has_due else f"{task.summary} ({task.due:%b %-d})"
                )
                match = _find_new_item(items, task.uid, summary, claimed)
                if match:
                    pushed[task.uid] = match
                    claimed.add(match)
            changed = True

        if changed:
            await self._async_save()
        self._notify()


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


def default_year(today: date | None = None) -> int:
    """Plan for next year once the main season is over."""
    today = today or dt_util.now().date()
    return today.year if today.month < 9 else today.year + 1
