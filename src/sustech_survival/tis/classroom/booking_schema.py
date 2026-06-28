"""
sustech_survival.tis.classroom.booking_schema — Dataclasses for TIS 场地借用
(Venue Borrowing / Venue Hire Application).

Mirrors the JSON shapes returned by the TIS 教务系统 endpoints under
``/cdjy/*`` and ``/gzlshywlc/*``.

All parsers are classmethods. API keys (jhdh, sqr, xn, xq, cdjymxlist, etc.)
are translated to snake_case at the parser boundary so Python code never
sees raw API field names.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from sustech_survival.semester import Semester


# ── Date / time helpers ──────────────────────────────────────────────────────


_DT_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S%z",       # 2026-06-26T08:15:18+00:00
    "%Y-%m-%dT%H:%M:%S.%f%z",    # 2026-06-26T08:15:18.000+00:00
    "%Y-%m-%d",
)


def _parse_dt(s) -> Optional[datetime]:
    """Parse a TIS datetime string. Returns None on failure or empty input."""
    if not s:
        return None
    if isinstance(s, datetime):
        return s
    s = str(s).strip()
    for fmt in _DT_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except (ValueError, TypeError):
            continue
    return None


def _fmt_dt(dt: Optional[datetime]) -> str:
    """Format a datetime back to TIS's preferred "YYYY-MM-DD HH:MM:SS" form."""
    if not dt:
        return ""
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _to_int(v, default: int = 0) -> int:
    """Best-effort int coercion. Returns default on None / empty / junk."""
    if v is None or v == "":
        return default
    try:
        return int(v)
    except (ValueError, TypeError):
        return default


# ── Audit status (审核状态) ──────────────────────────────────────────────────


@dataclass
class AuditStatus:
    """One entry from ``cdjy/shztlist`` (ywdm='CDJYLC').

    The endpoint returns a HISTORY of audit events (with timestamps) rather
    than a static enum — each entry has a status name and the time it was set.
    """
    code: str = ""                 # synthesized from the name (no explicit id)
    name: str = ""                 # YSHJDZTXSMC — display name (Chinese)
    name_en: str = ""              # server doesn't return an EN variant
    occurred_at: Optional[datetime] = None  # SJ — timestamp

    @classmethod
    def from_api(cls, raw: dict) -> "AuditStatus":
        name = raw.get("YSHJDZTXSMC") or raw.get("name") or ""
        return cls(
            code=str(raw.get("YWJDDM") or raw.get("code") or name),
            name=name,
            name_en=raw.get("YSHJDZTXSMC_EN") or raw.get("name_en") or "",
            occurred_at=_parse_dt(raw.get("SJ")),
        )


# ── Borrow time slot (jtsjlist entry) ────────────────────────────────────────


@dataclass
class BorrowTimeSlot:
    """One time period within a BorrowDetail row.

    Each detail row can span multiple periods (e.g. Monday 3-4 AND Tuesday 5-6).
    """
    seq: int = 0                   # xh — sequence within detail row
    weekday: int = 0               # xqj — 1=Mon … 7=Sun
    period_start: int = 0          # ksjc — 1-12
    period_end: int = 0            # jsjc — 1-12
    week_pattern: str = ""         # zcbds — e.g. "1-15" or "1,3,5,7,9,11,13,15,17"
    note: str = ""

    @classmethod
    def from_api(cls, raw: dict) -> "BorrowTimeSlot":
        return cls(
            seq=_to_int(raw.get("xh")),
            weekday=_to_int(raw.get("xqj")),
            period_start=_to_int(raw.get("ksjc")),
            period_end=_to_int(raw.get("jsjc")),
            week_pattern=str(raw.get("zcbds") or ""),
            note=str(raw.get("bz") or ""),
        )


# ── Borrow detail row (cdjymxlist entry) ─────────────────────────────────────


@dataclass
class BorrowDetail:
    """One (room × time-period) row inside a BorrowApplication.

    A single application can span multiple rooms and time periods — each is
    one detail row with its own time slots.
    """
    seq: int = 0                   # xuhhao — sequence within the application
    room_code: str = ""            # cddm — TIS 场地 code (e.g. "YJ-123")
    room_name: str = ""            # cdmc — Chinese display name (e.g. "一教123")
    capacity: int = 0              # zws — seats
    location: str = ""             # cdlocation — building/floor hint
    purpose: str = ""              # yongtu — free-text purpose for this room
    time_slots: List[BorrowTimeSlot] = field(default_factory=list)

    @classmethod
    def from_api(cls, raw: dict) -> "BorrowDetail":
        return cls(
            seq=_to_int(raw.get("xuhhao")),
            room_code=str(raw.get("cddm") or ""),
            room_name=str(raw.get("cdmc") or ""),
            capacity=_to_int(raw.get("zws")),
            location=str(raw.get("cdlocation") or ""),
            purpose=str(raw.get("yongtu") or ""),
            time_slots=[BorrowTimeSlot.from_api(t) for t in (raw.get("jtsjlist") or [])],
        )


# ── Audit progress node (审批流程节点) ───────────────────────────────────────


@dataclass
class AuditNode:
    """One step in the venue-borrowing approval workflow.

    Source: ``gzlshywlc/queryShywlcShck`` (ywlcslid, ywlcdm='CDJYLC').
    """
    seq: int = 0                   # internal sequence
    role_code: str = ""            # shjs — 审核角色 code
    role_name: str = ""            # shjsxm — display name
    role_name_en: str = ""         # shjsxm_en
    status: str = ""               # current node status
    opinion: str = ""              # shyj — audit opinion text
    auditor: str = ""              # who handled this node
    audited_at: Optional[datetime] = None

    @classmethod
    def from_api(cls, raw: dict) -> "AuditNode":
        return cls(
            seq=_to_int(raw.get("xh")),
            role_code=str(raw.get("shjs") or ""),
            role_name=str(raw.get("shjsxm") or ""),
            role_name_en=str(raw.get("shjsxm_en") or ""),
            status=str(raw.get("shzt") or raw.get("status") or ""),
            opinion=str(raw.get("shyj") or ""),
            auditor=str(raw.get("shr") or ""),
            audited_at=_parse_dt(raw.get("shsj")),
        )


# ── Permission result (yzkg) ────────────────────────────────────────────────


@dataclass
class PermissionResult:
    """Result of the ``cdjy/yzkg`` pre-check.

    Returns a raw ``"0"`` (not allowed) or ``"1"`` (allowed) string.
    """
    allowed: bool
    raw: str = ""

    @classmethod
    def from_api(cls, raw) -> "PermissionResult":
        if isinstance(raw, dict):
            content = raw.get("content") or raw.get("data") or ""
            s = str(content)
        else:
            s = str(raw or "")
        return cls(allowed=s.strip() == "1", raw=s)


# ── Borrow application (cdjyform) ────────────────────────────────────────────


# Status constants (server returns Chinese strings directly)
STATUS_SAVED = "保存待审核"
STATUS_SUBMITTED = "已提交"
STATUS_APPROVED = "审核通过"
STATUS_REJECTED = "驳回"


@dataclass
class BorrowApplication:
    """One 场地借用 application (cdjyform).

    This is the full data submitted by ``/cdjy/addChangDiJieYongShenQing/1``.
    After create, ``id`` and ``jhdh`` (plan number) are auto-populated server-side.
    """
    id: str = ""                   # auto-generated server id
    jhdh: str = ""                 # 计划单号 — plan number (auto)
    status: str = ""               # 保存待审核 / 已提交 / 审核通过 / 驳回

    # Applicant info (申请人)
    applicant_name: str = ""       # sqr
    applicant_phone: str = ""      # sqrdh
    applicant_employee_id: str = ""  # sqrzgh
    applicant_dept: str = ""       # sqrdw
    applicant_dept_code: str = ""  # sqrdwdh

    # User info (使用人 — actual room user)
    user_name: str = ""            # syr
    user_phone: str = ""           # syrdh
    user_employee_id: str = ""     # syrzgh
    user_dept_code: str = ""       # syrdwdm

    # Time scope
    semester: Optional[Semester] = None
    weeks: str = ""                # zc — week pattern, e.g. "5-8"
    start_end_weeks: str = ""      # qsjsz — explicit "start_week, end_week"
    campus: str = ""               # xiaoqu — "1" (一期) / "2" (二期) / "9" (九祥)

    # Booking content
    headcount: int = 0             # rs — number of people
    purpose: str = ""              # jyyy — 借用原因 / reason
    external_oa_approval: str = "" # sfsjysxtly — off-campus OA approval flag

    # Audit tracking (populated after submission)
    audit_role: str = ""           # shjs
    audit_role_name: str = ""      # shjsxm
    audit_opinion: str = ""        # shyj
    audit_office: str = ""         # shbj
    new_or_continued: str = ""     # xnxw

    # Nested lists
    details: List[BorrowDetail] = field(default_factory=list)

    @property
    def is_saved(self) -> bool:
        return self.status == STATUS_SAVED

    @property
    def is_submitted(self) -> bool:
        return self.status == STATUS_SUBMITTED

    @property
    def is_approved(self) -> bool:
        return self.status == STATUS_APPROVED

    @property
    def is_rejected(self) -> bool:
        return self.status == STATUS_REJECTED

    @property
    def room_codes(self) -> List[str]:
        """All room codes in this application (deduped, non-empty)."""
        seen = []
        for d in self.details:
            if d.room_code and d.room_code not in seen:
                seen.append(d.room_code)
        return seen

    @classmethod
    def from_api(cls, raw: dict) -> "BorrowApplication":
        # Extract semester from xnxq (preferred) or xn+xq pair
        semester: Optional[Semester] = None
        raw_xnxq = raw.get("xnxq")
        raw_xn = raw.get("xn")
        raw_xq = raw.get("xq")
        if raw_xnxq:
            try:
                semester = Semester(str(raw_xnxq))
            except (ValueError, TypeError):
                pass
        elif raw_xn and raw_xq:
            try:
                semester = Semester(str(raw_xn), str(raw_xq))
            except (ValueError, TypeError):
                pass

        return cls(
            id=str(raw.get("id") or ""),
            jhdh=str(raw.get("jhdh") or ""),
            status=str(raw.get("shztmc") or raw.get("status") or ""),
            applicant_name=str(raw.get("sqr") or ""),
            applicant_phone=str(raw.get("sqrdh") or ""),
            applicant_employee_id=str(raw.get("sqrzgh") or ""),
            applicant_dept=str(raw.get("sqrdw") or ""),
            applicant_dept_code=str(raw.get("sqrdwdh") or ""),
            user_name=str(raw.get("syr") or ""),
            user_phone=str(raw.get("syrdh") or ""),
            user_employee_id=str(raw.get("syrzgh") or ""),
            user_dept_code=str(raw.get("syrdwdm") or ""),
            semester=semester,
            weeks=str(raw.get("zc") or ""),
            start_end_weeks=str(raw.get("qsjsz") or ""),
            campus=str(raw.get("xiaoqu") or ""),
            headcount=_to_int(raw.get("rs")),
            purpose=str(raw.get("jyyy") or ""),
            external_oa_approval=str(raw.get("sfsjysxtly") or ""),
            audit_role=str(raw.get("shjs") or ""),
            audit_role_name=str(raw.get("shjsxm") or ""),
            audit_opinion=str(raw.get("shyj") or ""),
            audit_office=str(raw.get("shbj") or ""),
            new_or_continued=str(raw.get("xnxw") or ""),
            details=[BorrowDetail.from_api(d) for d in (raw.get("cdjymxlist") or [])],
        )

    def to_api(self) -> dict:
        """Serialize back to the API's cdjyform shape (for add/update)."""
        return {
            "id": self.id,
            "jhdh": self.jhdh,
            "sqr": self.applicant_name,
            "sqrdh": self.applicant_phone,
            "sqrzgh": self.applicant_employee_id,
            "sqrdw": self.applicant_dept,
            "sqrdwdh": self.applicant_dept_code,
            "syr": self.user_name,
            "syrdh": self.user_phone,
            "syrzgh": self.user_employee_id,
            "syrdwdm": self.user_dept_code,
            "xnxq": self.semester.xnxq if self.semester else "",
            "xn": self.semester.xn if self.semester else "",
            "xq": self.semester.xq if self.semester else "",
            "zc": self.weeks,
            "qsjsz": self.start_end_weeks,
            "xiaoqu": self.campus,
            "rs": self.headcount,
            "jyyy": self.purpose,
            "sfsjysxtly": self.external_oa_approval,
            "shjs": self.audit_role,
            "shbj": self.audit_office,
            "xnxw": self.new_or_continued or None,
            "cdjymxlist": [_detail_to_api(d) for d in self.details],
        }


def _detail_to_api(d: BorrowDetail) -> dict:
    return {
        "xuhhao": d.seq,
        "cddm": d.room_code,
        "cdmc": d.room_name,
        "zws": d.capacity,
        "cdlocation": d.location,
        "yongtu": d.purpose,
        "jtsjlist": [_slot_to_api(s) for s in d.time_slots],
    }


def _slot_to_api(s: BorrowTimeSlot) -> dict:
    return {
        "xh": s.seq,
        "xqj": s.weekday,
        "ksjc": s.period_start,
        "jsjc": s.period_end,
        "zcbds": s.week_pattern,
        "bz": s.note,
    }


# ── Venue occupancy entry (queryChangDiZhanYongShiJian) ──────────────────────


@dataclass
class VenueOccupancySlot:
    """One row from ``cdjy/queryChangDiZhanYongShiJian``."""
    room_code: str = ""
    weekday: int = 0
    period_start: int = 0
    period_end: int = 0
    week_pattern: str = ""
    label: str = ""

    @classmethod
    def from_api(cls, raw: dict) -> "VenueOccupancySlot":
        return cls(
            room_code=str(raw.get("cddm") or ""),
            weekday=_to_int(raw.get("xqj")),
            period_start=_to_int(raw.get("ksjc") or raw.get("jc")),
            period_end=_to_int(raw.get("jsjc") or raw.get("jc")),
            week_pattern=str(raw.get("zcbds") or raw.get("zc") or ""),
            label=str(raw.get("label") or raw.get("mc") or ""),
        )


# ── Public exports ────────────────────────────────────────────────────────────


__all__ = [
    "AuditNode",
    "AuditStatus",
    "BorrowApplication",
    "BorrowDetail",
    "BorrowTimeSlot",
    "PermissionResult",
    "VenueOccupancySlot",
    "STATUS_APPROVED",
    "STATUS_REJECTED",
    "STATUS_SAVED",
    "STATUS_SUBMITTED",
    "_parse_dt",
    "_fmt_dt",
    "_to_int",
]
