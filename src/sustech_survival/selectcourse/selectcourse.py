"""
sustech_survival.selectcourse.selectcourse — Read-side TIS client.

Orchestrator: catalog browse (any xq), personal enrollment lookup,
and (via `dry_run=False`) the 5 write methods in `writes.py`.

Architecture mirrors classroom.ClassroomOccupancy — same auth, same
cache, same TIS catalog endpoints. The difference: this client is
course-centric (one row per offering), not room-centric.

Files in this package (post-split, 2026-08-08):
  selectcourse.py (this file) — client orchestrator, cache, READ methods
  course.py                  — Course dataclass
  maps.py                    — CATEGORY_MAP, language_to_code, etc.
  endpoints.py               — TIS URL constants + XKTJZ_*
  queryform.py               — TIS wire-format payload builder (1 function)
  errors.py                  — EnrollmentError
  writes.py                  — 5 write methods + _post_xsxk helper
  ical.py                    — ICS calendar export (unchanged)
  __main__.py                — CLI entry (unchanged)
  __init__.py                — singleton + re-exports (unchanged)

Endpoints used (read side):
    Xsxktz/queryRwxxcxList          — public course catalog
    xszykb/queryxszykbzong          — your enrolled courses
    xszykb/queryxszykbzhou          — your enrolled courses for a week
    Xsxk/queryKxrw                  — 选课 search (personal)
    Xsxk/queryYxkc                  — course-type tabs
    Xsxk/queryXkdqXnxq              — current TIS active term

Write-side (add_course / drop_course / submit_bids / ...) lives in
`writes.py`. Every write defaults to `dry_run=True` and prints what
would be POSTed. Discovery doc: references/tis-api.md.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import List, Optional

from ..semester import Semester
from .course import Course
from .endpoints import (
    TIS_CAMPUS_SCHEDULE_URL,
    XKTJZ_TASK_TO_CART,  # re-export for back-compat
)

# DEFAULT_TTL was previously module-level here. Kept here (not in
# endpoints.py) because it's a client-behavior constant, not a TIS API
# constant.
DEFAULT_TTL = 3600
from .maps import (
    CATEGORY_MAP, CATEGORY_REVERSE,
    KCLBDM_MAP, KCLBDM_REVERSE,
    category_name_to_code, kclbmc_to_code,
    language_to_code,
)
from .errors import EnrollmentError  # re-export
from .writes import (  # mix into SelectCourseClient below
    add_course, drop_course, add_to_cart, remove_from_cart,
    update_bid, submit_bids,
)


class SelectCourseClient:
    """TIS course selection helper.

    Read side: catalog browse (any xq), personal enrollment lookup,
    filter options, by-code lookup.

    Write side: see `writes.py` — methods are bound onto this class at
    the bottom of this file. Every write defaults to `dry_run=True`.
    """

    BASE_URL = "https://tis.sustech.edu.cn"

    def __init__(self, *, semester: Optional[Semester] = None,
                 xn: Optional[str] = None, xq: Optional[str] = None,
                 max_age: int = DEFAULT_TTL, cache_dir: Optional[Path] = None):
        if semester is not None:
            self._sem = semester
            self.xn = semester.xn
            self.xq = semester.xq
        elif xn is None and xq is None:
            # Resolve the live academic term when the caller didn't pin one.
            self._sem = Semester.current()
            self.xn = self._sem.xn
            self.xq = self._sem.xq
        else:
            # Partial or full explicit term — fall back to the current term
            # for whichever component wasn't supplied.
            current = Semester.current()
            self._sem = Semester(xn or current.xn, xq or current.xq)
            self.xn = self._sem.xn
            self.xq = self._sem.xq
        self.max_age = max_age
        # Cache lives in the uniform unified ~/.sustech_survival/cache tree. The
        # caller may pass an explicit cache_dir= to override (tests, custom
        # locations); None uses the package default.
        from sustech_survival import _cache
        self._cache_helper = _cache
        self.cache_dir = cache_dir or _cache.cache_path("selectcourse")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._courses: Optional[List[Course]] = None
        # In-memory cache for the queryXkdqXnxq "current TIS active term"
        # response. The active term does not change during a session, so
        # caching eliminates the round-trip on every search_personal call —
        # critical for dodging TIS's "查询请求频率过高" rate limit.
        self._dq_cache: Optional[dict] = None
        self._dq_cache_at: float = 0.0
        # TISAuth — Authorizer subclass that hides all HTTP.
        # Use self._auth.post(path, ...) — never access .session directly.
        from sustech_survival.sso import TISAuth
        self._auth = TISAuth()

    # -- Cache management -----------------------------------------------------

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
                id=c.get("id", ""),
                enrolled=c.get("enrolled"),
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
                    "id": c.id,
                    "enrolled": c.enrolled,
                }
                for c in courses
            ],
        }, ensure_ascii=False))

    # -- Catalog fetch --------------------------------------------------------

    def _fetch_catalog(self) -> List[Course]:
        """Pull the full campus schedule for this xn/xq and parse as Courses."""
        self._auth.ensure()

        all_items: List[dict] = []
        page_size = 500
        for pg in range(1, 10):
            params = {
                "p_xn": self._sem.xn, "p_xq": self._sem.xq, "p_xnxq": None, "p_gjz": "",
                "p_xiaoqu": "", "p_kkyx": "", "p_rwlx": "", "p_kclb": "",
                "p_kcxz": "", "p_chaxunpylx": "3",
                "pageNum": str(pg), "pageSize": str(page_size),
            }
            r = self._auth.post("/Xsxktz/queryRwxxcxList", data=params,
                          timeout=30, headers={"X-Requested-With": "XMLHttpRequest"})
            r.raise_for_status()
            d = r.json()
            items = d.get("rwList", {}).get("list") or []
            all_items.extend(items)
            if len(items) < page_size:
                break
            # TIS rate-limits ~3-5s between catalog calls. Throttle
            # paginated fetches so a cold cache does not trigger
            # "查询请求频率过高". Skip on last page (no further call).
            if pg < 9:
                time.sleep(0.6)

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

    # -- Queries --------------------------------------------------------------

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


    def search_campus(self, *,
                      keyword: str = "",
                      cultivation: Optional[str] = None,
                      college: Optional[str] = None,
                      college_code: Optional[str] = None,
                      campus: Optional[str] = None,
                      category: Optional[str] = None,
                      task_type: Optional[str] = None,
                      language: Optional[str] = None,
                      teacher: Optional[str] = None,
                      scheduled_only: bool = False,
                      ) -> List[Course]:
        """Search the campus-wide course catalog (全校课表).

        All filters are case-insensitive substring matches on the cached
        catalog data.
        """
        courses = self._ensure_loaded()
        out: List[Course] = []
        kw = keyword.lower().strip() if keyword else ""
        tc = teacher.lower().strip() if teacher else ""
        for c in courses:
            if kw:
                hay = " ".join([c.code, c.name, c.name_en, c.section_name, c.section_name_en,
                                c.rwh, c.college, c.category, c.task_type]).lower()
                if kw not in hay:
                    continue
            if tc:
                tc_hay = " ".join(c.teachers).lower()
                if tc not in tc_hay:
                    continue
            if cultivation and cultivation not in c.cultivation:
                continue
            if college and college.lower() not in c.college.lower():
                continue
            if college_code and college_code != c.college_code:
                continue
            if campus and campus not in c.campus:
                continue
            if category and category not in c.category:
                continue
            if task_type and task_type not in c.task_type:
                continue
            if language and language not in c.language:
                continue
            if scheduled_only and not c.has_schedule:
                continue
            out.append(c)
        return out

    def search_courses(self, **kw) -> List[Course]:
        """Deprecated — use search_campus() instead."""
        return self.search_campus(**kw)

    def search_personal(self, *,
                       keyword: str = "",
                       teacher: str = "",
                       college: Optional[str] = None,
                       campus: Optional[str] = None,
                       category: Optional[str] = None,
                       language: Optional[str] = None,
                       cultivation: Optional[str] = None,
                       ignore_conflicts: bool = False,
                       ignore_zero_capacity: bool = False,
                       weekday: Optional[int] = None,
                       period_start: Optional[int] = None,
                       period_end: Optional[int] = None,
                       round_code: Optional[str] = None,
                       page: int = 1,
                       page_size: int = 50,
                       ) -> dict:
        """Search courses available for YOUR registration (选课 via Xsxk/queryKxrw).

        Returns dict with: ok, courses, total, enrolled, cart, message,
        course_types, current_type, round.

        `round_code` is the selection round code (e.g. "bxxk" for
        通识必修选课). Required by TIS to know which round to query.
        """
        self._auth.ensure()
        # Round-trip: get the current TIS active term for the dq fields.
        # Cached — the term does not change during a session, and re-fetching
        # on every call is what triggers TIS's "查询请求频率过高".
        dq = self._fetch_dq()
        # Translate display names → TIS DM codes. TIS's personal-mode
        # search silently returns 0 if given a display name in any of
        # these params — see CATEGORY_MAP docstring. Pass-through if the
        # input is already a code (digits) or unrecognized.
        category_code = category_name_to_code(category) if category else ""
        skyy_code = language_to_code(language) if language else ""
        queryform = {
            "p_pylx": "1",
            "p_sfgldjr": "",
            "p_sfredis": "",
            # Match the student-facing TIS page.  `1` restricts the result
            # set to the shopping-cart view and omits many otherwise
            # selectable sections (including their live seat counts).
            "p_sfsyxkgwc": "0",
            "p_xktjz": None,
            "p_chaxunxh": "",
            "p_chaxunxkfsdm": round_code or "",
            "p_gjz": keyword or "",
            "p_skjs": teacher or "",
            "p_xn": self._sem.xn,
            "p_xq": self._sem.xq,
            "p_xnxq": f"{self._sem.xn}{self._sem.xq}",
            "p_dqxn": dq.get("p_dqxn", ""),
            "p_dqxq": dq.get("p_dqxq", ""),
            "p_dqxnxq": dq.get("p_dqxnxq", ""),
            "p_xkfsdm": round_code or "",
            "p_xiaoqu": campus or "",
            "p_kkyx": college or "",
            "p_kclb": category_code,
            "p_xkxs": None,
            "p_dyc": None,
            "p_kkxnxq": "",
            "p_id": None,
            "p_ids": [],
            "p_sfhlctkc": "1" if ignore_conflicts else "0",
            "p_sfhllrlkc": "1" if ignore_zero_capacity else "0",
            "p_kxsj_xqj": str(weekday) if weekday else "",
            "p_kxsj_ksjc": str(period_start) if period_start else "",
            "p_kxsj_jsjc": str(period_end) if period_end else "",
            "p_kcdm_js": "",
            "p_kcdm_cxrw": "",
            "p_kcdm_cxrw_zckc": "",
            "p_kc_gjz": keyword or "",
            "p_xzcxtjz_nj": "",
            "p_xzcxtjz_yx": "",
            "p_xzcxtjz_zy": "",
            "p_xzcxtjz_zyfx": "",
            "p_xzcxtjz_bj": "",
            "p_sfxsgwckb": "1",
            "p_skyy": skyy_code,
            "p_sfmxzj": "0",
            "cxsfmt": dq.get("cxsfmt", "0"),
            "mxpylx": "1",
            "pageNum": str(page),
            "pageSize": str(page_size),
        }
        # Drop None values (TIS rejects keys with value 'None')
        queryform = {k: v for k, v in queryform.items() if v is not None}
        r = self._auth.post("/Xsxk/queryKxrw", data=queryform,
                            timeout=30, headers={"X-Requested-With": "XMLHttpRequest"})
        r.raise_for_status()
        d = r.json()
        jg = d.get("jg", "-1")
        if jg != "1":
            return {
                "ok": False,
                "courses": [],
                "total": 0,
                "enrolled": [],
                "cart": [],
                "message": d.get("message", "Course selection unavailable (jg={})".format(jg)),
                "course_types": d.get("xkgzszList") or d.get("xsxkPage", {}).get("xkgzszList") or [],
                "current_type": d.get("xkgzszOne") or d.get("xsxkPage", {}).get("xkgzszOne") or {},
            }
        kxrw = d.get("kxrwList") or {}
        raw_list = kxrw.get("list") or []
        courses = [Course.from_api(item) for item in raw_list]
        # Merge personal-mode results into the in-memory catalog so
        # `_lookup_id()` can find the 32-char hex `id` for any rwh the
        # user is about to write to. Personal-mode rows carry the id;
        # catalog rows (queryRwxxcxList) don't. Without this merge the
        # write path silently fails with 操作失败.
        if self._courses is None:
            self._courses = []
        existing = {c.rwh: i for i, c in enumerate(self._courses)}
        for course in courses:
            if course.rwh in existing:
                # Replace catalog row with personal-mode row (carries id)
                self._courses[existing[course.rwh]] = course
            else:
                self._courses.append(course)
        ct = d.get("xkgzszOne") or d.get("xsxkPage", {}).get("xkgzszOne") or {}
        return {
            "ok": True,
            "courses": courses,
            "total": kxrw.get("total", len(courses)),
            "enrolled": d.get("yxkcList") or [],
            "cart": d.get("xkgwcList") or [],
            "message": d.get("message", ""),
            "course_types": d.get("xkgzszList") or d.get("xsxkPage", {}).get("xkgzszList") or [],
            "current_type": ct,
            # Bid-panel fields — extracted from the current_type config so
            # the bid panel does not need a second TIS call.
            "round": {
                "xkfsdm": ct.get("xkfsdm", round_code or ""),
                "jffs": float(ct.get("jfxs") or 0),
                "ksrq": ct.get("ksrq", ""),
                "jsrq": ct.get("jsrq", ""),
                "lcmc": ct.get("lcmc", ""),
                "xkms": ct.get("xkms", ""),
            },
        }

    def course_types(self) -> list:
        """Get available selection course types (xkfsdm codes/names) from TIS.

        Uses queryYxkc which always returns the type config regardless of
        whether the user has enrolled courses or selection is active.
        Cached per (xn, xq) to avoid hitting TIS on every request.
        """
        cache_key = f"{self._sem.xn}_{self._sem.xq}"
        if not hasattr(self, '_course_types_cache'):
            self._course_types_cache = {}
        if cache_key in self._course_types_cache:
            return self._course_types_cache[cache_key]
        self._auth.ensure()
        r = self._auth.post("/Xsxk/queryYxkc",
                            data={"p_xn": self._sem.xn, "p_xq": self._sem.xq},
                            timeout=30, headers={"X-Requested-With": "XMLHttpRequest"})
        r.raise_for_status()
        d = r.json()
        types = d.get("xkgzszList") or []
        self._course_types_cache[cache_key] = types
        return types

    def filter_options(self) -> dict:
        """Distinct filter option values from the cached catalog."""
        courses = self._ensure_loaded()
        colleges: dict = {}
        cats: set = set()
        tasks: set = set()
        langs: set = set()
        camps: set = set()
        cults: dict = {}
        for c in courses:
            if c.college and c.college_code:
                colleges[c.college_code] = c.college
            if c.category:
                cats.add(c.category)
            if c.task_type:
                tasks.add(c.task_type)
            if c.language:
                langs.add(c.language)
            if c.campus:
                camps.add(c.campus)
            if c.cultivation:
                cults[c.cultivation] = True
        return {
            "colleges": sorted((code, name) for code, name in colleges.items()),
            "categories": sorted(cats),
            "task_types": sorted(tasks),
            "languages": sorted(langs),
            "campuses": sorted(camps),
            "cultivation_levels": sorted(cults),
        }

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

    # -- Personal enrollment --------------------------------------------------

    def _lookup_id(self, rwh: str) -> str:
        """Look up the 32-char hex `id` (TIS write-key) for an rwh.

        Walk the cached catalog for a course with matching rwh. Returns
        "" if not found — callers should treat empty as "id unknown".

        The catalog's queryRwxxcxList doesn't carry `id` — only
        queryKxrw does. So this lookup only succeeds after a personal
        search has populated `Course.id` on those rows. If the user
        runs a personal search then a write, this works. If they skip
        the personal search and try to write, this returns "" and the
        write endpoint rejects with 操作失败.
        """
        for c in self._ensure_loaded():
            if c.rwh == rwh and c.id:
                return c.id
        return ""

    def _fetch_dq(self) -> dict:
        """Cached queryXkdqXnxq response.

        The "current TIS active term" (`p_dqxn`/`p_dqxq`/`p_dqxnxq`/
        `cxsfmt`) is the same for every request in a session. Caching it
        avoids the round-trip on every `search_personal` call, which is
        what triggers TIS's "查询请求频率过高" rate-limit error.
        """
        ttl = 300  # 5 min — semantically stable, but allow a refresh in
                   # case the user crosses a semester boundary mid-session
        if self._dq_cache is not None and (time.time() - self._dq_cache_at) < ttl:
            return self._dq_cache
        self._auth.ensure()
        dq = self._auth.post("/Xsxk/queryXkdqXnxq", data={},
                             timeout=15,
                             headers={"X-Requested-With": "XMLHttpRequest"}).json()
        self._dq_cache = dq
        self._dq_cache_at = time.time()
        return dq

    def my_courses(self, semester: Optional[str] = None) -> List[dict]:
        """Your enrolled courses for a semester.

        `semester`: "2025-2026-2" or "2025-2026-3" (summer). Defaults to
        the current client's semester.

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
            xn, xq = self._sem.xn, self._sem.xq

        self._auth.ensure()
        r = self._auth.post("/xszykb/queryxszykbzong",
                            data={"xn": xn, "xq": xq}, timeout=15,
                            headers={"X-Requested-With": "XMLHttpRequest"})
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


# -- Mix in write methods ------------------------------------------------
# Defined in writes.py (split 2026-08-08). Bound here so callers can use
# `client.add_course(...)` exactly as before the split.
SelectCourseClient.add_course = add_course
SelectCourseClient.drop_course = drop_course
SelectCourseClient.add_to_cart = add_to_cart
SelectCourseClient.remove_from_cart = remove_from_cart
SelectCourseClient.update_bid = update_bid
SelectCourseClient.submit_bids = submit_bids


# -- Singleton factory ----------------------------------------------------


def selectcourse(*, semester: Optional[Semester] = None,
                 xn: Optional[str] = None, xq: Optional[str] = None,
                 max_age: int = DEFAULT_TTL) -> SelectCourseClient:
    """Module-level factory. Defaults to the live academic term.

    Pass `semester=Semester(...)` for full type support,
    or `xq="3"` for summer (kept for backward compatibility).
    """
    return SelectCourseClient(semester=semester, xn=xn, xq=xq, max_age=max_age)
