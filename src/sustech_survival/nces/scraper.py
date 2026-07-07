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
# Thresholds are 33/67/100 — verified 2026-07-07: NCES rounds 66.67→67 and
# labels it "Average" (中等), not "Light" (很少). Using 66 as the boundary
# put 66.67% in the "Light" bucket, which doesn't match the page.
DIMENSION_LABELS = {
    "difficulty": [  # 100% = easy
        (33, ("Hard", "困难")),
        (67, ("Average", "中等")),
        (100, ("Easy", "简单")),
    ],
    "workload": [    # 100% = light
        (33, ("Heavy", "很多")),
        (67, ("Average", "一般")),
        (100, ("Light", "很少")),
    ],
    "grading": [     # 100% = excellent
        (33, ("Poor", "差")),
        (67, ("Average", "一般")),
        (100, ("Excellent", "超好")),
    ],
    "takeaways": [   # 100% = high gain
        (33, ("Low", "没有")),
        (67, ("Average", "一般")),
        (100, ("High", "很多")),
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
        self._teacher_cache: dict[str, tuple[float, list[NCESCourse]]] = {}
        self._last_request_at: float = 0.0
        # Throttle: NCES API rate-limits aggressively; 1 req / 200ms is safe.
        self._min_interval = 0.2

    def _throttle(self) -> None:
        now = time.time()
        wait = self._last_request_at + self._min_interval - now
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.time()

    # ── Browse / search (NCES API supports these directly) ────────────────
    def browse(self, *, page: int = 1, per_page: int = 30, sort: str = "rating") -> dict:
        """Paginated course list, sorted client-side (NCES API ignores sort).

        Returns ``{items, total, page, per_page, pages}``.
        """
        per_page = max(1, min(50, per_page))
        data = self._api_search_for_browse(page=page, per_page=per_page)
        items = data.get("items", [])
        # Client-side sort — the NCES API doesn't honor sort_by direction
        if sort == "rating":
            items = sorted(items, key=lambda c: float(c.get("rate_average") or 0), reverse=True)
        elif sort == "reviews":
            items = sorted(items, key=lambda c: int(c.get("review_count") or 0), reverse=True)
        elif sort == "name":
            items = sorted(items, key=lambda c: c.get("name") or "")
        return {
            "items": items,
            "total": data.get("total", 0),
            "page": page,
            "per_page": per_page,
            "pages": data.get("pages", 0),
        }

    def search_code(self, q: str) -> dict:
        """Code-keyword search — returns matching course sections."""
        data = self._api_search(q)
        return {
            "items": data.get("courses", {}).get("items", []),
            "total": data.get("courses", {}).get("total", 0),
        }

    def course_detail(self, nces_id: int) -> dict | None:
        """Full course detail (one section) by NCES id, including reviews.

        Uses the direct /api/v1/courses/<id> + /api/v1/courses/<id>/reviews
        endpoints — no walking required.
        """
        self._throttle()
        r = self.session.get(f"{self.BASE}/api/v1/courses/{nces_id}", timeout=15)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        c = r.json()
        # The direct course endpoint nests rating data under "rate"
        rate = c.get("rate") or {}

        self._throttle()
        r2 = self.session.get(f"{self.BASE}/api/v1/courses/{nces_id}/reviews", timeout=15)
        reviews_raw = []
        if r2.status_code == 200:
            reviews_raw = r2.json().get("items", []) or []
        reviews = [self._to_review(rv) for rv in reviews_raw]

        # Direct course endpoint may have different field names — adapt.
        code = c.get("course_code") or c.get("courseries") or ""
        name = c.get("name", "")
        teacher = c.get("teacher_names") or ", ".join(
            t.get("name", "") for t in (c.get("teachers") or [])
        )
        # Normalize term_ids to a flat list of "YYYY1"/"YYYY2"/"YYYY3" strings.
        # Different endpoints use different shapes:
        #   - "term_ids": ["20252", "20251", ...]
        #   - "terms": [{"term": "20252", ...}, ...]
        #   - "review_term_list": ["20252", "20241", ...]
        raw_terms = c.get("term_ids")
        if not raw_terms:
            t = c.get("terms")
            if isinstance(t, list) and t and isinstance(t[0], dict):
                raw_terms = [x.get("term") or x.get("id") or "" for x in t]
            else:
                raw_terms = t
        if not raw_terms:
            raw_terms = c.get("review_term_list") or []
        term_ids = [str(x) for x in raw_terms if x]
        first_term = _term_id_to_display(term_ids[0]) if term_ids else ""
        rating = float(rate.get("rate_average") or rate.get("average_rate") or 0)
        review_count = int(rate.get("review_count") or len(reviews))
        dept = c.get("dept", "")
        dims = {
            k: {"label": _score_to_label(k, rate.get(score_key))[0],
                "pct":    _score_to_label(k, rate.get(score_key))[1]}
            for k, score_key in [
                ("difficulty", "difficulty_score"),
                ("workload",   "homework_score"),
                ("grading",    "grading_score"),
                ("takeaways",  "gain_score"),
            ]
        }

        return {
            "available": True,
            "code": code,
            "name": name,
            "teacher": teacher,
            "department": dept,
            "semester": first_term,
            "semesters": [_term_id_to_display(t) for t in term_ids],
            "rating": rating,
            "review_count": review_count,
            "nces_id": nces_id,
            "dimensions": dims,
            "detail_url": f"{self.BASE}/course/{nces_id}/",
            "reviews": reviews,
        }

    def _api_search_for_browse(self, *, page: int, per_page: int) -> dict:
        """GET /api/v1/courses?page=N&per_page=M → {items, total, pages, ...}."""
        self._throttle()
        r = self.session.get(
            f"{self.BASE}/api/v1/courses",
            params={"page": page, "per_page": per_page},
            timeout=15,
        )
        r.raise_for_status()
        return r.json()

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
        """Pick the best-matching course section for the TIS lookup.

        Scoring: (matched_tis_teachers, nces_teachers ⊆ tis_teachers, term_match)
        so a section where every TIS teacher is in NCES wins over one with
        the same number of matches but an extra teacher (TIS class A+B+C
        should prefer NCES A+B+C over NCES A+B+C+D).
        """
        if not courses:
            return None
        best: Optional[dict] = None
        best_score = (-1, -1, -1)  # (matched_count, exact_subset, term_match)
        for c in courses:
            nces_t = _split_teachers(c.get("teacher_names", ""))
            if tis_teachers:
                # Count matched TIS teachers (not just bool) so 4/4 > 3/4.
                matched = sum(
                    1 for t in tis_teachers
                    if any(t == n or t in n or n in t for n in nces_t)
                )
                # Bonus if NCES teachers are a subset of TIS (no extras)
                nces_subset = (
                    all(
                        any(t == n or t in n or n in t for t in tis_teachers)
                        for n in nces_t
                    ) if nces_t else False
                )
            else:
                matched, nces_subset = 0, True
            term_match = 1 if term_id and term_id in c.get("term_ids", []) else 0
            score = (matched, 1 if nces_subset else 0, term_match)
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

        Note: the NCES API's /search?q=<code> only returns ~5 sections
        (top by review_count). To find a specific teacher's section that
        didn't make the top-5, we also do a teacher-name search and merge
        any matching-course-code sections into the candidate pool.
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
        courses = list(data.get("courses", {}).get("items", []) or [])

        # If a TIS teacher was given and isn't in the top-5, augment with
        # a teacher-name search so the specific section is found.
        tis_teachers = _split_teachers(teacher.replace("，", ",")) if teacher else []
        seen_ids = {c.get("id") for c in courses}
        if tis_teachers:
            for t in tis_teachers:
                try:
                    tdata = self._api_search(t)
                except Exception:
                    continue
                for c in tdata.get("courses", {}).get("items", []) or []:
                    if (c.get("course_code") or "").upper() == code and c.get("id") not in seen_ids:
                        courses.append(c)
                        seen_ids.add(c.get("id"))

        if not courses:
            return (None, False, [])

        best = self._pick_course(courses, tis_teachers, term_id)
        if not best:
            return (None, False, [])

        nces_teachers = _split_teachers(best.get("teacher_names", ""))
        # exact_match means EVERY TIS teacher appears in the NCES section.
        # Mere overlap (1 of 4) is not enough — the user expects to see data
        # for THEIR section's full teacher team. For single-teacher TIS
        # cards, overlap degenerates to equality which is what we want.
        exact_match = bool(tis_teachers) and all(
            any(t == n or t in n or n in t for n in nces_teachers)
            for t in tis_teachers
        )
        if not tis_teachers:
            # No TIS teacher filter — treat the first section as a match
            exact_match = True

        course = self._to_course(best, code)

        # Alternatives = OTHER sections of the SAME course code, but only
        # ones that actually provide insight:
        #   1. must have at least 1 review (no-eval is useless)
        #   2. must share at least 1 teacher with the TIS section
        #      (otherwise the user is no better informed than the
        #      course-wide stats)
        #   3. show all matches (no slicing) so the user can pick
        alternatives = []
        for c in courses:
            if c["id"] == best["id"]:
                continue
            if int(c.get("review_count") or 0) == 0:
                continue
            nces_t = _split_teachers(c.get("teacher_names", ""))
            if not any(
                t == n or t in n or n in t
                for t in tis_teachers for n in nces_t
            ):
                continue
            alternatives.append({
                "name": c.get("name", ""),
                "teacher": c.get("teacher_names", ""),
                "nces_id": int(c["id"]),
                "review_count": int(c.get("review_count") or 0),
                "rating": float(c.get("rate_average") or 0),
                # Dimensions — same fields _to_course reads (lines 247-252).
                # Without these, the UI renders "0%" placeholders for every
                # alternative, which looks broken.
                "dimensions": {
                    k: {"label": _score_to_label(k, c.get(score_key))[0],
                        "pct":    _score_to_label(k, c.get(score_key))[1]}
                    for k, score_key in [
                        ("difficulty", "difficulty_score"),
                        ("workload",   "homework_score"),
                        ("grading",    "grading_score"),
                        ("takeaways",  "gain_score"),
                    ]
                },
            })

        self._course_cache[cache_key] = (now, course)
        return (course, exact_match, alternatives)

    def teacher_courses(self, teacher: str) -> list[NCESCourse]:
        """All NCES sections taught by a given teacher.

        Used as a fallback when a TIS course's teacher isn't in NCES under
        that exact course code — gives the user a sense of what the teacher
        is like based on reviews of their other courses.
        """
        teacher = teacher.strip()
        if not teacher:
            return []
        cache_key = teacher
        now = time.time()
        if cache_key in self._teacher_cache:
            ts, cached = self._teacher_cache[cache_key]
            if now - ts < self.TTL:
                return cached
        try:
            data = self._api_search(teacher)
        except Exception:
            return []
        raw = data.get("courses", {}).get("items", []) or []
        # Dedupe by nces_id (API may return the same section twice)
        seen: set[int] = set()
        out: list[NCESCourse] = []
        for c in raw:
            cid = c.get("id")
            if cid in seen:
                continue
            seen.add(cid)
            code = (c.get("course_code") or "").upper()
            if not code:
                continue
            out.append(self._to_course(c, code))
        self._teacher_cache[cache_key] = (now, out)
        return out

    def fetch_reviews(self, code: str, teacher: str = "") -> Optional[list[dict]]:
        """Fetch reviews for a course code. Returns [] if course not found.

        Like search_course, this also augments the code-search with a
        teacher-name search when a teacher is specified, so reviews for
        teachers outside the top-5-by-reviews are reachable.

        Then hits the direct ``/api/v1/courses/{id}/reviews`` endpoint
        for the chosen section so we get ALL of that section's reviews
        (the /search endpoint only returns page 1 of the teacher's review
        set, not the full count).
        """
        code = code.strip().upper()
        teacher = teacher.strip()
        try:
            data = self._api_search(code)
        except Exception:
            return None
        courses = data.get("courses", {}).get("items", []) or []
        # Augment with teacher-name search so this teacher's section is in scope
        tis_teachers = _split_teachers(teacher.replace("，", ",")) if teacher else []
        seen_ids = {c.get("id") for c in courses}
        for t in tis_teachers:
            try:
                tdata = self._api_search(t)
            except Exception:
                continue
            for c in tdata.get("courses", {}).get("items", []) or []:
                if (c.get("course_code") or "").upper() == code and c.get("id") not in seen_ids:
                    courses.append(c)
                    seen_ids.add(c.get("id"))
        if not courses:
            return None
        # Pick the same section the search would pick
        best = self._pick_course(courses, tis_teachers, "")
        if not best:
            return None
        target_id = best["id"]
        # Direct reviews endpoint — returns the FULL set of reviews for
        # this section, not just page 1 of the search endpoint.
        try:
            self._throttle()
            rr = self.session.get(
                f"{self.BASE}/api/v1/courses/{target_id}/reviews",
                timeout=15,
            )
            rr.raise_for_status()
            reviews_raw = rr.json().get("items", []) or []
        except Exception:
            reviews_raw = list(data.get("reviews", {}).get("items", []) or [])
        return [self._to_review(r) for r in reviews_raw]

    @staticmethod
    def _to_review(r: dict) -> dict:
        text = _strip_html(r.get("content", ""))
        return {
            "username": (r.get("author") or {}).get("username", ""),
            "semester": _term_id_to_display(r.get("term", "")),
            "likes": int(r.get("upvote_count") or 0),
            "rate": float(r.get("rate") or 0),
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
    def _collect_teacher_other(self, tis_teachers: list[str], exclude_code: str = "") -> list[dict]:
        """Aggregate the teacher's other courses for the teacher-other
        fallback panel. Returns one row per TIS teacher — the single
        best section each teacher has (most reviewed). Sorted by
        review_count desc. ``exclude_code`` filters out the requested
        course itself. No-eval sections are skipped — they're not
        useful for gauging the teacher.
        """
        # For each TIS teacher, find their single best reviewed section.
        per_teacher: dict[str, dict] = {}
        for t in tis_teachers:
            for c in self.teacher_courses(t):
                if c.review_count == 0:
                    continue
                if exclude_code and c.code == exclude_code:
                    continue
                if t not in per_teacher or c.review_count > per_teacher[t]["review_count"]:
                    per_teacher[t] = {
                        "teacher": c.teacher,
                        "code": c.code,
                        "name": c.name,
                        "nces_id": c.nces_id,
                        "rating": c.rating,
                        "review_count": c.review_count,
                        "difficulty": c.difficulty,
                        "workload": c.workload,
                        "grading": c.grading,
                        "takeaways": c.takeaways,
                        "semester": c.semester,
                    }
        return sorted(per_teacher.values(), key=lambda r: r["review_count"], reverse=True)

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
        # When a TIS teacher was specified but no NCES section matches it,
        # don't pretend the data belongs to the TIS teacher — surface a
        # teacher-mismatch signal so the UI can show the alternatives
        # instead of misleading ratings from an unrelated section.
        tis_teachers = _split_teachers(teacher.replace("，", ",")) if teacher else []
        teacher_mismatch = bool(tis_teachers) and not exact_match
        reviews = self.fetch_reviews(code, teacher=teacher) or []
        top = sorted(reviews, key=lambda r: r.get("likes", 0), reverse=True)[:3]

        # Teacher-other fallback: when the user can't see reviews for the
        # requested section (either because the teacher is wrong, or the
        # section exists but has no reviews yet), pull the teacher's
        # other courses so they can gauge the teacher from courses that
        # DO have reviews.
        teacher_other = []
        if tis_teachers and (teacher_mismatch or course.review_count == 0):
            teacher_other = self._collect_teacher_other(
                tis_teachers, exclude_code=course.code,
            )

        return {
            "available": True,
            "code": course.code,
            "name": course.name,
            "teacher": course.teacher,
            "tis_teacher": teacher,                # what the user actually asked for
            "teacher_mismatch": teacher_mismatch,  # True when the TIS teacher isn't in NCES
            "semester": course.semester,
            "semesters": course.semesters,
            "rating": course.rating,
            "review_count": course.review_count,
            "nces_id": course.nces_id,
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
                    "rate": r.get("rate", 0),
                    "excerpt": r.get("excerpt", ""),
                }
                for r in top
            ],
            "exact_match": exact_match,
            "nces_teacher": course.teacher,
            "alternatives": alternatives,
            "teacher_other": teacher_other,  # other courses the TIS teacher teaches (for mismatch fallback)
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
