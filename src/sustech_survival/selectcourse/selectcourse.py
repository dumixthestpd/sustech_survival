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
import time
from pathlib import Path
from typing import Dict, List, Optional

import requests

from .schema import Course


TIS_BASE = "https://tis.sustech.edu.cn"
TIS_CAMPUS_SCHEDULE_URL = f"{TIS_BASE}/Xsxktz/queryRwxxcxList"
TIS_PERSONAL_SCHEDULE_URL = f"{TIS_BASE}/xszykb/queryxszykbzong"
TIS_PERSONAL_WEEK_URL = f"{TIS_BASE}/xszykb/queryxszykbzhou"
TIS_ADD_XUANKE_URL = f"{TIS_BASE}/Xsxk/addXuanke"
TIS_TUIKE_URL = f"{TIS_BASE}/Xsxk/tuike"
TIS_ADD_GOUWUCHE_URL = f"{TIS_BASE}/Xsxk/addGouwuche"
TIS_DEL_GOUWUCHE_URL = f"{TIS_BASE}/Xsxk/delGouwuche"
DEFAULT_TTL = 3600

# xktjz (选课提交至) values — where the action lands
XKTJZ_CART_TO_ENROLLED = "gwctjzyx"   # 购物车提交至已选 (cart → enrolled) — used by addXuanke
XKTJZ_TASK_TO_CART = "rwtjzgwc"      # 任务提交至购物车 (task → cart) — used by addGouwuche


class EnrollmentError(RuntimeError):
    """Raised when TIS rejects a write-side enrollment action."""
    def __init__(self, jg: str, message: str, *, endpoint: str, rwh: str):
        self.jg = jg              # '0' or '-1' or other non-success code
        self.message = message
        self.endpoint = endpoint
        self.rwh = rwh
        super().__init__(f"[{endpoint}] rwh={rwh} jg={jg}: {message}")


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
                         ignore_zero_capacity: bool = False) -> dict:
        """Build the TIS `queryform` payload for write-side endpoints.

        Mirrors the keys seen in `pub/xkgl/xsxk/xsxk-*.js` queryform
        definition. Values not provided default to safe no-ops.
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
            "p_xn": self.xn,                         # 学年
            "p_xq": self.xq,                         # 学期
            "p_xnxq": None,                          # 学年学期（合并）
            "p_dqxn": None, "p_dqxq": None, "p_dqxnxq": None,
            "p_xkfsdm": "",                          # 选课方式代码
            "p_xiaoqu": "",                          # 校区
            "p_kkyx": "",                            # 开课院系
            "p_kclb": "",                            # 课程类别
            "p_xkxs": None,                          # 选课系数
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

        sess = self._login_for_write()
        sess.headers["X-Requested-With"] = "XMLHttpRequest"
        r = sess.post(endpoint, data=payload, timeout=30)
        r.raise_for_status()
        res = r.json() if r.content else {}
        jg = str(res.get("jg", ""))
        if jg != "1":
            raise EnrollmentError(jg, res.get("message", "(no message)"),
                                  endpoint=endpoint, rwh=rwh)
        return res

    def _login_for_write(self) -> requests.Session:
        """Fresh TIS login for a write-side call."""
        from sustech_survival.sso import Authorizer
        creds = Authorizer(skill_dir=str(self.skill_root))
        uname, pw = creds.read_creds()
        return _tis_login(uname, pw)

    def add_course(self, rwh: str, *,
                   dry_run: bool = True,
                   ignore_conflicts: bool = False,
                   ignore_zero_capacity: bool = False,
                   pylx: Optional[str] = None) -> dict:
        """Add a course to your enrolled list (直接选课).

        `rwh`: the 任务号 (task number) from `Course.rwh` or `my_courses()`.
               Used as `p_id` in the POST body.

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

    def add_to_cart(self, rwh: str, *, dry_run: bool = True,
                    pylx: Optional[str] = None,
                    xktjz: str = XKTJZ_TASK_TO_CART) -> dict:
        """Add a course to your shopping cart (购物车).

        `xktjz` defaults to `rwtjzgwc` (任务→购物车). Set to
        `gwctjzyx` (购物车→已选) to commit the cart in one step
        (equivalent to `add_course`).

        Fires `Xsxk/addGouwuche`.
        """
        payload = self._build_queryform(rwh=rwh, xktjz=xktjz, pylx=pylx)
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


# ── Singleton factory ────────────────────────────────────────────────────────


def selectcourse(*, xn: str = "2025-2026", xq: str = "2",
                 max_age: int = DEFAULT_TTL) -> SelectCourseClient:
    """Module-level factory. Defaults to current Spring semester.

    Pass `xq="3"` for summer.
    """
    return SelectCourseClient(xn=xn, xq=xq, max_age=max_age)
