"""
sustech_survival.classroom.classroom — Live client for TIS 全校课表 reverse view.

ONE class. ALL operations. ZERO local data — every call hits the live TIS
server (with on-disk JSON cache, 1h TTL by default).

Architecture mirrors `sustech_survival.booking.BookingClient`:
    ClassroomOccupancy             ← one client, all the methods
        .rooms()                       → list of unique rooms (with capacity)
        .room_by_name(name)            → single Room (fuzzy match)
        .slots_for_room(name)          → all ScheduleSlots in a given room
        .occupancy(room, week, day)    → what's happening in this room on this day
        .free(week, day, pstart, pend) → rooms free during this timeslot

The full campus schedule (~1499 courses × N slots) is fetched once, parsed
into ScheduleSlots, and indexed. Subsequent queries are O(1) dict lookups.

Cache: stored at <skill_root>/classroom/cache/schedule_<xn>_<xq>.json with
a timestamp. Default TTL: 3600s. Pass `max_age=0` to force a refresh.
"""
from __future__ import annotations

import json
import re
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

from .live import LiveOccupancyClient, RoomScheduleEntry, live as _live_default
from .schema import Room, ScheduleSlot


# ── TIS endpoints (mirrors tis/campus_schedule.py) ───────────────────────────

TIS_BASE = "https://tis.sustech.edu.cn"


# ── Building name aliases ────────────────────────────────────────────────────
#
# SUSTech renames teaching buildings occasionally. The TIS catalog keeps
# BOTH the old and new entries for a while (verified 2026-06-28: 智华楼
# and 三教 coexist as 56 + 56 entries with identical room numbers). To
# give users a single canonical spelling, normalize the prefix BEFORE
# looking up in the catalog. Any prefix in `BUILDING_ALIASES` is rewritten
# to its canonical form; non-matching prefixes pass through unchanged.
#
# Add new aliases here when a building is renamed. Order doesn't matter
# since aliases don't share prefixes (yet) — if they ever do, match
# longer prefixes first.
BUILDING_ALIASES: Dict[str, str] = {
    # 三教 renamed to 智华楼 (verified 2026-06-28). Self-aliases included
    # so the longest-prefix-first sort picks the canonical form when the
    # user types it directly (otherwise '智华楼102' would get rewritten to
    # '智华楼楼102' by the '智华' alias).
    "三教":   "智华楼",
    "智华":   "智华楼",
    "智华楼": "智华楼",
}


def normalize_room_name(name: str) -> str:
    """Rewrite the building prefix if it's in BUILDING_ALIASES.

    Examples (2026-06-28):
        '三教102'   → '智华楼102'
        '智华102'   → '智华楼102'
        '智华楼102' → '智华楼102'   (no-op)
        '一教324'   → '一教324'     (not aliased, pass through)
    """
    n = name.strip()
    # Iterate longest-prefix first so '智华楼' beats '智华' and doesn't
    # double-up (e.g. '智华楼102' would otherwise become '智华楼楼102').
    for old in sorted(BUILDING_ALIASES, key=len, reverse=True):
        new = BUILDING_ALIASES[old]
        if n.startswith(old):
            return new + n[len(old):]
    return n


TIS_CAMPUS_SCHEDULE_URL = f"{TIS_BASE}/Xsxktz/queryRwxxcxList"
DEFAULT_TTL = 3600  # 1 hour


# ── Manual TIS CAS login (avoids LegacyAdapter urllib3 bug) ─────────────────


def _tis_login(username: str, password: str) -> Tuple[requests.Session, dict]:
    """Perform a fresh CAS login for TIS and return (session, cookies)."""
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


# ── Client ───────────────────────────────────────────────────────────────────


class ClassroomOccupancy:
    """Reverse view of TIS 全校课表: room-centric queries."""

    BASE_URL = TIS_BASE

    def __init__(self, *, xn: str = "2025-2026", xq: str = "2",
                 max_age: int = DEFAULT_TTL, skill_root: Optional[Path] = None,
                 live_client: Optional[LiveOccupancyClient] = None):
        self.xn = xn
        self.xq = xq
        self.max_age = max_age
        self.skill_root = skill_root or (
            Path.home() / ".openclaw" / "workspace" / "skills" / "sustech_survival"
        )
        self.cache_dir = self.skill_root / "classroom" / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._slots: Optional[List[ScheduleSlot]] = None
        self._rooms: Optional[Dict[str, Room]] = None
        self._live_client: LiveOccupancyClient = live_client or _live_default()

    # ── Cache management ─────────────────────────────────────────────────────

    def _cache_file(self) -> Path:
        return self.cache_dir / f"schedule_{self.xn}_{self.xq}.json"

    def _load_cache(self) -> Optional[List[ScheduleSlot]]:
        cf = self._cache_file()
        if not cf.exists():
            return None
        try:
            payload = json.loads(cf.read_text())
        except Exception:
            return None
        if time.time() - payload.get("saved_at", 0) > self.max_age:
            return None
        # Reconstruct ScheduleSlot objects.
        out: List[ScheduleSlot] = []
        for s in payload.get("slots", []):
            out.append(ScheduleSlot(
                course_code=s["course_code"],
                course_name=s["course_name"],
                class_group=s["class_group"],
                weeks=s["weeks"],
                day=s["day"],
                period_start=s["period_start"],
                period_end=s["period_end"],
                room=s["room"],
            ))
        return out

    def _save_cache(self, slots: List[ScheduleSlot]) -> None:
        cf = self._cache_file()
        cf.write_text(json.dumps({
            "saved_at": time.time(),
            "slots": [
                {
                    "course_code": s.course_code, "course_name": s.course_name,
                    "class_group": s.class_group, "weeks": s.weeks,
                    "day": s.day, "period_start": s.period_start,
                    "period_end": s.period_end, "room": s.room,
                }
                for s in slots
            ],
        }, ensure_ascii=False))

    # ── Fetch ────────────────────────────────────────────────────────────────

    def _fetch_all_courses(self) -> List[dict]:
        """Fetch the full campus schedule via Xsxktz/queryRwxxcxList.

        Uses raw TIS CAS login (bypassing the LegacyAdapter in CASAuthorizer).
        """
        from sustech_survival.sso import Authorizer
        creds = Authorizer(skill_dir=str(self.skill_root))
        uname, pw = creds.read_creds()
        sess, _ = _tis_login(uname, pw)
        sess.headers["X-Requested-With"] = "XMLHttpRequest"

        # Paginate the full campus list (p_chaxunpylx='3' for ~1499 courses).
        all_items: List[dict] = []
        page_size = 500
        for pg in range(1, 10):  # safety cap: 10 pages × 500 = 5000
            params = {
                "p_xn": self.xn, "p_xq": self.xq, "p_xnxq": None, "p_gjz": "",
                "p_xiaoqu": "", "p_kkyx": "", "p_rwlx": "", "p_kclb": "",
                "p_kcxz": "", "p_chaxunpylx": "3",
                "pageNum": str(pg), "pageSize": str(page_size),
            }
            r = sess.post(TIS_CAMPUS_SCHEDULE_URL, data=params, timeout=30)
            r.raise_for_status()
            d = r.json()
            items = d.get("rwList", {}).get("list") or []
            all_items.extend(items)
            if len(items) < page_size:
                break
        return all_items

    def _ensure_loaded(self) -> List[ScheduleSlot]:
        if self._slots is not None:
            return self._slots
        cached = self._load_cache()
        if cached is not None:
            self._slots = cached
            return cached
        # Fetch fresh + parse + cache.
        items = self._fetch_all_courses()
        slots: List[ScheduleSlot] = []
        for course in items:
            slots.extend(ScheduleSlot.from_course_and_kcxx(course))
        self._slots = slots
        self._save_cache(slots)
        return slots

    def refresh(self) -> int:
        """Force-fetch from TIS. Returns the new slot count."""
        items = self._fetch_all_courses()
        slots: List[ScheduleSlot] = []
        for course in items:
            slots.extend(ScheduleSlot.from_course_and_kcxx(course))
        self._slots = slots
        self._save_cache(slots)
        self._rooms = None  # invalidate derived index
        return len(slots)

    # ── Derived indexes ──────────────────────────────────────────────────────

    def _build_rooms_index(self) -> Dict[str, Room]:
        """Build the room → Room map (with capacity + slot_count)."""
        if self._rooms is not None:
            return self._rooms
        slots = self._ensure_loaded()
        # Capacity comes from the course's jszws field — we lose it after
        # parsing. So we re-fetch capacities via a lightweight pass.
        # For now: best-effort capacity from course jszws is preserved by
        # rebuilding from the raw course list when capacity is requested.
        index: Dict[str, Room] = {}
        for s in slots:
            if s.room not in index:
                index[s.room] = Room(name=s.room, slot_count=0)
            index[s.room].slot_count += 1
        # Try to enrich capacity — fetch raw courses once.
        try:
            items = self._fetch_all_courses()
            for course in items:
                cap = course.get("jszws")
                if cap:
                    try:
                        capacity = int(cap)
                    except (ValueError, TypeError):
                        continue
                    for s in ScheduleSlot.from_course_and_kcxx(course):
                        if s.room in index and index[s.room].capacity is None:
                            index[s.room].capacity = capacity
        except Exception:
            pass
        self._rooms = index
        return index

    # ── Queries ──────────────────────────────────────────────────────────────

    def rooms(self, *, keyword: str = "") -> List[Room]:
        """All unique rooms (with slot counts and best-effort capacity).

        `keyword` filters by substring match against the room name.
        """
        rooms = list(self._build_rooms_index().values())
        if keyword:
            kw = keyword.lower()
            rooms = [r for r in rooms if kw in r.name.lower()]
        return sorted(rooms, key=lambda r: (-r.slot_count, r.name))

    def room_by_name(self, name: str) -> Optional[Room]:
        """Fuzzy match a single room by name. Returns the best match or None."""
        target = name.strip().lower()
        if not target:
            return None
        for room in self.rooms():
            if room.name.lower() == target:
                return room
        # Substring fallback
        matches = [r for r in self.rooms() if target in r.name.lower()]
        if len(matches) == 1:
            return matches[0]
        if matches:
            # Pick the one with most slots (most "active" room matching).
            return max(matches, key=lambda r: r.slot_count)
        return None

    def slots_for_room(self, name: str) -> List[ScheduleSlot]:
        """All ScheduleSlots in a given room, sorted by (day, period, week)."""
        target = name.strip().lower()
        slots = [s for s in self._ensure_loaded() if s.room.lower() == target]
        if not slots:
            # Try substring.
            slots = [s for s in self._ensure_loaded() if target in s.room.lower()]
        return sorted(slots, key=lambda s: (s.day, s.period_start, s.weeks[0] if s.weeks else 0))

    def occupancy(self, room_name: str, week: int, day: int) -> List[ScheduleSlot]:
        """What's happening in this room during `day` of `week`?

        Returns all slots active on (week, day) in the given room.
        """
        return [
            s for s in self.slots_for_room(room_name)
            if s.active_on(week, day)
        ]

    def free(self, week: int, day: int, period_start: int,
             period_end: Optional[int] = None) -> List[str]:
        """Rooms free during this timeslot (week, day, period range).

        Returns sorted list of room names NOT occupied during the slot.
        A room is "occupied" if any active slot overlaps the requested range.
        """
        if period_end is None:
            period_end = period_start
        slots = self._ensure_loaded()
        # Set of room names that have an active overlapping slot.
        busy = set()
        for s in slots:
            if s.day != day or week not in s.weeks:
                continue
            if s.overlaps(period_start, period_end):
                busy.add(s.room)
        all_rooms = {s.room for s in slots}
        return sorted(all_rooms - busy)

    # ── Live occupancy (cdkb/querycdkbList) ─────────────────────────────────

    def _init_live(self, *, live_client: Optional[LiveOccupancyClient] = None) -> None:
        """Wire up the live client (no-op after __init__ — kept for tests)."""
        if live_client is not None:
            self._live_client = live_client

    # ── Live bridge: room name → TIS code (cddm) ───────────────────────────

    def _query_didian_catalog(self) -> List[dict]:
        """Fetch all rooms from TIS 场地 (queryDiDian) — for name → code mapping.

        Returns the raw list of room dicts from the API. Cached for 1h.
        """
        cache_dir = self.skill_root / "classroom" / "cache" / "live"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cf = cache_dir / f"didian_{self.xn}_{self.xq}.json"
        if cf.exists():
            try:
                payload = json.loads(cf.read_text())
                if time.time() - payload.get("saved_at", 0) < self.max_age:
                    return payload.get("rooms", [])
            except Exception:
                pass

        sess = self._fetch_all_courses.__self__ if False else None
        # Use the live client session to query didian (shares the same TIS auth).
        live_sess = self._live_client._ensure_session()
        all_rooms: List[dict] = []
        for page in range(1, 15):
            params = [
                ("pylx", "1"),
                ("pageNum", str(page)),
                ("pageSize", "50"),
                ("xn", self.xn),
                ("xq", self.xq),
                ("hlct", "0"),
                ("hltyxct", "0"),
                ("sfjtjs", "2"),
                ("zysfkyd", "2"),
                ("jslx", ""),
                ("xiaoqu", "1"),
                ("lc", ""),
                ("kkyx", ""),
                ("key", ""),
                ("sybm", ""),
                ("mxid", "[]"),
                ("sfxsyxzws", "0"),
                ("yqzws", "0"),
                ("yqkszws", "0"),
                ("yxzws", "0"),
                ("yxkszws", "0"),
                ("bjrs", "0"),
                ("zws", "0"),
                ("kszws", "0"),
            ]
            r = live_sess.post(
                "https://tis.sustech.edu.cn/component/queryDiDian",
                data=params,
                headers={"RoleCode": "00"},
                timeout=60,
            )
            if not r.text.strip():
                break
            try:
                data = r.json()
            except Exception:
                break
            rooms = data.get("list", [])
            if not rooms:
                break
            all_rooms.extend(rooms)
            if len(all_rooms) >= data.get("total", 0):
                break
            time.sleep(0.3)
        cf.write_text(json.dumps({"saved_at": time.time(), "rooms": all_rooms},
                                ensure_ascii=False))
        return all_rooms

    def _room_code_for_name(self, name: str) -> Optional[str]:
        """Find the TIS 场地 code (dm) for a given room display name (mc).

        Uses queryDiDian's room catalog. Exact match on `mc` first, then
        substring. Returns None if not found.

        Building prefix is normalized via BUILDING_ALIASES first, so
        `三教102`, `智华102`, and `智华楼102` all resolve to the same room.
        """
        name_norm = normalize_room_name(name).strip().lower()
        rooms = self._query_didian_catalog()
        # Exact match on display name
        for r in rooms:
            if (r.get("mc") or "").strip().lower() == name_norm:
                return r.get("dm")
        # Substring match
        substring_matches = [r for r in rooms
                             if name_norm in (r.get("mc") or "").strip().lower()]
        if len(substring_matches) == 1:
            return substring_matches[0].get("dm")
        if substring_matches:
            # Pick the one with highest zws (largest room — likely the
            # "main" version of the named room, e.g. 一教 vs 一教A)
            return max(substring_matches, key=lambda r: int(r.get("zws") or 0)).get("dm")
        return None

    # ── Live queries ───────────────────────────────────────────────────────

    def live_entries_for_name(self, room_name: str) -> List[RoomScheduleEntry]:
        """All live schedule entries (courses + borrowings) for a room name.

        Resolves the name → TIS code via queryDiDian, then queries
        cdkb/querycdkbList. Returns [] if the name cannot be resolved.
        """
        cddm = self._room_code_for_name(room_name)
        if not cddm:
            return []
        return self._live_client.query_room(cddm, xn=self.xn, xq=self.xq)

    def live_occupancy(self, room_name: str, week: int, day: int) -> List[RoomScheduleEntry]:
        """Live entries active at (week, day) in the named room.

        Combines registered courses + borrowings (借用).
        """
        return [e for e in self.live_entries_for_name(room_name)
                if e.active_on(week, day)]

    def live_occupancy_at(self, room_name: str, week: int, day: int,
                          period: int) -> List[RoomScheduleEntry]:
        """Live entries active at (week, day, period) in the named room."""
        return [e for e in self.live_occupancy(room_name, week, day)
                if e.period_start == period]

    def live_rooms_occupied_at(self, *, week: int, day: int, period: int,
                               min_capacity: Optional[int] = None
                               ) -> List[Tuple[str, List[RoomScheduleEntry]]]:
        """All rooms occupied at (week, day, period) — by name.

        Walks every room in the didian catalog, queries cdkb, returns
        rooms that have an active entry. Slow first call (421 cdkb
        queries); cached on subsequent calls.
        """
        didian = self._query_didian_catalog()
        out = []
        for room in didian:
            mc = room.get("mc") or ""
            dm = room.get("dm") or ""
            if not dm:
                continue
            cap = int(room.get("zws") or 0)
            if min_capacity and cap < min_capacity:
                continue
            try:
                entries = self._live_client.query_room(dm, xn=self.xn, xq=self.xq)
            except Exception:
                continue
            hits = [e for e in entries
                    if e.active_on(week, day) and e.period_start == period]
            if hits:
                out.append((mc, hits))
        return out

    def live_rooms_free_at(self, *, week: int, day: int, period_start: int,
                           period_end: Optional[int] = None,
                           min_capacity: Optional[int] = None
                           ) -> List[str]:
        """All rooms free at (week, day, period range) — by name.

        Returns a sorted list of room names that have no entry overlapping
        the queried slot in cdkb. Slow first call (~421 queries, cached).
        """
        if period_end is None:
            period_end = period_start
        didian = self._query_didian_catalog()
        out = []
        for room in didian:
            mc = room.get("mc") or ""
            dm = room.get("dm") or ""
            if not dm:
                continue
            cap = int(room.get("zws") or 0)
            if min_capacity and cap < min_capacity:
                continue
            try:
                entries = self._live_client.query_room(dm, xn=self.xn, xq=self.xq)
            except Exception:
                continue
            busy = False
            for e in entries:
                if e.active_on(week, day):
                    if not (e.period_start > period_end or
                            e.period_start + 0 < period_start):
                        # e is a single-period entry — only checks period_start.
                        # For multi-period entries we'd need the underlying API
                        # to expose end period; for now this matches TIS's
                        # granularity.
                        busy = True
                        break
            if not busy:
                out.append(mc)
        return sorted(out)


# ── Singleton ────────────────────────────────────────────────────────────────


def classroom(*, xn: str = "2025-2026", xq: str = "2",
              max_age: int = DEFAULT_TTL,
              live_client: Optional[LiveOccupancyClient] = None) -> ClassroomOccupancy:
    """Module-level factory. Returns a ClassroomOccupancy for the given semester.

    Default semester is 2025-2026 Spring (xq=2). Override with kwargs.
    Pass `live_client` to inject a custom live client (mainly for tests).
    """
    return ClassroomOccupancy(xn=xn, xq=xq, max_age=max_age,
                              live_client=live_client)
