"""
TIS course-selector blueprint.

Page:  GET /tis                → course selector SPA (inline JS)
API:   GET  /api/tis/info                 → semester + filter options
       GET  /api/tis/courses              → filtered catalog (JSON list)
       POST /api/tis/refresh              → force-fetch from TIS
       GET  /api/tis/course/<rwh>         → one section detail
       GET  /api/tis/enrolled             → your enrolled sections
       POST /api/tis/solve                → non-conflicting section combos
       POST /api/tis/add                  → add course (dry-run by default)
       POST /api/tis/drop                 → drop course (dry-run by default)
       POST /api/tis/add-to-cart          → cart add (dry-run default)
       POST /api/tis/remove-from-cart     → cart remove (dry-run default)
       GET  /api/tis/nces?code=X          → NCES community eval for a course

All data comes from the existing ``SelectCourseClient`` so this layer
contains no business logic — it only serializes Course objects and
proxies write calls. The browser never sees credentials/cookies.

Two search modes:
  GET /api/tis/courses?mode=campus (default) — 全校课表, all courses
  GET /api/tis/courses?mode=personal — 选课, your eligible courses

TIS parameter mapping (queryRwxxcxList POST → our API):
  p_gjz       → ?keyword=
  p_kkyx      → ?college_code=   (TIS college ID like "010030")
  p_xiaoqu    → ?campus=         (name, e.g. "一期校区")
  p_kclb      → ?category=       (kclbmc name, e.g. "通识必修课")
  p_rwlx      → ?task_type=      (rwlxmc name, e.g. "专业任务")
  p_chaxunpylx→ ?cultivation=    ("本科" / "研究生")
  skyymc      → ?language=       (teaching lang: "中文" / "英文" / "双语")
  dgjsmc      → ?teacher=        (teacher name search)
  p_kcxz      → NOT exposed      (课程性质 — use ?category= instead)

TIS queryform mapping (Xsxk/queryKxrw POST → our personal-mode params):
  p_gjz       → ?keyword=
  p_skjs      → ?teacher=
  p_kkyx      → ?college=
  p_xiaoqu    → ?campus=
  p_kclb      → ?category=       (dm code, e.g. "08" for 通识必修课)
  p_skyy      → ?language=
  p_pylx      → ?cultivation=
  p_sfhlctkc  → ?ignore_conflicts=
  p_sfhllrlkc → ?ignore_zero_capacity=
  p_kxsj_xqj  → ?weekday=
  p_kxsj_ksjc → ?period_start=
  p_kxsj_jsjc → ?period_end=
"""
from __future__ import annotations

import itertools
import json
import threading
from typing import Dict, List, Optional

from flask import Blueprint, jsonify, render_template, request

from sustech_survival.semester import Semester, Season
from sustech_survival.selectcourse.selectcourse import (
    SelectCourseClient,
    EnrollmentError,
    selectcourse as sc_factory,
)

bp = Blueprint("tis", __name__)

# One client per (xn, xq) — cached so we don't re-login on every request.
_clients: Dict[str, SelectCourseClient] = {}
_clients_lock = threading.Lock()

# Default semester for course selection.
DEFAULT_XN = "2026-2027"  # Fall 2026 — the upcoming course-selecting season
DEFAULT_XQ = "1"          # Fall semester


def _client(xn: str, xq: str) -> SelectCourseClient:
    key = f"{xn}-{xq}"
    with _clients_lock:
        c = _clients.get(key)
        if c is None:
            c = sc_factory(xn=xn, xq=xq)
            _clients[key] = c
        return c


def _course_to_dict(c) -> dict:
    return {
        "code": c.code, "name": c.name, "name_en": c.name_en,
        "class_group": c.class_group, "rwh": c.rwh,
        "college": c.college, "category": c.category,
        "campus": c.campus,
        "credits": c.credits, "total_hours": c.total_hours,
        "capacity": c.capacity,
        "undergrad_seats": c.undergrad_seats, "grad_seats": c.grad_seats,
        "cultivation": c.cultivation,
        "rooms": c.rooms, "teachers": c.teachers,
        "schedule": c.schedule_str,
        "slots": c.slots_raw,
        "has_schedule": c.has_schedule,
        "task_type": c.task_type,
        "language": c.language,
        "college_code": c.college_code,
    }


def _parse_sem(args) -> tuple[str, str]:
    return (args.get("xn", DEFAULT_XN) or DEFAULT_XN,
            args.get("xq", DEFAULT_XQ) or DEFAULT_XQ)


def _int_or_none(v):
    try:
        return int(v) if v else None
    except (ValueError, TypeError):
        return None


# ── Page ────────────────────────────────────────────────────────────────────
@bp.route("/tis")
def page():
    xn, xq = _parse_sem(request.args)
    return render_template("tis.html", xn=xn, xq=xq)


# ── API ──────────────────────────────────────────────────────────────────────
@bp.route("/api/tis/info")
def api_info():
    """Semester info + filter options for the course search UI.

    TIS mapping:
      colleges     → (kkyx code, kkyxmc) pairs
      categories   → kclbmc values
      task_types   → rwlxmc values  — e.g. 通识必修选课, 通识选修选课, ...
      languages    → skyymc values  — 中文, 英文, 双语
      campuses     → xiaoqumc
      cultivation  → 本科 / 研究生
    """
    xn, xq = _parse_sem(request.args)
    try:
        c = _client(xn, xq)
        opts = c.filter_options()
    except Exception as e:
        return jsonify({"error": str(e), "count": 0,
                        "colleges": [], "categories": [],
                        "task_types": [], "languages": [],
                        "campuses": [], "cultivation_levels": []}), 200
    sem = Semester(xn, xq)
    display_year = sem.end_year if sem.season == Season.FALL else sem.cohort_year
    semester_label = f"{sem.season.name.capitalize()} {display_year}"
    return jsonify({
        "xn": xn, "xq": xq,
        "semester_label": semester_label,
        "count": len(c.list_courses()),
        "colleges": opts["colleges"],        # [(code, name), ...]
        "categories": opts["categories"],     # [name, ...]
        "task_types": opts["task_types"],     # [name, ...]
        "languages": opts["languages"],       # [name, ...]
        "campuses": opts["campuses"],         # [name, ...]
        "cultivation_levels": opts["cultivation_levels"],
    })


@bp.route("/api/tis/courses")
def api_courses():
    """Search courses. Default: campus-wide catalog (全校课表).

    Query params (all optional):
      mode       — "campus" (default, all courses) or "personal" (your eligible)

    Campus mode filters (全校课表):
      keyword, teacher, college, college_code, campus,
      category, task_type, language, cultivation, scheduled

    Personal mode filters (选课):
      keyword, teacher, college, campus, category, language,
      cultivation, ignore_conflicts, ignore_zero_capacity,
      weekday (1-7), period_start, period_end, page, page_size
    """
    xn, xq = _parse_sem(request.args)
    mode = request.args.get("mode", "campus")
    try:
        c = _client(xn, xq)
        if mode == "personal":
            result = c.search_personal(
                keyword=request.args.get("keyword", ""),
                teacher=request.args.get("teacher") or "",
                college=request.args.get("college") or None,
                campus=request.args.get("campus") or None,
                category=request.args.get("category") or None,
                language=request.args.get("language") or None,
                cultivation=request.args.get("cultivation") or None,
                ignore_conflicts=request.args.get("ignore_conflicts") == "1",
                ignore_zero_capacity=request.args.get("ignore_zero_capacity") == "1",
                weekday=_int_or_none(request.args.get("weekday")),
                period_start=_int_or_none(request.args.get("period_start")),
                period_end=_int_or_none(request.args.get("period_end")),
                xkfsdm=request.args.get("xkfsdm") or None,
                page=int(request.args.get("page", "1")),
                page_size=int(request.args.get("page_size", "50")),
            )
            courses = result["courses"]
            enrolled = result["enrolled"]
            cart = result["cart"]
            out = [_course_to_dict(x) for x in courses]
            # Translate common TIS "operation failed" to friendly English
            msg = result["message"]
            if not result["ok"]:
                if msg == "操作失败":
                    msg = ("Course selection period not yet open. "
                           "Catalog mode shows all courses — use the toggle above.")
                elif not msg:
                    msg = "Personal selection unavailable."
            return jsonify({
                "mode": "personal",
                "ok": result["ok"],
                "count": len(courses),
                "total": result["total"],
                "courses": out,
                "enrolled": enrolled,
                "cart": cart,
                "message": msg,
                "course_types": result["course_types"],
                "current_type": result["current_type"],
            })
        else:
            # Campus mode (default)
            courses = c.search_campus(
                keyword=request.args.get("keyword", ""),
                teacher=request.args.get("teacher") or None,
                college=request.args.get("college") or None,
                college_code=request.args.get("college_code") or None,
                campus=request.args.get("campus") or None,
                category=request.args.get("category") or None,
                task_type=request.args.get("task_type") or None,
                language=request.args.get("language") or None,
                cultivation=request.args.get("cultivation") or None,
                scheduled_only=request.args.get("scheduled") == "1",
            )
    except Exception as e:
        return jsonify({"error": str(e), "courses": []}), 200
    out = [_course_to_dict(x) for x in courses[: 3000]]
    return jsonify({
        "mode": "campus",
        "count": len(courses), "shown": len(out), "courses": out,
    })


@bp.route("/api/tis/refresh", methods=["POST"])
def api_refresh():
    xn, xq = _parse_sem(request.args)
    try:
        c = _client(xn, xq)
        n = c.refresh()
        return jsonify({"ok": True, "count": n})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/tis/course/<rwh>")
def api_course(rwh: str):
    xn, xq = _parse_sem(request.args)
    try:
        c = _client(xn, xq)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    for x in c.list_courses():
        if x.rwh == rwh:
            return jsonify(_course_to_dict(x))
    return jsonify({"error": "not found"}), 404


@bp.route("/api/tis/enrolled")
def api_enrolled():
    xn, xq = _parse_sem(request.args)
    sem = request.args.get("semester") or f"{xn}-{xq}"
    try:
        c = _client(xn, xq)
        items = c.my_courses(sem)
    except Exception as e:
        return jsonify({"error": str(e), "enrolled": []}), 200
    return jsonify({"semester": sem, "enrolled": items})


# ── Solver: non-conflicting section combinations with priority dropping ─────
def _slots_overlap(a: dict, b: dict) -> bool:
    if a.get("day") != b.get("day"):
        return False
    ap = set(range(int(a["period_start"]), int(a["period_end"]) + 1))
    bp = set(range(int(b["period_start"]), int(b["period_end"]) + 1))
    if not (ap & bp):
        return False
    aw = set(a.get("weeks") or [])
    bw = set(b.get("weeks") or [])
    if aw and bw and not (aw & bw):
        return False
    return True


def _sections_conflict(slots_a: List[dict], slots_b: List[dict]) -> bool:
    return any(_slots_overlap(x, y) for x in slots_a for y in slots_b)


def _conflicts_blocked(slots, blocked_slots):
    for bd, bps in blocked_slots:
        for s in slots:
            if s.get("day") == bd and set(range(int(s["period_start"]),
                      int(s["period_end"]) + 1)) & bps:
                return True
    return False


@bp.route("/api/tis/solve", methods=["POST"])
def api_solve():
    """Solve for non-conflicting combinations with priority dropping.

    Like c.x-d.fun: operates on the user's **picked sections** (by RWH),
    groups them by course code, and tries all section combinations.
    If no full schedule works, it tries dropping entire course codes
    (lower priority first).

    Request body:
      codes    — list of course codes (deduplicated)
      priority — same codes in priority order (most important first)
      rwhs     — list of RWH strings the user actually picked
      blocked  — list of [day, [periods]] to exclude
      max      — max solutions total (default 30)
    """
    body = request.get_json(silent=True) or {}
    codes: list = body.get("codes", [])
    priority: list = body.get("priority", codes)
    rwhs: list = body.get("rwhs", [])
    blocked: list = body.get("blocked", [])
    max_res = int(body.get("max", 30))

    xn, xq = _parse_sem(request.args)
    try:
        c = _client(xn, xq)
        all_courses = c.list_courses()
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    # Build a lookup from rwh → course, then group by code
    by_rwh = {x.rwh: x for x in all_courses}
    # Only use the specific sections the user picked
    by_code: Dict[str, list] = {}
    for rwh in rwhs:
        course = by_rwh.get(rwh)
        if course:
            by_code.setdefault(course.code, []).append(course)

    if not by_code:
        return jsonify({"solutions": [], "count": 0})

    blocked_slots = [(b[0], set(b[1])) for b in blocked]

    # Build priority index for sorting subsets
    pidx = {code: i for i, code in enumerate(priority)}

    # Only codes that have at least one picked section
    active_codes = [co for co in codes if co in by_code]
    if not active_codes:
        return jsonify({"solutions": [], "count": 0})

    def _solve_subset(subset_codes: List[str], _limit: int) -> list:
        """Backtrack to find non-conflicting combos for this subset (max _limit).
        Tries each section option (bundle) per course code group."""
        result: list = []

        def backtrack(i: int, current: list):
            if len(result) >= _limit:
                return
            if i == len(subset_codes):
                result.append([_course_to_dict(x) for x in current])
                return
            for sec in by_code[subset_codes[i]]:
                if not sec.has_schedule:
                    continue
                if _conflicts_blocked(sec.slots_raw, blocked_slots):
                    continue
                if any(_sections_conflict(sec.slots_raw, y.slots_raw) for y in current):
                    continue
                current.append(sec)
                backtrack(i + 1, current)
                current.pop()

        backtrack(0, [])
        return result

    n = len(active_codes)
    final_solutions: list = []
    remaining_budget = max_res

    # Try sizes from n down to 1 — like c.x-d.fun's dfsWithSkips
    for size in range(n, 0, -1):
        if remaining_budget <= 0:
            break
        # All subsets of this size, sorted by priority (higher priority = better)
        subsets: List[tuple] = list(itertools.combinations(active_codes, size))
        subsets.sort(key=lambda s: sum(pidx.get(c, 999) for c in s))
        for subset in subsets:
            if remaining_budget <= 0:
                break
            subset_list = list(subset)
            solutions = _solve_subset(subset_list, remaining_budget)
            if solutions:
                kept_codes = set(s["code"] for s in solutions[0])
                dropped = [c for c in active_codes if c not in kept_codes]
                dropped.sort(key=lambda c: pidx.get(c, 999))
                for sol in solutions:
                    final_solutions.append({
                        "sections": sol,
                        "covered": len(sol),
                        "total": n,
                        "dropped": dropped,
                        "size": size,
                    })
                remaining_budget -= len(solutions)

    # Sort: higher coverage first, then by priority (lower sum = better priority kept)
    final_solutions.sort(key=lambda s: (
        -s["covered"],
        sum(pidx.get(c, 999) for c in {x["code"] for x in s["sections"]})
    ))

    return jsonify({
        "solutions": final_solutions[:max_res],
        "count": len(final_solutions),
        "codes": active_codes,
        "priority": priority,
    })


# ── Write side (dry-run by default; commit is opt-in) ───────────────────────
def _write(action: str, rwh: str, *, dry_run: bool, **kw):
    xn, xq = _parse_sem(request.args)
    try:
        c = _client(xn, xq)
        fn = {"add": c.add_course, "drop": c.drop_course,
              "add_to_cart": c.add_to_cart, "remove_from_cart": c.remove_from_cart}[action]
        res = fn(rwh, dry_run=dry_run, **{k: v for k, v in kw.items() if v is not None})
        return jsonify(res)
    except EnrollmentError as e:
        return jsonify({"ok": False, "error": str(e), "jg": e.jg,
                        "message": e.message}), 200
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/tis/add", methods=["POST"])
def api_add():
    b = request.get_json(silent=True) or {}
    return _write("add", b.get("rwh", ""),
                  dry_run=b.get("dry_run", True),
                  ignore_conflicts=b.get("ignore_conflicts"),
                  ignore_zero_capacity=b.get("ignore_zero_capacity"),
                  pylx=b.get("pylx"))


@bp.route("/api/tis/drop", methods=["POST"])
def api_drop():
    b = request.get_json(silent=True) or {}
    return _write("drop", b.get("rwh", ""), dry_run=b.get("dry_run", True),
                  pylx=b.get("pylx"))


@bp.route("/api/tis/add-to-cart", methods=["POST"])
def api_add_cart():
    b = request.get_json(silent=True) or {}
    return _write("add_to_cart", b.get("rwh", ""), dry_run=b.get("dry_run", True),
                  pylx=b.get("pylx"))


@bp.route("/api/tis/remove-from-cart", methods=["POST"])
def api_remove_cart():
    b = request.get_json(silent=True) or {}
    return _write("remove_from_cart", b.get("rwh", ""), dry_run=b.get("dry_run", True),
                  pylx=b.get("pylx"))


# ── NCES community eval overlay ──────────────────────────────────────────────
@bp.route("/api/tis/nces")
def api_nces():
    """Fetch course evaluations from ncesnext.com."""
    code = (request.args.get("code") or "").strip()
    if not code:
        return jsonify({"available": False, "reason": "no course code provided"})
    # NCES uses JS rendering + bot protection — server-side fetch blocked.
    # Provide the direct URL so the frontend can open it in a new tab.
    return jsonify({
        "available": True,
        "direct_url": f"https://ncesnext.com/search?q={code}",
        "results": [{"source": "ncesnext.com", "url": f"https://ncesnext.com/search?q={code}"}],
    })


# ── Selection course types (xkfsdm codes) ───────────────────────────────────
@bp.route("/api/tis/course-types")
def api_course_types():
    """Return available selection course types (xkfsdm list) from TIS.

    Uses queryYxkc which always returns the type config regardless
    of whether the user has enrolled courses or selection is active.
    """
    xn, xq = _parse_sem(request.args)
    try:
        c = _client(xn, xq)
        types = c.course_types()
    except Exception as e:
        return jsonify({"course_types": [], "error": str(e)}), 200
    return jsonify({"course_types": types})
