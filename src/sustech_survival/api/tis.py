"""
sustech_survival.api.tis — TIS course data contract (Flask-free).

Returns JSON-ready dicts the UI/skins consume. No Flask; no ``request``.
The write proxies (add/drop/cart/bids) and the solver live here too, defaulting
to ``dry_run=True``.

Serializers mirror the shapes the course-selector UI already consumes, so a
skin that worked against ``/api/tis/...`` keeps working unchanged.
"""
from __future__ import annotations

import threading
from typing import Any, Optional

from sustech_survival.semester import Semester, Season
from sustech_survival.selectcourse.selectcourse import (
    EnrollmentError, SelectCourseClient, selectcourse as sc_factory,
)

# One client per (xn, xq) — cached so we don't re-login every call.
_clients: "dict[str, SelectCourseClient]" = {}
_clients_lock = threading.Lock()


def _default_sem() -> "tuple[str, str]":
    s = Semester.current()
    return s.xn, s.xq


def resolve_semester(xn: Optional[str], xq: Optional[str]) -> "tuple[str, str]":
    """Return an effective (xn, xq), defaulting to the live term."""
    dxn, dxq = _default_sem()
    return xn or dxn, xq or dxq


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


def _int_or_none(v: Any) -> "Optional[int]":
    try:
        return int(v) if v not in (None, "", 0) else None
    except (ValueError, TypeError):
        return None


# -- Info ------------------------------------------------------------------

def info(xn: Optional[str] = None, xq: Optional[str] = None) -> dict:
    """Semester info + filter options for the course-search UI.

    Mirrors ``/api/tis/info``.
    """
    xn, xq = resolve_semester(xn, xq)
    try:
        c = _client(xn, xq)
        opts = c.filter_options()
    except Exception as e:
        return {"error": str(e), "count": 0,
                "colleges": [], "categories": [], "category_codes": {},
                "task_types": [], "languages": [], "campuses": [],
                "cultivation_levels": []}
    sem = Semester(xn, xq)
    display_year = sem.end_year if sem.season == Season.FALL else sem.cohort_year
    semester_label = f"{sem.season.name.capitalize()} {display_year}"
    from sustech_survival.selectcourse import CATEGORY_MAP, LANGUAGE_MAP
    category_codes = {name: CATEGORY_MAP.get(name, "") for name in opts["categories"]}
    return {
        "semester": {"xn": xn, "xq": xq, "label": semester_label},
        "count": len(c.list_courses()),
        "colleges": opts["colleges"],
        "categories": opts["categories"],
        "category_codes": category_codes,
        "language_codes": LANGUAGE_MAP,
        "task_types": opts["task_types"],
        "languages": opts["languages"],
        "campuses": opts["campuses"],
        "cultivation_levels": opts["cultivation_levels"],
    }


# -- Courses ---------------------------------------------------------------

def courses(
    xn: Optional[str] = None,
    xq: Optional[str] = None,
    *,
    mode: str = "campus",
    keyword: str = "",
    teacher: str = "",
    college: Optional[str] = None,
    college_code: Optional[str] = None,
    campus: Optional[str] = None,
    category: Optional[str] = None,
    task_type: Optional[str] = None,
    language: Optional[str] = None,
    cultivation: Optional[str] = None,
    scheduled_only: bool = False,
    ignore_conflicts: bool = False,
    ignore_zero_capacity: bool = False,
    weekday: Optional[int] = None,
    period_start: Optional[int] = None,
    period_end: Optional[int] = None,
    round_code: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
) -> dict:
    """Search courses. Mirrors ``/api/tis/courses``."""
    xn, xq = resolve_semester(xn, xq)
    try:
        c = _client(xn, xq)
        if mode == "personal":
            result = c.search_personal(
                keyword=keyword, teacher=teacher or "",
                college=college, campus=campus, category=category,
                language=language, cultivation=cultivation,
                ignore_conflicts=ignore_conflicts,
                ignore_zero_capacity=ignore_zero_capacity,
                weekday=weekday, period_start=period_start, period_end=period_end,
                round_code=round_code,
                page=page, page_size=page_size,
            )
            courses_ = result["courses"]
            out = [_course_to_dict(x) for x in courses_]
            enrolled = result["enrolled"]
            cart = result["cart"]
            msg = result["message"]
            if not result["ok"]:
                if msg == "操作失败":
                    msg = ("Course selection period not yet open. "
                           "Catalog mode shows all courses — use the toggle above.")
                elif not msg:
                    msg = "Personal selection unavailable."
            return {
                "mode": "personal", "ok": result["ok"], "count": len(courses_),
                "total": result["total"], "courses": out,
                "enrolled": enrolled, "cart": cart, "message": msg,
                "course_types": result["course_types"],
                "current_type": result["current_type"],
                "round": result.get("round", {}),
            }
        # Campus mode (default)
        courses_ = c.search_campus(
            keyword=keyword, teacher=teacher or None,
            college=college, college_code=college_code,
            campus=campus, category=category, task_type=task_type,
            language=language, cultivation=cultivation,
            scheduled_only=scheduled_only,
        )
    except Exception as e:
        return {"error": str(e), "courses": []}
    out = [_course_to_dict(x) for x in courses_[:3000]]
    return {"mode": "campus", "count": len(courses_), "shown": len(out),
            "courses": out}


def course_detail(rwh: str, xn: Optional[str] = None, xq: Optional[str] = None) -> dict:
    """One section's detail. Mirrors ``/api/tis/course/<rwh>``."""
    xn, xq = resolve_semester(xn, xq)
    try:
        c = _client(xn, xq)
    except Exception as e:
        return {"error": str(e)}
    for x in c.list_courses():
        if x.rwh == rwh:
            return _course_to_dict(x)
    return {"error": "not found"}


# -- Write proxies (dry-run by default) ------------------------------------

def write(action: str, rwh: str, *, dry_run: bool, xn: Optional[str] = None,
          xq: Optional[str] = None, **kw) -> dict:
    """Add / drop / add-to-cart / remove-from-cart. Mirrors the webui writes."""
    xn, xq = resolve_semester(xn, xq)
    try:
        c = _client(xn, xq)
        fn = {"add": c.add_course, "drop": c.drop_course,
              "add_to_cart": c.add_to_cart, "remove_from_cart": c.remove_from_cart}[action]
        return _call_write(fn, rwh, dry_run=dry_run, kw=kw)
    except EnrollmentError as e:
        return {"ok": False, "error": str(e), "jg": e.jg, "message": e.message}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _call_write(fn, rwh, *, dry_run, kw):
    filtered = {k: v for k, v in kw.items() if v is not None}
    return fn(rwh, dry_run=dry_run, **filtered)


__all__ = ["info", "courses", "course_detail", "write", "resolve_semester",
           "_course_to_dict"]
