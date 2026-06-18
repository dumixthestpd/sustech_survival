"""
sustech_survival.selectcourse.selectcourse — Live client for TIS course browsing.

ONE class. ALL read operations on the 选课 catalog and your enrolled courses.

Architecture mirrors classroom.ClassroomOccupancy — same auth, same cache,
same TIS campus_schedule endpoint. The difference: this client is
course-centric (one row per offering), not room-centric.

Endpoints used:
    Xsxktz/queryRwxxcxList          — public course catalog (any xq, including
                                       summer xq=3)
    xszykb/queryxszykbzong           — your enrolled courses for a semester
    xszykb/queryxszykbzhou           — your enrolled courses for a specific week

The WRITE side (AddMeeting/Submit equivalent for course enrollment) is
gated behind a Vue component and not yet wrapped — see
references/tis-api.md for the open question.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Dict, List, Optional

import requests

from .schema import Course


TIS_BASE = "https://tis.sustech.edu.cn"
TIS_CAMPUS_SCHEDULE_URL = f"{TIS_BASE}/Xsxktz/queryRwxxcxList"
TIS_PERSONAL_SCHEDULE_URL = f"{TIS_BASE}/xszykb/queryxszykbzong"
TIS_PERSONAL_WEEK_URL = f"{TIS_BASE}/xszykb/queryxszykbzhou"
DEFAULT_TTL = 3600


def _tis_login(username: str, password: str) -> requests.Session:
    """Manual TIS CAS login (avoids the LegacyAdapter urllib3 bug)."""
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
    return sess


class SelectCourseClient:
    """TIS course selection helper — read side.

    Provides catalog browse (any xq) and personal enrollment lookup.
    Write side (AddCourse / DropCourse) is NOT wrapped — see the SKILL
    notes for the open question.
    """

    BASE_URL = TIS_BASE

    def __init__(self, *, xn: str = "2025-2026", xq: str = "2",
                 max_age: int = DEFAULT_TTL,
                 skill_root: Optional[Path] = None):
        self.xn = xn
        self.xq = xq
        self.max_age = max_age
        self.skill_root = skill_root or (
            Path.home() / ".openclaw" / "workspace" / "skills" / "sustech_survival"
        )
        self.cache_dir = self.skill_root / "selectcourse" / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._courses: Optional[List[Course]] = None

    # ── Cache management ─────────────────────────────────────────────────────

    def _cache_file(self) -> Path:
        return self.cache_dir / f"catalog_{self.xn}_{self.xq}.json"

    def _load_cache(self) -> Optional[List[Course]]:
        cf = self._cache_file()
        if not cf.exists():
            return None
        try:
            payload = json.loads(cf.read_text())
        except Exception:
            return None
        if time.time() - payload.get("saved_at", 0) > self.max_age:
            return None
        # Reconstruct Course objects (skip kcxx-derived fields — they'll
        # be re-parsed from the cached raw on demand).
        out: List[Course] = []
        for c in payload.get("courses", []):
            course = Course(
                code=c["code"], name=c["name"], name_en=c["name_en"],
                class_group=c["class_group"], rwh=c["rwh"],
                college=c["college"], category=c["category"],
                nature=c["nature"], campus=c["campus"],
                credits=c["credits"], total_hours=c["total_hours"],
                capacity=c.get("capacity"), undergrad_seats=c.get("undergrad_seats"),
                grad_seats=c.get("grad_seats"),
                cultivation=c["cultivation"],
                rooms=c["rooms"], teachers=c["teachers"],
                slots_raw=c["slots_raw"],
            )
            out.append(course)
        return out

    def _save_cache(self, courses: List[Course]) -> None:
        cf = self._cache_file()
        cf.write_text(json.dumps({
            "saved_at": time.time(),
            "courses": [
                {
                    "code": c.code, "name": c.name, "name_en": c.name_en,
                    "class_group": c.class_group, "rwh": c.rwh,
                    "college": c.college, "category": c.category,
                    "nature": c.nature, "campus": c.campus,
                    "credits": c.credits, "total_hours": c.total_hours,
                    "capacity": c.capacity, "undergrad_seats": c.undergrad_seats,
                    "grad_seats": c.grad_seats, "cultivation": c.cultivation,
                    "rooms": c.rooms, "teachers": c.teachers,
                    "slots_raw": c.slots_raw,
                }
                for c in courses
            ],
        }, ensure_ascii=False))

    # ── Catalog fetch ────────────────────────────────────────────────────────

    def _fetch_catalog(self) -> List[Course]:
        """Pull the full campus schedule for this xn/xq and parse as Courses."""
        from sustech_survival.sso import Authorizer
        creds = Authorizer(skill_dir=str(self.skill_root))
        uname, pw = creds.read_creds()
        sess = _tis_login(uname, pw)
        sess.headers["X-Requested-With"] = "XMLHttpRequest"

        all_items: List[dict] = []
        page_size = 500
        for pg in range(1, 10):
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

        courses = [Course.from_api(item) for item in all_items]
        return courses

    def _ensure_loaded(self) -> List[Course]:
        if self._courses is not None:
            return self._courses
        cached = self._load_cache()
        if cached is not None:
            self._courses = cached
            return cached
        courses = self._fetch_catalog()
        self._courses = courses
        self._save_cache(courses)
        return courses

    def refresh(self) -> int:
        """Force-fetch from TIS. Returns the new course count."""
        courses = self._fetch_catalog()
        self._courses = courses
        self._save_cache(courses)
        return len(courses)

    # ── Queries ──────────────────────────────────────────────────────────────

    def list_courses(self, *, keyword: str = "",
                     cultivation: Optional[str] = None,
                     college: Optional[str] = None,
                     nature: Optional[str] = None,
                     campus: Optional[str] = None) -> List[Course]:
        """List course offerings with optional filters.

        `cultivation`: "本科" (1) or "研究生" (2) — matches the pylx field.
        All other filters are case-insensitive substring matches.
        """
        courses = self._ensure_loaded()
        out: List[Course] = []
        kw = keyword.lower().strip() if keyword else ""
        for c in courses:
            if kw:
                hay = " ".join([c.code, c.name, c.name_en, c.rwh,
                                c.college, c.category]).lower()
                if kw not in hay:
                    continue
            if cultivation and cultivation not in c.cultivation:
                continue
            if college and college.lower() not in c.college.lower():
                continue
            if nature and nature not in c.nature:
                continue
            if campus and campus not in c.campus:
                continue
            out.append(c)
        return out

    def by_code(self, code: str, class_group: str = "") -> Optional[Course]:
        """Find a course by code (and optionally class_group)."""
        code_l = code.strip().lower()
        for c in self._ensure_loaded():
            if c.code.lower() != code_l:
                continue
            if class_group and c.class_group != class_group:
                continue
            return c
        return None

    # ── Personal enrollment ──────────────────────────────────────────────────

    def my_courses(self, semester: Optional[str] = None) -> List[dict]:
        """Your enrolled courses for a semester.

        `semester`: "2025-2026-2" or "2025-2026-3" (summer). Defaults to
        the current client's xn/xq.

        Returns raw dicts from the xszykb API (no kcxx parsing — these
        are already your personal schedule items).
        """
        if semester:
            parts = semester.split("-")
            if len(parts) != 3:
                raise ValueError(f"semester must be 'YYYY-YYYY-N', got {semester!r}")
            xn = f"{parts[0]}-{parts[1]}"
            xq = parts[2]
        else:
            xn, xq = self.xn, self.xq

        from sustech_survival.sso import Authorizer
        creds = Authorizer(skill_dir=str(self.skill_root))
        uname, pw = creds.read_creds()
        sess = _tis_login(uname, pw)
        sess.headers["X-Requested-With"] = "XMLHttpRequest"

        r = sess.post(TIS_PERSONAL_SCHEDULE_URL,
                      data={"xn": xn, "xq": xq}, timeout=15)
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []

    def enrolled_rwhs(self, semester: Optional[str] = None) -> set:
        """Set of `rwh` strings for the courses you're enrolled in.

        Useful for cross-referencing with `list_courses()` — find which
        catalog courses you've already signed up for.
        """
        rwhs = set()
        for item in self.my_courses(semester):
            rwh = item.get("RWH") or item.get("rwh")
            if rwh:
                rwhs.add(rwh)
        return rwhs


# ── Singleton factory ────────────────────────────────────────────────────────


def selectcourse(*, xn: str = "2025-2026", xq: str = "2",
                 max_age: int = DEFAULT_TTL) -> SelectCourseClient:
    """Module-level factory. Defaults to current Spring semester.

    Pass `xq="3"` for summer.
    """
    return SelectCourseClient(xn=xn, xq=xq, max_age=max_age)
