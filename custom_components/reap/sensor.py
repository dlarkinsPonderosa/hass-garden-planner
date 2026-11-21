"""Summary sensors for Reap."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .manager import GardenManager
from .planner import Task, is_southern, planting_timeline

MAX_LISTED = 25
# Open tasks listed per planting on the plantings sensor. Every task of every
# planting would go to each open dashboard on every change.
MAX_PLANTING_TASKS = 10


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    manager: GardenManager = entry.runtime_data
    async_add_entities(
        [
            NextTaskSensor(manager),
            DueThisWeekSensor(manager),
            OverdueSensor(manager),
            PlantingsSensor(manager),
        ]
    )


def _task_attr(manager: GardenManager, task: Task) -> dict[str, Any]:
    planting = manager.data["plantings"].get(task.planting_id, {})
    return {
        "summary": task.summary,
        "due": task.due.isoformat(),
        "kind": task.kind,
        "crop": planting.get("crop"),
        "method": planting.get("method"),
        "planting_id": task.planting_id,
        "icon": task.icon,
        "crop_icon": task.crop_icon,
    }


class GardenSensor(SensorEntity):
    """Base sensor that refreshes when the planner changes."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, manager: GardenManager, key: str) -> None:
        self.manager = manager
        self._attr_translation_key = key
        self._attr_unique_id = f"{manager.entry.entry_id}_{key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, manager.entry.entry_id)},
            "name": "Reap",
            "model": "Reap what you Sow",
            "entry_type": "service",
        }

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.manager.add_listener(self._handle_update))
        # Dates roll over at midnight even when nothing else changes.
        self.async_on_remove(
            async_track_time_change(
                self.hass, self._handle_midnight, hour=0, minute=0, second=5
            )
        )
        self._update_from_manager()

    @callback
    def _handle_midnight(self, _now: Any) -> None:
        self._handle_update()

    @callback
    def _handle_update(self) -> None:
        self._update_from_manager()
        self.async_write_ha_state()

    def _update_from_manager(self) -> None:
        raise NotImplementedError


class NextTaskSensor(GardenSensor):
    """The next open task."""

    _attr_icon = "mdi:sprout"

    def __init__(self, manager: GardenManager) -> None:
        super().__init__(manager, "next_task")

    def _update_from_manager(self) -> None:
        tasks = self.manager.open_tasks()
        if not tasks:
            self._attr_icon = "mdi:sprout"
            self._attr_native_value = None
            self._attr_extra_state_attributes = {}
            return
        task = tasks[0]
        self._attr_icon = task.crop_icon
        self._attr_native_value = task.summary[:255]
        self._attr_extra_state_attributes = _task_attr(self.manager, task)


class DueThisWeekSensor(GardenSensor):
    """Open tasks due in the next 7 days, including overdue ones."""

    _attr_icon = "mdi:calendar-week"

    def __init__(self, manager: GardenManager) -> None:
        super().__init__(manager, "due_this_week")

    def _update_from_manager(self) -> None:
        horizon = dt_util.now().date() + timedelta(days=7)
        tasks = [t for t in self.manager.open_tasks() if t.due <= horizon]
        self._attr_native_value = len(tasks)
        self._attr_extra_state_attributes = {
            "tasks": [_task_attr(self.manager, t) for t in tasks[:MAX_LISTED]]
        }


class OverdueSensor(GardenSensor):
    """Open tasks past their due date."""

    _attr_icon = "mdi:alert-circle-outline"

    def __init__(self, manager: GardenManager) -> None:
        super().__init__(manager, "overdue")

    def _update_from_manager(self) -> None:
        today = dt_util.now().date()
        tasks = [t for t in self.manager.open_tasks() if t.due < today]
        self._attr_native_value = len(tasks)
        self._attr_extra_state_attributes = {
            "tasks": [_task_attr(self.manager, t) for t in tasks[:MAX_LISTED]]
        }


class PlantingsSensor(GardenSensor):
    """Every planting, with its next open tasks."""

    _attr_icon = "mdi:flower"
    _unrecorded_attributes = frozenset({"plantings", "locations", "problems"})

    def __init__(self, manager: GardenManager) -> None:
        super().__init__(manager, "plantings")

    def _update_from_manager(self) -> None:
        crops = self.manager.crops
        dismissed = set(self.manager.data["dismissed"])
        planted_out = self.manager.planted_out_ids()
        plantings = []
        for planting in self.manager.plantings():
            crop = crops.get(planting.crop)
            tasks = [t for t in self.manager.tasks if t.planting_id == planting.id]
            open_tasks = [t for t in tasks if not t.done_on]
            plantings.append(
                {
                    **planting.to_dict(),
                    "crop_name": crop.name if crop else planting.crop,
                    # Where it is now: the start location until it's planted out.
                    "current_location": self.manager.current_location(planting, planted_out),
                    "icon": crop.icon if crop else "mdi:sprout",
                    "sowings": len({t.succession for t in tasks}),
                    "task_count": len(tasks),
                    "open_count": len(open_tasks),
                    "tasks": [t.to_dict() for t in open_tasks[:MAX_PLANTING_TASKS]],
                    # Phase date ranges for the planner card's season chart.
                    # Tasks deleted from the to-do list aren't planned any more.
                    "timeline": (
                        planting_timeline([t for t in tasks if t.uid not in dismissed], crop)
                        if crop else None
                    ),
                    # Why it can't be scheduled right now, if it can't.
                    "problem": self.manager.problems.get(planting.id),
                }
            )
        self._attr_native_value = len(plantings)
        self._attr_extra_state_attributes = {
            "plantings": plantings,
            "locations": self.manager.locations(),
            # The planner card runs a southern growing year July to June.
            "southern": is_southern(self.manager.settings),
            "problems": [
                {"planting_id": pid, "problem": text}
                for pid, text in self.manager.problems.items()
            ],
        }
