"""
sustech_survival.classroom — TIS 全校课表 reverse view.

ONE client class wrapping the campus schedule API. ZERO local data — every
call hits the live TIS server (with on-disk cache for fast re-query).

The "trick": `Xsxktz/queryRwxxcxList` returns 1499 courses per semester, but
the API's `skdd`/`jsz` location fields are NEVER populated. The real schedule
data is embedded as HTML inside the `kcxx` field as strings like
"1-15周,星期一第3-4节 一教324". We parse that to recover (room × week × day ×
period) occupancy.

Public API:
    from sustech_survival.classroom import classroom, ScheduleSlot, Room

Singleton:
    classroom() — returns a ClassroomOccupancy. Logs in via TISAuth on first
    call. Uses a 1-hour disk cache to avoid hammering the 30s-paginated API.

Schema (all live-parsed via `from_api()` classmethods):
    Room       — a physical classroom (with capacity, building, GPS if avail)
    ScheduleSlot — one (course, week, day, period-range) tuple in a room

Auth: handled by `sustech_survival.sso.TISAuth`.
"""
from __future__ import annotations

from .classroom import ClassroomOccupancy, classroom
from .schema import Room, ScheduleSlot, parse_kcxx_slot, expand_weeks


__all__ = [
    "ClassroomOccupancy", "classroom",
    "Room", "ScheduleSlot",
    "parse_kcxx_slot", "expand_weeks",
]
