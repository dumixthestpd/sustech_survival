"""
sustech_survival.api.nces — NCES course-evaluation data contract (Flask-free).

Thin Flask-free layer over ``sustech_survival.nces.NCESScraper``. All domain
logic lives in ``NCESScraper``; here we only own the scraper singleton and the
JSON responses a skin/UI consumes.
"""
from __future__ import annotations

from typing import Any

from sustech_survival.nces import NCESScraper

_scraper: "NCESScraper | None" = None


def _get_scraper() -> NCESScraper:
    global _scraper
    if _scraper is None:
        _scraper = NCESScraper()
    return _scraper


def code(code: str, *, teacher: str = "", xn: str = "", xq: str = "") -> dict:
    """Structured NCES data for one course code (hover-card feed)."""
    s = _get_scraper()
    brief = s.brief(code, teacher=teacher, xn=xn, xq=xq)
    return brief if brief is not None else s.not_found(code)


def teacher(name: str) -> dict:
    """All NCES sections taught by a teacher."""
    s = _get_scraper()
    name = (name or "").strip()
    if not name:
        return {"available": False, "reason": "missing ?name=", "items": []}
    courses = s.teacher_courses(name)
    return {
        "available": True,
        "teacher": name,
        "items": [
            {
                "nces_id": c.nces_id,
                "code": c.code,
                "name": c.name,
                "teacher": c.teacher,
                "semester": c.semester,
                "semesters": c.semesters,
                "rating": c.rating,
                "review_count": c.review_count,
                "dimensions": {
                    "difficulty": {"label": c.difficulty[0], "pct": c.difficulty[1]},
                    "workload": {"label": c.workload[0], "pct": c.workload[1]},
                    "grading": {"label": c.grading[0], "pct": c.grading[1]},
                    "takeaways": {"label": c.takeaways[0], "pct": c.takeaways[1]},
                },
                "detail_url": c.direct_url,
            }
            for c in courses
        ],
    }


def course(nces_id: int) -> dict:
    """Single course detail by NCES id."""
    s = _get_scraper()
    detail = s.course_detail(nces_id)
    if detail is None:
        return {"available": False, "reason": "course not found in NCES",
                "nces_id": nces_id}
    return detail


def browse(page: int = 1, per_page: int = 30, sort: str = "rating") -> dict:
    """Paginated NCES course list.

    Degrades to an empty list with an ``error`` field if the upstream NCES
    browse endpoint is unavailable, so a UI can show "NCES browse unavailable"
    instead of hard-failing.
    """
    s = _get_scraper()
    page = max(1, int(page or 1))
    per_page = max(1, min(50, int(per_page or 30)))
    sort = sort or "rating"
    try:
        return s.browse(page=page, per_page=per_page, sort=sort)
    except Exception as e:
        return {"items": [], "total": 0, "page": page, "per_page": per_page,
                "pages": 0,
                "error": f"NCES browse API unavailable: {type(e).__name__}"}


def search(q: str) -> dict:
    """Code-keyword search (eval-tab search box)."""
    s = _get_scraper()
    q = (q or "").strip()
    if not q:
        return {"items": [], "total": 0}
    return s.search_code(q)


def status() -> dict:
    """Cache freshness, for a UI status panel."""
    return _get_scraper().status()


def refresh(max_pages: int = 6) -> dict:
    """Force-refresh the cache after semester changes."""
    n = _get_scraper().refresh_index(max_pages=max_pages)
    return {"ok": True, "count": n}


def reviews(code: str, *, teacher: str = "") -> dict:
    """Full review list for a course code."""
    reviews_ = _get_scraper().fetch_reviews(code, teacher=teacher)
    if reviews_ is None:
        return {"available": False, "reason": "course not found in NCES"}
    return {"available": True, "code": code, "count": len(reviews_), "reviews": reviews_}


__all__ = ["code", "teacher", "course", "browse", "search", "status",
           "refresh", "reviews"]
