"""sustech_survival.nces.api — NCES community-eval web API.

Thin HTTP layer over ``sustech_survival.nces.NCESScraper``. All domain
logic (search, parsing, review ranking, response shaping) lives in the
module — see ``NCESScraper.browse`` / ``course_detail`` / etc.

This file owns only:
  - process-wide scraper singleton lifecycle
  - HTTP request parsing (query params)
  - JSON response

Endpoints:
  GET  /api/nces/code/<code>      — single-course brief (TIS-card hover/click)
  GET  /api/nces/teacher          — all sections taught by a teacher
  GET  /api/nces/course/<id>      — single-course detail (eval-tab click)
  GET  /api/nces/browse           — paginated course list (eval-tab browse)
  GET  /api/nces/search           — code-search results (eval-tab search)
  GET  /api/nces/status           — cache freshness
  POST /api/nces/refresh          — force-refresh index
  GET  /api/nces/reviews/<code>   — full review list for a code
"""
from __future__ import annotations

from flask import jsonify, request

from sustech_survival.nces import NCESScraper
from sustech_survival.webui.api_registry import CollectorRegistry


_scraper: NCESScraper | None = None


def _get_scraper() -> NCESScraper:
    global _scraper
    if _scraper is None:
        _scraper = NCESScraper()
    return _scraper


def register(reg: CollectorRegistry) -> None:
    """Wire up the NCES endpoints under the collector."""

    @reg.get("nces.code", "/api/nces/code/<code>")
    def api_nces_code(code: str):
        """Structured NCES data for one course code — feed for the hover card."""
        s = _get_scraper()
        brief = s.brief(
            code,
            teacher=request.args.get("teacher", ""),
            xn=request.args.get("xn", ""),
            xq=request.args.get("xq", ""),
        )
        return jsonify(brief if brief is not None else s.not_found(code))

    @reg.get("nces.teacher", "/api/nces/teacher")
    def api_nces_teacher():
        """All NCES sections taught by a given teacher.

        Query params:
          name — teacher name (URL-encoded UTF-8)
        """
        s = _get_scraper()
        name = request.args.get("name", "").strip()
        if not name:
            return jsonify({"available": False,
                            "reason": "missing ?name=", "items": []})
        courses = s.teacher_courses(name)
        return jsonify({
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
                        "difficulty": {"label": c.difficulty[0],
                                       "pct": c.difficulty[1]},
                        "workload":   {"label": c.workload[0],
                                       "pct": c.workload[1]},
                        "grading":    {"label": c.grading[0],
                                       "pct": c.grading[1]},
                        "takeaways":  {"label": c.takeaways[0],
                                       "pct": c.takeaways[1]},
                    },
                    "detail_url": c.direct_url,
                }
                for c in courses
            ],
        })

    @reg.get("nces.course", "/api/nces/course/<int:nces_id>")
    def api_nces_course(nces_id: int):
        """Single course detail by NCES id — feed for the eval-tab expand."""
        s = _get_scraper()
        detail = s.course_detail(nces_id)
        if detail is None:
            return jsonify({"available": False,
                            "reason": "course not found in NCES",
                            "nces_id": nces_id})
        return jsonify(detail)

    @reg.get("nces.browse", "/api/nces/browse")
    def api_nces_browse():
        """Paginated NCES course list — feed for the eval-tab browse view."""
        s = _get_scraper()
        page = max(1, int(request.args.get("page", 1)))
        per_page = max(1, min(50, int(request.args.get("per_page", 30))))
        sort = request.args.get("sort", "rating")
        try:
            result = s.browse(page=page, per_page=per_page, sort=sort)
        except Exception as e:
            # Upstream NCES endpoint dead — degrade to empty list with a
            # visible error field. The UI shows "NCES browse unavailable".
            return jsonify({
                "items": [], "total": 0, "page": page,
                "per_page": per_page, "pages": 0,
                "error": f"NCES browse API unavailable: {type(e).__name__}",
            }), 200
        return jsonify(result)

    @reg.get("nces.search", "/api/nces/search")
    def api_nces_search():
        """Code-keyword search — used by the eval-tab search box."""
        s = _get_scraper()
        q = request.args.get("q", "").strip()
        if not q:
            return jsonify({"items": [], "total": 0})
        return jsonify(s.search_code(q))

    @reg.get("nces.status", "/api/nces/status")
    def api_nces_status():
        """Cache freshness — for the UI status panel."""
        return jsonify(_get_scraper().status())

    @reg.post("nces.refresh", "/api/nces/refresh")
    def api_nces_refresh():
        """Force-refresh the cache. Used after semester changes."""
        max_pages = int(request.args.get("max_pages", 6))
        n = _get_scraper().refresh_index(max_pages=max_pages)
        return jsonify({"ok": True, "count": n})

    @reg.get("nces.reviews", "/api/nces/reviews/<code>")
    def api_nces_reviews(code: str):
        """Full review list for a course code.

        Accepts ``?teacher=...`` to disambiguate sections. Pagination
        happens client-side.
        """
        teacher = request.args.get("teacher", "")
        reviews = _get_scraper().fetch_reviews(code, teacher=teacher)
        if reviews is None:
            return jsonify({"available": False,
                            "reason": "course not found in NCES"})
        return jsonify({"available": True, "code": code,
                        "count": len(reviews), "reviews": reviews})


try:
    from sustech_survival import _version as _v
    reg.version = _v.__version__
except Exception:  # pragma: no cover
    pass