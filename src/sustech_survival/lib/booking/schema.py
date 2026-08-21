"""
sustech_survival.lib.booking.schema — Dataclasses for IC library booking.

All parsers are classmethods — never expose loose `parse_*` functions.

Field name conventions: API uses PascalCase / camelCase (e.g. devId,
labId, openStartTime). We translate to snake_case at the parser boundary
so the rest of the codebase never sees raw API field names.

Quirks worth knowing:
- Date format in reservation create is "YYYY/MM/DD HH:mm:00" (slash +
  0-padded seconds). NOT ISO, NOT Unix timestamp. The server echoes
  these as ISO timestamps (`YYYY-MM-DD HH:mm:ss`).
- Two id types: small ints for `devId` (room) and `labId` (lab). No
  UUIDs in the read API.
- `openTimes` come nested as `[{openStartTime, openEndTime, openLimit}]`
  with multiple entries per room (a room may be open in multiple windows
  per day, e.g. morning + afternoon).
- `resvInfos` is `null` when the room is free, populated when reserved.
  Field shape NOT verified — wire-payload probe needed.
- `accNo` is the user's account number (SUSTech-specific), NOT their
  student ID. The student ID is `pid` (Personal ID).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import List, Optional


# -- Time-only string helpers -------------------------------------------------

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:\.\d+)?$"
)


def _parse_dt(s) -> Optional[datetime]:
    """Parse an ISO-ish datetime string OR Unix milliseconds (int).

    The IC booking API returns:
      - Strings: ISO-ish formats (ISO with T, "YYYY-MM-DD HH:mm:ss", etc.)
      - Integers: Unix milliseconds (e.g. resvBeginTime=1782885600000)

    Returns None on failure. The "IC native format" (slash-separated) is
    also accepted for backward compat.
    """
    if s is None:
        return None
    # Unix milliseconds (int) or numeric string
    if isinstance(s, (int, float)):
        try:
            return datetime.fromtimestamp(int(s) / 1000)
        except (ValueError, OSError, OverflowError):
            return None
    if isinstance(s, str):
        s_strip = s.strip()
        if s_strip.isdigit():
            try:
                return datetime.fromtimestamp(int(s_strip) / 1000)
            except (ValueError, OSError, OverflowError):
                return None
        for fmt in (
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S.000",
            "%Y-%m-%dT%H:%M",
            "%Y-%m-%d %H:%M",
            "%Y/%m/%d %H:%M:%S",   # IC native format
            "%Y/%m/%d %H:%M",
        ):
            try:
                return datetime.strptime(s, fmt)
            except (ValueError, TypeError):
                continue
    return None


def format_ic_dt(dt: datetime) -> str:
    """Format a datetime in the IC native string format: "YYYY-MM-DD HH:mm:00".

    The server expects dashes (NOT slashes) and seconds to be ":00".
    Verified against the SPA source: moment.format("YYYY-MM-DD HH:mm:00").
    """
    return f"{dt.year:04d}-{dt.month:02d}-{dt.day:02d} {dt.hour:02d}:{dt.minute:02d}:00"


# -- Lab (楼层 / 区域) --------------------------------------------------------


@dataclass
class Lab:
    """A lab / building / floor — the intermediate grouping between campus and room.

    Source: `GET /lab/devKindLabs?classKind=1` for the list of labs;
    or extracted from `roomDevice/roomInfos` nested structure.
    """
    lab_id: int                              # labId — small int
    lab_name: str                            # labName — e.g. "琳恩一层(Lynn 1st floor)"

    @classmethod
    def from_api(cls, raw: dict) -> "Lab":
        return cls(
            lab_id=int(raw["labId"]),
            lab_name=raw.get("labName", ""),
        )


# -- Room (设备 / 房间) --------------------------------------------------------


@dataclass
class OpenTime:
    """One open-hours window for a room on a given day.

    Most rooms have ONE window (e.g. 08:00-21:59). Some have multiple
    (e.g. morning + afternoon) — the IC server returns them as a list.
    """
    open_start_time: str                     # "HH:MM" (no seconds)
    open_end_time: str                       # "HH:MM"
    open_limit: int                          # bitmask: 1=日 2=周 etc. (unverified)

    @classmethod
    def from_api(cls, raw: dict) -> "OpenTime":
        return cls(
            open_start_time=raw.get("openStartTime", ""),
            open_end_time=raw.get("openEndTime", ""),
            open_limit=int(raw.get("openLimit", 0) or 0),
        )


@dataclass
class Room:
    """A bookable room / device (讨论间, 会议室, 培训室, etc.).

    Source: `GET /roomDevice/roomInfos?classKind=1&kindId=...&labId=...`
    """
    dev_id: int                              # devId — small int
    dev_name: str                            # devName — e.g. "C105（1-3人）"
    min_resv_time: int = 0                   # minResvTime — minutes (10 typical)
    open_times: List[OpenTime] = field(default_factory=list)
    resv_infos: Optional[dict] = None        # populated when reserved (shape TBD)

    @classmethod
    def from_api(cls, raw: dict) -> "Room":
        return cls(
            dev_id=int(raw["devId"]),
            dev_name=raw.get("devName", ""),
            min_resv_time=int(raw.get("minResvTime", 0) or 0),
            open_times=[OpenTime.from_api(t) for t in raw.get("openTimes", []) or []],
            resv_infos=raw.get("resvInfos"),
        )


@dataclass
class LabWithRooms:
    """A lab plus its list of rooms (from roomDevice/roomInfos nested structure)."""
    lab_id: int
    lab_name: str
    rooms: List[Room] = field(default_factory=list)

    @classmethod
    def from_api(cls, raw: dict) -> "LabWithRooms":
        return cls(
            lab_id=int(raw["labId"]),
            lab_name=raw.get("labName", ""),
            rooms=[Room.from_api(r) for r in raw.get("roomInfos", []) or []],
        )


@dataclass
class CampusGroup:
    """A campus grouping containing one or more labs (from roomDevice/roomInfos).

    The IC system groups labs by campus (e.g. 涵泳讨论间, 一丹讨论间).
    """
    campus_id: int
    campus_name: str
    labs: List[LabWithRooms] = field(default_factory=list)

    @classmethod
    def from_api(cls, raw: dict) -> "CampusGroup":
        return cls(
            campus_id=int(raw.get("campusId", 0) or 0),
            campus_name=raw.get("campusName", ""),
            labs=[LabWithRooms.from_api(l) for l in raw.get("labInfos", []) or []],
        )


# -- Room idle summary (homepage) ---------------------------------------------


@dataclass
class RoomIdleCategory:
    """A room category on the homepage idle summary (per-kind count).

    Source: `GET /home/page/room/idle`
    """
    name: str                                # "讨论间  Reserve Group Study Room (3-7 persons)"
    idle_quantity: int                       # currently free
    total_quantity: int                      # total in this category

    @classmethod
    def from_api(cls, raw: dict) -> "RoomIdleCategory":
        return cls(
            name=raw.get("name", ""),
            idle_quantity=int(raw.get("idelQuantity", 0) or 0),
            total_quantity=int(raw.get("totalQuantity", 0) or 0),
        )

    @property
    def used_quantity(self) -> int:
        return self.total_quantity - self.idle_quantity


# -- Reservation --------------------------------------------------------------


# Status bitmask values (from the IC booking system).
# The server returns a single int with bit flags; common composites:
#   1027 = 1024 | 2 | 1  = upcoming + booked + applied
# These are the values returned by `resvStatus` in resvInfo. The SPA's
# "未开始 / 已开始 / 已违约 / 已结束" tabs map to `needStatus` query params.
RESV_STATUS_UPCOMING   = 6     # value used by SPA default filter (未开始 tab)
RESV_STATUS_STARTED    = 4
RESV_STATUS_VIOLATED   = 16    # 已违约
RESV_STATUS_FINISHED   = 8     # 已结束


@dataclass
class Reservation:
    """A library room reservation.

    Source: `GET /reserve/resvInfo?beginDate=...&endDate=...&page=...&pageNum=...`
    (the userinfo page endpoint). The `resvId` form (`/reserve/resvInfo?resvId=...`)
    also works for single-record lookups — see `client.resv_info()`.

    Verified wire shape (2026-06-30 Playwright probe of /#/ic/userinfo):

        {
            "uuid": "bdb93949...",            # cancel key
            "resvId": 183442,                 # primary key
            "resvDate": 20260701,             # YYYYMMDD int
            "resvBeginTime": 1782885600000,   # unix ms
            "resvEndTime":   1782889200000,   # unix ms
            "resvStatus": 1027,               # bitmask
            "testName": "team sync",          # title / 主题
            "memo": "",
            "resvDevInfoList": [{             # nested
                "devId": 13,
                "devName": "C105（1-3人）",
                "roomName": "C105（1-3人）",
                "labName": "涵泳一层(Learning Nexus 1st floor)",
                "kindName": "讨论间 ...",
                "classKind": 1,
            }],
            "resvMemberInfoList": [{          # co-applicants
                "accNo": 100001, "trueName": "<name>", "logonName": "<sid>"
            }],
            "resvKind": 16,                   # 16 = research room, etc.
            "classKind": 1,
            "dayOfWeek": 2,
            "latestCheckInTime": 1782886500000,
            "gmtCreate": 1782751690000,
            ...
        }
    """
    resv_id: int                             # reservation primary key (resvId)
    uuid: str = ""                           # 32-hex cancel key
    dev_id: int = 0                          # the room booked (from resvDevInfoList[0].devId)
    dev_name: str = ""                       # e.g. "C105（1-3人）" (resvDevInfoList[0].devName)
    room_name: str = ""                      # e.g. "C105（1-3人）" (resvDevInfoList[0].roomName)
    lab_name: str = ""                       # e.g. "涵泳一层" (resvDevInfoList[0].labName)
    kind_name: str = ""                      # e.g. "讨论间 ..." (resvDevInfoList[0].kindName)
    title: str = ""                          # testName — the 主题 displayed in userinfo
    begin_time: Optional[datetime] = None    # resvBeginTime (unix ms → datetime)
    end_time: Optional[datetime] = None      # resvEndTime (unix ms → datetime)
    resv_date: Optional[date] = None         # resvDate as YYYY-MM-DD (from YYYYMMDD int)
    memo: str = ""                           # notes
    resv_status: int = 0                     # resvStatus bitmask
    class_kind: int = 0                      # classKind (1 = research room)
    resv_kind: int = 0                       # resvKind
    day_of_week: Optional[int] = None        # dayOfWeek (0=Sun..6=Sat)
    latest_check_in_time: Optional[datetime] = None  # latestCheckInTime (unix ms)
    members: List["ResvMember"] = field(default_factory=list)  # resvMemberInfoList

    @classmethod
    def from_api(cls, raw: dict) -> "Reservation":
        # resvDevInfoList[0] is the (only) room booked
        dev_list = raw.get("resvDevInfoList") or []
        dev = dev_list[0] if dev_list else {}

        # resvMemberInfoList[] is the co-applicants (may be None for solo)
        members_raw = raw.get("resvMemberInfoList") or []
        members = [ResvMember.from_api(m) for m in members_raw]

        # resvDate: int YYYYMMDD OR a YYYY-MM-DD string
        rd = raw.get("resvDate")
        resv_date: Optional[date] = None
        if isinstance(rd, int):
            try:
                resv_date = date(rd // 10000, (rd // 100) % 100, rd % 100)
            except (ValueError, ZeroDivisionError):
                resv_date = None
        elif isinstance(rd, str) and rd:
            try:
                resv_date = date.fromisoformat(rd)
            except ValueError:
                resv_date = None

        return cls(
            resv_id=int(raw.get("resvId") or raw.get("id") or 0),
            uuid=str(raw.get("uuid", "") or ""),
            dev_id=int(dev.get("devId") or 0),
            dev_name=str(dev.get("devName", "") or ""),
            room_name=str(dev.get("roomName", "") or ""),
            lab_name=str(dev.get("labName", "") or ""),
            kind_name=str(dev.get("kindName", "") or ""),
            title=str(raw.get("testName", "") or ""),
            begin_time=_parse_dt(raw.get("resvBeginTime")),
            end_time=_parse_dt(raw.get("resvEndTime")),
            resv_date=resv_date,
            memo=str(raw.get("memo", "") or ""),
            resv_status=int(raw.get("resvStatus", 0) or 0),
            class_kind=int(raw.get("classKind", 0) or 0),
            resv_kind=int(raw.get("resvKind", 0) or 0),
            day_of_week=(int(raw["dayOfWeek"]) if raw.get("dayOfWeek") is not None else None),
            latest_check_in_time=_parse_dt(raw.get("latestCheckInTime")),
            members=members,
        )

    @property
    def is_upcoming(self) -> bool:
        """True if reservation is in the future (server-side check, not a status
        flag — server tells us the next check-in time and we compare to now)."""
        if not self.begin_time:
            return False
        return self.begin_time > datetime.now()

    @property
    def display_name(self) -> str:
        """Human-readable summary for CLI output."""
        room = self.room_name or self.dev_name or f"dev#{self.dev_id}"
        date_str = self.resv_date.isoformat() if self.resv_date else "?"
        t1 = self.begin_time.strftime("%H:%M") if self.begin_time else "?"
        t2 = self.end_time.strftime("%H:%M") if self.end_time else "?"
        return f"#{self.resv_id} {date_str} {t1}–{t2} {room} '{self.title}'"


@dataclass
class ResvMember:
    """A co-applicant on a reservation (from resvMemberInfoList[])."""
    acc_no: int                              # accNo
    true_name: str = ""                      # trueName
    logon_name: str = ""                     # logonName (student/faculty ID)
    ident: int = 0                           # identity bitmask
    kind: int = 0                            # member kind

    @classmethod
    def from_api(cls, raw: dict) -> "ResvMember":
        return cls(
            acc_no=int(raw.get("accNo", 0) or 0),
            true_name=str(raw.get("trueName", "") or ""),
            logon_name=str(raw.get("logonName", "") or ""),
            ident=int(raw.get("ident", 0) or 0),
            kind=int(raw.get("kind", 0) or 0),
        )


# -- User info (whoami) ------------------------------------------------------


@dataclass
class UserInfo:
    """The current user's profile (from `GET /auth/userInfo`).

    Sensitive fields (`idCard`, `cardNo`, `cardId`, `handPhone`, `email`,
    `token`, `uuid`) are stored as "***" in the on-disk user_info.json
    (see auth.py:_redact_user_info). They're present in the in-memory
    dict at runtime so the user can read them in interactive use, but
    they should not be logged.
    """
    acc_no: int                              # SUSTech account number
    pid: str = ""                            # personal ID (student/faculty)
    logon_name: str = ""
    true_name: str = ""
    class_name: str = ""                     # e.g. "2025级本科"
    dept_name: str = ""                      # e.g. "南方科技大学"
    manager: int = 0                         # permission bitmask
    ident: int = 0                           # identity bitmask
    status: int = 0
    kind: int = 0

    @classmethod
    def from_api(cls, raw: dict) -> "UserInfo":
        return cls(
            acc_no=int(raw.get("accNo", 0) or 0),
            pid=str(raw.get("pid", "")),
            logon_name=raw.get("logonName", ""),
            true_name=raw.get("trueName", ""),
            class_name=raw.get("className", ""),
            dept_name=raw.get("deptName", ""),
            manager=int(raw.get("manager", 0) or 0),
            ident=int(raw.get("ident", 0) or 0),
            status=int(raw.get("status", 0) or 0),
            kind=int(raw.get("kind", 0) or 0),
        )

    def __str__(self) -> str:
        return f"UserInfo({self.true_name} / accNo={self.acc_no} / pid={self.pid})"


# -- Build a reservation create payload ---------------------------------------


def build_reservation_payload(
    *,
    acc_no: int,
    dev_id: int,
    begin: datetime,
    end: datetime,
    title: str,
    class_kind: int = 1,
    member_kind: int = 1,
    resv_member: Optional[List[int]] = None,
    resv_property: int = 0,
    memo: str = "",
) -> dict:
    """Build the payload for `POST /reserve` (the create endpoint).

    All defaults reflect a single-user reservation of a research room
    (`classKind=1`, `memberKind=1`). For group reservations, pass
    `member_kind=2` and a list of accNos in `resv_member`.

    Per the verified wire shape (2026-06-29 probe of chunk-a1fdd30a):

        {
            "sysKind": <classKind>,            # 1 for research rooms
            "appAccNo": <applicant accNo>,
            "memberKind": <1=self, 2=group>,
            "resvMember": [accNo, ...],        # list (defaults to [acc_no])
            "resvBeginTime": "YYYY/MM/DD HH:mm:00",
            "resvEndTime":   "YYYY/MM/DD HH:mm:00",
            "testName": <title>,
            "resvProperty": <0=normal, ...>,
            "resvDev": [devId, ...],           # list (defaults to [dev_id])
            "memo": <notes>,
        }

    The wire format uses `axios params` (query string), so the payload
    is sent as URL query parameters on `POST /reserve`.
    """
    if resv_member is None:
        resv_member = [acc_no]
    return {
        "sysKind": class_kind,
        "appAccNo": acc_no,
        "memberKind": member_kind,
        "resvMember": resv_member,
        "resvBeginTime": format_ic_dt(begin),
        "resvEndTime": format_ic_dt(end),
        "testName": title,
        "resvProperty": resv_property,
        "resvDev": [dev_id],
        "memo": memo,
    }
