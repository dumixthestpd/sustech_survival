# NCES scraper + hover card — plan

## Context

User feedback (voice memo):
1. Some NCES evaluations are login-only → must fetch ourselves + display with our UI
2. Hover card should show the SPECIFIC course page, not search results (iframe can't due to cross-origin)
3. Display priority: **course name > teacher > class # > course code** (humans identify courses by name+teacher)
4. Use GitHub solutions for Anubis bypass (`anubis-solver` PyPI / `sleeyax/anubis-solver` Go)
5. Solver perf concern (mentioned but not blocking) — defer to separate follow-up

User already approved option A in the clarify prompt: server-side Anubis solver + scraper + cache.

## What we found by probing ncesnext.com

- `/course/?sort_by=rating` returns 32 KB real HTML (sometimes — Anubis kicks in on rapid-fire)
- Each course on the listing has clean markup:
  ```html
  <a class="px16" href="/course/524/">写作与交流 （周秀梅） <span class="badge mono-font">HUM032</span></a>
  <span class="rl-pd-sm h4 mono-font">10.0</span>     ← rating
  <span class="text-body-secondary px12">(38 人评价)</span>   ← review count
  <li class="list-inline-item">课程难度 <div class="progress-bar ...">简单 93.42%</div></li>
  <li>作业多少 ... 很少 92.11%</li>
  <li>给分好坏 ... 超好 100%</li>
  <li>收获大小 ... 很多 90.79%</li>
  ```
- 5709 courses total (6 pages × ~20 per page on sort_by=rating; up to 285 pages for full directory)
- The `?code=` query param doesn't filter — ignored

## Anubis bypass algorithm (verified from `main.mjs`)

- `id` (UUID), `randomData` (hex string), `difficulty` (number)
- Submit via GET `/.within.website/x/cmd/anubis/api/pass-challenge?id={id}&response={hash}&nonce={n}&redir={url}&elapsedTime={ms}`
- PoW: find nonce where `SHA256(randomData + nonce)` has `difficulty` leading hex zeros
- Cookie `techaro.lol-anubis-auth` set on success, lasts **7 days**
- At difficulty=2 (~256 hashes), solve takes ~1-10ms on a single core

Reference repos confirmed:
- `sleeyax/anubis-solver` (Go, 26★)
- `huzpsb/anubis-solver` (Python PyPI, 4★) — `pip install anubis-solver`
- `999Samurai/anubis_challenge_pow_solver` (Python multiprocessing)

## Plan — three files

### 1. `src/sustech_survival/nces/scraper.py` (NEW, ~120 LOC)

```python
class AnubisSolver:
    """Solve Anubis PoW + manage 7-day cookie cache."""
    def __init__(self, cookie_file: Path): ...
    def _solve_pow(self, random_data: str, difficulty: int) -> tuple[str, int]: ...
    def ensure_auth(self, base_url: str, session: requests.Session) -> None:
        """If cookie missing/expired, solve challenge + set cookie."""

@dataclass
class NCESCourse:
    nces_id: int
    code: str          # e.g. "HUM032"
    name: str          # e.g. "写作与交流"
    teacher: str       # e.g. "周秀梅"
    semester: str      # e.g. "2026秋"
    rating: float      # 0–10
    review_count: int
    difficulty: tuple[str, float]   # (label, pct)
    workload: tuple[str, float]
    grading: tuple[str, float]
    takeaways: tuple[str, float]

class NCESScraper:
    """Paginated listing scraper with cache."""
    CACHE_FILE = "~/.cache/sustech_survival/nces_index.json"
    CACHE_TTL = 24 * 3600
    BASE = "https://ncesnext.com"

    def __init__(self): ...
    def _fetch_page(self, page: int, sort: str) -> str:
        """GET /course/?page=N&sort_by=rating with Anubis auth."""
    def _parse_listing(self, html: str) -> list[NCESCourse]:
        """Regex over HTML — extract course cards."""
    def refresh_index(self, sort: str = "rating", max_pages: int = 6) -> int:
        """Fetch + cache all courses. Returns count."""
    def lookup(self, code: str) -> NCESCourse | None:
        """Case-insensitive lookup in cached index."""
    def detail_url(self, nces_id: int) -> str:
        return f"{self.BASE}/course/{nces_id}/"
```

### 2. Update `src/sustech_survival/nces/__init__.py`

Replace the lazy stub with real exports:

```python
from .scraper import NCESCourse, NCESScraper, AnubisSolver

__all__ = ["NCESCourse", "NCESScraper", "AnubisSolver"]
```

### 3. Update `src/sustech_survival/webui/blueprints/tis.py` — `/api/tis/nces`

Replace the current "direct_url only" stub:

```python
@bp.route("/api/tis/nces")
def api_nces():
    code = (request.args.get("code") or "").strip()
    if not code:
        return jsonify({"available": False, "reason": "no course code"})

    scraper = _nces_scraper()  # singleton
    course = scraper.lookup(code)
    if course is None:
        # Cache miss — try refreshing once
        scraper.refresh_index(max_pages=6)
        course = scraper.lookup(code)

    if course is None:
        return jsonify({
            "available": False,
            "reason": "course not found in NCES",
            "direct_url": f"https://ncesnext.com/search?q={code}",
        })

    return jsonify({
        "available": True,
        "code": course.code,
        "name": course.name,
        "teacher": course.teacher,
        "rating": course.rating,
        "review_count": course.review_count,
        "dimensions": {
            "difficulty": {"label": course.difficulty[0], "pct": course.difficulty[1]},
            "workload":   {"label": course.workload[0],   "pct": course.workload[1]},
            "grading":    {"label": course.grading[0],    "pct": course.grading[1]},
            "takeaways":  {"label": course.takeaways[0],  "pct": course.takeaways[1]},
        },
        "detail_url": scraper.detail_url(course.nces_id),
        "direct_url": f"https://ncesnext.com/search?q={code}",
    })
```

### 4. Update `src/sustech_survival/webui/templates/tis.html` — hover card

Apply the display priority (**name > teacher > class # > code**):

```
┌──────────────────────────────────────────┐
│ 写作与交流                                 │  ← name (top, large)
│ 周秀梅 · 001                              │  ← teacher · class #
│ HUM032                                    │  ← code (small, muted)
│ ────────────────────────────              │
│ ★ 10.0 / 10 · (38 reviews)                │
│ ────────────────────────────              │
│ Difficulty   简单     ▰▰▰▰▱  93%         │
│ Workload     很少     ▰▰▰▰▱  92%         │
│ Grading      超好     ▰▰▰▰▰  100%        │
│ Takeaways    很多     ▰▰▰▰▱  91%         │
│ ────────────────────────────              │
│ [Open full NCES page ↗]                   │
└──────────────────────────────────────────┘
```

Replace iframe approach with structured DOM:
- Card is plain div with our own styling
- Real data populated from `/api/tis/nces` response
- "Open full NCES page" button opens the `detail_url` in new tab
- 380px wide × 440px tall (same as before)

## File set summary

- NEW `src/sustech_survival/nces/scraper.py` (~120 LOC)
- MOD `src/sustech_survival/nces/__init__.py` (replace stub)
- MOD `src/sustech_survival/webui/blueprints/tis.py` (`/api/tis/nces` returns structured data)
- MOD `src/sustech_survival/webui/templates/tis.html` (hover card renders real structured data; drop iframe)
- MOD `.hermes/skills/sustech-dev/SKILL.md` (note: Anubis solver + scraper live in `sustech_survival/nces/scraper.py`)

## Verification bar

1. Direct module test: `python -c "from sustech_survival.nces import NCESScraper; s = NCESScraper(); s.refresh_index(); print(s.lookup('MSE306'))"` — first call solves Anubis + caches, second call instant
2. HTTP test: `curl /api/tis/nces?code=HUM032` returns structured JSON with rating, dimensions, etc.
3. UI test: open web UI, hover MSE306 → structured card appears with real data
4. Display priority: name at top, teacher+class on line 2, code small + muted
5. "Open full NCES page" button navigates to `/course/<id>/` in new tab
6. No regressions: solver, schedule grid, picked list, eval tab all work
7. 4-Python-version unified CLI smoke test still passes

## Out of scope (defer to follow-up)

- Solver perf optimization (user noted concern; current solver runs in ~100-300ms for 8 courses, acceptable)
- Pulling NCES login-only evaluations (requires user's NCES session — auth flow needs design first)
- Aggregated reviews per-course (current data only has aggregate stats from listing; per-review details would need scraping detail pages with cookie)