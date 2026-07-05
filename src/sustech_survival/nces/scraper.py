"""
sustech_survival.nces.scraper — Live NCES scraper (no caching).

Fetches course rating + dimensions + review text live from NCES by
searching for a course code, finding the detail page, and parsing it.

Supports **teacher disambiguation** via ``teacher='周秀梅'`` and
**semester-aware matching** via ``xn='2026-2027', xq='1'``.

When the exact teacher isn't found, returns alternatives (other sections
of the same code) so the UI can show them.

Anubis PoW is solved once per session (cookie lasts 7 days).
"""
from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests


@dataclass
class NCESCourse:
    """One course record parsed from the NCES course detail page."""
    nces_id: int
    code: str
    name: str
    teacher: str
    semester: str                     # first matched semester (e.g. "2026秋")
    semesters: list[str]              # all semesters this section was offered
    rating: float
    review_count: int
    difficulty: tuple[str, float]
    workload: tuple[str, float]
    grading: tuple[str, float]
    takeaways: tuple[str, float]
    direct_url: str


LABEL_EN = {
    "简单": "Easy", "中等": "Medium", "困难": "Hard",
    "很少": "Light", "一般": "Average", "很多": "Heavy",
    "超好": "Excellent", "好": "Good", "差": "Poor",
}


def _tis_semester_to_nces(xn: str, xq: str) -> str:
    """Convert TIS xn/xq to NCES semester label.

    TIS: xn='2026-2027', xq='1' (Fall) → '2026秋'
    TIS: xn='2025-2026', xq='2' (Spring) → '2026春'
    TIS: xn='2025-2026', xq='3' (Summer) → '2026夏'
    """
    parts = xn.split("-")
    if xq == "1":
        return f"{parts[0]}秋"
    elif xq == "2":
        return f"{parts[1]}春"
    else:  # xq == "3" or summer
        return f"{parts[1]}夏"


class NCESScraper:
    """Live NCES data fetcher — no cache, fetches per-course on demand."""

    BASE = "https://ncesnext.com"
    ANUBIS_SUBMIT = (
        "https://ncesnext.com/.within.website/x/cmd/anubis/api/pass-challenge"
    )
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

    # ── Anubis PoW ─────────────────────────────────────────────────────────
    def _solve_anubis(self) -> None:
        r = self.session.get(f"{self.BASE}/course/?sort_by=rating")
        m = re.search(
            r'"id":"([0-9a-f-]{36})"[^}]*"randomData":"([0-9a-f]+)"'
            r'[^}]*"difficulty":(\d+)',
            r.text,
        )
        if not m:
            if "anubis" not in r.text.lower():
                return
            raise RuntimeError("Anubis challenge format changed")
        ch_id, ch_data, diff = m.group(1), m.group(2), int(m.group(3))
        prefix = "0" * diff
        n = 0
        while True:
            h = hashlib.sha256((ch_data + str(n)).encode()).hexdigest()
            if h.startswith(prefix):
                break
            n += 1
        self.session.get(
            self.ANUBIS_SUBMIT,
            params={
                "id": ch_id, "response": h, "nonce": n,
                "redir": f"{self.BASE}/course/?sort_by=rating",
                "elapsedTime": 50,
            },
        )

    def _ensure_anubis(self) -> None:
        r = self.session.get(f"{self.BASE}/course/?sort_by=rating")
        if 'id="anubis_challenge"' in r.text or len(r.text) < 5000:
            self._solve_anubis()

    # ── Search: find NCES sections for a course code ───────────────────────
    def _search_candidates(self, code: str) -> list[tuple[int, str]]:
        """Search NCES and return all (nces_id, teacher_name) with this code."""
        code = code.strip().upper()
        search_url = f"{self.BASE}/search/?q={code}"
        r = self.session.get(search_url, timeout=15)
        if 'id="anubis_challenge"' in r.text or len(r.text) < 2000:
            self._solve_anubis()
            r = self.session.get(search_url, timeout=15)

        candidates: list[tuple[int, str]] = []
        for m in re.finditer(
            r'<a class="px16" href="/course/(\d+)/">(.*?)</a>',
            r.text,
        ):
            card_html = m.group(0)
            m_code = re.search(
                r'<span class="badge[^>]*>([A-Za-z0-9]+)</span>', card_html
            )
            if not m_code or m_code.group(1).upper() != code:
                continue
            nces_id = int(m.group(1))
            m_teacher = re.search(r'（([^）]+)）', card_html)
            nces_teacher = m_teacher.group(1).strip() if m_teacher else ""
            candidates.append((nces_id, nces_teacher))
        return candidates

    def _teachers_overlap(self, tis_teachers: list[str], nces_teacher: str) -> bool:
        """Check if any TIS teacher name overlaps with the NCES teacher name."""
        for t in tis_teachers:
            if t in nces_teacher or nces_teacher in t:
                return True
        return False

    def _parse_semesters(self, html: str) -> list[str]:
        """Extract semester labels from a course detail page.

        Pattern: ``2026秋 2026春 2025秋 ...`` inside a <span> in the header area.
        """
        # Semester block looks like: <span class="small grey ...">2026秋 2026春 ...</span>
        # Find any span containing the semester pattern
        m_sem_block = re.search(
            r'<span[^>]*class="[^"]*(?:small|grey)[^"]*"[^>]*>'
            r'((?:\d{4}[春秋]\s*)+)',
            html,
        )
        if m_sem_block:
            sems = re.findall(r'\d{4}[春秋]', m_sem_block.group(1))
            # Deduplicate while preserving order
            seen = set()
            unique = []
            for s in sems:
                if s not in seen:
                    seen.add(s)
                    unique.append(s)
            return unique
        return []

    # ── Main search API ────────────────────────────────────────────────────
    def search_course(
        self, code: str, teacher: str = "",
        xn: str = "", xq: str = "",
    ) -> tuple[Optional[NCESCourse], bool, list[dict]]:
        """Search NCES for a course and return (course, exact_match, alternatives).

        ``exact_match`` is True when the teacher name matched an NCES section.
        ``alternatives`` is a list of other sections {nces_id, teacher, name}
        with the same code when exact match failed (empty list on exact match).

        Semester matching: when ``xn``/``xq`` are provided, sections whose
        semester list includes the TIS semester are preferred.
        """
        code = code.strip().upper()
        teacher = teacher.strip()
        cache_key = f"{code}::{' '.join(sorted(teacher.replace('，', ',').split(',')))}"
        now = time.time()

        if cache_key in self._course_cache:
            ts, course = self._course_cache[cache_key]
            if now - ts < self.TTL:
                return (course, True, [])

        self._ensure_anubis()
        candidates = self._search_candidates(code)
        if not candidates:
            return (None, False, [])

        tis_teachers_list = (
            [t.strip() for t in teacher.replace("，", ",").split(",") if t.strip()]
            if teacher else []
        )

        # Rank candidates: 0=teacher match, 1=code only (fallback)
        ranked: list[tuple[int, int]] = []  # (nces_id, rank)

        for nces_id, nces_teacher in candidates:
            if tis_teachers_list and self._teachers_overlap(tis_teachers_list, nces_teacher):
                ranked.append((nces_id, 0))
            elif not tis_teachers_list:
                ranked.append((nces_id, 1))

        # No teacher match at all — fallback to first candidate
        if not ranked and tis_teachers_list and candidates:
            ranked = [(candidates[0][0], 1)]

        if not ranked:
            return (None, False, [])

        # Best ranked
        ranked.sort(key=lambda x: x[1])
        best_nces_id, best_rank = ranked[0]

        # Fetch the best course page
        best_course = self._parse_course_page(best_nces_id, code)
        if best_course is None:
            return (None, False, [])

        exact_match = best_rank == 0

        # Build alternatives: other sections of same code (always include)
        seen_ids = {best_nces_id}
        alternatives = []
        for nces_id, nces_teacher in candidates:
            if nces_id not in seen_ids:
                seen_ids.add(nces_id)
                try:
                    alt_html = self._fetch_course_page_raw(nces_id)
                    m_t = re.search(r'<title>NCES\s*-\s*([^（]+)（([^）]+)）', alt_html)
                    alt_name = m_t.group(1).strip() if m_t else ""
                    alt_teacher = m_t.group(2).strip() if m_t else nces_teacher
                except Exception:
                    alt_name = ""
                    alt_teacher = nces_teacher
                alternatives.append({
                    "name": alt_name,
                    "teacher": alt_teacher,
                    "nces_id": nces_id,
                })

        self._course_cache[cache_key] = (time.time(), best_course)
        return (best_course, exact_match, alternatives)

    def _fetch_course_page_raw(self, nces_id: int) -> str:
        url = f"{self.BASE}/course/{nces_id}/"
        r = self.session.get(url, timeout=15)
        if 'id="anubis_challenge"' in r.text or len(r.text) < 5000:
            self._solve_anubis()
            r = self.session.get(url, timeout=15)
        return r.text

    def _parse_course_page(self, nces_id: int, code: str) -> Optional[NCESCourse]:
        url = f"{self.BASE}/course/{nces_id}/"
        r = self.session.get(url, timeout=15)
        if 'id="anubis_challenge"' in r.text or len(r.text) < 5000:
            self._solve_anubis()
            r = self.session.get(url, timeout=15)
        html = r.text

        m_title = re.search(r'<title>NCES\s*-\s*([^（]+)（([^）]+)）', html)
        name = m_title.group(1).strip() if m_title else ""
        teacher = m_title.group(2).strip() if m_title else ""

        semesters = self._parse_semesters(html)
        semester = semesters[0] if semesters else ""

        m_rating = re.search(
            r'class="rl-pd-sm h4 mono-font"[^>]*>([\d.]+)</span>'
            r'\s*<span[^>]*>\s*\((\d+)人评价\)',
            html,
        )
        rating = float(m_rating.group(1)) if m_rating else 0.0
        review_count = int(m_rating.group(2)) if m_rating else 0

        dims: dict[str, tuple[str, float]] = {}
        for cn_label, key in [
            ("课程难度", "difficulty"), ("作业多少", "workload"),
            ("给分好坏", "grading"), ("收获大小", "takeaways"),
        ]:
            m_d = re.search(
                rf'{re.escape(cn_label)}'
                r'.*?<div class="progress-bar[^"]*"[^>]*style="width:\s*([\d.]+)%;"'
                r'[^>]*>\s*([^<]+?)\s*</div>',
                html, re.DOTALL,
            )
            if m_d:
                pct = float(m_d.group(1))
                val = m_d.group(2).strip()
                dims[key] = (LABEL_EN.get(val, val), pct)
            else:
                m_d2 = re.search(rf'{re.escape(cn_label)}[：:]\s*([^<\n]+)', html)
                if m_d2:
                    dims[key] = (LABEL_EN.get(m_d2.group(1).strip(), m_d2.group(1).strip()), 0.0)
                else:
                    dims[key] = ("—", 0.0)

        return NCESCourse(
            nces_id=nces_id, code=code, name=name, teacher=teacher,
            semester=semester, semesters=semesters,
            rating=rating, review_count=review_count,
            difficulty=dims.get("difficulty", ("—", 0.0)),
            workload=dims.get("workload", ("—", 0.0)),
            grading=dims.get("grading", ("—", 0.0)),
            takeaways=dims.get("takeaways", ("—", 0.0)),
            direct_url=url,
        )

    # ── Reviews ────────────────────────────────────────────────────────────
    def fetch_reviews(self, code: str, teacher: str = "") -> Optional[list[dict]]:
        code = code.strip().upper()
        teacher = teacher.strip()

        self._ensure_anubis()
        candidates = self._search_candidates(code)
        if not candidates:
            return None

        tis_teachers_list = (
            [t.strip() for t in teacher.replace("，", ",").split(",") if t.strip()]
            if teacher else []
        )

        # Pick first matching teacher, or first candidate
        target_id = candidates[0][0]
        for nces_id, nces_teacher in candidates:
            if not tis_teachers_list:
                target_id = nces_id
                break
            if self._teachers_overlap(tis_teachers_list, nces_teacher):
                target_id = nces_id
                break

        url = f"{self.BASE}/course/{target_id}/"
        r = self.session.get(url, timeout=15)
        if 'id="anubis_challenge"' in r.text or len(r.text) < 5000:
            self._solve_anubis()
            r = self.session.get(url, timeout=15)
        html = r.text
        return self._parse_reviews(html)

    def _parse_reviews(self, html: str) -> list[dict]:
        reviews: list[dict] = []
        blocks = re.split(
            r'<div class="card small-padding-card mb-3 shadow-sm review review-content[^"]*"',
            html,
        )
        for block in blocks[1:]:
            m_user = re.search(r'href="/user/\d+/?"[^>]*>([^<]+)</a>', block)
            username = m_user.group(1).strip() if m_user else ""
            m_sem = re.search(r'class="text-body-secondary"[^>]*>\s*(\d{4}[春秋])\s*<', block)
            semester = m_sem.group(1) if m_sem else ""
            dims = {}
            for short_label, key in [("难度", "difficulty"), ("作业", "workload"),
                                      ("给分", "grading"), ("收获", "takeaways")]:
                m_d = re.search(rf'{re.escape(short_label)}[：:]\s*([^<]+)', block)
                if m_d:
                    dims[key] = m_d.group(1).strip()
            m_body = re.search(r'<div class="card-body">(.*?)<div class="card-footer">', block, re.DOTALL)
            review_text = ""
            if m_body:
                body_html = m_body.group(1)
                body_html = re.sub(r'<ul[^>]*>.*?</ul>', '', body_html, flags=re.DOTALL)
                review_text = re.sub(r'<[^>]+>', '', body_html).strip()
                review_text = re.sub(r'\s+', ' ', review_text).strip()
            m_date = re.search(r'class="small localtime"[^>]*>\s*(\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}:\d{2})', block)
            date = m_date.group(1) if m_date else ""
            m_likes = re.search(r'id="review-upvote-count-\d+"[^>]*>(\d+)', block)
            likes = int(m_likes.group(1)) if m_likes else 0
            if username or review_text:
                reviews.append({
                    "username": username, "semester": semester,
                    "text": review_text, "date": date, "likes": likes,
                    "dimensions": dims,
                })
        return reviews

    # ── Domain response shape (UI-agnostic payload) ─────────────────────────
    def brief(self, code: str, *, teacher: str = "", xn: str = "", xq: str = "") -> dict | None:
        """Structured hover-brief data for one course code.

        Returns the exact shape the UI consumes, or None if the course
        isn't in NCES (callers should use ``not_found(code)`` for that case).

        Domain decisions owned here (not in the webui):
          - top-N reviews by likes (3)
          - excerpt length (200 chars)
          - dimension shape {label, pct}
          - alternatives included even on exact match (UI hides them)
        """
        course, exact_match, alternatives = self.search_course(
            code, teacher=teacher, xn=xn, xq=xq,
        )
        if course is None:
            return None

        reviews = self.fetch_reviews(code, teacher=teacher) or []
        top = sorted(reviews, key=lambda r: r.get("likes", 0), reverse=True)[:3]
        excerpts = [
            {
                "username": r.get("username", ""),
                "semester": r.get("semester", ""),
                "likes": r.get("likes", 0),
                "excerpt": (r.get("text", "") or "")[:200],
            }
            for r in top
        ]

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
            "review_excerpts": excerpts,
            "exact_match": exact_match,
            "nces_teacher": course.teacher,
            "alternatives": alternatives,
        }

    def not_found(self, code: str) -> dict:
        """Standard 'course not in NCES' payload — keeps callers dumb."""
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
