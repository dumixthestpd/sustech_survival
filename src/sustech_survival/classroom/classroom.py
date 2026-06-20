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

from .schema import Room, ScheduleSlot


# ── TIS endpoints (mirrors tis/campus_schedule.py) ───────────────────────────

TIS_BASE = "https://tis.sustech.edu.cn"
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
                 max_age: int = DEFAULT_TTL, skill_root: Optional[Path] = None):
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


# ── Singleton ────────────────────────────────────────────────────────────────


def classroom(*, xn: str = "2025-2026", xq: str = "2",
              max_age: int = DEFAULT_TTL) -> ClassroomOccupancy:
    """Module-level factory. Returns a ClassroomOccupancy for the given semester.

    Default semester is 2025-2026 Spring (xq=2). Override with kwargs.
    """
    return ClassroomOccupancy(xn=xn, xq=xq, max_age=max_age)
