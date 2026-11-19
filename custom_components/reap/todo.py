"""The planner's own to-do list, used when no existing list was chosen."""

from __future__ import annotations

from datetime import date
from typing import Any
import uuid

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .manager import GardenManager


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    manager: GardenManager = entry.runtime_data
    if manager.uses_own_list:
        async_add_entities([GardenTasksList(manager)])


def _to_item(raw: dict[str, Any]) -> TodoItem:
    due = raw.get("due")
    return TodoItem(
        uid=raw["uid"],
        summary=raw["summary"],
        status=TodoItemStatus(raw.get("status", TodoItemStatus.NEEDS_ACTION)),
        due=date.fromisoformat(due) if due else None,
        description=raw.get("description"),
    )


def _to_raw(item: TodoItem) -> dict[str, Any]:
    due = item.due
    if due is not None and not isinstance(due, date):
        due = None
    return {
        "uid": item.uid or uuid.uuid4().hex,
        "summary": item.summary or "",
        "status": str(item.status or TodoItemStatus.NEEDS_ACTION),
        "due": due.isoformat() if due else None,
        "description": item.description,
    }


class GardenTasksList(TodoListEntity):
    """Garden Tasks, a to-do list stored by the planner."""

    _attr_has_entity_name = True
    _attr_translation_key = "garden_tasks"
    _attr_should_poll = False
    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.MOVE_TODO_ITEM
        | TodoListEntityFeature.SET_DUE_DATE_ON_ITEM
        | TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM
    )

    def __init__(self, manager: GardenManager) -> None:
        self._manager = manager
        self._attr_unique_id = f"{manager.entry.entry_id}_tasks"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, manager.entry.entry_id)},
            "name": "Reap",
            "model": "Reap what you Sow",
            "entry_type": "service",
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._manager.own_entity_id = self.entity_id
        self._refresh()
        self.hass.async_create_task(self._manager.async_sync())

    def _refresh(self) -> None:
        self._attr_todo_items = [_to_item(raw) for raw in self._manager.own_items]

    async def _async_changed(self, resync: bool = True) -> None:
        await self._manager.async_save_own_items()
        self._refresh()
        self.async_write_ha_state()
        if resync:
            self.hass.async_create_task(self._manager.async_sync())

    async def async_create_todo_item(self, item: TodoItem) -> None:
        self._manager.own_items.append(_to_raw(item))
        await self._async_changed(resync=False)

    async def async_update_todo_item(self, item: TodoItem) -> None:
        items = self._manager.own_items
        for idx, raw in enumerate(items):
            if raw["uid"] == item.uid:
                items[idx] = _to_raw(item)
                break
        await self._async_changed()

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        self._manager.own_items[:] = [
            raw for raw in self._manager.own_items if raw["uid"] not in uids
        ]
        await self._async_changed()

    async def async_move_todo_item(
        self, uid: str, previous_uid: str | None = None
    ) -> None:
        items = self._manager.own_items
        moving = next((raw for raw in items if raw["uid"] == uid), None)
        if moving is None:
            return
        items.remove(moving)
        pos = 0
        if previous_uid:
            for idx, raw in enumerate(items):
                if raw["uid"] == previous_uid:
                    pos = idx + 1
                    break
        items.insert(pos, moving)
        await self._async_changed(resync=False)
