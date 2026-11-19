"""Constants for Garden Planner."""

from __future__ import annotations

DOMAIN = "garden_planner"

CONF_TODO_ENTITY = "todo_entity"
CONF_LAST_FROST = "last_frost"
CONF_FIRST_FROST = "first_frost"
CONF_SHIFT_WINDOWS = "shift_windows"
CONF_SHIFT_FROST_TENDER = "shift_frost_tender"
CONF_GREENHOUSE_SPRING_WEEKS = "greenhouse_spring_weeks"
CONF_GREENHOUSE_FALL_WEEKS = "greenhouse_fall_weeks"
CONF_HARDEN_OFF_DAYS = "harden_off_days"
CONF_GREENHOUSE_HARDEN_OFF_DAYS = "greenhouse_harden_off_days"
CONF_LOOKAHEAD_DAYS = "lookahead_days"

NEW_LIST = "__new__"

DEFAULTS = {
    CONF_TODO_ENTITY: NEW_LIST,
    # Victoria, from the South Coastal BC Vegetable Planting Guide.
    CONF_LAST_FROST: "03-06",
    CONF_FIRST_FROST: "11-16",
    CONF_SHIFT_WINDOWS: True,
    CONF_SHIFT_FROST_TENDER: False,
    CONF_GREENHOUSE_SPRING_WEEKS: 4,
    CONF_GREENHOUSE_FALL_WEEKS: 4,
    CONF_HARDEN_OFF_DAYS: 7,
    CONF_GREENHOUSE_HARDEN_OFF_DAYS: 3,
    CONF_LOOKAHEAD_DAYS: 30,
}

STORAGE_VERSION = 1
SYNC_INTERVAL_MINUTES = 15

# Added to a task's description so the planner can find it on a shared list.
MARKER_PREFIX = "garden-planner:"

SIGNAL_UPDATED = f"{DOMAIN}_updated"
