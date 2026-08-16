"""
sustech_survival.tis.classroom — Classroom inquiry + venue borrowing (场地借用).

TWO sub-modules:

1. **Inquiry** (查空教室) — room catalog, schedule occupancy, live per-room
   schedule (incl. borrowings). Two TIS data sources:
   - `Xsxktz/queryRwxxcxList`: the public course catalog.
   - `cdkb/querycdkbList`: per-room schedule (courses + borrowings).

2. **Booking** (借用 cdjy) — venue borrowing application form building
   and submission via `addChangDiJieYongShenQing`.

Public API::

    # Inquiry
    from sustech_survival.tis.classroom import (
        classroom, ClassroomOccupancy,
        live, LiveOccupancyClient,
        Room, ScheduleSlot, RoomScheduleEntry,
    )

    # Booking
    from sustech_survival.tis.classroom.booking import (
        venue_borrow, VenueBorrowClient, BorrowError,
    )

Auth: both sub-modules use `sustech_survival.sso.TISAuth`.
"""
from __future__ import annotations

# -- Inquiry (查空教室) ----------------------------------------------------
from .classroom import ClassroomOccupancy, classroom, normalize_room_name, BUILDING_ALIASES  # noqa: F401
from .live import (  # noqa: F401
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
from .schema import Room, ScheduleSlot, parse_kcxx_slot, expand_weeks  # noqa: F401

# -- Booking (借用 cdjy) ----------------------------------------------------
from . import booking as booking  # noqa: F401

__all__ = [
    # Inquiry
    "ClassroomOccupancy", "classroom",
    "LiveOccupancyClient", "live",
    "Room", "ScheduleSlot", "RoomScheduleEntry",
    "parse_kcxx_slot", "expand_weeks",
    "parse_sksj", "parse_key",
    "BUILDING_ALIASES", "normalize_room_name",
    "current_period", "current_semester", "current_week",
    "current_weekday_and_period",
    # Booking
    "booking",
]
