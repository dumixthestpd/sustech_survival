"""
sustech_survival.classroom.live — TIS 场地课表 (per-room live schedule) client.

The current classroom module derives occupancy from the public course
catalog (Xsxktz/queryRwxxcxList → kcxx HTML parse). It misses all
borrowings (借用 = TA tutor sessions, study groups, recruitment events,
etc.) because those are NOT in the public catalog — they're created
through TIS's hidden 选择场地 dialog and stored against a `cdkb`
(场地课表) table.

This module queries that hidden table via `cdkb/querycdkbList` and
returns both registered courses AND borrowings as a unified schedule.

Endpoint (verified 2026-06-28):
    POST https://tis.sustech.edu.cn/cdkb/querycdkbList
    Body: {cddm: <room_code>, xn: <year>, xq: <1|2|3>}
    Header: RoleCode: '00'  (any value, server only checks presence)

Response: list of entries with fields:
    KCDM    — course code, or 'jy' for 借用 (borrowing)
    SKSJ    — schedule text. For borrowings: "【借用】[N周]\\n使用人:NAME\\n联系电话:PHONE".
              For courses: "【本/研/研本】COURSE_NAME[TEACHER][GROUP][N周][J1-J2节]".
    SKSJ_EN — purpose / English description
    XB      — internal sequence id (stable per entry, not the week)
    KEY     — "xq{WEEKDAY}_jc{PERIOD}" — slot in the schedule grid
              (weekday 1-7, period 1-12). Multiple entries can share a KEY
              (different weeks, same day/period).

Public API:
    from sustech_survival.classroom.live import (
        LiveOccupancyClient, RoomScheduleEntry,
        parse_sksj, parse_key, current_semester, now_to_tis_slot,
    )

    client = LiveOccupancyClient()
    entries = client.query_room("YJ-123", xn="2025-2026", xq="2")
    now_occupied = client.now_occupied(cddm="YJ-123")  # checks current time

The schedule data is cached to disk per (cddm, xn, xq) with a 1-hour TTL,
so live occupancy queries are O(1) after the first hit per room.

Auth: handled by `sustech_survival.sso.TISAuth` (raw CAS login — same
bypass as the rest of the classroom module).
"""
from __future__ import annotations

import datetime as dt
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

from .schema import DAY_NAMES_ZH
from sustech_survival.semester import Semester


# ── Endpoints ────────────────────────────────────────────────────────────────

TIS_BASE = "https://tis.sustech.edu.cn"
TIS_QUERY_ROOM_SCHEDULE_URL = f"{TIS_BASE}/cdkb/querycdkbList"
TIS_DQ_XNXQ_URL = f"{TIS_BASE}/component/dq_xnxq"

DEFAULT_TTL = 3600  # 1 hour


# ── Manual TIS CAS login (mirrors classroom.py) ─────────────────────────────


def _tis_login(username: str, password: str) -> Tuple[requests.Session, dict]:
    """Fresh CAS login for TIS, bypassing the LegacyAdapter urllib3 bug."""
    sess = requests.Session()
    sess.headers["User-Agent"] = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    SERVICE = f"{TIS_BASE}/cas"
    r = sess.get("https://cas.sustech.edu.cn/cas/login",
                 params={"service": SERVICE}, timeout=10)
    m = re.search(r'name="execution" value="([^"]+)"', r.text)
    if not m:
        raise RuntimeError("No execution token at CAS login page.")
    exec_token = m.group(1)

    r = sess.post("https://cas.sustech.edu.cn/cas/login",
                  params={"service": SERVICE},
                  data={"username": username, "password": password,
                        "execution": exec_token, "_eventId": "submit",
                        "submit": ""},
                  allow_redirects=False, timeout=10)
    if r.status_code not in (301, 302):
        raise RuntimeError(f"CAS POST failed: HTTP {r.status_code}")
    ticket_url = r.headers.get("Location", "")
    if "ticket=" not in ticket_url:
        raise RuntimeError("CAS did not return a ticket.")
    sess.get(ticket_url, allow_redirects=True, timeout=10)

    cookies = {c.name: c.value for c in sess.cookies}
    return sess, cookies


# ── Parsing ──────────────────────────────────────────────────────────────────


# Extract [N周] or [N1-N2周] from SKSJ text.
# Matches: "[17周]", "[1-15周]", "[9周]", "[1,3,5周]" (rare)
_SKSJ_WEEK_RE = re.compile(r"\[([0-9,\-]+)周\]")

# Extract 使用人:NAME
_SKSJ_USER_RE = re.compile(r"使用人[:：]([^\n]+)")
# Extract 联系电话:PHONE
_SKSJ_PHONE_RE = re.compile(r"联系电话[:：]([0-9\-\s]+)")
# Extract the 【...】 prefix: 【借用】、【本】、【研】、【研本】
_SKSJ_TYPE_RE = re.compile(r"^【(借用|本|研|研本|本研|其他)】")
# Extract course name [course_name][teacher][group]
_SKSJ_COURSE_NAME_RE = re.compile(r"【[^\]]+】([^\[\n]+)\[")

# KEY → (weekday, period)
_KEY_RE = re.compile(r"^xq(\d+)_jc(\d+)$")


def parse_key(key: str) -> Optional[Tuple[int, int]]:
    """Parse 'xq{W}_jc{P}' → (weekday, period). Returns None on bad format."""
    if not key:
        return None
    m = _KEY_RE.match(key)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def parse_sksj(sksj: str) -> dict:
    """Parse SKSJ text into a structured dict.

    Returns dict with:
        type — 'borrowing' (借用) | 'undergrad' (本) | 'grad' (研)
               | 'mixed' (研本/本研) | 'unknown'
        weeks — list[int] of applicable weeks (expanded from patterns like
                '1-15', '1,3,5', '1-9,11-15')
        borrower — str | None (for 借用)
        phone — str | None (for 借用)
        course_name — str | None (for courses)
        raw — str (the original SKSJ text, for display)

    The function is defensive — any missing field returns the default
    rather than raising.
    """
    if not sksj:
        return {
            "type": "unknown", "weeks": [],
            "borrower": None, "phone": None,
            "course_name": None, "raw": "",
        }

    # Type from 【...】 prefix
    m = _SKSJ_TYPE_RE.search(sksj)
    if m:
        type_str = m.group(1)
        if type_str == "借用":
            entry_type = "borrowing"
        elif type_str in ("本",):
            entry_type = "undergrad"
        elif type_str in ("研",):
            entry_type = "grad"
        elif type_str in ("研本", "本研"):
            entry_type = "mixed"
        else:
            entry_type = "unknown"
    else:
        entry_type = "unknown"

    # Weeks from [N周]
    weeks: List[int] = []
    m = _SKSJ_WEEK_RE.search(sksj)
    if m:
        weeks = _expand_week_pattern(m.group(1))

    # Borrower info (for 借用)
    borrower = None
    phone = None
    m = _SKSJ_USER_RE.search(sksj)
    if m:
        borrower = m.group(1).strip()
    m = _SKSJ_PHONE_RE.search(sksj)
    if m:
        phone = m.group(1).strip()

    # Course name (for registered courses)
    course_name = None
    if entry_type != "borrowing":
        m = _SKSJ_COURSE_NAME_RE.search(sksj)
        if m:
            course_name = m.group(1).strip()

    return {
        "type": entry_type,
        "weeks": weeks,
        "borrower": borrower,
        "phone": phone,
        "course_name": course_name,
        "raw": sksj,
    }


def _expand_week_pattern(s: str) -> List[int]:
    """Expand '1-15' / '3,7,9' / '1-9,11-15' → sorted unique week ints.

    Mirrors the schema.expand_weeks logic but lives here to avoid an
    import cycle.
    """
    out: List[int] = []
    for chunk in s.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            try:
                a, b = chunk.split("-", 1)
                a, b = int(a), int(b)
                if a <= b:
                    out.extend(range(a, b + 1))
                else:
                    out.extend(range(b, a + 1))
            except (ValueError, TypeError):
                continue
        else:
            try:
                out.append(int(chunk))
            except (ValueError, TypeError):
                continue
    return sorted(set(out))


# ── Dataclasses ──────────────────────────────────────────────────────────────


@dataclass
class RoomScheduleEntry:
    """One schedule entry for a room — either a registered course or a borrowing."""
    raw: dict                          # full API response
    cddm: str                          # room code (e.g. "YJ-123")
    weekday: int                       # 1-7
    period_start: int                  # 1-12 (TIS period index)
    weeks: List[int]                   # expanded list of weeks
    type: str                          # "borrowing" | "undergrad" | "grad" | "mixed" | "unknown"
    borrower: Optional[str] = None
    phone: Optional[str] = None
    course_code: Optional[str] = None
    course_name: Optional[str] = None
    purpose: Optional[str] = None       # SKSJ_EN — English description / purpose
    sksj_text: str = ""                # original SKSJ text

    @property
    def is_borrowing(self) -> bool:
        return self.type == "borrowing"

    @property
    def is_course(self) -> bool:
        return self.type in ("undergrad", "grad", "mixed")

    def active_on(self, week: int, weekday: int) -> bool:
        """Is this entry active on (week, weekday)?"""
        return weekday == self.weekday and week in self.weeks

    @classmethod
    def from_api(cls, raw: dict, *, cddm: str) -> Optional["RoomScheduleEntry"]:
        if not raw:
            return None
        key = raw.get("KEY", "")
        parsed_key = parse_key(key)
        if not parsed_key:
            return None
        weekday, period = parsed_key
        parsed = parse_sksj(raw.get("SKSJ") or "")
        return cls(
            raw=raw,
            cddm=cddm,
            weekday=weekday,
            period_start=period,
            weeks=parsed["weeks"],
            type=parsed["type"],
            borrower=parsed["borrower"],
            phone=parsed["phone"],
            course_code=raw.get("KCDM"),
            course_name=parsed["course_name"],
            purpose=raw.get("SKSJ_EN"),
            sksj_text=raw.get("SKSJ") or "",
        )

    @property
    def when_str(self) -> str:
        """Pretty '1-15周 周一 第3节'."""
        weeks = self.weeks
        if not weeks:
            week_str = "?"
        elif len(weeks) == 1:
            week_str = f"{weeks[0]}"
        elif weeks == list(range(weeks[0], weeks[-1] + 1)):
            week_str = f"{weeks[0]}-{weeks[-1]}"
        else:
            week_str = ",".join(str(w) for w in weeks)
        day = DAY_NAMES_ZH[self.weekday] if 1 <= self.weekday <= 7 else f"day{self.weekday}"
        return f"{week_str}周 {day} 第{self.period_start}节"

    def to_markdown(self) -> str:
        """Compact markdown rendering for CLI output."""
        if self.is_borrowing:
            who = f"{self.borrower or '?'} ({self.phone or '?'})"
            purpose = (self.purpose or "").strip()
            purpose_str = f" — {purpose}" if purpose else ""
            return f"🔑 **{self.when_str}** 借用 · {who}{purpose_str}"
        # Course
        cname = self.course_name or self.course_code or "?"
        ccode = self.course_code or "?"
        purpose = (self.purpose or "").strip()
        purpose_str = f" — {purpose}" if purpose else ""
        return f"📚 **{self.when_str}** {ccode} {cname}{purpose_str}"


# ── Current time → TIS format ────────────────────────────────────────────────


# SUSTech period schedule (verified from /tmp/didian_bundle.js / period field).
# Each period is a 45-min block with a 10-min break. Returns (start, end) as
# (start_period, end_period) — same period index if the time falls within
# one block, or a range if it spans.
PERIOD_TIMES = [
    # (period_start_hour, period_start_min, period_end_hour, period_end_min)
    (0, 0, 0, 0),        # 0 placeholder
    (8, 0, 8, 45),       # 1
    (8, 55, 9, 40),      # 2
    (10, 0, 10, 45),     # 3
    (10, 55, 11, 40),    # 4
    (14, 0, 14, 45),     # 5
    (14, 55, 15, 40),    # 6
    (16, 0, 16, 45),     # 7
    (16, 55, 17, 40),    # 8
    (19, 0, 19, 45),     # 9
    (19, 55, 20, 40),    # 10
    (20, 50, 21, 35),    # 11
    (21, 45, 22, 30),    # 12
]


def current_period(time_h: int, time_m: int) -> Optional[int]:
    """Map an (hour, minute) clock time → TIS period (1-12), or None if outside class hours."""
    if time_h < 8 or time_h >= 23:
        return None
    for p in range(1, 13):
        sh, sm, eh, em = PERIOD_TIMES[p]
        sh_total = sh * 60 + sm
        eh_total = eh * 60 + em
        now_total = time_h * 60 + time_m
        if sh_total <= now_total <= eh_total:
            return p
    # If between periods, snap to the next upcoming period if within 10 min
    for p in range(1, 13):
        sh, sm, _, _ = PERIOD_TIMES[p]
        sh_total = sh * 60 + sm
        now_total = time_h * 60 + time_m
        if 0 <= sh_total - now_total <= 10:
            return p
    return None


def current_semester(sess: requests.Session) -> Semester:
    """Query TIS for the current academic year + semester. Returns a Semester."""
    r = sess.post(TIS_DQ_XNXQ_URL, headers={"RoleCode": "00"}, timeout=15)
    r.raise_for_status()
    data = r.json()
    content = data.get("content") or {}
    xn = content.get("XN") or "2025-2026"
    xq = content.get("XQ") or "2"
    return Semester(xn, xq)


def current_weekday_and_period(now: Optional[dt.datetime] = None) -> Tuple[int, Optional[int]]:
    """Return (weekday 1-7, period 1-12 or None) for `now` (default: local time)."""
    if now is None:
        now = dt.datetime.now()
    weekday = now.isoweekday()  # 1=Mon ... 7=Sun
    period = current_period(now.hour, now.minute)
    return weekday, period


# ── Semester week inference ─────────────────────────────────────────────────
#
# TIS does NOT expose a "what week is today" endpoint to student sessions
# (verified 2026-06-28: `component/queryRlZcSj` returns empty `{}`,
# `cdkb/queryRlZcSj` is 404, brute-probed ~20 candidates — all dead).
# So we infer the week from the public academic calendar in
# `sustech_survival.context.ACADEMIC_CALENDARS`, with a critical fix:
#
#   TIS weeks are numbered from the FIRST FULL Mon-Sun week that follows
#   (or contains) the first class day. If the semester officially starts
#   on a Tuesday (e.g. 2026-02-24), TIS still calls the NEXT Monday
#   "week 1" — the days Tue-Sun before it are "week 0" (orientation /
#   registration / pre-class). The borrowings data spans weeks 1-17 with
#   no entries in week 0, confirming this.
#
# Verified 2026-06-28 (Sunday):
#   - Borrowings for YJ-123 span weeks 1-17 (max week = 17, no week 0).
#   - Today (Jun 28) is the last day of week 17.
#   - With the "round UP to next Monday" rule: week 17. Confirmed.
#   - Spring 2026 `semester_start` = Tue Feb 24 → anchor = Mon Mar 2.
#   - days = (Jun 28 - Mar 2) = 118; 118 // 7 + 1 = 17. ✓

def _first_full_week_start(semester_start: dt.date) -> dt.date:
    """The Monday that begins TIS week 1.

    If `semester_start` is already a Monday, that's the anchor.
    Otherwise, TIS week 1 starts on the NEXT Monday (the days before it
    are "week 0" / pre-class — counted as week 1 for the `now` query but
    not in the borrowings data).
    """
    # weekday(): Mon=0 ... Sun=6
    wd = semester_start.weekday()
    if wd == 0:
        return semester_start
    # Round UP: add (7 - wd) days to land on next Monday
    return semester_start + dt.timedelta(days=(7 - wd))


def current_week(
    xn: str,
    xq: str,
    today: Optional[dt.date] = None,
    *,
    acal: Optional[Dict[str, Dict]] = None,
) -> Optional[int]:
    """Compute current semester week (1-18) from the academic calendar.

    Args:
        xn: academic year (e.g. "2025-2026").
        xq: semester code ("1", "2", or "3" for summer).
        today: date to compute for (default: today, local time).
        acal: override for `ACADEMIC_CALENDARS` (testing).

    Returns:
        Week number 1-18, or None if:
          - The (xn, xq) is not in the academic calendar
          - Today is before `semester_start` (no classes yet)
          - Today is after `semester_end` (semester over — use
            `summer_start` instead, or pass `--week` explicitly)
    """
    if acal is None:
        try:
            from sustech_survival.context import ACADEMIC_CALENDARS as _ACAL
        except ImportError:
            return None
        acal = _ACAL

    if today is None:
        today = dt.date.today()

    # Map (xn, xq) → calendar key. TIS uses "2025-2026" + "1"/"2"/"3".
    # The ACADEMIC_CALENDARS table is keyed by "2026 Spring" / "2025 Fall"
    # / "2026 Summer" (label-based) — there's no summer entry yet.
    # Build a reverse map: (xn, xq) → calendar entry.
    label_for: Dict[Tuple[str, str], str] = {}
    for label, cal in acal.items():
        parts = label.split()
        if len(parts) != 2:
            continue
        try:
            y0 = int(parts[0])
        except ValueError:
            continue
        season = parts[1]
        if season == "Fall":
            label_for[(f"{y0}-{y0 + 1}", "1")] = label
        elif season == "Spring":
            label_for[(f"{y0 - 1}-{y0}", "2")] = label
        elif season == "Summer":
            label_for[(f"{y0 - 1}-{y0}", "3")] = label

    label = label_for.get((xn, xq))
    if label is None:
        return None
    cal = acal[label]

    start = dt.datetime.strptime(cal["semester_start"], "%Y-%m-%d").date()
    end = dt.datetime.strptime(cal["semester_end"], "%Y-%m-%d").date()
    if not (start <= today <= end):
        return None

    anchor = _first_full_week_start(start)
    if today < anchor:
        # Today is in the partial first week (e.g. Tue Feb 24 - Sun Mar 1
        # for Spring 2026). Count it as week 1 — that's the first week
        # of classes, even if it's a partial Mon-Sun week.
        return 1

    # Spring-break adjustment: if today is in spring_break, snap to the
    # week that contains the START of the break. Without this, the
    # formula would over-count by 1 after a multi-day break spans two
    # calendar weeks (e.g. Qingming Apr 4-12 spans the Mon-Sun week of
    # Apr 6-12 AND the week before).
    spring_break = cal.get("spring_break")
    if spring_break:
        sb_start_str, sb_end_str = spring_break
        sb_start = dt.datetime.strptime(sb_start_str, "%Y-%m-%d").date()
        sb_end = dt.datetime.strptime(sb_end_str, "%Y-%m-%d").date()
        if sb_start <= today <= sb_end:
            sb_days = (sb_start - anchor).days
            if sb_days < 0:
                return 1
            return sb_days // 7 + 1

    days = (today - anchor).days
    return days // 7 + 1


# ── Client ───────────────────────────────────────────────────────────────────


class LiveOccupancyClient:
    """Live per-room schedule from TIS 场地课表 (cdkb).

    Cache: stored at <skill_root>/classroom/cache/live_<xn>_<xq>_<cddm>.json
    Default TTL: 3600s.
    """

    BASE_URL = TIS_BASE

    def __init__(self, *, max_age: int = DEFAULT_TTL, skill_root: Optional[Path] = None):
        self.max_age = max_age
        self.skill_root = skill_root or (
            Path.home() / ".openclaw" / "workspace" / "skills" / "sustech_survival"
        )
        self.cache_dir = self.skill_root / "classroom" / "cache" / "live"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._sess: Optional[requests.Session] = None

    # ── Session management ──────────────────────────────────────────────────

    def _ensure_session(self) -> requests.Session:
        if self._sess is not None:
            return self._sess
        # Let Authorizer resolve skill_dir from credentials.txt location
        # (don't override with our cache path — we don't ship credentials).
        from sustech_survival.sso import Authorizer
        creds = Authorizer()
        uname, pw = creds.read_creds()
        sess, _ = _tis_login(uname, pw)
        sess.headers["X-Requested-With"] = "XMLHttpRequest"
        self._sess = sess
        return sess

    # ── Cache ──────────────────────────────────────────────────────────────

    def _cache_file(self, cddm: str, xn: str, xq: str) -> Path:
        return self.cache_dir / f"{xn}_{xq}_{cddm}.json"

    def _load_cache(self, cddm: str, xn: str, xq: str) -> Optional[List[RoomScheduleEntry]]:
        cf = self._cache_file(cddm, xn, xq)
        if not cf.exists():
            return None
        try:
            payload = json.loads(cf.read_text())
        except Exception:
            return None
        if time.time() - payload.get("saved_at", 0) > self.max_age:
            return None
        return [RoomScheduleEntry(**e) for e in payload.get("entries", [])]

    def _save_cache(self, cddm: str, xn: str, xq: str,
                    entries: List[RoomScheduleEntry]) -> None:
        cf = self._cache_file(cddm, xn, xq)
        cf.write_text(json.dumps({
            "saved_at": time.time(),
            "entries": [e.__dict__ for e in entries],
        }, ensure_ascii=False))

    # ── Fetch ──────────────────────────────────────────────────────────────

    def query_room(self, cddm: str, *, xn: str, xq: str,
                   use_cache: bool = True) -> List[RoomScheduleEntry]:
        """Fetch all schedule entries for one room from TIS 场地课表.

        `cddm` is the room code (e.g. 'YJ-123'). xn/xq select the semester.
        Returns a list of RoomScheduleEntry (parsed from API).
        """
        if use_cache:
            cached = self._load_cache(cddm, xn, xq)
            if cached is not None:
                return cached

        sess = self._ensure_session()
        r = sess.post(TIS_QUERY_ROOM_SCHEDULE_URL,
                      data={"cddm": cddm, "xn": xn, "xq": xq},
                      headers={"RoleCode": "00"}, timeout=30)
        r.raise_for_status()
        raw_list = r.json() or []
        entries: List[RoomScheduleEntry] = []
        for raw in raw_list:
            entry = RoomScheduleEntry.from_api(raw, cddm=cddm)
            if entry:
                entries.append(entry)

        # Always persist to disk — `use_cache=False` just means "skip the
        # load step", not "skip the write". Refresh should refresh the
        # cache.
        self._save_cache(cddm, xn, xq, entries)
        return entries

    def refresh(self, cddm: str, *, xn: str, xq: str) -> List[RoomScheduleEntry]:
        """Force-refresh the cache for one room."""
        return self.query_room(cddm, xn=xn, xq=xq, use_cache=False)

    # ── Live queries ───────────────────────────────────────────────────────

    def live_at(self, cddm: str, *, week: int, weekday: int,
                xn: str, xq: str) -> List[RoomScheduleEntry]:
        """Entries active at (week, weekday) in a given room."""
        return [e for e in self.query_room(cddm, xn=xn, xq=xq)
                if e.active_on(week, weekday)]

    def live_during_period(self, cddm: str, *, week: int, weekday: int,
                           period: int, xn: str, xq: str) -> List[RoomScheduleEntry]:
        """Entries active at (week, weekday, period) in a given room."""
        return [e for e in self.live_at(cddm, week=week, weekday=weekday,
                                         xn=xn, xq=xq)
                if e.period_start == period]

    def now_occupied(self, cddm: str, *, week: int,
                     xn: Optional[str] = None, xq: Optional[str] = None
                     ) -> List[RoomScheduleEntry]:
        """Entries currently occupying this room (now = current weekday/period).

        If `xn`/`xq` are None, queries TIS for the current semester via
        `dq_xnxq`. If `period` is None (outside class hours), returns [].
        """
        sess = self._ensure_session()
        if xn is None or xq is None:
            sem = current_semester(sess)
            xn, xq = sem.xn, sem.xq
        weekday, period = current_weekday_and_period()
        if period is None:
            return []
        return self.live_during_period(cddm, week=week, weekday=weekday,
                                       period=period, xn=xn, xq=xq)


# ── Singleton ────────────────────────────────────────────────────────────────


_client: Optional[LiveOccupancyClient] = None


def live() -> LiveOccupancyClient:
    """Module-level singleton. Lazy-initializes on first call."""
    global _client
    if _client is None:
        _client = LiveOccupancyClient()
    return _client