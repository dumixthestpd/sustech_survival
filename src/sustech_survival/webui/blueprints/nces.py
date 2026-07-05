"""NCES blueprint — `/api/nces/...`.

Thin HTTP layer over ``sustech_survival.nces.NCESScraper``. All domain
logic (search, parsing, review ranking, response shaping) lives in
the module — see ``NCESScraper.brief`` / ``not_found`` / etc.

This file owns only:
  - process-wide scraper singleton lifecycle
  - HTTP request parsing (query params)
  - JSON response
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
    """Structured NCES data for one course code — feed for the hover card.

    Query params:
      teacher — teacher name for disambiguation (optional)
      xn      — TIS academic year, e.g. "2026-2027"
      xq      — TIS semester, "1" (Fall) / "2" (Spring) / "3" (Summer)
    """
    s = _get_scraper()
    brief = s.brief(
        code,
        teacher=request.args.get("teacher", ""),
        xn=request.args.get("xn", ""),
        xq=request.args.get("xq", ""),
    )
    return jsonify(brief if brief is not None else s.not_found(code))


@bp.route("/api/nces/status")
def api_nces_status():
    """Cache freshness — for the UI status panel."""
    return jsonify(_get_scraper().status())


@bp.route("/api/nces/refresh", methods=["POST"])
def api_nces_refresh():
    """Force-refresh the cache. Used after semester changes."""
    max_pages = int(request.args.get("max_pages", 6))
    n = _get_scraper().refresh_index(max_pages=max_pages)
    return jsonify({"ok": True, "count": n})


@bp.route("/api/nces/reviews/<code>")
def api_nces_reviews(code: str):
    """Full review list for a course code.

    Accepts ``?teacher=...`` to disambiguate sections. Pagination happens
    client-side.
    """
    teacher = request.args.get("teacher", "")
    reviews = _get_scraper().fetch_reviews(code, teacher=teacher)
    if reviews is None:
        return jsonify({"available": False, "reason": "course not found in NCES"})
    return jsonify({"available": True, "code": code, "count": len(reviews), "reviews": reviews})
