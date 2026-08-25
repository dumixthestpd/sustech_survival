"""
sustech_survival.booking.booking — Live client for the ehall 场地预约 sub-app.

ONE class. ALL operations. ZERO local data (every call hits the live site).

Architecture mirrors `sustech_survival.faculty.FacultyClient` and
`sustech_survival.pms.PMSClient`:

    BookingClient                    ← one client, all the methods
        .whoami()                          → GetUserProfile echo
        .rooms(...)                        → GetMeetingRoomAllByCondition
        .room_by_id(id)                    → helper over rooms()
        .my_meetings(...)                  → GetMyMeetings (paged)
        .add_meeting(room_id, start, end, title, ...)  → AddMeeting
        .update_meeting(...)               → UpdateMeeting
        .cancel_meeting(meeting_id)        → CancelMeeting

Schema (`Room`, `Meeting`, `MyMeeting`) lives in `schema.py` with classmethod
`from_api()` parsers.

Auth is handled separately by `sustech_survival.sso.authlib.booking.BookingAuth`.
This class is auth-agnostic — pass it any `requests.Session` that has the
Authorization header set.

Auto-relogin: when the server returns "Authorization is NULL" / a 401/403,
the client transparently re-runs BookingAuth.login_password() and retries
the call once. Failures propagate as BookingError.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Iterable, List, Optional

import requests

from .schema import Room, Meeting, MyMeeting


BOOKING_BASE = "https://booking.sustech.edu.cn"
BOOKING_API = f"{BOOKING_BASE}/api/SystemApi"

# Off-campus signal: SUSTech firewall returns the same plain-text body on
# 403 before any auth runs across all internal services. Canonical
# detection lives in ``sustech_survival.sso._offcampus`` (PMS + booking +
# future modules share it).
from sustech_survival.sso._offcampus import (
    OFF_CAMPUS_BODY,
    looks_off_campus as _looks_off_campus,
    off_campus_hint,
)

OFF_CAMPUS_HINT = off_campus_hint("Booking")

# Server-side auth-error messages that should trigger an auto-relogin.
# Captured during the 2026-06-15 probe.
AUTH_ERROR_MESSAGES = (
    "Authorization is NULL",
    "Authorization is invalid",
    "未登录",
    "请先登录",
)


class BookingError(RuntimeError):
    """Any failure from the Booking API or its auth flow."""


def _looks_auth_error(body: dict) -> bool:
    if body.get("IsSuccess"):
        return False
    msg = body.get("Message") or ""
    return any(token in msg for token in AUTH_ERROR_MESSAGES)


class BookingClient:
    """One client object for the ehall 场地预约 sub-app.

    Encapsulates session + all API operations. Construct with a session that
    has the `Authorization` header set (use `BookingAuth` to obtain one).
    All operations are live HTTP calls — no local cache.
    """

    BASE_URL = BOOKING_BASE
    API_BASE = BOOKING_API

    # -- Construction --------------------------------------------------------

    def __init__(self, session: requests.Session, *, _auth=None):
        self.s = session
        # Optional handle to the BookingAuth singleton so we can auto-relogin
        # on auth-error responses. If None, errors propagate without retry.
        self._auth = _auth

    # -- Internal: API call + auth-error retry -------------------------------

    def _call(self, method: str, data: Optional[dict] = None,
              *, _is_retry: bool = False) -> dict:
        """POST to /api/SystemApi/{method} with the standard envelope.

        Auto-relogin-and-retry once on auth errors (when an auth handle was
        provided at construction time).
        """
        return self._call_raw(method, data or {}, _is_retry=_is_retry)

    def _call_raw(self, method: str, data: dict, *, _is_retry: bool = False) -> dict:
        """Same as _call but without re-wrapping `data` in a Data envelope."""
        body = {
            "MessageType": 1002,
            "MessageID": str(uuid.uuid4()),
            "Data": data,
        }
        r = self.s.post(f"{self.API_BASE}/{method}", json=body, timeout=15)

        if _looks_off_campus(r):
            raise BookingError(OFF_CAMPUS_HINT)

        try:
            payload = r.json()
        except Exception as e:
            raise BookingError(
                f"Booking API returned non-JSON for {method}: "
                f"HTTP {r.status_code}, {r.text[:200]}"
            ) from e

        if _looks_auth_error(payload) and self._auth and not _is_retry:
            try:
                username = self._auth.username
                password = self._auth.password
                self._auth.login_password(username, password)
                fresh = self._auth._api_session()
                self.s.headers.update(dict(fresh.headers))
                self.s.cookies.update(fresh.cookies)
            except Exception as e:
                raise BookingError(f"Auto-relogin failed: {e}") from e
            return self._call_raw(method, data, _is_retry=True)

        if not payload.get("IsSuccess"):
            raise BookingError(
                f"Booking API error on {method}: "
                f"code={payload.get('ErrorCode')} msg={payload.get('Message')!r}"
            )
        return payload

    # -- User ----------------------------------------------------------------

    def whoami(self) -> dict:
        """Return the cached user profile from the last successful login.

        Populated at login from GetUserProfile's Data field. Returns the raw
        dict (contains name, sid, email, groups, role actions, etc.).
        """
        user = getattr(self._auth, "_user_info", {}) if self._auth else {}
        return user or {}

    # -- Rooms (场地) --------------------------------------------------------

    def rooms(self, *, keyword: str = "", page: int = 1, page_size: int = 100) -> List[Room]:
        """List rooms. `keyword` is filtered CLIENT-side (case-insensitive
        substring match against name, id, type, dept). The server's own
        filter param is not reliable — keeping it local avoids surprises.

        Default page_size=100 — all 35 rooms fit in one page.
        """
        payload = self._call_raw("GetMeetingRoomAllByCondition", {
            "page": page,
            "rows": page_size,
        })
        rows = (payload.get("Data") or {}).get("rows") or []
        rooms = [Room.from_api(r) for r in rows]
        if keyword:
            kw = keyword.lower()
            rooms = [
                r for r in rooms
                if kw in r.name.lower()
                or kw in r.id.lower()
                or kw in r.room_type.lower()
                or kw in r.dept_name.lower()
                or kw in r.location.lower()
            ]
        return rooms

    def room_by_id(self, room_id: str) -> Optional[Room]:
        """Return the room matching `room_id` (case-insensitive), or None."""
        rid = room_id.strip().lower()
        for room in self.rooms():
            if room.id.lower() == rid:
                return room
        return None

    # -- My meetings (我的预约) ----------------------------------------------

    def my_meetings(self, *, page: int = 1, page_size: int = 50) -> List[MyMeeting]:
        """List the current user's bookings, paged."""
        payload = self._call_raw("GetMyMeetings", {
            "page": page,
            "rows": page_size,
        })
        rows = (payload.get("Data") or {}).get("rows") or []
        return [MyMeeting.from_api(r) for r in rows]

    # -- Create / update / cancel -------------------------------------------

    def add_meeting(
        self,
        room_id: str,
        start: datetime,
        end: datetime,
        title: str,
        *,
        participants: int = 1,
        description: str = "",
    ) -> dict:
        """Create a new booking.

        `room_id` must match an existing Room.id (e.g. "ZC02").
        `start`/`end` are naive datetimes (server treats as local SUSTech time).
        Returns the raw response Data dict (contains the new meeting's ID).
        """
        if end <= start:
            raise BookingError(f"end ({end}) must be after start ({start}).")
        if (end - start) > timedelta(hours=8):
            raise BookingError("Booking duration cannot exceed 8 hours.")
        if not title.strip():
            raise BookingError("Title is required.")

        payload = self._call_raw("AddMeeting", {
            "MeetingRoomID": room_id,
            "MeetingName": title.strip(),
            "MeetingStart": start.strftime("%Y-%m-%dT%H:%M:%S"),
            "MeetingEnd": end.strftime("%Y-%m-%dT%H:%M:%S"),
            "NumberOfParticipants": participants,
            "MeetingDesc": description,
        })
        return payload.get("Data") or {}

    def cancel_meeting(self, meeting_id: str) -> dict:
        """Cancel a booking by ID."""
        payload = self._call_raw("CancelMeeting", {"MeetingID": meeting_id})
        return payload.get("Data") or {}


# -- Module-level singleton --------------------------------------------------


def booking():
    """Return a singleton BookingClient. Auto-logs in on first call.

    Use this from a script:
        from sustech_survival.booking import booking
        client = booking()
        for r in client.rooms():
            print(r.name, r.capacity)
    """
    from sustech_survival.sso.authlib.booking import _auth as _booking_auth
    _booking_auth.ensure()
    sess = _booking_auth._api_session()
    return BookingClient(sess, _auth=_booking_auth)
