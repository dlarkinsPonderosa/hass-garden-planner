"""Constants for Reap."""

from __future__ import annotations

DOMAIN = "reap"

CONF_TODO_ENTITY = "todo_entity"
CONF_LAST_FROST = "last_frost"
CONF_FIRST_FROST = "first_frost"
CONF_WARM_LAST_FROST = "warm_last_frost"
CONF_OFFSET_DAYS = "offset_days"
CONF_ZONE = "zone"
CONF_PROFILE = "profile"
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
    # Warm crops in Victoria keep the chart's April 1 frost date, since the
    # early last frost there doesn't mean warm soil.
    CONF_WARM_LAST_FROST: "04-01",
    CONF_OFFSET_DAYS: 0,
    CONF_PROFILE: "cool_spring",
    CONF_GREENHOUSE_SPRING_WEEKS: 4,
    CONF_GREENHOUSE_FALL_WEEKS: 4,
    CONF_HARDEN_OFF_DAYS: 7,
    CONF_GREENHOUSE_HARDEN_OFF_DAYS: 3,
    CONF_LOOKAHEAD_DAYS: 30,
}

STORAGE_VERSION = 1
SYNC_INTERVAL_MINUTES = 15

# Added to a task's description so the planner can find it on a shared list.
MARKER_PREFIX = "reap:"

SIGNAL_UPDATED = f"{DOMAIN}_updated"

ZONE_VICTORIA = "victoria"
ZONE_CUSTOM = "custom"

# Rough average last spring and first fall frost dates by USDA hardiness zone.
# Zones measure winter cold, not season length, so these are only a starting
# point: local frost dates are much better.
ZONE_FROST_DATES: dict[str, tuple[str, str]] = {
    "2": ("05-25", "09-05"),
    "3": ("05-15", "09-15"),
    "4": ("05-10", "09-25"),
    "5": ("04-30", "10-10"),
    "6": ("04-20", "10-20"),
    "7": ("04-10", "10-30"),
    "8": ("03-25", "11-10"),
    "9": ("03-01", "11-30"),
    "10": ("02-01", "12-15"),
}

PROFILE_COOL_SPRING = "cool_spring"
PROFILE_CONTINENTAL = "continental"
PROFILE_ATLANTIC = "atlantic"
PROFILES = (PROFILE_COOL_SPRING, PROFILE_CONTINENTAL, PROFILE_ATLANTIC)
