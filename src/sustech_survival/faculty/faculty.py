"""
sustech_survival.faculty — Live SUSTech faculty directory query.

ONE class. FOUR operations. ZERO local data.

    from sustech_survival.faculty import faculty, Faculty

    cards = faculty.list("材料科学与工程系")                    # lightweight
    full  = faculty.list("材料科学与工程系", full=True)         # with research interests

    chengc = faculty.get("chengc")                           # one profile
    print(chengc.to_markdown())                              # AI-readable

    hits = faculty.search("电池", dept="材料科学与工程系")    # sorted by relevance
    for f in hits:
        print(f"  {f.name}  score={f.relevance_score}  matched={f.matched_fields}")

    print(faculty.departments)                               # 50+ dept names

CLI:
    python -m sustech_survival.faculty <depts|list|get|search|render> [...]
"""
from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional

import requests

from .schema import Faculty, IndexCard


# 50+ departments, extracted from the homepage nav on 2026-06-11.
DEPARTMENTS: List[str] = [
    "数学系", "物理系", "化学系", "地球与空间科学系", "统计与数据科学系",
    "先进光源科学中心", "力学与航空航天工程系", "机械与能源工程系",
    "材料科学与工程系", "电子与电气工程系", "计算机科学与工程系",
    "海洋科学与工程系", "生物医学工程系", "环境科学与工程学院",
    "深港微电子学院", "自动化与智能制造学院", "精密光学工程中心",
    "生物系", "基础免疫与微生物学系", "系统生物学系", "化学生物学系",
    "神经生物学系", "医学院", "医学神经科学系", "药理学系", "生物化学系",
    "人类细胞生物和遗传学系", "公共卫生及应急管理学院", "商学院",
    "金融系", "信息系统与管理工程系", "人文科学中心",
    "社会科学中心", "高等教育研究中心", "语言中心", "艺术中心",
    "创新创业学院", "创新创意设计学院", "半导体学院（国家卓越工程师学院）",
    "马克思主义学院", "体育中心", "海洋高等研究院", "杰曼诺夫数学中心",
    "格拉布斯研究院", "量子研究院", "前沿与交叉科学研究院",
    "未来网络研究院", "前沿生物技术研究院", "纳米科学与应用研究院",
    "分析测试中心",
]


# Field weights for search relevance scoring.
_FIELD_WEIGHT = {
    "name": 10,
    "title": 6,
    "department": 4,
    "research_interests": 8,
    "biography": 3,
    "email": 1,
    "education": 1,
    "work_history": 1,
    "slug": 2,  # pinyin transliteration — useful for ASCII queries like "wangf"
}


class FacultyClient:
    """The one object for SUSTech faculty queries.

    Encapsulates session, rate limiting, parallelism, and parsing.
    All operations are live HTTP calls to faculty.sustech.edu.cn.
    """

    BASE_URL = "https://faculty.sustech.edu.cn"

    def __init__(self, *, delay: float = 0.2, workers: int = 5):
        self.delay = delay
        self.workers = workers
        self._session: Optional[requests.Session] = None

    # -- Session management ----------------------------------------------------

    @property
    def session(self) -> requests.Session:
        """Lazy-initialized HTTP session with Chrome UA + lang cookie."""
        if self._session is None:
            self._session = self._make_session()
        return self._session

    def _make_session(self) -> requests.Session:
        s = requests.Session()
        s.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
        s.cookies.set("qtrans_front_language", "zh", domain="faculty.sustech.edu.cn")
        return s

    def close(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None

    # -- Public properties -----------------------------------------------------

    @property
    def departments(self) -> List[str]:
        """All 50+ known SUSTech department names (just the names, no HTTP)."""
        return list(DEPARTMENTS)

    # -- Public operations -----------------------------------------------------

    def list(
        self,
        dept: str,
        *,
        full: bool = False,
        limit: Optional[int] = None,
    ) -> List[Faculty]:
        """List faculty in one department.

        Args:
            dept:  department name (see .departments)
            full:  if True, fetch every profile and return Faculty with
                   research_interests / education / etc. populated.
                   SLOW (60 faculty × 2.2s / 5 workers ≈ 30s).
                   Default False: lightweight Faculty from the index page only.
            limit: stop after N faculty returned

        Returns:
            list[Faculty] in source-page order
        """
        cards = self._list_cards(dept, limit=limit)
        faculties = [Faculty.from_index_card(c) for c in cards]
        if not full:
            return faculties
        if limit:
            slugs = [f.slug for f in faculties]
        else:
            slugs = [f.slug for f in faculties]
        full_fac = self._fetch_profiles_parallel(slugs, on_error="warn")
        if limit:
            return full_fac[:limit]
        return full_fac

    def get(self, slug: str) -> Faculty:
        """Fetch one faculty profile. ~2.2s."""
        url = Faculty.from_index_card(IndexCard(slug=slug, name="")).profile_url_resolved
        r = self.session.get(url, timeout=20)
        r.raise_for_status()
        return Faculty.from_profile_html(r.text, slug=slug)

    def search(
        self,
        query: str,
        *,
        dept: Optional[str] = None,
        limit: int = 20,
    ) -> List[Faculty]:
        """Live keyword search. Fetches profiles in parallel as needed.

        Args:
            query: free-text, whitespace-split, AND semantics
            dept:  restrict to one department (recommended for speed)
                   If None, searches all 50+ departments (~10 min)
            limit: max results

        Returns:
            list[Faculty] sorted by relevance desc, each carrying
            .relevance_score (int) and .matched_fields (list[str])
        """
        if not query.strip():
            return []
        terms = query.split()

        if dept is not None:
            candidates = self.list(dept, full=True)
        else:
            candidates = self._candidates_for_cross_dept_search(terms, limit * 3)

        hits: List[Faculty] = []
        for f in candidates:
            if self._score_into(f, terms):
                hits.append(f)
        hits.sort(key=lambda f: f.relevance_score or 0, reverse=True)
        return hits[:limit]

    def render(self, slug: str) -> str:
        """Fetch one profile and return AI-readable Markdown. ~2.2s."""
        return self.get(slug).to_markdown()

    # -- Private HTTP helpers --------------------------------------------------

    def _list_cards(self, dept: str, *, limit: Optional[int] = None) -> List[IndexCard]:
        """Paginate ?ajax=users for one department, return IndexCard list."""
        out: List[IndexCard] = []
        for page in range(1, 100):
            if self.delay and page > 1:
                time.sleep(self.delay)
            chunk = self._fetch_index_page(dept, page)
            if chunk == "0" or not chunk.strip():
                break
            cards = IndexCard.list_from_index_html(chunk, default_dept=dept)
            if not cards:
                break
            out.extend(cards)
            if limit and len(out) >= limit:
                return out[:limit]
        return out

    def _fetch_index_page(self, dept: str, page: int) -> str:
        r = self.session.get(
            f"{self.BASE_URL}/index.php",
            params={"ajax": "users", "page": page, "field": dept, "lang": "zh"},
            timeout=15,
        )
        r.raise_for_status()
        return r.text

    def _fetch_profile(self, slug: str) -> Faculty:
        url = Faculty.from_index_card(IndexCard(slug=slug, name="")).profile_url_resolved
        r = self.session.get(url, timeout=20)
        r.raise_for_status()
        return Faculty.from_profile_html(r.text, slug=slug)

    def _fetch_profiles_parallel(
        self, slugs: List[str], on_error: str = "warn"
    ) -> List[Faculty]:
        if not slugs:
            return []
        out: List[Optional[Faculty]] = [None] * len(slugs)

        def fetch(idx: int, slug: str):
            try:
                return idx, self._fetch_profile(slug)
            except Exception as e:
                if on_error == "raise":
                    raise
                if on_error == "warn":
                    print(f"[faculty] {slug}: {type(e).__name__}: {e}", file=sys.stderr)
                return idx, None

        with ThreadPoolExecutor(max_workers=self.workers) as ex:
            for fut in as_completed([ex.submit(fetch, i, s) for i, s in enumerate(slugs)]):
                idx, fac = fut.result()
                out[idx] = fac
        return [f for f in out if f is not None]

    def _candidates_for_cross_dept_search(self, terms: List[str], cap: int) -> List[Faculty]:
        """Cross-dept search: prefilter on IndexCard fields, fetch survivors."""

        def card_match(card: IndexCard) -> bool:
            # Include slug so ASCII queries like "wangf" / "chengc" reach profile scoring
            hay = " ".join(
                filter(None, [card.slug, card.name, card.title or "", card.department or ""])
            ).lower()
            return any(t.lower() in hay for t in terms)

        out: List[Faculty] = []
        for d in DEPARTMENTS:
            try:
                cards = self._list_cards(d)
            except Exception:
                continue
            matched_cards = [c for c in cards if card_match(c)]
            if not matched_cards:
                continue
            slugs = [c.slug for c in matched_cards]
            for fac in self._fetch_profiles_parallel(slugs, on_error="warn"):
                out.append(fac)
                if len(out) >= cap:
                    return out
        return out

    # -- Private scoring -------------------------------------------------------

    @staticmethod
    def _score_into(fac: Faculty, terms: List[str]) -> bool:
        """Set fac.relevance_score and fac.matched_fields. Return True if matched."""
        score = 0
        matched: List[str] = []
        for fname, weight in _FIELD_WEIGHT.items():
            text = FacultyClient._haystack(fac, fname).lower()
            if not text:
                continue
            hits = 0
            for t in terms:
                t_low = t.lower()
                if not t_low:
                    continue
                n = text.count(t_low)
                if n > 0:
                    hits += n
            if hits > 0:
                score += hits * weight
                matched.append(fname)
        if score == 0:
            return False
        fac.relevance_score = score
        fac.matched_fields = matched
        return True

    @staticmethod
    def _haystack(fac: Faculty, field_name: str) -> str:
        if field_name == "name":
            return fac.name or ""
        if field_name == "title":
            return fac.title or ""
        if field_name == "department":
            return fac.department or ""
        if field_name == "research_interests":
            return " ".join(fac.research_interests)
        if field_name == "biography":
            return fac.biography or ""
        if field_name == "email":
            return fac.email or ""
        if field_name == "education":
            return " ".join(fac.education)
        if field_name == "work_history":
            return " ".join(fac.work_history)
        if field_name == "slug":
            return fac.slug or ""
        return ""


# -- Module-level singleton ----------------------------------------------------

faculty = FacultyClient()
