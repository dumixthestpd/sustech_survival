"""
sustech_survival.tis.classroom.booking_schema — Dataclasses for TIS 场地借用
(Venue Borrowing / Venue Hire Application).

Mirrors the JSON shapes returned by the TIS 教务系统 endpoints under
``/cdjy/*`` and ``/gzlshywlc/*``.

All parsers are classmethods. API keys (jhdh, sqr, xn, xq, cdjymxlist, etc.)
are translated to snake_case at the parser boundary so Python code never
sees raw API field names.

Wire-shape verification: 2026-06-29 via Playwright + $.ajax hook.
Probe script: ``scripts/probe_cdjy_post.py``.
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


def _parse_hlddct(v) -> bool:
    """Parse hlddct (忽略地点冲突) — can be bool, '1'/'0', or absent.
    
    TIS source (saveOrSubmit on code 100500) sets hlddct='1' (string)
    when user confirms location conflict override.
    Initial form default is false/'' (not set).
    """
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip() == "1"
    if isinstance(v, (int, float)):
        return v == 1
    return False


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

    The wire serializer emits JUST `{xqj, ksjc, jsjc}` (the form-level
    `jtsjlist[]` entries the TIS server uses for occupancy checking).
    The `seq`, `week_pattern`, and `note` fields are kept for human-facing
    display only — they are NOT in the wire (verified 2026-06-29).
    """
    seq: int = 0                   # xh — sequence within detail row (UI only)
    weekday: int = 0               # xqj — 1=Mon … 7=Sun
    period_start: int = 0          # ksjc — 1-12
    period_end: int = 0            # jsjc — 1-12
    week_pattern: str = ""         # zcbds — UI display only (e.g. "1-15")
    note: str = ""                 # bz — UI display only

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

    def to_api(self) -> dict:
        """Serialize to the wire's flat-slot shape: just `{xqj, ksjc, jsjc}`.

        Used for the form-level `jtsjlist[]` entry — the TIS server
        uses this for occupancy checking. Per-row `xqj/ksjc/jsqc`
        are duplicated on the row itself (see _detail_to_api).
        """
        return {
            "xqj": str(self.weekday) if self.weekday else "",
            "ksjc": str(self.period_start) if self.period_start else "",
            "jsjc": str(self.period_end) if self.period_end else "",
        }


# ── Borrow detail row (cdjymxlist entry) ─────────────────────────────────────


@dataclass
class BorrowDetail:
    """One (room × time-period) row inside a BorrowApplication.

    A single application can span multiple rooms and time periods — each is
    one detail row with its own time slots.

    Wire-shape (verified 2026-06-29): 28 keys per row. The row carries
    the full row identity (room, dates, semester, campus, per-row
    overrides for sqr/syr/etc.) AND a copy of the slot's
    xqj/ksjc/jsjc fields. The per-row `xqj/ksjc/jsjc` is duplicated
    from `time_slots[0]` — the server uses both.

    Fields NOT in the wire (kept for human display only): `capacity`,
    `location`, `purpose`. The server fills these from the cddm lookup.
    """
    seq: int = 0                   # xuhhao — sequence within the application
    room_code: str = ""            # cddm — TIS 场地 code (e.g. "YJ-123")
    room_name: str = ""            # cdmc — Chinese display name (e.g. "一教123")
    capacity: int = 0              # zws — seats (UI display; server fills from cddm)
    location: str = ""             # cdlocation — building/floor hint (UI display)
    purpose: str = ""              # yongtu — UI display
    # Date model — the wire sends actual dates (YYYY-MM-DD), not weeks.
    # Verified 2026-06-29: row's `ksrq`/`jsrq` are in the wire.
    start_date: str = ""           # ksrq — 开始日期 YYYY-MM-DD
    end_date: str = ""             # jsrq — 结束日期 YYYY-MM-DD
    # Week pattern (per-row, may differ from form-level)
    week_bitmask: str = ""         # zc — week bitmask (e.g. "1" or "1,3,5")
    week_range: str = ""           # qsjsz — "start_week,end_week"
    # Per-row filter snapshot (TriState)
    zysfkyd: str = "2"             # 座椅可移动: '1'=是, '0'=否, '2'=不限制
    sfjtjs: str = "2"              # 阶梯教室: '1'=是, '0'=否, '2'=不限制
    sfsysb: str = "1"              # 是否使用设备: '1'=是, '0'=否 (binary)
    time_slots: List[BorrowTimeSlot] = field(default_factory=list)

    @classmethod
    def from_api(cls, raw: dict) -> "BorrowDetail":
        # The wire may have time_slots nested OR just xqj/ksjc/jsjc on
        # the row itself (verified 2026-06-29). Build a single
        # BorrowTimeSlot from the row's xqj/ksjc/jsjc if no nested
        # list is present.
        slots = [BorrowTimeSlot.from_api(t) for t in (raw.get("jtsjlist") or [])]
        if not slots:
            xqj = _to_int(raw.get("xqj"))
            ksjc = _to_int(raw.get("ksjc"))
            jsjc = _to_int(raw.get("jsjc"))
            if xqj and ksjc:
                slots = [BorrowTimeSlot(
                    weekday=xqj,
                    period_start=ksjc,
                    period_end=jsjc,
                    week_pattern=str(raw.get("zc") or ""),
                )]

        # Per-row `rs` is a STRING in the wire — convert to int for the
        # capacity field. Per-row `jyyy` is the per-row purpose.
        # Also support legacy fields `zws`/`yongtu` (server-side fills,
        # occasionally present in the read API response).
        rs_str = raw.get("rs", "")
        zws_val = raw.get("zws")
        per_row_capacity = (
            _to_int(rs_str) if rs_str else (_to_int(zws_val) if zws_val else 0)
        )
        per_row_purpose = (
            str(raw.get("jyyy") or "")
            or str(raw.get("yongtu") or "")
        )

        return cls(
            seq=_to_int(raw.get("xuhhao")),
            room_code=str(raw.get("cddm") or ""),
            room_name=str(raw.get("cdmc") or ""),
            # Prefer wire's `rs` (per-row headcount). Fall back to `zws`.
            capacity=per_row_capacity,
            location=str(raw.get("cdlocation") or ""),
            purpose=per_row_purpose,
            start_date=str(raw.get("ksrq") or ""),
            end_date=str(raw.get("jsrq") or ""),
            week_bitmask=str(raw.get("zc") or ""),
            week_range=str(raw.get("qsjsz") or ""),
            zysfkyd=str(raw.get("zysfkyd") or "2"),
            sfjtjs=str(raw.get("sfjtjs") or "2"),
            sfsysb=str(raw.get("sfsysb") or "1"),
            time_slots=slots,
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

    Wire-shape (verified 2026-06-29): 35 form-level keys sent on POST.
    All fields below are in the wire — see `to_api()` for the wire mapping.
    """
    id: str = ""                   # auto-generated server id
    jhdh: str = ""                 # 计划单号 — plan number (auto)
    status: str = ""               # 保存待审核 / 已提交 / 审核通过 / 驳回

    # Applicant info (申请人) — Chinese + EN variants
    applicant_name: str = ""       # sqr
    applicant_name_en: str = ""    # sqr_en — __user.xm_en
    applicant_phone: str = ""      # sqrdh
    applicant_employee_id: str = ""  # sqrzgh
    applicant_dept: str = ""       # sqrdw
    applicant_dept_en: str = ""    # sqrdw_en — __user.bmmc_en
    applicant_dept_code: str = ""  # sqrdwdh

    # User info (使用人 — actual room user)
    user_name: str = ""            # syr
    user_name_en: str = ""         # syr_en
    user_phone: str = ""           # syrdh
    user_employee_id: str = ""     # syrzgh
    user_dept_code: str = ""       # syrdwdm

    # Time scope
    semester: Optional[Semester] = None
    weeks: str = ""                # zc — week pattern (form-level, often unused)
    start_end_weeks: str = ""      # qsjsz — "start_week,end_week"
    campus: str = ""               # xiaoqu — "1" / "2" / "9"

    # Booking content
    headcount: int = 0             # rs — number of people (per-row uses string)
    purpose: str = ""              # jyyy — 借用原因 / reason
    external_oa_approval: str = "" # sfsjysxtly — off-campus OA approval flag

    # Audit tracking (server-populated after submission)
    audit_role: str = ""           # shjs
    audit_role_name: str = ""      # shjsxm
    audit_role_name_en: str = ""   # shjsxm_en
    audit_opinion: str = ""        # shyj
    audit_office: str = "0"        # shbj — '0'=保存 (draft), '1'=提交 (submit)
                                   # Verified from TIS source 2026-06-29:
                                   # saveOrSubmit(flag) sets shbj=flag via $.extend
                                   # where flag='0' for 保存 btn, '1' for 提交 btn.
    new_or_continued: str = ""     # xnxw

    # Audit tracking — server-populated fields
    last_modifier: str = ""        # zhxgr
    last_modified_at: str = ""     # xhxgsj

    # 忽略地点冲突 (ignore-location-conflict) — boolean; becomes '1' on retry
    ignore_location_conflict: bool = False  # hlddct

    # Legacy duplicate / dup fields
    legacy_jyrdh: str = ""         # jyrdh — legacy duplicate phone field

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
        # Extract semester from xn+xq pair (xnxq is NOT in the wire).
        semester: Optional[Semester] = None
        raw_xn = raw.get("xn")
        raw_xq = raw.get("xq")
        if raw_xn and raw_xq:
            try:
                semester = Semester(str(raw_xn), str(raw_xq))
            except (ValueError, TypeError):
                pass

        # Per-row `time_slots[]` lives in the wire's `jtsjlist[]` field
        # — but the wire ALSO duplicates the first slot's
        # xqj/ksjc/jsjc ON the row itself (verified 2026-06-29).
        # Our `BorrowDetail.from_api` handles both.

        return cls(
            id=str(raw.get("id") or ""),
            jhdh=str(raw.get("jhdh") or ""),
            status=str(raw.get("shztmc") or raw.get("status") or ""),
            # Applicant
            applicant_name=str(raw.get("sqr") or ""),
            applicant_name_en=str(raw.get("sqr_en") or ""),
            applicant_phone=str(raw.get("sqrdh") or ""),
            applicant_employee_id=str(raw.get("sqrzgh") or ""),
            applicant_dept=str(raw.get("sqrdw") or ""),
            applicant_dept_en=str(raw.get("sqrdw_en") or ""),
            applicant_dept_code=str(raw.get("sqrdwdh") or ""),
            # User
            user_name=str(raw.get("syr") or ""),
            user_name_en=str(raw.get("syr_en") or ""),
            user_phone=str(raw.get("syrdh") or ""),
            user_employee_id=str(raw.get("syrzgh") or ""),
            user_dept_code=str(raw.get("syrdwdm") or ""),
            # Time + scope
            semester=semester,
            weeks=str(raw.get("zc") or ""),
            start_end_weeks=str(raw.get("qsjsz") or ""),
            campus=str(raw.get("xiaoqu") or ""),
            # Booking content
            headcount=_to_int(raw.get("rs")),
            purpose=str(raw.get("jyyy") or ""),
            external_oa_approval=str(raw.get("sfsjysxtly") or ""),
            # Audit
            audit_role=str(raw.get("shjs") or ""),
            audit_role_name=str(raw.get("shjsxm") or ""),
            audit_role_name_en=str(raw.get("shjsxm_en") or ""),
            audit_opinion=str(raw.get("shyj") or ""),
            audit_office=str(raw.get("shbj") or ""),
            new_or_continued=str(raw.get("xnxw") or ""),
            last_modifier=str(raw.get("zhxgr") or ""),
            last_modified_at=str(raw.get("xhxgsj") or ""),
            ignore_location_conflict=_parse_hlddct(raw.get("hlddct")),
            legacy_jyrdh=str(raw.get("jyrdh") or ""),
            details=[BorrowDetail.from_api(d) for d in (raw.get("cdjymxlist") or [])],
        )

    def to_api(self) -> dict:
        """Serialize to the live wire shape (verified 2026-06-29).

        Body shape is `JSON.stringify(this.cdjyform)` — direct Vue
        form serialization, 35 form-level keys. All snake_case
        fields below are translated to the wire's API key names.

        NOTE: `shbj` (save/submit flag) defaults to `""` here — the
        caller MUST set it explicitly via `audit_office='bc'` (save)
        or `audit_office='tj'` (submit) before the POST. The wire
        probe verified these are the only valid values.
        """
        xn = self.semester.xn if self.semester else ""
        xq = self.semester.xq if self.semester else ""
        semester_key = f"{xn}{xq}"  # jyxq — xn+xq concatenated (per-row)

        # Flat-slot list (form-level jtsjlist[]) — built from row[0]'s slots
        # for now. For multi-row applications, this is per-row on the wire,
        # but TIS uses the form-level jtsjlist[] for occupancy checking.
        flat_slots: List[dict] = []
        for d in self.details:
            for s in d.time_slots:
                flat_slots.append(s.to_api())

        return {
            "id": self.id,
            "jhdh": self.jhdh,
            # Applicant
            "sqr": self.applicant_name,
            "sqr_en": self.applicant_name_en,
            "sqrdh": self.applicant_phone,
            "sqrzgh": self.applicant_employee_id,
            "sqrdw": self.applicant_dept,
            "sqrdw_en": self.applicant_dept_en,
            "sqrdwdh": self.applicant_dept_code,
            # User
            "syr": self.user_name,
            "syr_en": self.user_name_en,
            "jyrdh": self.legacy_jyrdh,
            "syrdh": self.user_phone,
            "syrzgh": self.user_employee_id,
            "syrdwdm": self.user_dept_code,
            # Time + scope (NO xnxq — wire has xn + xq separately)
            "xn": xn,
            "xq": xq,
            "zc": self.weeks,
            "qsjsz": self.start_end_weeks,
            "xiaoqu": self.campus,
            # Booking content
            "rs": self.headcount,
            "jyyy": self.purpose,
            "sfsjysxtly": self.external_oa_approval,
            # Audit (caller MUST set audit_office to 'bc' or 'tj')
            "shjs": self.audit_role,
            "shjsxm": self.audit_role_name,
            "shjsxm_en": self.audit_role_name_en,
            "shyj": self.audit_opinion,
            # shbj — TIS source: '0'=保存 (draft), '1'=提交 (submit)
            # saveOrSubmit(flag) sets $.extend(cdjyform, {shbj: flag})
            # where flag is the btn param: '0' for 保存, '1' for 提交.
            "shbj": self.audit_office or "0",  # default '0' = 保存
            "xnxw": self.new_or_continued or "",
            # Server-populated (empty on create)
            "zhxgr": self.last_modifier,
            "xhxgsj": self.last_modified_at,
            # hlddct — string '1'/'0'. TIS source sets hlddct='1' (string)
            # on code 100500 retry. Initial/clean = '0' (not set).
            "hlddct": "1" if self.ignore_location_conflict else "0",
            # Flat-slot list + per-row list
            "jtsjlist": flat_slots,
            "cdjymxlist": [_detail_to_api(d, semester_key, xn, xq, self.campus) for d in self.details],
            # Legacy lists (always empty)
            "cdjymlist": [],
        }


def _detail_to_api(d: BorrowDetail, semester_key: str = "",
                   xn: str = "", xq: str = "", campus: str = "") -> dict:
    """Serialize a BorrowDetail row to the wire's per-row shape.

    Wire row has 28 keys (verified 2026-06-29). The row's `xqj/ksjc/jsjc`
    is duplicated from `time_slots[0]` — server uses both. Per-row
    `xn/xq/xiaoqu` are duplicated from form-level.
    """
    # Pull xqj/ksjc/jsjc from the first slot (if present)
    xqj = ksjc = jsjc = ""
    if d.time_slots:
        first = d.time_slots[0]
        xqj = str(first.weekday) if first.weekday else ""
        ksjc = str(first.period_start) if first.period_start else ""
        jsjc = str(first.period_end) if first.period_end else ""

    return {
        "xuhhao": d.seq,
        # Dates (YYYY-MM-DD)
        "ksrq": d.start_date,
        "jsrq": d.end_date,
        # Per-row headcount — WIRE IS A STRING
        "rs": str(d.capacity) if d.capacity else "",
        # Per-row purpose
        "jyyy": d.purpose,
        # Week pattern (per-row, may differ from form-level)
        "zc": d.week_bitmask,
        "qsjsz": d.week_range,
        # Slot fields (duplicated from time_slots[0])
        "xqj": xqj,
        "ksjc": ksjc,
        "jsjc": jsjc,
        # Semester + campus (per-row copies)
        "jyxq": semester_key,
        # Filter snapshot
        "sfsysb": d.sfsysb,
        "zysfkyd": d.zysfkyd,
        "sfjtjs": d.sfjtjs,
        # Per-row end timestamp (often empty)
        "jyjs": "",
        # Room identity
        "cddm": d.room_code,
        "cdmc": d.room_name,
        # Per-row copies of semester + campus
        "xn": xn,
        "xq": xq,
        "xiaoqu": campus,
        # Per-row override fields (empty when defaulted from form)
        "sqr": "",
        "sqrdh": "",
        "syr": "",
        "syrdh": "",
        "sqrdw": "",
        "sqrdwdh": "",
        "shjs": "",
        "shyj": "",
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


def _weekday_to_date(week: int, weekday: int, semester: Semester) -> tuple[str, str]:
    """Convert (week, weekday) → date strings for ksrq/jsrq.

    TIS week 1 starts on the Monday AFTER semester_start.
    Uses ACADEMIC_CALENDARS from sustech_survival.context.
    Returns (start_date, end_date) as YYYY-MM-DD strings,
    where start_date == end_date (single-day booking).

    Falls back to '' if the semester isn't in the calendar.
    """
    try:
        from sustech_survival.context import ACADEMIC_CALENDARS
        cal_key = f"{semester.xn} {'Spring' if semester.xq == '2' else 'Summer' if semester.xq == '3' else 'Fall' if semester.xq == '1' else ''}"
        cal = ACADEMIC_CALENDARS.get(cal_key)  # type: ignore[arg-type]
        if not cal:
            # Try shorter key
            for k, v in ACADEMIC_CALENDARS.items():
                if semester.xn in k:
                    cal = v
                    break
        if not cal:
            return ("", "")
        from datetime import datetime, timedelta
        start = datetime.strptime(cal["semester_start"], "%Y-%m-%d")
        # TIS week 1 = Monday ON or AFTER semester_start
        days_until_monday = (7 - start.weekday()) % 7
        tis_week1_monday = start + timedelta(days=days_until_monday)
        target = tis_week1_monday + timedelta(weeks=week - 1, days=weekday - 1)
        d = target.strftime("%Y-%m-%d")
        return (d, d)
    except Exception:
        return ("", "")


# ── RowTicket — one (room × time) ticket ─────────────────────────────────────


@dataclass
class RowTicket:
    """One (room × time) ticket — produces one cdjymxlist row + one jtsjlist entry.

    Maps to what the TIS UI calls a "borrow ticket": you pick a date range,
    a weekday, a period range, and a room. The TIS UI enters these via the
    选择场地 search → pick modal.
    """
    room_code: str = ""            # cddm — TIS room code (e.g. "YJ-107")
    room_name: str = ""            # cdmc — display name (e.g. "一教107")
    weekday: int = 0               # xqj — 1=Mon … 7=Sun
    period_start: int = 0          # ksjc — 1-12
    period_end: int = 0            # jsjc — 1-12
    week: str = ""                 # zc — week bitmask or single number
    week_range: str = ""           # qsjsz — "start_week,end_week" or ""
    start_date: str = ""           # ksrq — YYYY-MM-DD
    end_date: str = ""             # jsrq — YYYY-MM-DD


# ── build_booking — translate (demand + tickets) → BorrowApplication ─────────


def build_booking(
    tickets: list[RowTicket],
    semester: Semester,
    *,
    # Person
    applicant_name: str = "",
    applicant_phone: str = "",
    applicant_id: str = "",
    applicant_dept: str = "",
    applicant_dept_en: str = "",
    user_name: str = "",
    user_phone: str = "",
    user_dept_code: str = "",
    # Room
    campus: str = "1",
    headcount: int = 0,
    use_media: bool = True,        # sfsysb
    # Content
    purpose: str = "",
    external_oa: str = "",
    # Save vs submit
    save_as_draft: bool = False,   # shbj='0' vs '1'
    # Conflict
    ignore_location_conflict: bool = False,
    # TIS filter booleans (passed to room-search, not in wire payload to cdjy)
    tiered: str = "2",             # sfjtjs — '0'/'1'/'2' (不限制)
    movable_seats: str = "2",       # zysfkyd — '0'/'1'/'2'
) -> BorrowApplication:
    """Build a BorrowApplication from user-friendly inputs.

    Translates ``RowTicket`` entries → ``cdjymxlist`` rows with time slots.

    The returned ``BorrowApplication`` is ready for review/approval.
    Pass to ``VenueBorrowClient.create_borrow_application()`` when ready.

    ::

        tickets = [
            RowTicket(room_code="YJ-107", room_name="一教107",
                      weekday=2, period_start=3, period_end=4,
                      week="5", start_date="2026-07-01", end_date="2026-07-01"),
            RowTicket(room_code="ZH-201", room_name="智华楼201",
                      weekday=4, period_start=5, period_end=6,
                      week="6", start_date="2026-07-02", end_date="2026-07-02"),
        ]
        app = build_booking(
            tickets=tickets,
            semester=Semester("2025-2026", "3"),
            applicant_name="<name>", applicant_phone="<phone>",
            headcount=30, purpose="学术讲座",
        )
    """
    xn = semester.xn
    xq = semester.xq
    audit_office = "0" if save_as_draft else "1"
    sfsysb_val = "1" if use_media else "0"

    details: list[BorrowDetail] = []
    flat_slots: list[dict] = []

    for i, t in enumerate(tickets):
        # Auto-fill dates from week/weekday if not provided
        sd = t.start_date
        ed = t.end_date
        if not sd and t.week and t.weekday:
            w = 0
            try:
                w = int(t.week.split()[0])
            except (ValueError, IndexError):
                pass
            if w > 0:
                sd, ed = _weekday_to_date(w, t.weekday, semester)

        detail = BorrowDetail(
            seq=i + 1,
            room_code=t.room_code,
            room_name=t.room_name,
            capacity=headcount,
            purpose=purpose,
            start_date=sd,
            end_date=ed,
            week_bitmask=t.week,
            week_range=t.week_range or t.week,
            zysfkyd=movable_seats,
            sfjtjs=tiered,
            sfsysb=sfsysb_val,
            time_slots=[BorrowTimeSlot(
                seq=1,
                weekday=t.weekday,
                period_start=t.period_start,
                period_end=t.period_end,
                week_pattern=t.week,
            )],
        )
        details.append(detail)
        flat_slots.append({
            "xqj": str(t.weekday),
            "ksjc": str(t.period_start),
            "jsjc": str(t.period_end),
        })

    app = BorrowApplication(
        applicant_name=applicant_name,
        applicant_phone=applicant_phone,
        applicant_employee_id=applicant_id,
        applicant_dept=applicant_dept,
        applicant_dept_en=applicant_dept_en,
        user_name=user_name or applicant_name,
        user_phone=user_phone or applicant_phone,
        user_employee_id=applicant_id,
        user_dept_code=user_dept_code,
        semester=semester,
        campus=campus,
        headcount=headcount,
        purpose=purpose,
        external_oa_approval=external_oa,
        audit_office=audit_office,
        ignore_location_conflict=ignore_location_conflict,
        details=details,
    )

    # Patch the flat slots directly (to_api() builds them from row[0]'s slots)
    patched = app.to_api()
    patched["jtsjlist"] = flat_slots
    # Reconstruct from the patched dict to keep type safety
    reconstructed = BorrowApplication.from_api(patched)
    return reconstructed


# ── Public exports ────────────────────────────────────────────────────────────


__all__ = [
    "AuditNode",
    "AuditStatus",
    "BorrowApplication",
    "BorrowDetail",
    "BorrowTimeSlot",
    "PermissionResult",
    "RowTicket",
    "VenueOccupancySlot",
    "STATUS_APPROVED",
    "STATUS_REJECTED",
    "STATUS_SAVED",
    "STATUS_SUBMITTED",
    "_parse_dt",
    "_parse_hlddct",
    "_fmt_dt",
    "_to_int",
    "build_booking",
]
