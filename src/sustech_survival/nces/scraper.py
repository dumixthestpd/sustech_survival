"""
sustech_survival.nces.scraper — Live NCES scraper (no caching, single API call).

NCES migrated to a React SPA backed by a JSON API. We call:

    GET https://ncesnext.com/api/v1/search?q=<course_code>

which returns BOTH the list of section records (one per teacher offering
of the code) AND a sample of recent reviews — no follow-up requests, no
HTML parsing, no Anubis PoW.

Response shape:
  courses.items[]    — section records with id, name, course_code,
                       teacher_names, term_ids, review_count,
                       rate_average (0-10), *_score (0-100, higher=better)
  reviews.items[]    — full review objects with author, content (HTML),
                       term, rate, upvote_count, *_display (CN labels)

Domain decisions owned here (not in webui):
  - term_id conversion: TIS (xn, xq) → NCES "20261"/"20262"/"20253"
  - teacher matching: overlap on comma-split names
  - best-course pick: teacher match + term match wins ties
  - score → label: 0-33 / 34-66 / 67-100 thresholds (higher = better)
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from html import unescape
from typing import Optional

import requests


# Score (0-100, higher = better) → (English label, Chinese label)
DIMENSION_LABELS = {
    "difficulty": [  # 100% = easy
        (33, ("Hard", "困难")),
        (66, ("Medium", "中等")),
        (100, ("Easy", "简单")),
    ],
    "workload": [    # 100% = light
        (33, ("Heavy", "很多")),
        (66, ("Average", "一般")),
        (100, ("Light", "很少")),
    ],
    "grading": [     # 100% = excellent
        (33, ("Poor", "差")),
        (66, ("Good", "好")),
        (100, ("Excellent", "超好")),
    ],
    "takeaways": [   # 100% = high gain
        (33, ("Low", "低")),
        (66, ("Medium", "中")),
        (100, ("High", "高")),
    ],
}


def _score_to_label(dim: str, score) -> tuple[str, float]:
    """Map a 0-100 score to (English label, pct). Handles None gracefully."""
    try:
        pct = max(0.0, min(100.0, float(score or 0)))
    except (TypeError, ValueError):
        pct = 0.0
    for threshold, (en, _cn) in DIMENSION_LABELS[dim]:
        if pct <= threshold:
            return en, pct
    return DIMENSION_LABELS[dim][-1][1][0], pct  # fallback to top label


def _tis_to_nces_term(xn: str, xq: str) -> str:
    """TIS (xn, xq) → NCES term_id. E.g. 2026-2027+1 → "20261"."""
    if xq == "1":
        return f"{xn[:4]}1"          # Fall — start year
    return f"{xn[5:9]}{xq}"          # Spring/Summer — end year


def _term_id_to_display(term_id: str) -> str:
    """NCES "20252" → "2025春"."""
    if not term_id or len(term_id) < 5:
        return term_id
    season = {"1": "秋", "2": "春", "3": "夏"}.get(term_id[4], "")
    return f"{term_id[:4]}{season}"


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _strip_html(html: str) -> str:
    """Strip HTML tags and collapse whitespace."""
    if not html:
        return ""
    text = _TAG_RE.sub("", html)
    text = unescape(text)
    return _WS_RE.sub(" ", text).strip()


def _split_teachers(s: str) -> list[str]:
    """Split teacher names on , / ， / 、 — the formats NCES uses."""
    if not s:
        return []
    return [t.strip() for t in re.split(r"[,，、]", s) if t.strip()]


def _teachers_overlap(tis_teachers: list[str], nces_teachers: list[str]) -> bool:
    for t in tis_teachers:
        for n in nces_teachers:
            if t == n or t in n or n in t:
                return True
    return False


@dataclass
class NCESCourse:
    """One course record parsed from the NCES API."""
    nces_id: int
    code: str
    name: str
    teacher: str
    semester: str
    semesters: list[str]
    rating: float
    review_count: int
    difficulty: tuple[str, float]   # (label, pct)
    workload: tuple[str, float]
    grading: tuple[str, float]
    takeaways: tuple[str, float]
    direct_url: str


class NCESScraper:
    """Live NCES data fetcher — single API call, no caching, no auth."""

    BASE = "https://ncesnext.com"
    API_SEARCH = f"{BASE}/api/v1/search"
    TTL = 300  # 5 min in-memory TTL
    USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )

    def __init__(self, *, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = self.USER_AGENT
        self._course_cache: dict[str, tuple[float, NCESCourse]] = {}
        self._last_request_at: float = 0.0
        # Throttle: NCES API rate-limits aggressively; 1 req / 200ms is safe.
        self._min_interval = 0.2

    def _throttle(self) -> None:
        now = time.time()
        wait = self._last_request_at + self._min_interval - now
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.time()

    # ── Low-level API call ─────────────────────────────────────────────────
    def _api_search(self, code: str) -> dict:
        """GET /api/v1/search?q=<code> → {courses, reviews} JSON."""
        self._throttle()
        r = self.session.get(self.API_SEARCH, params={"q": code}, timeout=15)
        r.raise_for_status()
        return r.json()

    # ── Course selection ───────────────────────────────────────────────────
    def _pick_course(
        self,
        courses: list[dict],
        tis_teachers: list[str],
        term_id: str,
    ) -> Optional[dict]:
        """Pick the best-matching course section for the TIS lookup."""
        if not courses:
            return None
        best: Optional[dict] = None
        best_score = (-1, -1)  # (teacher_match, term_match)
        for c in courses:
            t_match = (
                1 if tis_teachers and _teachers_overlap(tis_teachers, _split_teachers(c.get("teacher_names", ""))) else 0
            )
            term_match = 1 if term_id and term_id in c.get("term_ids", []) else 0
            score = (t_match, term_match)
            if score > best_score:
                best_score = score
                best = c
        # Fall back to first candidate if all scored 0
        return best or courses[0]

    def _to_course(self, c: dict, code: str) -> NCESCourse:
        sem_ids = c.get("term_ids", []) or []
        first_term = _term_id_to_display(sem_ids[0]) if sem_ids else ""
        def _f(v) -> float:
            try: return float(v or 0)
            except (TypeError, ValueError): return 0.0
        def _i(v) -> int:
            try: return int(v or 0)
            except (TypeError, ValueError): return 0
        return NCESCourse(
            nces_id=_i(c.get("id")),
            code=code,
            name=c.get("name", "") or "",
            teacher=c.get("teacher_names", "") or "",
            semester=first_term,
            semesters=[_term_id_to_display(t) for t in sem_ids],
            rating=_f(c.get("rate_average")),
            review_count=_i(c.get("review_count")),
            difficulty=_score_to_label("difficulty", c.get("difficulty_score")),
            workload=_score_to_label("workload", c.get("homework_score")),
            grading=_score_to_label("grading", c.get("grading_score")),
            takeaways=_score_to_label("takeaways", c.get("gain_score")),
            direct_url=f"{self.BASE}/course/{c.get('id', '')}/",
        )

    # ── Public API ─────────────────────────────────────────────────────────
    def search_course(
        self, code: str, teacher: str = "",
        xn: str = "", xq: str = "",
    ) -> tuple[Optional[NCESCourse], bool, list[dict]]:
        """Search NCES for a course and return (course, exact_match, alternatives).

        exact_match is True when the teacher name matched an NCES section.
        alternatives is a list of other sections of the same code.
        """
        code = code.strip().upper()
        teacher = teacher.strip()
        term_id = _tis_to_nces_term(xn, xq) if xn and xq else ""
        cache_key = f"{code}::{teacher}::{term_id}"
        now = time.time()
        if cache_key in self._course_cache:
            ts, course = self._course_cache[cache_key]
            if now - ts < self.TTL:
                return (course, True, [])

        data = self._api_search(code)
        courses = data.get("courses", {}).get("items", []) or []
        if not courses:
            return (None, False, [])

        tis_teachers = _split_teachers(teacher.replace("，", ",")) if teacher else []
        best = self._pick_course(courses, tis_teachers, term_id)
        if not best:
            return (None, False, [])

        nces_teachers = _split_teachers(best.get("teacher_names", ""))
        exact_match = bool(tis_teachers) and _teachers_overlap(tis_teachers, nces_teachers)
        if not tis_teachers:
            # No TIS teacher filter — treat the first section as a match
            exact_match = True

        course = self._to_course(best, code)

        alternatives = [
            {
                "name": c.get("name", ""),
                "teacher": c.get("teacher_names", ""),
                "nces_id": int(c["id"]),
            }
            for c in courses if c["id"] != best["id"]
        ]

        self._course_cache[cache_key] = (now, course)
        return (course, exact_match, alternatives)

    def fetch_reviews(self, code: str, teacher: str = "") -> Optional[list[dict]]:
        """Fetch reviews for a course code. Returns [] if course not found."""
        code = code.strip().upper()
        teacher = teacher.strip()
        try:
            data = self._api_search(code)
        except Exception:
            return None
        courses = data.get("courses", {}).get("items", []) or []
        if not courses:
            return None
        # Pick the same section the search would pick
        tis_teachers = _split_teachers(teacher.replace("，", ",")) if teacher else []
        best = self._pick_course(courses, tis_teachers, "")
        if not best:
            return None
        target_id = best["id"]
        # Filter reviews to the chosen section
        reviews_raw = data.get("reviews", {}).get("items", []) or []
        reviews = [r for r in reviews_raw if r.get("course", {}).get("id") == target_id]
        return [self._to_review(r) for r in reviews]

    @staticmethod
    def _to_review(r: dict) -> dict:
        text = _strip_html(r.get("content", ""))
        return {
            "username": (r.get("author") or {}).get("username", ""),
            "semester": _term_id_to_display(r.get("term", "")),
            "likes": int(r.get("upvote_count") or 0),
            "text": text,
            "excerpt": text[:200],
            "dimensions": {
                "difficulty": (r.get("difficulty_display") or "—"),
                "workload":   (r.get("homework_display") or "—"),
                "grading":    (r.get("grading_display") or "—"),
                "takeaways":  (r.get("gain_display") or "—"),
            },
            "date": r.get("publish_time", ""),
        }

    # ── Domain response shape (UI-agnostic payload) ────────────────────────
    def brief(
        self, code: str, *, teacher: str = "", xn: str = "", xq: str = "",
    ) -> dict | None:
        """Structured hover-brief data for one course code.

        Returns the exact shape the UI consumes, or None if the course
        isn\'t in NCES (callers should use ``not_found(code)`` for that).
        """
        course, exact_match, alternatives = self.search_course(
            code, teacher=teacher, xn=xn, xq=xq,
        )
        if course is None:
            return None
        reviews = self.fetch_reviews(code, teacher=teacher) or []
        top = sorted(reviews, key=lambda r: r.get("likes", 0), reverse=True)[:3]
        return {
            "available": True,
            "code": course.code,
            "name": course.name,
            "teacher": course.teacher,
            "semester": course.semester,
            "semesters": course.semesters,
            "rating": course.rating,
            "review_count": course.review_count,
            "dimensions": {
                "difficulty": {"label": course.difficulty[0], "pct": course.difficulty[1]},
                "workload":   {"label": course.workload[0],   "pct": course.workload[1]},
                "grading":    {"label": course.grading[0],    "pct": course.grading[1]},
                "takeaways":  {"label": course.takeaways[0],  "pct": course.takeaways[1]},
            },
            "detail_url": course.direct_url,
            "review_excerpts": [
                {
                    "username": r.get("username", ""),
                    "semester": r.get("semester", ""),
                    "likes": r.get("likes", 0),
                    "excerpt": r.get("excerpt", ""),
                }
                for r in top
            ],
            "exact_match": exact_match,
            "nces_teacher": course.teacher,
            "alternatives": alternatives,
        }

    def not_found(self, code: str) -> dict:
        return {
            "available": False,
            "reason": "course not found in NCES",
            "search_url": f"{self.BASE}/search?q={code}",
        }

    # ── CLI compat ─────────────────────────────────────────────────────────
    def status(self) -> dict:
        return {"cached": False, "mode": "live"}

    def refresh_index(self, **kw) -> int:
        return 0

    def clear_cache(self) -> bool:
        self._course_cache.clear()
        return True
