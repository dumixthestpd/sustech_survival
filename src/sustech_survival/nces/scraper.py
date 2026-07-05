"""NCES listing scraper — Anubis-aware + JSON cache.

NCES public listing pages (`/course/?sort_by=rating`) return clean HTML
with all the structured data the hover card needs:
  - course name (Chinese), teacher, course code (badge)
  - NCES internal ID (in /course/<id>/ link)
  - overall rating (0-10), review count
  - 4 dimensions × (label, pct): 课程难度 / 作业多少 / 给分好坏 / 收获大小

The pages are behind Anubis PoW. We solve it inline (10-line hashlib loop)
and cache the `techaro.lol-anubis-auth` cookie for 7 days.

Cache lives at `~/.cache/sustech_survival/nces_index.json`, refreshed
every 24h or on-demand via `sustech nces refresh`.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

import requests


@dataclass
class NCESCourse:
    """One course record parsed from the NCES listing."""
    nces_id: int
    code: str                       # TIS-style code, e.g. "HUM032"
    name: str                       # Chinese course name
    teacher: str                    # teacher display name
    semester: str                   # e.g. "2026秋"
    rating: float                   # 0–10 aggregate rating
    review_count: int               # how many student reviews
    difficulty: tuple               # (label, pct) — 课程难度
    workload: tuple                 # (label, pct) — 作业多少
    grading: tuple                  # (label, pct) — 给分好坏
    takeaways: tuple                # (label, pct) — 收获大小
    direct_url: str                 # https://ncesnext.com/course/<id>/


# Label maps — convert Chinese to English for the UI.
LABEL_EN = {
    "简单": "Easy",
    "中等": "Medium",
    "困难": "Hard",
    "很少": "Light",
    "一般": "Average",
    "很多": "Heavy",
    "超好": "Excellent",
    "好": "Good",
    "差": "Poor",
}


class NCESScraper:
    """Anubis-aware paginated scraper for the NCES course listing."""

    BASE = "https://ncesnext.com"
    ANUBIS_SUBMIT = (
        "https://ncesnext.com/.within.website/x/cmd/anubis/api/pass-challenge"
    )
    CACHE_FILE = Path("~/.cache/sustech_survival/nces_index.json").expanduser()
    CACHE_TTL = 24 * 3600  # 24h
    USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )

    def __init__(self, *, use_cache: bool = True, session: Optional[requests.Session] = None):
        self.use_cache = use_cache
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = self.USER_AGENT

    # ── Anubis PoW ─────────────────────────────────────────────────────────
    def _solve_anubis(self) -> None:
        """GET a page, parse challenge, solve PoW, submit, get cookie.

        Anubis 'fast' algorithm: find nonce where SHA256(randomData + nonce)
        has `difficulty` leading hex zeros. At difficulty=2, ~256 hashes.
        Cookie `techaro.lol-anubis-auth` valid for 7 days.
        """
        r = self.session.get(f"{self.BASE}/course/?sort_by=rating")
        m = re.search(
            r'"id":"([0-9a-f-]{36})"[^}]*"randomData":"([0-9a-f]+)"'
            r'[^}]*"difficulty":(\d+)',
            r.text,
        )
        if not m:
            if "anubis" not in r.text.lower():
                return  # already past Anubis (cookie still valid)
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
                "id": ch_id,
                "response": h,
                "nonce": n,
                "redir": f"{self.BASE}/course/?sort_by=rating",
                "elapsedTime": 50,
            },
        )

    # ── Page fetch + parse ─────────────────────────────────────────────────
    def _fetch_page(self, page: int, sort: str = "rating") -> str:
        url = f"{self.BASE}/course/?page={page}&sort_by={sort}"
        r = self.session.get(url)
        # Re-solve if Anubis challenged (cookie expired or first hit)
        if 'id="anubis_challenge"' in r.text or len(r.text) < 5000:
            self._solve_anubis()
            r = self.session.get(url)
        r.raise_for_status()
        return r.text

    def _parse_listing(self, html: str) -> list[NCESCourse]:
        """Parse course cards from one listing page."""
        courses: list[NCESCourse] = []
        # Split on the per-course container — each block starts with the link
        blocks = re.split(r'<div class="ud-pd-md dashed">', html)
        for block in blocks[1:]:
            # Course link: /course/<id>/ then NAME (TEACHER) <badge>CODE</badge>
            m_link = re.search(
                r'<a class="px16" href="/course/(\d+)/">([^<（]+)（([^）]+)）\s*'
                r'<span class="badge[^>]+>([A-Z]{2,4}\d{3}[A-Z]?)</span>',
                block,
            )
            if not m_link:
                continue
            nces_id = int(m_link.group(1))
            name = m_link.group(2).strip()
            teacher = m_link.group(3).strip()
            code = m_link.group(4)

            # Rating + review count
            m_rating = re.search(
                r'<span class="rl-pd-sm h4 mono-font">([\d.]+)</span>'
                r'\s*<span class="text-body-secondary px12">\((\d+) 人评价\)',
                block,
            )
            rating = float(m_rating.group(1)) if m_rating else 0.0
            review_count = int(m_rating.group(2)) if m_rating else 0

            # Semester
            m_sem = re.search(
                r'<span class="small text-body-secondary">\s*(\d{4}[春秋])', block
            )
            semester = m_sem.group(1) if m_sem else ""

            # 4 dimension progress bars
            dims = {}
            for cn_label, key in [
                ("课程难度", "difficulty"),
                ("作业多少", "workload"),
                ("给分好坏", "grading"),
                ("收获大小", "takeaways"),
            ]:
                m_d = re.search(
                    rf'{re.escape(cn_label)}'
                    r'.*?<div class="progress-bar[^"]*"[^>]*style="width:\s*([\d.]+)%;"'
                    r'[^>]*>\s*([^<]+?)\s*</div>',
                    block,
                    re.DOTALL,
                )
                if m_d:
                    pct = float(m_d.group(1))
                    val = m_d.group(2).strip()
                else:
                    pct, val = 0.0, ""
                dims[key] = (LABEL_EN.get(val, val), pct)

            courses.append(NCESCourse(
                nces_id=nces_id,
                code=code,
                name=name,
                teacher=teacher,
                semester=semester,
                rating=rating,
                review_count=review_count,
                difficulty=dims["difficulty"],
                workload=dims["workload"],
                grading=dims["grading"],
                takeaways=dims["takeaways"],
                direct_url=f"{self.BASE}/course/{nces_id}/",
            ))
        return courses

    # ── Index management ───────────────────────────────────────────────────
    def refresh_index(self, *, sort: str = "rating", max_pages: int = 6,
                      progress: bool = False) -> int:
        """Fetch all listing pages, parse, save to cache. Returns count."""
        all_courses: dict[str, NCESCourse] = {}
        for page in range(1, max_pages + 1):
            try:
                html = self._fetch_page(page, sort=sort)
                page_courses = self._parse_listing(html)
            except Exception as e:  # noqa: BLE001
                if progress:
                    print(f"  page {page}: error {e}")
                continue
            for c in page_courses:
                all_courses[c.code] = c
            if progress:
                print(f"  page {page}: +{len(page_courses)} courses "
                      f"(total {len(all_courses)})")
            time.sleep(0.4)  # be polite

        self.CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        cache_data = {
            "fetched_at": time.time(),
            "sort": sort,
            "courses": {
                c.code: asdict(c) for c in all_courses.values()
            },
        }
        self.CACHE_FILE.write_text(
            json.dumps(cache_data, ensure_ascii=False, indent=2)
        )
        return len(all_courses)

    def lookup(self, code: str) -> Optional[NCESCourse]:
        """Case-insensitive code lookup. Uses cache if fresh, else refreshes."""
        code = code.strip().upper()

        if self.use_cache and self.CACHE_FILE.exists():
            try:
                data = json.loads(self.CACHE_FILE.read_text())
                age = time.time() - data.get("fetched_at", 0)
                if age < self.CACHE_TTL and code in data.get("courses", {}):
                    return NCESCourse(**data["courses"][code])
            except (json.JSONDecodeError, KeyError, TypeError):
                pass  # corrupt cache → refresh

        # Cache miss or stale — refresh and retry
        self.refresh_index()
        if self.CACHE_FILE.exists():
            data = json.loads(self.CACHE_FILE.read_text())
            if code in data.get("courses", {}):
                return NCESCourse(**data["courses"][code])
        return None

    def status(self) -> dict:
        """Cache freshness info for status display."""
        if not self.CACHE_FILE.exists():
            return {"cached": False}
        try:
            data = json.loads(self.CACHE_FILE.read_text())
            return {
                "cached": True,
                "age_hours": (time.time() - data.get("fetched_at", 0)) / 3600,
                "count": len(data.get("courses", {})),
                "sort": data.get("sort"),
                "path": str(self.CACHE_FILE),
            }
        except Exception:
            return {"cached": False, "corrupt": True}

    def clear_cache(self) -> bool:
        if self.CACHE_FILE.exists():
            self.CACHE_FILE.unlink()
            return True
        return False