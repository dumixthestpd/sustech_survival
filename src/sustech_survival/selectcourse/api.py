"""sustech_survival.selectcourse.api — TIS course-selector web API.

Page:  GET /tis                → course catalog page (painted by the active skin)
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
       GET  /api/tis/ical                 → .ics export of picked courses
       POST /api/tis/refresh-load         → live "currently selected" counts

All data comes from the existing ``SelectCourseClient`` so this layer
contains no business logic — it only serializes Course objects and
proxies write calls. The browser never sees credentials/cookies.

Two search modes:
  GET /api/tis/courses?mode=campus (default) — 全校课表, all courses
  GET /api/tis/courses?mode=personal — 选课, your eligible courses

The /tis page route is also handled here because it is inseparable from
the API surface (the page calls these endpoints). The active skin owns
the actual HTML file; this route just resolves the skin-local file.
"""
from __future__ import annotations

import itertools
import json
import threading
from typing import Dict, List

from flask import Response, abort, current_app, jsonify, request, send_from_directory
from pathlib import Path as _Path

from sustech_survival.semester import Semester, Season
from sustech_survival.selectcourse.selectcourse import (
    EnrollmentError,
    SelectCourseClient,
    selectcourse as sc_factory,
)
from sustech_survival.webui.api_registry import CollectorRegistry


def register(reg: CollectorRegistry) -> None:
    """Wire up the TIS endpoints under the collector."""

    # -- Page ---------------------------------------------------------------
    @reg.page("tis.page", "/tis")
    def page():
        # The active skin owns its /tis page: the skin's root tis.html is
        # served if present; a head that ships no tis.html has dropped the
        # feature (404). There is NO package-level fallback template — skins
        # are self-contained and paint the page from /api/tis/* themselves.
        sr = current_app.config.get("SKIN_ROOT")
        _skin_root = _Path(sr) if sr else None
        if _skin_root:
            plain = _skin_root / "tis.html"
            if plain.is_file():
                return send_from_directory(plain.parent, plain.name)
        abort(404)

    # -- API ---------------------------------------------------------------
    @reg.get("tis.info", "/api/tis/info")
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
        # (e.g. "通识必修课-外语类" the catalog sometimes produces) still
        # show in the dropdown but won't have a code suffix. Frontend can
        # use `category_codes` as a translation dict before sending the
        # filter.
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

    @reg.get("tis.courses", "/api/tis/courses")
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
          weekday (1-7), period_start, period_end, free_weekday (1-7),
          free_period_start, free_period_end, page, page_size
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
                    free_weekday=_int_or_none(request.args.get("free_weekday")),
                    free_period_start=_int_or_none(request.args.get("free_period_start")),
                    free_period_end=_int_or_none(request.args.get("free_period_end")),
                    round_code=request.args.get("round_code") or request.args.get("xkfsdm") or None,
                    page=int(request.args.get("page", "1")),
                    page_size=int(request.args.get("page_size", "50")),
                )
                courses = result["courses"]
                out = [_course_to_dict(x) for x in courses]
                # Enrolled (yxkcList) / cart (xkgwcList) rows arrive RAW
                # from search_personal. Parse them into the SAME
                # render-ready shape as `courses` so the skin can show
                # the enrolled courses with full details (code, name,
                # teachers, schedule, credits, grading, capacity, bid)
                # — not just a count. Raw `xkxs` is kept on the row so
                # older skins (default_zh reads items[i].xkxs) keep
                # working unchanged.
                enrolled = [_member_row(e, tis_enrolled=True)
                            for e in (result["enrolled"] or [])]
                cart = [_member_row(g, in_cart=True)
                        for g in (result["cart"] or [])]
                # Translate common TIS "operation failed" to friendly English.
                # 操作失败 is GENERIC — never claim "round closed"; the real
                # cause is usually a missing/wrong selection-round code
                # (xkfsdm), which TIS refuses with this while a round is open.
                msg = result["message"]
                if not result["ok"]:
                    if msg == "操作失败":
                        msg = ("TIS rejected the personal query (raw: 操作失败) — "
                               "the selection round (xkfsdm) is probably unset or "
                               "wrong for the current phase. Pick a round in the "
                               "tabs, or use Catalog mode.")
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

    @reg.post("tis.refresh", "/api/tis/refresh")
    def api_refresh():
        xn, xq = _parse_sem(request.args)
        try:
            c = _client(xn, xq)
            n = c.refresh()
            return jsonify({"ok": True, "count": n})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500

    @reg.post("tis.refresh-load", "/api/tis/refresh-load")
    def api_refresh_load():
        """Fetch live "currently selected" counts for the current search filters.

        Hits TIS's personal-mode search (``Xsxk/queryKxrw``) which is the
        only endpoint that exposes per-row enrollment
        (``bkrs``/``yxrs``/``xkrs``). Returns a ``{rwh: enrolled_count}``
        map for every row the search returned — the frontend can then
        merge these into its local COURSES map and re-render so the
        ``[N] / [M]`` load badge fills in.

        Query params mirror ``/api/tis/courses`` (personal-mode filters):
          keyword, teacher, college, campus, category, language,
          cultivation, ignore_conflicts, ignore_zero_capacity,
          weekday, period_start, period_end, round_code, page_size

        If the personal endpoint is unavailable (round not open, TIS
        rate-limit, etc.) the response is ``ok=false`` with a friendly
        message and ``loads={}`` — the frontend should keep showing
        ``? / M`` on cards in that case.
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
                msg = ("TIS rejected the load query (raw: 操作失败) — the "
                       "selection round (xkfsdm) is probably unset or wrong "
                       "for the current phase.")
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

        # Backfill: explicit rwhs (e.g. picks loaded from a saved file)
        # that the filtered search page did not return. Live counts exist
        # only in the personal search, so run ONE keyword=code search per
        # distinct missing code (no other filters — we only want the
        # section rows) and merge. This is what keeps a pick row's
        # badge from sitting at "? / M" forever.
        extra_rwhs = [r.strip() for r in (request.args.get("rwhs", "") or "").split(",") if r.strip()]
        if extra_rwhs:
            missing = [r for r in extra_rwhs if r not in loads]
            if missing:
                code_by_rwh: Dict[str, str] = {}
                try:
                    for x in c.list_courses():
                        code_by_rwh.setdefault(x.rwh, x.code)
                except Exception:
                    code_by_rwh = {}
                round_code = request.args.get("round_code") or request.args.get("xkfsdm") or None
                missing_codes = sorted({code_by_rwh[r] for r in missing if code_by_rwh.get(r)})
                for code in missing_codes:
                    try:
                        sub = c.search_personal(
                            keyword=code, page=1, page_size=100,
                            round_code=round_code,
                        )
                    except Exception:
                        continue
                    if not sub.get("ok"):
                        continue
                    for course in sub.get("courses", []):
                        if course.enrolled is not None:
                            loads.setdefault(course.rwh, course.enrolled)
        return jsonify({
            "ok": True,
            "loads": loads,
            "fetched": len(result["courses"]),
            "with_count": len(loads),
            "round": result.get("round", {}),
        })

    @reg.get("tis.course", "/api/tis/course/<rwh>")
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

    @reg.get("tis.enrolled", "/api/tis/enrolled")
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
            # Teacher list on line 2 (may carry literal brackets — strip
            # them, then split on the usual delimiters like from_api).
            teachers_raw = lines[1] if len(lines) >= 2 else ""
            if teachers_raw.startswith("[") and teachers_raw.endswith("]"):
                teachers_raw = teachers_raw[1:-1]
            import re as _re
            teachers = [t.strip() for t in _re.split(r"[,，、]", teachers_raw)
                        if t.strip()]
            # Drop [brackets] from the section line for a clean display.
            section = lines[2] if len(lines) >= 3 else ""
            if section.startswith("[") and section.endswith("]"):
                section = section[1:-1]
            # The first schedule-block row for this rwh has the meta that
            # kcmc/section came from, but every block for the rwh shares
            # those (only KEY / KSJC / JSJC / ZC differ per block). We
            # need to walk ALL blocks to build the full slot list, so
            # iterate the raw rows once more for this rwh.
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
                # Teachers so enrolled rows never render "TBD" when this
                # endpoint is the only data source (the personal-search
                # ingest also carries them; this covers toggle-first
                # flows and JSON-file enrichment).
                "teachers": teachers,
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

    @reg.post("tis.solve", "/api/tis/solve")
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
          required_codes — list of course CODES that MUST be covered in
                        every solution (MUST-take courses). Unlike
                        locked_rwhs, ANY section of the code is acceptable
                        (teacher/class doesn't matter) — only the code must
                        appear. If the full must-set is infeasible, the
                        best partial solutions are still returned, plus
                        must_feasible / must_impossible so the UI can
                        report "what got removed in must-takes".
          max         — max solutions total (default 30)
        """
        body = request.get_json(silent=True) or {}
        codes: list = body.get("codes", [])
        priority: list = list(body.get("priority", codes))
        rwhs: list = body.get("rwhs", [])
        blocked: list = body.get("blocked", [])
        locked_rwhs: list = body.get("locked_rwhs", []) or []
        required_codes: list = body.get("required_codes", []) or []
        max_res = int(body.get("max", 30))

        xn, xq = _parse_sem(request.args)
        try:
            c = _client(xn, xq)
            all_courses = c.list_courses()
        except Exception as e:
            return jsonify({"error": str(e)}), 500

        # An EMPTY catalog must never masquerade as "no valid combination".
        # TIS unreachable (off-campus/VPN), expired session, or a semester
        # with no offerings all produce an empty list — solving is then
        # impossible regardless of what the user picked/marked.
        if not all_courses:
            return jsonify({
                "solutions": [],
                "count": 0,
                "catalog_empty": True,
                "message": "Course catalog is empty — TIS is unreachable "
                           "(off-campus/VPN?) or the session expired. "
                           "Cannot solve until the catalog loads.",
            })

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

        # MUST-take pool: for required codes the solver may choose ANY
        # catalog section of the code — "no matter the teacher/class".
        # Locked rwhs stay exact; free codes stay picked-only.
        required_set = set(required_codes)
        must_all: Dict[str, list] = {}
        for code in required_codes:
            secs = [x for x in all_courses if x.code == code]
            if secs:
                must_all[code] = secs

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
                # Required (MUST-take) codes draw from ALL their catalog
                # sections; everything else from the user's picked sections.
                pool = must_all.get(code) if code in required_set else by_code.get(code, [])
                for sec in pool:
                    if not sec.has_schedule:
                        continue
                    # Locked rwhs MUST appear in every solution — never pick
                    # an alternative section for a code that has a locked
                    # rwh. (There's exactly one section per locked rwh —
                    # the actual enrolled slot — so this filter just
                    # enforces "use the enrolled section, not a phantom
                    # alternative.")
                    if code in locked_codes and sec.rwh not in locked_set:
                        continue
                    if _conflicts_blocked(sec.slots_raw, blocked_slots):
                        continue
                    if any(_sections_conflict(sec.slots_raw, y.slots_raw)
                           for y in current):
                        continue
                    current.append(sec)
                    backtrack(i + 1, current)
                    current.pop()

            backtrack(0, [])
            return result

        n = len(active_codes)

        final_solutions: list = []
        remaining_budget = max_res

        # Tiered MUST search (#4): first try the FULL must-set (drop_n=0),
        # then progressively allow dropping ONE required code at a time
        # (lowest priority first). When the full must-set is infeasible the
        # user still gets the best partial solutions — each annotated with
        # must_dropped ("what got removed in must-takes"). Locked rwhs are
        # never dropped at any tier.
        required_order = sorted(required_codes, key=lambda c: pidx.get(c, 999))
        for drop_n in range(0, len(required_order) + 1):
            if remaining_budget <= 0:
                break
            for dropped_required in itertools.combinations(required_order, drop_n):
                if remaining_budget <= 0:
                    break
                drop_set = set(dropped_required)
                tier_must = list(locked_codes) + [
                    c for c in required_order if c not in drop_set]
                tier_set = set(tier_must)
                free_codes = [c for c in active_codes if c not in tier_set]
                # Max subset size = free + tier_must; min = tier_must alone.
                for size in range(len(free_codes) + len(tier_must),
                                  len(tier_must) - 1, -1):
                    if remaining_budget <= 0:
                        break
                    free_needed = size - len(tier_must)
                    subsets: List[tuple] = list(itertools.combinations(free_codes, free_needed))
                    # Sort by priority sum: lower pidx = higher priority = preferred.
                    subsets.sort(key=lambda s: sum(pidx.get(c, 999) for c in s))
                    for subset in subsets:
                        if remaining_budget <= 0:
                            break
                        subset_list = list(tier_must) + list(subset)
                        solutions = _solve_subset(subset_list, remaining_budget)
                        if solutions:
                            kept_codes = set(s["code"] for s in solutions[0])
                            dropped = [c for c in active_codes if c not in kept_codes]
                            dropped.sort(key=lambda c: pidx.get(c, 999))
                            # MUST-take report for this solution group: which
                            # required codes were dropped (the "removed in
                            # must-takes" list per solution).
                            must_dropped = [c for c in required_codes if c not in kept_codes]
                            must_dropped.sort(key=lambda c: pidx.get(c, 999))
                            for sol in solutions:
                                final_solutions.append({
                                    "sections": sol,
                                    "covered": len(sol),
                                    "total": n,
                                    "dropped": dropped,
                                    "size": size,
                                    "must_dropped": must_dropped,
                                    "must_covered": len(required_codes) - len(must_dropped),
                                    "must_total": len(required_codes),
                                })
                            remaining_budget -= len(solutions)

        # Sort: MUST coverage first (solutions keeping every required code
        # win), then higher code coverage, then by priority kept.
        final_solutions.sort(key=lambda s: (
            -s["must_covered"],
            -s["covered"],
            sum(pidx.get(c, 999) for c in {x["code"] for x in s["sections"]})
        ))

        # MUST means MUST: when a solution keeping EVERY required code
        # exists, the partial tiers (which drop a required code) are noise —
        # the user never wants to see a must-code dropped if it can fit.
        if required_codes and any(not s["must_dropped"] for s in final_solutions):
            final_solutions = [s for s in final_solutions if not s["must_dropped"]]

        # MUST-take feasibility:
        #  - must_feasible = the FULL must-set is coverable in a single
        #    solution (no required code dropped). Two required codes can
        #    be mutually exclusive even when each appears in some
        #    solution, so this must be checked per solution.
        #  - must_impossible = required codes that appear in NONE of the
        #    returned solutions (inherently impossible with the current
        #    picks / blocks / other must codes).
        must_feasible = any(not s["must_dropped"] for s in final_solutions)
        must_impossible: list = []
        if required_codes:
            for c in required_codes:
                if not final_solutions or all(c in s["must_dropped"] for s in final_solutions):
                    must_impossible.append(c)

        return jsonify({
            "solutions": final_solutions[:max_res],
            "count": len(final_solutions),
            "codes": active_codes,
            "priority": priority,
            "must_feasible": must_feasible,
            "must_impossible": must_impossible,
        })

    @reg.post("tis.add", "/api/tis/add")
    def api_add():
        b = request.get_json(silent=True) or {}
        return _write("add", b.get("rwh", ""),
                      dry_run=b.get("dry_run", False),
                      ignore_conflicts=b.get("ignore_conflicts"),
                      ignore_zero_capacity=b.get("ignore_zero_capacity"),
                      pylx=b.get("pylx"))

    @reg.post("tis.drop", "/api/tis/drop")
    def api_drop():
        b = request.get_json(silent=True) or {}
        return _write("drop", b.get("rwh", ""),
                      dry_run=b.get("dry_run", False),
                      pylx=b.get("pylx"),
                      xkfsdm=b.get("xkfsdm"))

    @reg.post("tis.add-to-cart", "/api/tis/add-to-cart")
    def api_add_cart():
        b = request.get_json(silent=True) or {}
        return _write("add_to_cart", b.get("rwh", ""),
                      dry_run=b.get("dry_run", False),
                      pylx=b.get("pylx"),
                      xkfsdm=b.get("xkfsdm"))

    @reg.post("tis.remove-from-cart", "/api/tis/remove-from-cart")
    def api_remove_cart():
        b = request.get_json(silent=True) or {}
        return _write("remove_from_cart", b.get("rwh", ""),
                      dry_run=b.get("dry_run", False),
                      pylx=b.get("pylx"),
                      xkfsdm=b.get("xkfsdm"))

    @reg.get("tis.course-types", "/api/tis/course-types")
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

    @reg.get("tis.round", "/api/tis/round")
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

    @reg.post("tis.bids", "/api/tis/bids")
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
            "jffs_limit": <float>,           # optional: REMAINING pts (TIS
                                             # xkgzszOne.jfxs — NOT the round
                                             # total; semester total =
                                             # committed + jffs)
            "baseline":  {rwh: bid, ...},    # optional: bids TIS already
                                             # holds (enrolled/cart xkxs).
                                             # Budget consumption per pick =
                                             # max(0, bid - baseline) —
                                             # re-stating an enrolled bid
                                             # costs nothing.
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
        baseline = b.get("baseline")
        if not isinstance(baseline, dict):
            baseline = None
        else:
            clean_baseline = {}
            for brwh, bval in baseline.items():
                try:
                    clean_baseline[str(brwh)] = int(bval)
                except (TypeError, ValueError):
                    continue
            baseline = clean_baseline or None

        if not isinstance(picks, dict) or not picks:
            return jsonify({"ok": False,
                            "error": "picks must be a non-empty dict",
                            "results": [], "sum": 0,
                            "jffs_limit": jffs_limit,
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
            result = c.submit_bids(picks, round_code=round_code,
                                   where=where, jffs_limit=jffs_limit,
                                   baseline=baseline,
                                   pylx=pylx, dry_run=dry_run,
                                   id_map=id_map, xkfsdm=xkfsdm)
            return jsonify(result)
        except Exception as e:
            return jsonify({"ok": False, "error": str(e), "results": []}), 200

    @reg.get("tis.ical", "/api/tis/ical")
    def api_ical():
        """Build an .ics file from the current picked list.

        Reads the picked list from sessionStorage on the client (passed as
        the ``picks`` query param, JSON-encoded). Each pick is a dict of
        class-time fields; this route maps them to ``calendar.ClassTime``
        and registers them on the resolved Semester, then hands off to
        ``selectcourse.ical.courses_to_ical``.

        Calendar is loaded online (GitHub raw is the canonical source).
        If the fetch fails, fall back to a 502 with a useful error.
        """
        from sustech_survival.calendar import (
            AcademicCalendar, ClassTime, CalendarError,
        )
        from sustech_survival.selectcourse.ical import courses_to_ical

        raw = request.args.get("picks", "")
        if not raw:
            return Response("missing 'picks' query param", status=400,
                            mimetype="text/plain")
        try:
            picks = json.loads(raw)
        except Exception as e:
            return Response(f"invalid 'picks' JSON: {e}", status=400,
                            mimetype="text/plain")
        if not isinstance(picks, list) or not picks:
            return Response("'picks' must be a non-empty list",
                            status=400, mimetype="text/plain")

        xn, xq = _parse_sem(request.args)
        try:
            # xn is "2025-2026", split year for AcademicCalendar
            cal_year = int(xn.split("-")[0]) + (1 if xq == "2" else 0)
            cal = AcademicCalendar.load(cal_year, "undergraduate")
        except CalendarError as e:
            return Response(f"calendar load failed: {e}", status=502,
                            mimetype="text/plain")
        except Exception as e:
            return Response(f"calendar load failed: "
                            f"{type(e).__name__}: {e}",
                            status=502, mimetype="text/plain")

        sem = cal.spring if xq == "2" else cal.fall
        if sem is None:
            return Response(f"semester not found for {xn}-{xq}",
                            status=404, mimetype="text/plain")

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


# -- module-level helpers (used by the registered handlers above) -----------


# One client per (xn, xq) — cached so we don't re-login on every request.
_clients: Dict[str, SelectCourseClient] = {}
_clients_lock = threading.Lock()


def _default_sem() -> tuple[str, str]:
    from sustech_survival.semester import Semester
    s = Semester.current()
    return s.xn, s.xq


def _client(xn: str, xq: str) -> SelectCourseClient:
    key = f"{xn}-{xq}"
    with _clients_lock:
        c = _clients.get(key)
        if c is None:
            # Catalog TTL: the campus catalog (queryRwxxcxList) is a 9-page
            # paginated fetch — expensive and rate-limit-prone. BUT its rows
            # also carry the LIVE "currently selected" counts (yxzrs & co),
            # which change constantly during a round. A 6h cache was serving
            # a snapshot fetched while TIS wasn't populating counts (the
            # "? / M" bug). 10 min keeps refetches rare while counts stay
            # usable; the 🔄 refresh button forces a fresh fetch on demand.
            c = sc_factory(xn=xn, xq=xq, max_age=10 * 60)
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
        "grading": c.grading,
        "conflicts": c.conflicts,
        "requirement": c.requirement,
        "note": c.note,
    }


def _member_row(raw: dict, **markers) -> dict:
    """Parse one enrolled (yxkcList) / cart (xkgwcList) raw row into the
    same render-ready shape as ``_course_to_dict``, plus:

    - ``bid`` — the TIS-held 选课系数 (raw ``xkxs``), the baseline for
      the budget model and sync.
    - ``xkxs`` — kept verbatim for backward compatibility (older skins
      read ``items[i].xkxs`` directly).
    - any caller markers (``tis_enrolled`` / ``in_cart``).

    Falls back to the raw row (plus bid/markers) if parsing fails, so a
    layout change on TIS degrades to the old behavior instead of 500s.
    """
    from sustech_survival.selectcourse.course import Course
    try:
        d = _course_to_dict(Course.from_api(raw))
    except Exception:
        d = dict(raw)
    d["xkxs"] = raw.get("xkxs")
    d["bid"] = raw.get("xkxs")
    d.update(markers)
    return d


def _parse_sem(args) -> tuple[str, str]:
    dxn, dxq = _default_sem()
    return (args.get("xn") or dxn, args.get("xq") or dxq)


def _int_or_none(v):
    try:
        return int(v) if v else None
    except (ValueError, TypeError):
        return None


def _write(action: str, rwh: str, *, dry_run: bool, **kw):
    xn, xq = _parse_sem(request.args)
    try:
        c = _client(xn, xq)
        fn = {"add": c.add_course, "drop": c.drop_course,
              "add_to_cart": c.add_to_cart,
              "remove_from_cart": c.remove_from_cart}[action]
        res = fn(rwh, dry_run=dry_run,
                 **{k: v for k, v in kw.items() if v is not None})
        # Surface consequence metadata so the UI can warn before a real
        # commit.
        from sustech_survival.consequence import consequence_by_name
        _name = {"add": "selectcourse.add_course",
                 "drop": "selectcourse.drop_course",
                 "add_to_cart": "selectcourse.add_to_cart",
                 "remove_from_cart":
                     "selectcourse.remove_from_cart"}[action]
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
        # CANONICAL response shape: success must carry `ok: true` — the
        # TIS raw dict (jg='1', message=…) has no `ok` key, so UI callers
        # that check `r.ok` used to report REAL successes as failures
        # (drop-all reported "did not succeed" while TIS had dropped).
        if isinstance(res, dict) and not dry_run:
            res = dict(res)
            res.setdefault("ok", True)
        return jsonify(res)
    except EnrollmentError as e:
        return jsonify({"ok": False, "error": str(e), "jg": e.jg,
                        "message": e.message}), 200
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# -- rwh / slot parsing (used by /api/tis/enrolled) -----------------------

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
      ZC = "01010101..."      — 32-char binary week-parity pattern.
                                Verified 2026-08-09 against [1-16周],
                                [1-15单周], [2-16双周] all matching.

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
    if ksjc is None or jsjc is None:
        return None
    period_start = int(ksjc)
    period_end = int(jsjc)
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


# Set the collector's module version from the package version at import
# time so the registry can warn on mismatch if a future skin demands it.
try:
    from sustech_survival import _version as _v
    reg.version = _v.__version__
except Exception:  # pragma: no cover
    pass