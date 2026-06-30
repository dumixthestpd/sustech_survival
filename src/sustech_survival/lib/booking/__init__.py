"""
sustech_survival.lib.booking — IC library booking (research rooms, meeting rooms, etc.)

Public API:
    from sustech_survival.lib.booking import (
        LibBookingClient, LibBookingError, lib_booking,
        Room, Lab, LabWithRooms, CampusGroup, Reservation, UserInfo,
    )

Singleton:
    lib_booking() — returns a LibBookingClient. Auto-auths via LibBookingAuth.

Schema (all live-parsed via `from_api()` classmethods):
    Room, Lab, LabWithRooms, CampusGroup, RoomIdleCategory
    Reservation, UserInfo
    build_reservation_payload(...) — Python API for the create payload

Auth: `sustech_survival.lib.booking.auth.LibBookingAuth`. The 6-hop CAS +
authcenter handshake is fully reverse-engineered; no Playwright needed.

⚠️  **Do not** confuse with `sustech_survival.booking` (ehall 35-venue
booking on `booking.sustech.edu.cn`) — different host, different auth,
different module. The two `booking`s live under different parents and
share no auth.
"""
from __future__ import annotations

from .auth import (
    BOOKING_BASE,
    BOOKING_API,
    LibBookingAuth,
    OFF_CAMPUS_BODY,
    OFF_CAMPUS_HINT,
)
from .client import (
    AUTH_ERROR_MESSAGES,
    DEFAULT_CLASS_KIND,
    LibBookingClient,
    LibBookingError,
    LibBookingPolicyError,
    PolicyWarning,
    lib_booking,
    validate_against_policy,
    validate_cancellation_timing,
)
from .schema import (
    CampusGroup,
    Lab,
    LabWithRooms,
    OpenTime,
    Reservation,
    Room,
    RoomIdleCategory,
    UserInfo,
    build_reservation_payload,
    format_ic_dt,
)


__all__ = [
    # Client
    "LibBookingClient", "LibBookingError", "lib_booking",
    "DEFAULT_CLASS_KIND", "AUTH_ERROR_MESSAGES",
    # Policy
    "LibBookingPolicyError", "PolicyWarning",
    "validate_against_policy", "validate_cancellation_timing",
    # Auth
    "LibBookingAuth", "BOOKING_BASE", "BOOKING_API",
    "OFF_CAMPUS_BODY", "OFF_CAMPUS_HINT",
    # Schema
    "Room", "Lab", "LabWithRooms", "CampusGroup", "OpenTime",
    "RoomIdleCategory", "Reservation", "UserInfo",
    "build_reservation_payload", "format_ic_dt",
]
