"""
sustech_survival.classroom — TIS 全校课表 reverse view + live occupancy.

ONE client class wrapping two TIS data sources:

1. **Catalog** (`Xsxktz/queryRwxxcxList`): the public course catalog.
   Parses `kcxx` HTML blobs to recover (room × week × day × period)
   occupancy. Misses all borrowings (TA tutor sessions, study groups,
   recruitment events, etc.).

2. **Live schedule** (`cdkb/querycdkbList`): the per-room schedule table
   that includes BOTH registered courses AND borrowings (借用).
   Source for true live occupancy. See `live.py` for the per-room
   client.

Public API:
    from sustech_survival.classroom import classroom, ScheduleSlot, Room
    from sustech_survival.classroom.live import LiveOccupancyClient

Singleton:
    classroom() — returns a ClassroomOccupancy. Logs in via TISAuth on
    first call. Uses a 1-hour disk cache per data source.

Schema (all live-parsed via `from_api()` classmethods):
    Room            — a physical classroom (with capacity, building, GPS if avail)
    ScheduleSlot    — one (course, week, day, period-range) tuple in a room
    RoomScheduleEntry — one (course OR borrowing, week, day, period) entry
                       (from cdkb/querycdkbList, see live.py)

Auth: handled by `sustech_survival.sso.TISAuth`.
"""
from __future__ import annotations

from .classroom import ClassroomOccupancy, classroom, normalize_room_name, BUILDING_ALIASES
from .live import (
    LiveOccupancyClient,
    RoomScheduleEntry,
    _first_full_week_start,
    _expand_week_pattern,
    current_period,
    current_semester,
    current_week,
    current_weekday_and_period,
    live,
)
from .schema import Room, ScheduleSlot, parse_kcxx_slot, expand_weeks


__all__ = [
    # Client
    "ClassroomOccupancy", "classroom",
    "LiveOccupancyClient", "live",
    # Schema
    "Room", "ScheduleSlot", "RoomScheduleEntry",
    # Parsers
    "parse_kcxx_slot", "expand_weeks",
    "parse_sksj", "parse_key",
    # Building name aliases
    "BUILDING_ALIASES", "normalize_room_name",
    # Time helpers
    "current_period", "current_semester", "current_week",
    "current_weekday_and_period",
] 
