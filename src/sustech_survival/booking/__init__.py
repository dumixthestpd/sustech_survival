"""
sustech_survival.booking — Live client for the ehall 场地预约 sub-app.

ONE client class, TWO record types, ZERO local data.

Public API:
    from sustech_survival.booking import booking, BookingClient, Room, Meeting, MyMeeting

Singleton:
    booking() — returns a BookingClient. Logs in automatically via BookingAuth.

Schema (all live-parsed via `from_api()` classmethods):
    Room      — venue (meeting room, study room, gym, etc.)
    Meeting   — a booked slot (for create/cancel/update operations)

API endpoints used (see `references/ehall-booking-venue-2026-06-15.md`):
    GetMeetingRoomAllByCondition   list rooms (paginated)
    GetMyMeetings                   list my bookings (paginated)
    AddMeeting                      create a booking
    UpdateMeeting                   modify a booking
    CancelMeeting                   cancel a booking
    GetMeetingCalendar              schedule view

"Auth: handled by `sustech_survival.sso.authlib.booking.BookingAuth`. The
singleton auto-auths on first call. Session + token are in-memory only
(next to the package's convention: no disk-persisted session.json)."
"""
from __future__ import annotations

from .booking import (
    BookingClient, BookingError,
    booking,
)
from .schema import Room, Meeting, MyMeeting


__all__ = [
    # Client
    "BookingClient", "BookingError", "booking",
    # Schema
    "Room", "Meeting", "MyMeeting",
]
