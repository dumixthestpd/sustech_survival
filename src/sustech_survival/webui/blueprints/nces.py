"""NCES blueprint — `/api/nces/...`.

Hover card data + review text for the TIS course selector.
NCES is its own module, not nested under TIS — see sustech_survival/nces/.
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from sustech_survival.nces import NCESScraper

bp = Blueprint("nces", __name__)
_scraper: NCESScraper | None = None


def _get_scraper() -> NCESScraper:
    global _scraper
    if _scraper is None:
        _scraper = NCESScraper()
    return _scraper


@bp.route("/api/nces/code/<code>")
def api_nces_code(code: str):
    """Structured NCES data for one course code — live fetch.

    Query params:
      teacher  — teacher name for disambiguation (optional)
      xn       — TIS academic year, e.g. "2026-2027" (for semester matching)
      xq       — TIS semester, "1" (Fall), "2" (Spring), "3" (Summer)

    Returns rating, 4 dimensions, review count, top 3 review snippets,
    semester info, and alternatives when exact match fails.
    """
    s = _get_scraper()
    teacher = request.args.get("teacher", "")
    xn = request.args.get("xn", "")
    xq = request.args.get("xq", "")
    course, exact_match, alternatives = s.search_course(
        code, teacher=teacher, xn=xn, xq=xq,
    )
    if course is None:
        return jsonify({
            "available": False,
            "reason": "course not found in NCES",
            "search_url": f"https://ncesnext.com/search?q={code}",
        })

    # Top 3 review excerpts
    reviews = s.fetch_reviews(code, teacher=teacher)
    review_excerpts = []
    if reviews:
        sorted_revs = sorted(reviews, key=lambda r: r.get("likes", 0), reverse=True)
        for r in sorted_revs[:3]:
            text = r.get("text", "")
            review_excerpts.append({
                "username": r.get("username", ""),
                "semester": r.get("semester", ""),
                "likes": r.get("likes", 0),
                "excerpt": text[:200] if text else "",
            })

    return jsonify({
        "available": True,
        "code": course.code,
        "name": course.name,
        "teacher": course.teacher,
        "semester": course.semester,
        "semesters": course.semesters,
        "rating": course.rating,
        "review_count": course.review_count,
        "dimensions": {
            "difficulty": {"label": course.difficulty[0],
                           "pct": course.difficulty[1]},
            "workload":   {"label": course.workload[0],
                           "pct": course.workload[1]},
            "grading":    {"label": course.grading[0],
                           "pct": course.grading[1]},
            "takeaways":  {"label": course.takeaways[0],
                           "pct": course.takeaways[1]},
        },
        "detail_url": course.direct_url,
        "review_excerpts": review_excerpts,
        "exact_match": exact_match,
        "nces_teacher": course.teacher,
        "alternatives": alternatives,
    })


@bp.route("/api/nces/status")
def api_nces_status():
    """Cache freshness — for the UI status panel."""
    s = _get_scraper()
    return jsonify(s.status())


@bp.route("/api/nces/refresh", methods=["POST"])
def api_nces_refresh():
    """Force-refresh the cache. Used after semester changes."""
    s = _get_scraper()
    max_pages = int(request.args.get("max_pages", 6))
    n = s.refresh_index(max_pages=max_pages)
    return jsonify({"ok": True, "count": n})


@bp.route("/api/nces/reviews/<code>")
def api_nces_reviews(code: str):
    """Individual review text for a course code.

    Accepts ``?teacher=周秀梅`` to disambiguate sections.
    """
    s = _get_scraper()
    teacher = request.args.get("teacher", "")
    reviews = s.fetch_reviews(code, teacher=teacher)
    if reviews is None:
        return jsonify({
            "available": False,
            "reason": "course not found in NCES",
        })
    return jsonify({
        "available": True,
        "code": code,
        "count": len(reviews),
        "reviews": reviews,
    })
