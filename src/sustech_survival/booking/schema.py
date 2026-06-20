"""
sustech_survival.booking.schema — Dataclasses for the ehall 场地预约 sub-app.

Mirrors the JSON shapes returned by `booking.sustech.edu.cn/api/SystemApi/*`.
All parsers are classmethods — never expose loose `parse_*` functions.

Field name conventions: API uses PascalCase / camelCase (e.g. MeetingRoomID,
CapacityNumber). We translate to snake_case at the parser boundary so the
rest of the codebase never sees raw API field names.

Quirks worth knowing:
- Two id patterns coexist: short codes (ZC02) for legacy rooms, UUIDs for
  newer rooms. Always compare with `==` after normalizing to lower.
- `CanBookStartTime` / `CanBookEndTime` carry a TIME-only value but use the
  full ISO datetime format ("1970-01-01T08:00:00"). The 1970 epoch is a
  server-side convention meaning "always" — we strip it to just HH:MM:SS.
- `MeetingRoomEquipments` and `MeetingRoomManagers` come nested; we flatten
  them to lists of strings.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


# ── Time-only string helper ──────────────────────────────────────────────────

_TIME_RE = re.compile(r"T(\d{2}:\d{2}:\d{2})")


def _time_only(s: Optional[str]) -> str:
    """Extract HH:MM:SS from "1970-01-01T08:00:00" or pass through "08:00:00"."""
    if not s:
        return ""
    m = _TIME_RE.search(s)
    return m.group(1) if m else s


def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    """Parse a meeting datetime string. Returns None on failure."""
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f",
                "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s, fmt)
        except (ValueError, TypeError):
            continue
    return None


# ── Room (场地 / 会议室) ──────────────────────────────────────────────────────


@dataclass
class Room:
    """A bookable venue (meeting room, study room, gym in 书院).

    Source: GetMeetingRoomAllByCondition. 35 rooms in current SUSTech
    catalog (verified 2026-06-15).
    """
    id: str                         # MeetingRoomID — short code OR uuid
    name: str                       # MeetingRoomName — Chinese display name
    room_type: str                  # MeetingRoomType — "会议室", "健身房", etc.
    capacity: int                   # CapacityNumber — max occupants
    location: str                   # MeetingRoomLocal — "湖畔公寓2栋1层102"
    is_available: bool              # IsAvailable
    needs_approval: bool            # IsApproval — manager signoff required
    bookable_days_ahead: int        # NumberOfDaysAhead — typically 100
    book_start: str                 # CanBookStartTime — HH:MM:SS only ("08:00:00")
    book_end: str                   # CanBookEndTime   — HH:MM:SS only ("22:00:00")
    longitude: float                # GPS
    latitude: float                 # GPS
    dept_name: str                  # DeptName — owning department
    equipment: List[str] = field(default_factory=list)
    managers: List[str] = field(default_factory=list)
    register_distance_m: int = 0    # RegisterDistance — attendance geo-fence

    @classmethod
    def from_api(cls, raw: dict) -> "Room":
        return cls(
            id=str(raw.get("MeetingRoomID") or ""),
            name=raw.get("MeetingRoomName") or "",
            room_type=raw.get("MeetingRoomType") or "",
            capacity=int(raw.get("CapacityNumber") or 0),
            location=raw.get("MeetingRoomLocal") or "",
            is_available=bool(raw.get("IsAvailable", False)),
            needs_approval=bool(raw.get("IsApproval", False)),
            bookable_days_ahead=int(raw.get("NumberOfDaysAhead") or 0),
            book_start=_time_only(raw.get("CanBookStartTime")),
            book_end=_time_only(raw.get("CanBookEndTime")),
            longitude=float(raw.get("Longitude") or 0.0),
            latitude=float(raw.get("Latitude") or 0.0),
            dept_name=raw.get("DeptName") or "",
            equipment=[
                (e.get("EquipmentName") or "")
                for e in (raw.get("MeetingRoomEquipments") or [])
                if e.get("EquipmentName")
            ],
            managers=[
                ((m.get("UserInfoModel") or {}).get("XM") or "")
                for m in (raw.get("MeetingRoomManagers") or [])
                if (m.get("UserInfoModel") or {}).get("XM")
            ],
            register_distance_m=int(raw.get("RegisterDistance") or 0),
        )

    def bookable_hours_str(self) -> str:
        """Pretty HH:MM-HH:MM string, or 'unavailable'."""
        if self.book_start and self.book_end:
            s = self.book_start[:5]
            e = self.book_end[:5]
            return f"{s}-{e}"
        return "n/a"


# ── Meeting (预约记录) ────────────────────────────────────────────────────────


@dataclass
class Meeting:
    """A meeting (booking) payload — used for both reading existing bookings
    and creating new ones.

    For create, only `room_id`, `title`, `start_at`, `end_at` are required;
    the API fills the rest from the user's profile + the room.
    """
    id: str = ""
    room_id: str = ""
    title: str = ""
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    user_name: str = ""
    user_id: str = ""
    status: str = ""
    meeting_type: str = ""
    participants: int = 0
    description: str = ""

    @classmethod
    def from_api(cls, raw: dict) -> "Meeting":
        return cls(
            id=str(raw.get("MeetingID") or raw.get("ID") or ""),
            room_id=str(raw.get("MeetingRoomID") or ""),
            title=raw.get("MeetingName") or raw.get("Title") or "",
            start_at=_parse_dt(raw.get("StartTime") or raw.get("MeetingStart")),
            end_at=_parse_dt(raw.get("EndTime") or raw.get("MeetingEnd")),
            user_name=raw.get("UserName") or raw.get("XM") or "",
            user_id=str(raw.get("UserID") or raw.get("YHID") or ""),
            status=raw.get("Status") or raw.get("MeetingStatus") or "",
            meeting_type=raw.get("MeetingType") or "",
            participants=int(raw.get("Participants") or raw.get("NumberOfParticipants") or 0),
            description=raw.get("MeetingDesc") or raw.get("Description") or "",
        )


@dataclass
class MyMeeting:
    """An entry from GetMyMeetings — slightly different shape than the
    create/update payload.

    Includes `unread` flag and the `room_name` denormalized for convenience.
    """
    id: str
    room_id: str
    room_name: str
    title: str
    start_at: Optional[datetime]
    end_at: Optional[datetime]
    status: str
    unread: bool = False

    @classmethod
    def from_api(cls, raw: dict) -> "MyMeeting":
        return cls(
            id=str(raw.get("MeetingID") or raw.get("ID") or ""),
            room_id=str(raw.get("MeetingRoomID") or ""),
            room_name=raw.get("MeetingRoomName") or "",
            title=raw.get("MeetingName") or raw.get("Title") or "",
            start_at=_parse_dt(raw.get("StartTime") or raw.get("MeetingStart")),
            end_at=_parse_dt(raw.get("EndTime") or raw.get("MeetingEnd")),
            status=raw.get("Status") or raw.get("MeetingStatus") or "",
            unread=bool(raw.get("IsUnread") or raw.get("Unread") or False),
        )
