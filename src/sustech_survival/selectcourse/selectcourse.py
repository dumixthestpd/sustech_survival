"""
sustech_survival.selectcourse.selectcourse — Live client for TIS course browsing + enrollment.

ONE class. ALL operations on the 选课 catalog, your enrolled courses,
and (with `dry_run=False`) course add/drop.

Architecture mirrors classroom.ClassroomOccupancy — same auth, same cache,
same TIS campus_schedule endpoint. The difference: this client is
course-centric (one row per offering), not room-centric.

Endpoints used:
    Xsxktz/queryRwxxcxList          — public course catalog (any xq, including
                                       summer xq=3) — READ
    xszykb/queryxszykbzong           — your enrolled courses for a semester — READ
    xszykb/queryxszykbzhou           — your enrolled courses for a specific week — READ
    Xsxk/addXuanke                   — submit shopping cart → enrolled — WRITE
    Xsxk/tuike                       — drop a course — WRITE
    Xsxk/addGouwuche                 — add to shopping cart — WRITE
    Xsxk/delGouwuche                 — remove from shopping cart — WRITE
    Xsxk/updXuefeijiaofei            — tuition payment (not wrapped; TIS-internal flow)
    Xsxk/updXkxsByyx                 — update by enrolled status
    Xsxk/updXkxsBygwc                — update by cart status

Write-side (AddCourse / DropCourse) was discovered by walking the
`/pub/xkgl/xsxk/xsxk-*.js` bundle on 2026-06-19. Endpoints + payload
shape documented in `references/tis-api.md`. The `dry_run=True` default
on `add_course()` / `drop_course()` means they print what would be POSTed
without actually mutating your enrollment — flip to `dry_run=False` to
fire the real request.
"""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

import requests

from ..semester import Semester
from .schema import Course


TIS_BASE = "https://tis.sustech.edu.cn"
TIS_CAMPUS_SCHEDULE_URL = f"{TIS_BASE}/Xsxktz/queryRwxxcxList"
TIS_PERSONAL_SCHEDULE_URL = f"{TIS_BASE}/xszykb/queryxszykbzong"
TIS_PERSONAL_WEEK_URL = f"{TIS_BASE}/xszykb/queryxszykbzhou"
TIS_QUERY_KXRW_URL = f"{TIS_BASE}/Xsxk/queryKxrw"  # 选课 search (personal selection)
TIS_ADD_XUANKE_URL = f"{TIS_BASE}/Xsxk/addXuanke"
TIS_TUIKE_URL = f"{TIS_BASE}/Xsxk/tuike"
TIS_ADD_GOUWUCHE_URL = f"{TIS_BASE}/Xsxk/addGouwuche"
TIS_DEL_GOUWUCHE_URL = f"{TIS_BASE}/Xsxk/delGouwuche"
TIS_UPD_XKXS_BY_YX = f"{TIS_BASE}/Xsxk/updXkxsByyx"
TIS_UPD_XKXS_BY_GWC = f"{TIS_BASE}/Xsxk/upd_xkxsBygwc"
DEFAULT_TTL = 3600

# xktjz (选课提交至) values — where the action lands
XKTJZ_CART_TO_ENROLLED = "gwctjzyx"   # 购物车提交至已选 (cart → enrolled) — used by addXuanke
XKTJZ_TASK_TO_CART = "rwtjzgwc"      # 任务提交至购物车 (task → cart) — used by addGouwuche

# kclbdm (课程类别代码) map — display name → DM code.
# Discovered from the TIS kclb SPA bundle (`inco.component.kclb-*.js`)
# endpoint `component/queryKclb` (NOT `/Xsxk/queryKclb` which 404s).
# Full discovery: sustech-dev/references/tis-kclbdm-discovery-2026-07-08.md
#
# Personal mode TIS search expects the kclbdm code in `p_kclb`. Passing
# the display name silently returns 0 results. Use this to translate
# dropdown values before hitting TIS.
#
# Sub-categories (level 2 like 0901-0909) are stored in TIS response
# kclbmc as `<parent>-<sub>` (e.g. "通识选修课-美育类"). The frontend
# dropdown shows only the bare sub-name (e.g. "美育类") so the bare
# key is what callers send.
KCLBDM_MAP: dict = {
    # Top-level (level 1) — undergrad
    "专业基础课": "03",
    "专业必修课": "04",   # 04 (undergrad) and 10 both named "专业必修课"
    "专业选修课": "05",
    "专业核心课": "07",
    "通识必修课": "08",
    "通识选修课": "09",
    "实践": "11",
    "国际化人才培养": "13",
    "任选": "98",
    "其他": "99",
    "辅修专业选修学分": "998",
    "辅修专业必修学分": "999",
    # Sub-categories (level 2) — child of 09 通识选修课
    "人文类": "0901",
    "社科类": "0902",
    "艺术类": "0903",
    "其它任选类": "0904",
    "外语类": "0905",
    "劳育类": "0906",
    "美育类": "0907",
    "国学类": "0908",
    "专业导论类": "0909",
    # Graduate-only (level 1) — pylb=2
    "培养环节": "01",     # grad only (pylb=1 has no 培养环节 — it's a 研究生 thing)
    "校外共享课": "200",
}

# Reverse: code → display name (for /api/tis/info payload).
KCLBDM_REVERSE: dict = {v: k for k, v in KCLBDM_MAP.items()}

# kclbmc (TIS response format) — can be "通识选修课" or "通识选修课-美育类".
# When translating from a TIS response kclbmc to a code, strip the
# parent prefix if present.
def kclbmc_to_code(kclbmc: str) -> str:
    """Translate TIS response `kclbmc` to a kclbdm code.

    Handles both bare names (`美育类`) and hyphenated names
    (`通识选修课-美育类`). If the input is already a digit code
    (`0907`), pass it through. Returns empty string if not recognized
    (callers should treat unknown as no-filter).
    """
    if not kclbmc:
        return ""
    s = kclbmc.strip()
    # Pass-through: already a digit code
    if s.isdigit():
        return s
    # Direct lookup first
    if s in KCLBDM_MAP:
        return KCLBDM_MAP[s]
    # Try stripping "<parent>-" prefix
    if "-" in s:
        suffix = s.split("-", 1)[1]
        if suffix in KCLBDM_MAP:
            return KCLBDM_MAP[suffix]
    return ""

# Language code (p_skyy) — TIS personal mode expects a code, not name.
# 1=中文, 2=英文, 3=双语. Verified by trial 2026-07-07.
LANGUAGE_MAP: dict = {
    "中文": "1",
    "英文": "2",
    "双语": "3",
}


def language_to_code(language: str) -> str:
    """Translate display language name to TIS code. Returns input as-is
    if already a code (or unrecognized)."""
    if not language:
        return ""
    return LANGUAGE_MAP.get(language.strip(), language.strip())


class EnrollmentError(RuntimeError):
    """Raised when TIS rejects a write-side enrollment action."""
    def __init__(self, jg: str, message: str, *, endpoint: str, rwh: str):
        self.jg = jg              # '0' or '-1' or other non-success code
        self.message = message
        self.endpoint = endpoint
        self.rwh = rwh
        super().__init__(f"[{endpoint}] rwh={rwh} jg={jg}: {message}")



class SelectCourseClient:
    """TIS course selection helper — read side.

    Provides catalog browse (any xq) and personal enrollment lookup.
    Write side (AddCourse / DropCourse) is NOT wrapped — see the SKILL
    notes for the open question.
    """

    BASE_URL = TIS_BASE

    def __init__(self, *, semester: Optional[Semester] = None,
                 xn: str = "2025-2026", xq: str = "2",
                 max_age: int = DEFAULT_TTL):
        if semester is not None:
            self._sem = semester
            self.xn = semester.xn
            self.xq = semester.xq
        else:
            self._sem = Semester(xn, xq)
            self.xn = xn
            self.xq = xq
        self.max_age = max_age
        # Cache lives in the uniform package-scoped tmp/ tree.
        from sustech_survival import _cache
        self._cache_helper = _cache
        self.cache_dir = _cache.cache_path("selectcourse")
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
                       xkfsdm: Optional[str] = None,     # course type code (xkfsdm)
                       page: int = 1,
                       page_size: int = 50,
                       ) -> dict:
        """Search courses available for YOUR registration (选课 via Xsxk/queryKxrw).

        Returns dict with: ok, courses, total, enrolled, cart, message,
        course_types, current_type, round.

        Note: TIS rejects with "操作失败" if the queryform is incomplete.
        The full payload (extracted from `pub/xkgl/xsxk/xsxk-*.js`) requires
        not just the target xn/xq + xkfsdm, but also the CURRENT term
        (p_dqxn/p_dqxq/p_dqxnxq) and several behavior flags. We populate
        those from a queryXkdqXnxq round-trip (cached 5 min).
        """
        self._auth.ensure()
        # Round-trip: get the current TIS active term for the dq fields.
        # Cached — the term does not change during a session, and re-fetching
        # on every call is what triggers "查询请求频率过高".
        dq = self._fetch_dq()
        # Translate display names → TIS DM codes. TIS's personal-mode
        # search silently returns 0 if given a display name in any of
        # these params — see KCLBDM_MAP docstring. Pass-through if the
        # input is already a code (digits) or unrecognized.
        kclb_code = kclbmc_to_code(category) if category else ""
        skyy_code = language_to_code(language) if language else ""
        queryform = {
            "p_pylx": "1",
            "p_sfgldjr": "",
            "p_sfredis": "",
            "p_sfsyxkgwc": "1",          # 是否使用选课购物车
            "p_xktjz": None,
            "p_chaxunxh": "",
            "p_gjz": keyword or "",
            "p_skjs": teacher or "",
            "p_xn": self._sem.xn,
            "p_xq": self._sem.xq,
            "p_xnxq": "",
            "p_dqxn": dq.get("p_dqxn", ""),
            "p_dqxq": dq.get("p_dqxq", ""),
            "p_dqxnxq": dq.get("p_dqxnxq", ""),
            "p_xkfsdm": xkfsdm or "",
            "p_xiaoqu": campus or "",
            "p_kkyx": college or "",
            "p_kclb": kclb_code,
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
            "p_kc_gjz": "",
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
                "xkfsdm": ct.get("xkfsdm", xkfsdm or ""),
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

    # ── Personal enrollment ──────────────────────────────────────────────────

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

    # ── WRITE side: add / drop courses ───────────────────────────────────────
    #
    # Discovered 2026-06-19 by walking /pub/xkgl/xsxk/xsxk-*.js.
    # See references/tis-api.md for the full payload shape + every Xsxk/* endpoint.
    #
    # The "click select" flow is:
    #   1. TIS UI calls Xsxk/cxmtctPd (POST) — conflict check
    #   2. If OK, calls Xsxk/addGouwuche (add to cart) OR Xsxk/addXuanke (direct enroll)
    #   3. If tuition-based, also calls Xsxk/updXuefeijiaofei
    #
    # For "click drop":
    #   1. TIS UI calls Xsxk/tuike (POST) — drop by id
    #
    # The `p_id` field is the row's `id` from queryKxrw/queryYxkc — we
    # assume it matches `rwh` from queryRwxxcxList (both are 任务号/task
    # number). If TIS rejects, the error message will say so and you can
    # pass a different `id_field` value.
    #
    # All write methods default to `dry_run=True` — they print what would
    # be POSTed without touching TIS. Set `dry_run=False` to fire the real
    # request. We don't auto-flip this; course selection is a state-mutating
    # operation and the user must opt in explicitly.

    def _build_queryform(self, *, rwh: Optional[str] = None,
                         ids: Optional[list] = None,
                         xktjz: Optional[str] = None,
                         pylx: Optional[str] = None,
                         ignore_conflicts: bool = False,
                         ignore_zero_capacity: bool = False,
                         bid: Optional[int] = None) -> dict:
        """Build the TIS `queryform` payload for write-side endpoints.

        Mirrors the keys seen in `pub/xkgl/xsxk/xsxk-*.js` queryform
        definition. Values not provided default to safe no-ops.

        `bid` is the 选课系数 (selection coefficient, aka the credit bid
        in 积分选课). Goes into `p_xkxs`. Leave None to omit (TIS then
        uses the default 1 — fine for round tables that don't score).
        """
        return {
            "p_pylx": pylx,                          # 1=本科, 2=研究生
            "p_sfgldjr": "0",                        # 是否管理端进入
            "p_sfredis": "",                         # 是否Redis缓存
            "p_sfsyxkgwc": "1",                      # 是否使用选课购物车
            "p_xktjz": xktjz,                        # 选课提交至 (gwctjzyx / rwtjzgwc)
            "p_chaxunxh": "",                        # 管理端查询学号
            "p_gjz": "",                             # 关键字
            "p_skjs": "",                            # 上课教师
            "p_xn": self._sem.xn,                         # 学年
            "p_xq": self._sem.xq,                         # 学期
            "p_xnxq": None,                          # 学年学期（合并）
            "p_dqxn": None, "p_dqxq": None, "p_dqxnxq": None,
            "p_xkfsdm": "",                          # 选课方式代码
            "p_xiaoqu": "",                          # 校区
            "p_kkyx": "",                            # 开课院系
            "p_kclb": "",                            # 课程类别
            "p_xkxs": bid if bid is not None else None,  # 选课系数 / 积分选课的 bid
            "p_dyc": None,                           # 多语种
            "p_kkxnxq": "",                          # 开课学年学期
            "p_id": rwh,                             # ★ 课程id（任务号rwh）
            "p_ids": ids if ids is not None else [], # ★ 批量id列表
            "p_sfhlctkc": "1" if ignore_conflicts else "0",     # 是否忽略冲突课程
            "p_sfhllrlkc": "1" if ignore_zero_capacity else "0", # 是否忽略零容量课程
            "p_kxsj_xqj": "", "p_kxsj_ksjc": "", "p_kxsj_jsjc": "",
            "p_kcdm_js": "", "p_kcdm_cxrw": "", "p_kcdm_cxrw_zckc": "",
            "p_kc_gjz": "",
            "p_xzcxtjz_nj": "", "p_xzcxtjz_yx": "", "p_xzcxtjz_zy": "",
            "p_xzcxtjz_zyfx": "", "p_xzcxtjz_bj": "",
            "p_sfxsgwckb": "1",
            "p_skyy": "",
            "p_sfmxzj": "0",
        }

    def _post_xsxk(self, endpoint: str, payload: dict, *,
                   dry_run: bool, rwh: str) -> dict:
        """POST to a write-side Xsxk/* endpoint.

        With `dry_run=True`, returns a synthetic "would-post" response
        without sending anything. With `dry_run=False`, logs in via TIS
        and fires the real POST.

        Response shape: `{jg: '1'|'0'|'-1', message: '...', ...}`
        Raises EnrollmentError when jg != '1'.
        """
        if dry_run:
            return {
                "dry_run": True,
                "endpoint": endpoint,
                "would_post": payload,
                "jg": None, "message": "(dry_run: no request sent)",
            }

        self._auth.ensure()
        r = self._auth.post(endpoint, data=payload, timeout=30,
                            headers={"X-Requested-With": "XMLHttpRequest"})
        r.raise_for_status()
        res = r.json() if r.content else {}
        jg = str(res.get("jg", ""))
        if jg != "1":
            raise EnrollmentError(jg, res.get("message", "(no message)"),
                                  endpoint=endpoint, rwh=rwh)
        return res

    def add_course(self, rwh: str, *,
                   bid: int = 1,
                   dry_run: bool = True,
                   ignore_conflicts: bool = False,
                   ignore_zero_capacity: bool = False,
                   pylx: Optional[str] = None) -> dict:
        """Add a course to your enrolled list (直接选课).

        `rwh`: the 任务号 (task number) from `Course.rwh` or `my_courses()`.
               Used as `p_id` in the POST body.

        `bid`: 选课系数 (the credit bid in 积分选课). 1 = minimum (the
               default — TIS will use this if `p_xkxs` is missing).
               Pass higher numbers to outbid others on a popular class;
               see `references/credit-based-selection.md` for the auction
               mechanic.

        `dry_run=True` (default): returns what would be POSTed without
                                  firing the request. SAFE.
        `dry_run=False`: actually fires `Xsxk/addXuanke`. This MUTATES
                         your enrollment — use only after reviewing.

        `ignore_conflicts`/`ignore_zero_capacity`: pass through to the
            TIS form's `p_sfhlctkc` / `p_sfhllrlkc`. Note that TIS may
            still reject based on its own rules even when these are True.

        Returns the TIS response dict. On dry_run, includes `dry_run=True`
        and `would_post=<full payload>`. On real call, includes `jg='1'`
        and `message='选课成功'` (or similar) on success.

        Raises EnrollmentError on real-call failure (jg != '1').
        """
        payload = self._build_queryform(
            rwh=rwh,
            xktjz=XKTJZ_CART_TO_ENROLLED,
            pylx=pylx,
            ignore_conflicts=ignore_conflicts,
            ignore_zero_capacity=ignore_zero_capacity,
            bid=bid,
        )
        return self._post_xsxk(TIS_ADD_XUANKE_URL, payload,
                               dry_run=dry_run, rwh=rwh)

    def drop_course(self, rwh: str, *, dry_run: bool = True,
                    pylx: Optional[str] = None) -> dict:
        """Drop a course (退课) by 任务号.

        Same `dry_run` semantics as `add_course`. Fires `Xsxk/tuike`.
        """
        payload = self._build_queryform(rwh=rwh, pylx=pylx)
        return self._post_xsxk(TIS_TUIKE_URL, payload,
                               dry_run=dry_run, rwh=rwh)

    def add_to_cart(self, rwh: str, *, bid: int = 1,
                    dry_run: bool = True,
                    pylx: Optional[str] = None,
                    xktjz: str = XKTJZ_TASK_TO_CART) -> dict:
        """Add a course to your shopping cart (购物车).

        `xktjz` defaults to `rwtjzgwc` (任务→购物车). Set to
        `gwctjzyx` (购物车→已选) to commit the cart in one step
        (equivalent to `add_course`).

        `bid`: 选课系数 (the credit bid). Sent as `p_xkxs`. TIS will
               reject with 操作失败 if the round uses 积分 mode and the
               bid is missing/0/non-integer.

        Fires `Xsxk/addGouwuche`.
        """
        payload = self._build_queryform(rwh=rwh, xktjz=xktjz, pylx=pylx, bid=bid)
        return self._post_xsxk(TIS_ADD_GOUWUCHE_URL, payload,
                               dry_run=dry_run, rwh=rwh)

    def remove_from_cart(self, rwh: str, *, dry_run: bool = True,
                         pylx: Optional[str] = None) -> dict:
        """Remove a course from your shopping cart.

        Fires `Xsxk/delGouwuche`.
        """
        payload = self._build_queryform(rwh=rwh, pylx=pylx)
        return self._post_xsxk(TIS_DEL_GOUWUCHE_URL, payload,
                               dry_run=dry_run, rwh=rwh)

    # ── Bid (积分 / 选课系数) ────────────────────────────────────────────────

    def update_bid(self, rwh: str, bid: int, *,
                   where: str = "enrolled",
                   pylx: Optional[str] = None,
                   dry_run: bool = True) -> dict:
        """Update the bid (选课系数) on an already-picked course.

        `where`: "enrolled" (已选 → calls Xsxk/updXkxsByyx)
                 or  "cart"    (购物车 → calls Xsxk/upd_xkxsBygwc)

        `bid`: positive integer. TIS rejects if the round uses 积分
               mode and bid is missing / 0 / non-integer.

        For NEW picks (not yet in cart/enrolled), use `add_to_cart(bid=…)`
        or `add_course(bid=…)` instead — they pass the bid on the create.
        """
        bid = int(bid)
        if bid < 1:
            raise ValueError(f"bid must be a positive integer, got {bid}")
        if where == "enrolled":
            url = TIS_UPD_XKXS_BY_YX
        elif where == "cart":
            url = TIS_UPD_XKXS_BY_GWC
        else:
            raise ValueError(f"where must be 'enrolled' or 'cart', got {where!r}")
        payload = self._build_queryform(rwh=rwh, pylx=pylx, bid=bid)
        return self._post_xsxk(url, payload, dry_run=dry_run, rwh=rwh)

    def submit_bids(self, picks: dict, *,
                    xkfsdm: str = "",
                    where: str = "cart",
                    jffs_limit: Optional[float] = None,
                    pylx: Optional[str] = None,
                    dry_run: bool = True) -> dict:
        """Submit a batch of bid values for the user's picked courses.

        `picks`:  {rwh: bid_int, ...} — the user's desired bid per course.
        `xkfsdm`: the active round code (informational; not strictly
                  required by the wire but useful for context).
        `where`:  "enrolled" (call updXkxsByyx) or "cart" (call
                  upd_xkxsBygwc) — same as `update_bid`.
        `jffs_limit`: if provided, validate that `sum(picks.values())`
                      does not exceed it (the 剩余积分 from the round).
                      If sum > jffs_limit, return ok=False without any
                      TIS calls.

        Returns a dict:
          {
            "ok": True/False,
            "results": [{rwh, bid, ok, message}, ...],
            "sum": N,
            "jffs_limit": X or None,
            "over_limit": True/False,
          }

        Each TIS call still respects `dry_run` — the loop is read+write
        either way; `dry_run` only controls whether the actual POST
        fires. Validation (jffs check) always runs.

        If `sum(picks.values()) > jffs_limit`, the function short-circuits
        BEFORE making any TIS calls (including dry-run). The result
        includes the picks you asked for so the caller can show them
        back to the user.
        """
        results: list = []

        # Pre-compute the total. If it would blow the budget, return
        # WITHOUT firing any TIS calls (including dry-run). Build a
        # synthetic per-pick result so the caller can render what was
        # rejected.
        try:
            coerced = {rwh: int(b) for rwh, b in picks.items()}
        except (TypeError, ValueError):
            return {
                "ok": False, "results": [],
                "error": "all bid values must be integers",
                "sum": 0, "jffs_limit": jffs_limit, "over_limit": False,
                "xkfsdm": xkfsdm, "dry_run": dry_run,
            }
        total = sum(max(0, b) for b in coerced.values())
        if jffs_limit is not None and total > jffs_limit:
            results = [{"rwh": rwh, "bid": b, "ok": False,
                        "message": f"over budget ({total} > {jffs_limit})",
                        "dry_run": dry_run}
                       for rwh, b in coerced.items() if b >= 1]
            return {
                "ok": False,
                "results": results,
                "sum": total,
                "jffs_limit": jffs_limit,
                "over_limit": True,
                "xkfsdm": xkfsdm,
                "dry_run": dry_run,
            }

        for rwh, bid in coerced.items():
            if bid < 1:
                results.append({"rwh": rwh, "bid": bid, "ok": False,
                                "message": "bid must be ≥ 1",
                                "dry_run": dry_run})
                continue
            try:
                res = self.update_bid(rwh, bid, where=where, pylx=pylx,
                                      dry_run=dry_run)
                results.append({
                    "rwh": rwh,
                    "bid": bid,
                    "ok": res.get("jg") == "1" or res.get("dry_run"),
                    "message": res.get("message", ""),
                    "dry_run": res.get("dry_run", False),
                })
            except Exception as e:
                results.append({"rwh": rwh, "bid": bid, "ok": False,
                                "message": str(e),
                                "dry_run": dry_run})
        return {
            "ok": all(r["ok"] for r in results),
            "results": results,
            "sum": total,
            "jffs_limit": jffs_limit,
            "over_limit": False,
            "xkfsdm": xkfsdm,
            "dry_run": dry_run,
        }


# ── Singleton factory ────────────────────────────────────────────────────────


def selectcourse(*, semester: Optional[Semester] = None,
                 xn: str = "2025-2026", xq: str = "2",
                 max_age: int = DEFAULT_TTL) -> SelectCourseClient:
    """Module-level factory. Defaults to current Spring semester.

    Pass `semester=Semester(...)` for full type support,
    or `xq="3"` for summer (kept for backward compatibility).
    """
    return SelectCourseClient(semester=semester, xn=xn, xq=xq, max_age=max_age)
