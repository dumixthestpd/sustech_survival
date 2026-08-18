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
       GET  /api/tis/course-types         → xkfsdm tabs
       GET  /api/tis/round                → 剩余积分 + round window (积分选课)
       POST /api/tis/bids                 → submit bid values for picked courses
       (NCES eval data served at /api/nces/code/<code> — see nces blueprint)

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

# Default semester for course selection — resolved from the live term.
def _default_sem() -> tuple[str, str]:
    from sustech_survival.semester import Semester
    s = Semester.current()
    return s.xn, s.xq


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
        "section_name": c.section_name, "section_name_en": c.section_name_en,
        "class_group": c.class_group, "rwh": c.rwh,
        "college": c.college, "category": c.category,
        "campus": c.campus,
        "credits": c.credits, "total_hours": c.total_hours,
        "capacity": c.capacity,
        "undergrad_seats": c.undergrad_seats, "grad_seats": c.grad_seats,
        "cultivation": c.cultivation,
        "enrolled": c.enrolled,
        "id": c.id,
        "rooms": c.rooms, "teachers": c.teachers,
        "schedule": c.schedule_str,
        "slots": c.slots_raw,
        "has_schedule": c.has_schedule,
        "task_type": c.task_type,
        "language": c.language,
        "college_code": c.college_code,
    }


def _parse_sem(args) -> tuple[str, str]:
    dxn, dxq = _default_sem()
    return (args.get("xn") or dxn, args.get("xq") or dxq)


def _int_or_none(v):
    try:
        return int(v) if v else None
    except (ValueError, TypeError):
        return None


# -- Page --------------------------------------------------------------------
@bp.route("/tis")
def page():
    xn, xq = _parse_sem(request.args)
    # The active head may provide its own /tis page. A custom (non-default)
    # head is authoritative: if it ships no tis.html, the feature is dropped
    # (404). Only the shipped default head falls back to the package template.
    from flask import current_app, abort, send_from_directory
    from pathlib import Path as _Path
    sr = current_app.config.get("SKIN_ROOT")
    _skin_root = _Path(sr) if sr else None
    if _skin_root and (_skin_root / "tis.html").is_file():
        return send_from_directory(_skin_root, "tis.html")
    if current_app.config.get("SKIN_IS_DEFAULT", False):
        return render_template("tis.html", xn=xn, xq=xq)
    abort(404)


# -- API ----------------------------------------------------------------------
@bp.route("/api/tis/info")
def api_info():
    """Semester info + filter options for the course search UI.

    TIS mapping:
      colleges       → (kkyx code, kkyxmc) pairs
      categories     → kclbmc values
      category_codes → kclbmc → kclbdm map (for personal-mode search)
      task_types     → rwlxmc values  — e.g. 通识必修选课, 通识选修选课, ...
      languages      → skyymc values  — 中文, 英文, 双语
      language_codes → skyymc → skyydm map
      campuses       → xiaoqumc
      cultivation    → 本科 / 研究生
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

    # Augment categories with kclbdm codes from the central map. Only
    # categories that have a known code get the annotation; the rest
    # (e.g. "通识必修课-外语类" the catalog sometimes produces) still show
    # in the dropdown but won't have a code suffix. Frontend can use
    # `category_codes` as a translation dict before sending the filter.
    from sustech_survival.selectcourse import CATEGORY_MAP, LANGUAGE_MAP
    category_codes = {name: CATEGORY_MAP.get(name, "") for name in opts["categories"]}
    return jsonify({
        "semester": {"xn": xn, "xq": xq, "label": semester_label},
        "count": len(c.list_courses()),
        "colleges": opts["colleges"],         # [(code, name), ...]
        "categories": opts["categories"],     # [name, ...]
        "category_codes": category_codes,     # {name: code, ...}
        "language_codes": LANGUAGE_MAP,       # {name: code, ...}
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
                round_code=request.args.get("round_code") or request.args.get("xkfsdm") or None,
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
                "round": result.get("round", {}),
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


@bp.route("/api/tis/refresh-load", methods=["POST"])
def api_refresh_load():
    """Fetch live "currently selected" counts for the current search filters.

    Hits TIS's personal-mode search (`Xsxk/queryKxrw`) which is the only
    endpoint that exposes per-row enrollment (`bkrs`/`yxrs`/`xkrs`).
    Returns a `{rwh: enrolled_count}` map for every row the search
    returned — the frontend can then merge these into its local COURSES
    map and re-render so the `[N] / [M]` load badge fills in.

    Query params mirror `/api/tis/courses` (personal-mode filters):
      keyword, teacher, college, campus, category, language,
      cultivation, ignore_conflicts, ignore_zero_capacity,
      weekday, period_start, period_end, round_code, page_size

    If the personal endpoint is unavailable (round not open, TIS
    rate-limit, etc.) the response is `ok=false` with a friendly
    message and `loads={}` — the frontend should keep showing `? / M`
    on cards in that case.
    """
    xn, xq = _parse_sem(request.args)
    try:
        c = _client(xn, xq)
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
            round_code=request.args.get("round_code") or request.args.get("xkfsdm") or None,
            page=int(request.args.get("page", "1")),
            page_size=int(request.args.get("page_size", "500")),
        )
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "loads": {}}), 200

    if not result["ok"]:
        msg = result["message"]
        if msg == "操作失败":
            msg = ("Course selection period not yet open — cannot "
                   "fetch live load. Try again later, or use Catalog mode.")
        elif not msg:
            msg = "Personal selection unavailable."
        return jsonify({"ok": False, "message": msg, "loads": {}}), 200

    # Build the rwh → enrolled map. Skip rows where enrolled is None
    # (TIS doesn't always send it, and guessing wrong is worse than
    # leaving it blank — the UI shows `? / M` until known).
    loads = {}
    for course in result["courses"]:
        if course.enrolled is not None:
            loads[course.rwh] = course.enrolled
    return jsonify({
        "ok": True,
        "loads": loads,
        "fetched": len(result["courses"]),
        "with_count": len(loads),
        "round": result.get("round", {}),
    })


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
        raw = c.my_courses(sem)
    except Exception as e:
        return jsonify({"error": str(e), "enrolled": []}), 200
    # `my_courses` returns TIS personal-schedule rows — one row per
    # (rwh × schedule-block × week-parity × 校区), NOT per enrolled
    # course. Dedupe by rwh and lift the kcmc / section out of the
    # multi-line SKSJ string so the frontend renders one card per
    # actually-enrolled course, not 4-13 mostly-empty cards. We also
    # lift the schedule slots out of the raw row fields so the step-3
    # weekly grid can render TIS-enrolled alongside picked sections.
    by_rwh: "dict[str, dict]" = {}
    for row in raw:
        rwh = row.get("RWH") or row.get("rwh") or ""
        if not rwh:
            continue
        if rwh in by_rwh:
            continue
        sksj = row.get("SKSJ") or ""
        # SKSJ shape (newline-joined):
        #   kcmc                     ← course name
        #   [teacher, ...]           ← teacher list
        #   [section / class group]
        #   [weeks][day][periods]
        #   [room]
        lines = [ln.strip() for ln in sksj.splitlines() if ln.strip()]
        name = lines[0] if lines else ""
        # Drop [brackets] from the section line for a clean display.
        section = lines[2] if len(lines) >= 3 else ""
        if section.startswith("[") and section.endswith("]"):
            section = section[1:-1]
        # The first schedule-block row for this rwh has the meta that
        # kcmc/section came from, but every block for the rwh shares
        # those (only KEY / KSJC / JSJC / ZC differ per block). We need
        # to walk ALL blocks to build the full slot list, so iterate
        # the raw rows once more for this rwh.
        slots: list = []
        for sb in raw:
            if (sb.get("RWH") or sb.get("rwh") or "") != rwh:
                continue
            slot = _raw_schedule_slot(sb)
            if slot is not None:
                slots.append(slot)
        by_rwh[rwh] = {
            "rwh": rwh,
            "name": name,
            "section": section,
            "code": rwh_to_code(rwh),
            # Schedule data so the step-3 grid can render the enrolled
            # course block alongside picked sections. Same shape as
            # `Course.slots_raw` (a list of {day, period_start,
            # period_end, weeks: [...]}). `weeks` uses 0=odd, 1=even
            # to match sectionsToBlocks().
            "slots": slots,
            "has_schedule": bool(slots),
            "enrolled": True,  # marker so frontend can show 🔒 badge
        }
    items = list(by_rwh.values())
    return jsonify({"semester": sem, "enrolled": items})


def rwh_to_code(rwh: str) -> str:
    """Extract the course code from an rwh like '2026-2027-1-MSE307-002' → 'MSE307'."""
    if not rwh:
        return ""
    parts = rwh.split("-")
    # parts: ['2026', '2027', '1', 'MSE307', '002']
    if len(parts) >= 5:
        return parts[3]
    if len(parts) >= 4:
        return parts[3]
    return ""


def _raw_schedule_slot(row: dict) -> "dict | None":
    """Build a Course.slots_raw-shaped dict from a raw TIS schedule row.

    Raw fields used:
      KEY = "xq<N>_jc<M>"     — N is weekday (1-7), M is the index of the
                                class block on that day (1st, 2nd, 3rd, 4th).
                                NOT the period number. Don't trust it for
                                period_start — use KSJC for that.
      KSJC                   — start period (1-12)
      JSJC                   — END period (inclusive). NOT a count.
                                JSJC=8 with KSJC=7 means periods 7-8,
                                not "8 periods". Verified 2026-08-09.
      ZC = "01010101..."      — 32-char binary week-parity pattern. ZC[i]=1
                                means week (i+1) is active. ZC[0] is week 1
                                (was being skipped previously with i+1).
                                Verified 2026-08-09 against [1-16周],
                                [1-15单周], [2-16双周] all matching
                                after this fix.

    Returns a dict with day / period_start / period_end / weeks, or None
    if the row doesn't have enough data to build one.
    """
    key = row.get("KEY") or ""
    ksjc = row.get("KSJC")
    jsjc = row.get("JSJC")
    zc = row.get("ZC") or ""
    # Parse weekday out of KEY: "xq3_jc1" → 3. The `jc<N>` part is the
    # class-block index on that day, NOT the period — ignore it for
    # period math. The weekday is the only useful bit from KEY.
    m = key.split("_") if key else []
    if not m or len(m) < 2:
        return None
    try:
        weekday = int(m[0].lstrip("xq")) if m[0].startswith("xq") else None
    except (TypeError, ValueError):
        return None
    if weekday is None or weekday < 1 or weekday > 7:
        return None
    # Period start/end come from KSJC and JSJC — they're the actual
    # period numbers (inclusive). Earlier code treated JSJC as a count
    # (period_end = KSJC + JSJC - 1) which stretched short blocks across
    # 8+ rows of the schedule grid. Verified against the SKSJ text
    # ("7-8节" → KSJC=7, JSJC=8 → periods 7-8) on 2026-08-09.
    if ksjc is None or jsjc is None:
        return None
    period_start = int(ksjc)
    period_end = int(jsjc)
    # Parse ZC: 32-char binary string, position N (0-indexed) = "is
    # week N+1 active?". Wait — verified against real data 2026-08-09:
    #   [1-16周]   → ZC active at positions 1-16  (positions 0 and 17-31 = 0)
    #   [1-15单周] → ZC active at odd positions 1,3,5,...,15
    #   [2-16双周] → ZC active at even positions 2,4,6,...,16
    # In every case ZC[0] is '0' regardless of pattern, and the i-th
    # '1' bit corresponds to the i-th active week (1-indexed). So the
    # correct mapping is "ZC[i]=1 means week i+1 is active" — append
    # `i + 1`. But that gave weeks 2-17 for [1-16周] above — so the
    # mapping is actually "ZC[i]=1 means week i+1 active" and the
    # pattern positions line up to weeks (i+1). For [1-16周] active
    # positions 1-16 → weeks 2-17, which is OFF BY ONE — the user
    # expects weeks 1-16.
    #
    # The simplest hypothesis that fits all three: ZC is 1-indexed
    # against weeks, but position 0 is a 1-char buffer/header. So:
    #   ZC[0] = unused
    #   ZC[i] for i>=1 = "is week i active?" → append i (not i+1)
    # That gives:
    #   [1-16周]   active 1-16 → weeks 1-16 ✓
    #   [1-15单周] active 1,3,...,15 → weeks 1,3,...,15 ✓
    #   [2-16双周] active 2,4,...,16 → weeks 2,4,...,16 ✓
    # Use `weeks.append(i)` and skip ZC[0] explicitly.
    weeks: list = []
    for i, ch in enumerate(zc):
        if i == 0:
            continue  # ZC[0] is a 1-char header / unused, not week 0
        if ch == "1":
            weeks.append(i)  # i=1 → week 1, i=16 → week 16
    if not weeks:
        return None
    return {
        "day": weekday,
        "period_start": period_start,
        "period_end": period_end,
        "weeks": weeks,
        "room": (row.get("JASMC") or ""),  # classroom name if available
    }


# -- Solver: non-conflicting section combinations with priority dropping -----
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
      codes       — list of course codes (deduplicated)
      priority    — same codes in priority order (most important first)
      rwhs        — list of RWH strings the user actually picked
      blocked     — list of [day, [periods]] to exclude
      locked_rwhs — list of RWH strings that MUST appear in every
                    solution. Their codes get the highest priority
                    (index 0) and the solver drops other codes first.
                    Use this for "TIS-enrolled is unquestionable":
                    TIS-enrolled rwhs go in here, and the solver drops
                    other picked courses to make them fit.
      max         — max solutions total (default 30)
    """
    body = request.get_json(silent=True) or {}
    codes: list = body.get("codes", [])
    priority: list = list(body.get("priority", codes))
    rwhs: list = body.get("rwhs", [])
    blocked: list = body.get("blocked", [])
    locked_rwhs: list = body.get("locked_rwhs", []) or []
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

    # Compute locked codes (codes that have at least one locked rwh).
    # When the user marks TIS-enrolled as "unquestionable", these
    # codes win every conflict — solver drops other picked courses
    # before touching them. We prepend them to priority so they sort
    # first (lowest pidx = highest priority = last dropped).
    locked_set = set(locked_rwhs)
    locked_codes: list = []
    for code, secs in by_code.items():
        if any(s.rwh in locked_set for s in secs):
            locked_codes.append(code)
    for code in locked_codes:
        if code in priority:
            priority.remove(code)
        priority.insert(0, code)

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
            code = subset_codes[i]
            for sec in by_code[code]:
                if not sec.has_schedule:
                    continue
                # Locked rwhs MUST appear in every solution — never pick
                # an alternative section for a code that has a locked
                # rwh. (There's exactly one section per locked rwh — the
                # actual enrolled slot — so this filter just enforces
                # "use the enrolled section, not a phantom alternative.")
                if code in locked_codes and sec.rwh not in locked_set:
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
    # Locked codes MUST be in every subset — restrict the iteration to
    # subsets that contain all of them. The solver would still try
    # dropping them otherwise (it's a global "drop lowest priority"
    # rule), which is exactly what the user said NO to.
    free_codes = [c for c in active_codes if c not in set(locked_codes)]
    if locked_codes and not free_codes:
        # Only locked codes present; trivially solve if compatible
        return jsonify({
            "solutions": [{
                "sections": [_course_to_dict(s) for s in
                             [sec for code in locked_codes for sec in by_code[code]
                              if sec.rwh in locked_set and sec.has_schedule]],
                "covered": len(locked_codes),
                "total": n,
                "dropped": [],
                "size": len(locked_codes),
            }],
            "count": 1,
            "codes": active_codes,
            "priority": priority,
        })
    # The max subset size is len(free_codes) + len(locked_codes) — every
    # solution must include all locked codes.
    max_subset_size = len(free_codes) + len(locked_codes)
    # Min size is locked_codes (at least — if they fit alone)
    min_subset_size = len(locked_codes)

    final_solutions: list = []
    remaining_budget = max_res

    # Try sizes from max down to min. For each size, enumerate
    # combinations of free_codes (size - len(locked_codes)) and
    # always include locked_codes.
    for size in range(max_subset_size, min_subset_size - 1, -1):
        if remaining_budget <= 0:
            break
        free_needed = size - len(locked_codes)
        subsets: List[tuple] = list(itertools.combinations(free_codes, free_needed))
        # Sort by priority sum: lower pidx = higher priority = preferred.
        subsets.sort(key=lambda s: sum(pidx.get(c, 999) for c in s))
        for subset in subsets:
            if remaining_budget <= 0:
                break
            subset_list = list(locked_codes) + list(subset)
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


# -- Write side (dry-run by default; commit is opt-in) -----------------------
def _write(action: str, rwh: str, *, dry_run: bool, **kw):
    xn, xq = _parse_sem(request.args)
    try:
        c = _client(xn, xq)
        fn = {"add": c.add_course, "drop": c.drop_course,
              "add_to_cart": c.add_to_cart, "remove_from_cart": c.remove_from_cart}[action]
        res = fn(rwh, dry_run=dry_run, **{k: v for k, v in kw.items() if v is not None})
        # Surface consequence metadata so the UI can warn before a real commit.
        from sustech_survival.consequence import consequence_by_name
        _name = {"add": "selectcourse.add_course", "drop": "selectcourse.drop_course",
                 "add_to_cart": "selectcourse.add_to_cart",
                 "remove_from_cart": "selectcourse.remove_from_cart"}[action]
        cons = consequence_by_name(_name)
        if isinstance(res, dict) and cons is not None and not dry_run:
            res = dict(res)
            res["consequence"] = {
                "severity": cons.severity.value,
                "irreversible": cons.irreversible,
                "what_changes": cons.what_changes,
                "risk": cons.risk,
                "verify_url": cons.verify_url,
            }
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
                  dry_run=b.get("dry_run", False),
                  ignore_conflicts=b.get("ignore_conflicts"),
                  ignore_zero_capacity=b.get("ignore_zero_capacity"),
                  pylx=b.get("pylx"))


@bp.route("/api/tis/drop", methods=["POST"])
def api_drop():
    b = request.get_json(silent=True) or {}
    return _write("drop", b.get("rwh", ""), dry_run=b.get("dry_run", False),
                  pylx=b.get("pylx"))


@bp.route("/api/tis/add-to-cart", methods=["POST"])
def api_add_cart():
    b = request.get_json(silent=True) or {}
    return _write("add_to_cart", b.get("rwh", ""), dry_run=b.get("dry_run", False),
                  pylx=b.get("pylx"))


@bp.route("/api/tis/remove-from-cart", methods=["POST"])
def api_remove_cart():
    b = request.get_json(silent=True) or {}
    return _write("remove_from_cart", b.get("rwh", ""), dry_run=b.get("dry_run", False),
                  pylx=b.get("pylx"))


# -- NCES community eval overlay ----------------------------------------------
# Moved to blueprints/nces.py — NCES is its own submodule parallel to TIS,
# not a feature of TIS. See sustech_survival/nces/. Endpoint paths: /api/nces/*.


# -- Selection course types (xkfsdm codes) -----------------------------------
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


# -- Bid panel (积分选课) -----------------------------------------------------
@bp.route("/api/tis/round")
def api_round():
    """Return the current selection round's bid-relevant metadata.

    jffs  = 剩余积分 (credits remaining for this student this round)
    ksrq  = 选课开始时间 (round start)
    jsrq  = 选课结束时间 (round end)
    lcmc  = round phase label (预选 / 退补课 / ...)
    kxrwlbsfxsxkxqxgkc = whether 选课显示结果 (TIS-side UI flag)
    """
    xn, xq = _parse_sem(request.args)
    round_code = request.args.get("round_code", "") or request.args.get("xkfsdm", "")
    try:
        c = _client(xn, xq)
        res = c.search_personal(round_code=round_code, page=1, page_size=1)
        ct = res.get("current_type") or {}
        return jsonify({
            "ok": res.get("ok", False),
            "xkfsdm": ct.get("xkfsdm", round_code),
            "jffs": float(ct.get("jfxs") or 0),
            "ksrq": ct.get("ksrq", ""),
            "jsrq": ct.get("jsrq", ""),
            "lcmc": ct.get("lcmc", ""),
            "xkms": ct.get("xkms", ""),
            "message": res.get("message", ""),
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "jffs": 0}), 200


@bp.route("/api/tis/bids", methods=["POST"])
def api_bids():
    """Submit a batch of bid values for the user's picked courses.

    Body:
      {
        "picks":     {rwh: bid, ...},    # the user's desired bid per course
        "id_map":    {rwh: id_hex, ...}, # optional: 32-char hex UUID per rwh
                                        # (TIS write-key). If missing, we
                                        # run a personal-mode search to
                                        # populate Course.id on the client
                                        # cache, then look up.
        "round_code": "...",             # selection round code (TIS xkfsdm)
        "xkfsdm":    "...",              # optional override; defaults to "yixuan"
        "where":     "cart" | "enrolled",
        "jffs_limit": <float>,           # optional: from /api/tis/round
        "pylx":      "1" | "2",
        "dry_run":   <bool>              # default True
      }

    Always returns 200 with structured result. TIS per-course failures
    are inside `results[*].ok` / `results[*].message`.
    """
    b = request.get_json(silent=True) or {}
    picks = b.get("picks") or {}
    id_map = b.get("id_map") or {}
    round_code = b.get("round_code", "") or ""
    xkfsdm = b.get("xkfsdm") or None
    where = b.get("where", "cart") or "cart"
    pylx = b.get("pylx")
    dry_run = bool(b.get("dry_run", True))
    jffs_limit = b.get("jffs_limit")
    if jffs_limit is not None:
        try:
            jffs_limit = float(jffs_limit)
        except (TypeError, ValueError):
            jffs_limit = None

    if not isinstance(picks, dict) or not picks:
        return jsonify({"ok": False, "error": "picks must be a non-empty dict",
                        "results": [], "sum": 0, "jffs_limit": jffs_limit,
                        "over_limit": False}), 200

    xn, xq = _parse_sem(request.args)
    try:
        c = _client(xn, xq)
        # If id_map wasn't supplied, run a personal search first so the
        # catalog's Course.id field gets populated. Then look up.
        if not id_map:
            try:
                c.search_personal(round_code=round_code or None,
                                  page_size=500)
            except Exception:
                pass
            for rwh in picks.keys():
                hit = c._lookup_id(rwh)
                if hit:
                    id_map[rwh] = hit
        result = c.submit_bids(picks, round_code=round_code, where=where,
                               jffs_limit=jffs_limit, pylx=pylx,
                               dry_run=dry_run, id_map=id_map,
                               xkfsdm=xkfsdm)
        return jsonify(result)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "results": []}), 200


@bp.route("/api/tis/ical", methods=["GET"])
def api_ical():
    """Build an .ics file from the current picked list.

    Reads the picked list from sessionStorage on the client (passed as the
    ``picks`` query param, JSON-encoded). Each pick is a dict of class-time
    fields; this route maps them to ``calendar.ClassTime`` and registers
    them on the resolved Semester, then hands off to
    ``selectcourse.ical.courses_to_ical``.

    Calendar is loaded online (GitHub raw is the canonical source). If the
    fetch fails, fall back to a 502 with a useful error.
    """
    import json as _json
    from flask import Response, current_app
    from sustech_survival.calendar import (
        AcademicCalendar, ClassTime, CalendarError,
    )
    from sustech_survival.selectcourse.ical import courses_to_ical

    raw = request.args.get("picks", "")
    if not raw:
        return Response("missing 'picks' query param", status=400,
                        mimetype="text/plain")
    try:
        picks = _json.loads(raw)
    except Exception as e:
        return Response(f"invalid 'picks' JSON: {e}", status=400,
                        mimetype="text/plain")
    if not isinstance(picks, list) or not picks:
        return Response("'picks' must be a non-empty list", status=400,
                        mimetype="text/plain")

    xn, xq = _parse_sem(request.args)
    try:
        # xn is "2025-2026", split year for AcademicCalendar
        cal_year = int(xn.split("-")[0]) + (1 if xq == "2" else 0)
        cal = AcademicCalendar.load(cal_year, "undergraduate")
    except CalendarError as e:
        return Response(f"calendar load failed: {e}", status=502,
                        mimetype="text/plain")
    except Exception as e:
        return Response(f"calendar load failed: {type(e).__name__}: {e}",
                        status=502, mimetype="text/plain")

    sem = cal.spring if xq == "2" else cal.fall
    if sem is None:
        return Response(f"semester not found for {xn}-{xq}", status=404,
                        mimetype="text/plain")

    for p in picks:
        try:
            weeks = tuple(int(w) for w in p.get("weeks", []))
            periods = tuple(int(x) for x in p.get("periods", []))
            ct = ClassTime(
                weeks=weeks,
                weekday=int(p.get("weekday", 0)),
                periods=periods,
                title=p.get("title", ""),
                teacher=p.get("teacher", ""),
                room=p.get("room", ""),
            )
            sem.fill(ct)
        except Exception as e:
            # Skip malformed entries but keep going — best-effort export.
            current_app.logger.warning("ical: skipped pick %r: %s", p, e)

    text = courses_to_ical(sem)
    return Response(text, mimetype="text/calendar")
