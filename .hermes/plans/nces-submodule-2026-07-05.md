# NCES submodule — parallel to TIS

## Context

User direction (voice memo, 2026-07-05):
1. **NCES and TIS are parallel, not nested.** They cross-relate but don't belong to each other.
2. **NCES auth uses SUSTech CAS** (we discovered: Keycloak OIDC at `sso.cra.ac.cn` that federates to CAS).
3. **NCES should be optional** — `pip install sustech-survival[nces]` pulls in `anubis-solver`.
4. **CAS Auth as a subclass of Authorizer** (same pattern as `TISAuth`/`BBAuth` in `sustech_survival/sso/`).

User already approved option A (server-side Anubis solver + scraper + cache).

## What we found

- `ncesnext.com` is behind Anubis PoW challenge (cookie lasts 7 days after solve)
- Public listing at `/course/?sort_by=rating` returns clean HTML — name, code, teacher, rating, 4 dimensions, review count
- ~5709 courses, 6 pages × ~20 each on default sort
- Auth flow: `/login/oauth/` → 302 → `sso.cra.ac.cn/realms/cra-service-realm/protocol/openid-connect/auth?client_id=cra-nces&redirect_uri=...` (Keycloak OIDC)
- Some evaluations are login-only (per the user's voice)
- Display priority: **course name > teacher > class # > code** (per user)

## Architecture

```
sustech_survival/
├── nces/                          # NEW: parallel to tis/, bb/, lib/
│   ├── __init__.py                # Real exports: NCESAuth, NCESScraper
│   ├── auth.py                    # NCESAuth(CASAuthorizer)
│   │                              #   - login via Keycloak OIDC (TODO: implement)
│   │                              #   - falls back to Anubis for listing scrape
│   ├── scraper.py                 # NCESScraper
│   │                              #   - Anubis-aware HTTP (uses anubis-solver pkg)
│   │                              #   - paginates /course/?sort_by=rating
│   │                              #   - parses course data
│   │                              #   - JSON cache, 24h TTL
│   ├── cli.py                     # Click subcommand: sustech nces
│   │                              #   - refresh, lookup, status
│   └── cache.py                   # Simple JSON cache helpers
└── webui/
    └── blueprints/
        └── nces.py                # NEW blueprint at /api/nces/...
```

## Module file set

### NEW `sustech_survival/nces/__init__.py`

Real exports with optional-dep fallback. If `anubis-solver` not installed, lazy stub.

```python
from typing import TYPE_CHECKING

__all__ = ["NCESAuth", "NCESScraper", "NCESCourse"]

def __getattr__(name):
    if name in __all__:
        try:
            from .auth import NCESAuth  # always available
            from .scraper import NCESScraper, NCESCourse  # requires anubis-solver
        except ImportError as e:
            raise ImportError(
                f"sustech_survival.nces.{name} requires the [nces] extra.\n"
                f"Install with: pip install sustech-survival[nces]\n"
                f"Original error: {e}"
            )
        return {"NCESAuth": NCESAuth, "NCESScraper": NCESScraper,
                "NCESCourse": NCESCourse}[name]
    raise AttributeError(name)

if TYPE_CHECKING:
    from .auth import NCESAuth
    from .scraper import NCESScraper, NCESCourse
```

### NEW `sustech_survival/nces/auth.py`

```python
from dataclasses import dataclass
from ..sso.authorizer import CASAuthorizer

class NCESAuth(CASAuthorizer):
    """CAS SSO for NCES (sustech course eval community).
    
    ncesnext.com uses Keycloak OIDC (sso.cra.ac.cn) which federates
    to SUSTech CAS. Browser flow: /login/oauth/ → sso.cra.ac.cn → 
    Keycloak login form → callback to /login/oauth/callback/.
    
    The full OIDC code flow requires implementing the Keycloak dance.
    For now, this Authorizer is a placeholder that supports credential
    reading + a headless fallback using Anubis (public listing access).
    """
    BASE_URL = "https://ncesnext.com"
    SERVICE_URL = "https://ncesnext.com/login/oauth/callback/"  # Keycloak redirect_uri
    XHR_MODE = False
    
    def _get_ticket_cookies(self, username, password):
        # TODO: implement full OIDC code flow:
        # 1. GET /login/oauth/ → 302 to sso.cra.ac.cn
        # 2. POST credentials to Keycloak token endpoint
        # 3. Exchange code for tokens
        # 4. GET /login/oauth/callback/ with code → nces session cookie
        raise NotImplementedError(
            "NCES uses Keycloak OIDC (sso.cra.ac.cn), not direct CAS. "
            "Full OIDC flow not yet implemented. Use NCESScraper for "
            "public listing access (no login required)."
        )
```

### NEW `sustech_survival/nces/scraper.py`

```python
import re, json, hashlib, time, requests
from dataclasses import dataclass, asdict
from pathlib import Path

@dataclass
class NCESCourse:
    nces_id: int
    code: str            # "HUM032"
    name: str            # "写作与交流"
    teacher: str         # "周秀梅"
    semester: str        # "2026秋"
    rating: float        # 0–10
    review_count: int
    difficulty: tuple    # (label, pct)
    workload: tuple
    grading: tuple
    takeaways: tuple
    direct_url: str      # https://ncesnext.com/course/<id>/

class NCESScraper:
    BASE = "https://ncesnext.com"
    CACHE_FILE = Path("~/.cache/sustech_survival/nces_index.json").expanduser()
    CACHE_TTL = 24 * 3600

    def __init__(self, *, use_cache: bool = True):
        self.session = requests.Session()
        self.session.headers['User-Agent'] = (
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/120.0.0.0 Safari/537.36'
        )
        self.use_cache = use_cache

    def _solve_anubis(self) -> None:
        """GET a page, parse challenge, solve PoW, submit, get cookie."""
        # (uses anubis-solver library OR our 10-line hashlib loop)
        r = self.session.get(f'{self.BASE}/course/?sort_by=rating')
        m = re.search(
            r'"id":"([0-9a-f-]{36})"[^}]*"randomData":"([0-9a-f]+)"'
            r'[^}]*"difficulty":(\d+)', r.text
        )
        if not m:
            # Maybe already authed / no challenge
            if 'anubis' not in r.text.lower():
                return
            raise RuntimeError("Anubis challenge format changed")
        ch_id, ch_data, diff = m.group(1), m.group(2), int(m.group(3))
        prefix = '0' * diff
        n = 0
        while True:
            h = hashlib.sha256((ch_data + str(n)).encode()).hexdigest()
            if h.startswith(prefix):
                break
            n += 1
        # Submit + get cookie
        self.session.get(
            f'{self.BASE}/.within.website/x/cmd/anubis/api/pass-challenge',
            params={'id': ch_id, 'response': h, 'nonce': n,
                    'redir': f'{self.BASE}/course/?sort_by=rating',
                    'elapsedTime': 50}
        )

    def _fetch_page(self, page: int, sort: str = "rating") -> str:
        url = f'{self.BASE}/course/?page={page}&sort_by={sort}'
        r = self.session.get(url)
        # If Anubis blocked, solve + retry
        if 'anubis_challenge' in r.text.lower() or len(r.text) < 5000:
            self._solve_anubis()
            r = self.session.get(url)
        return r.text

    def _parse_listing(self, html: str) -> list[NCESCourse]:
        """Parse course cards from listing page."""
        # Pattern: <a href="/course/ID/">NAME （TEACHER） <span ...>CODE</span>
        # Then rating + dimensions
        courses = []
        for block in html.split('<div class="ud-pd-md dashed">'):
            m_link = re.search(
                r'<a class="px16" href="/course/(\d+)/">([^<]+)（([^）]+)）'
                r'\s*<span class="badge[^>]+>([A-Z]{2,4}\d{3}[A-Z]?)</span>',
                block
            )
            if not m_link:
                continue
            nces_id = int(m_link.group(1))
            name = m_link.group(2).strip()
            teacher = m_link.group(3).strip()
            code = m_link.group(4)
            # Rating
            m_rating = re.search(
                r'<span class="rl-pd-sm h4 mono-font">([\d.]+)</span>'
                r'\s*<span class="text-body-secondary px12">\((\d+) 人评价\)',
                block
            )
            rating = float(m_rating.group(1)) if m_rating else 0.0
            review_count = int(m_rating.group(2)) if m_rating else 0
            # Semester
            m_sem = re.search(r'<span class="small text-body-secondary">\s*(\d{4}[春秋]?)', block)
            semester = m_sem.group(1) if m_sem else ''
            # Dimensions: 4 progress bars
            dims = {}
            for label, key in [
                ('课程难度', 'difficulty'),
                ('作业多少', 'workload'),
                ('给分好坏', 'grading'),
                ('收获大小', 'takeaways'),
            ]:
                m_d = re.search(
                    rf'{re.escape(label)}.*?<div class="progress-bar[^"]*"[^>]*style="width:\s*([\d.]+)%;"[^>]*>\s*([^<]+?)\s*</div>',
                    block, re.DOTALL
                )
                if m_d:
                    pct = float(m_d.group(1))
                    val = m_d.group(2).strip()
                    dims[key] = (val, pct)
                else:
                    dims[key] = ('', 0.0)
            courses.append(NCESCourse(
                nces_id=nces_id, code=code, name=name, teacher=teacher,
                semester=semester, rating=rating, review_count=review_count,
                difficulty=dims['difficulty'], workload=dims['workload'],
                grading=dims['grading'], takeaways=dims['takeaways'],
                direct_url=f'{self.BASE}/course/{nces_id}/',
            ))
        return courses

    def refresh_index(self, *, sort: str = "rating", max_pages: int = 6,
                      progress: bool = False) -> int:
        """Fetch all listing pages, parse, save to cache. Returns count."""
        all_courses = {}
        for page in range(1, max_pages + 1):
            try:
                html = self._fetch_page(page, sort=sort)
            except Exception as e:
                if progress:
                    print(f"  page {page}: error {e}")
                continue
            page_courses = self._parse_listing(html)
            for c in page_courses:
                all_courses[c.code] = c
            if progress:
                print(f"  page {page}: +{len(page_courses)} courses "
                      f"(total {len(all_courses)})")
            time.sleep(0.5)
        # Save cache
        self.CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        cache_data = {
            'fetched_at': time.time(),
            'sort': sort,
            'courses': {c.code: asdict(c) for c in all_courses.values()}
        }
        self.CACHE_FILE.write_text(json.dumps(cache_data, ensure_ascii=False, indent=2))
        return len(all_courses)

    def lookup(self, code: str) -> NCESCourse | None:
        """Case-insensitive lookup. Uses cache if fresh, else refreshes."""
        code = code.strip().upper()
        # Try cache first
        if self.use_cache and self.CACHE_FILE.exists():
            try:
                data = json.loads(self.CACHE_FILE.read_text())
                age = time.time() - data.get('fetched_at', 0)
                if age < self.CACHE_TTL and code in data.get('courses', {}):
                    c = data['courses'][code]
                    return NCESCourse(**c)
            except (json.JSONDecodeError, KeyError, TypeError):
                pass  # cache corrupt → fall through to refresh
        # Refresh
        self.refresh_index()
        if self.CACHE_FILE.exists():
            data = json.loads(self.CACHE_FILE.read_text())
            if code in data.get('courses', {}):
                c = data['courses'][code]
                return NCESCourse(**c)
        return None

    def status(self) -> dict:
        """Cache freshness info."""
        if not self.CACHE_FILE.exists():
            return {'cached': False}
        try:
            data = json.loads(self.CACHE_FILE.read_text())
            return {
                'cached': True,
                'age_hours': (time.time() - data.get('fetched_at', 0)) / 3600,
                'count': len(data.get('courses', {})),
                'sort': data.get('sort'),
            }
        except Exception:
            return {'cached': False, 'corrupt': True}
```

### NEW `sustech_survival/nces/cli.py`

```python
import click
from .scraper import NCESScraper

@click.group("nces")
def cli():
    """NCES — community course evaluation."""
    pass

@cli.command("refresh")
@click.option("--sort", default="rating",
              type=click.Choice(["rating", "popular"]))
@click.option("--max-pages", default=6, type=int)
@click.option("--no-cache", is_flag=True)
def refresh_cmd(sort, max_pages, no_cache):
    """Refresh the NCES course index cache."""
    s = NCESScraper(use_cache=not no_cache)
    n = s.refresh_index(sort=sort, max_pages=max_pages, progress=True)
    click.echo(f"✓ cached {n} courses")

@cli.command("lookup")
@click.argument("code")
def lookup_cmd(code):
    """Look up a course by code (e.g. HUM032)."""
    s = NCESScraper()
    c = s.lookup(code)
    if c:
        click.echo(f"{c.name} · {c.teacher}")
        click.echo(f"  {c.code} · {c.semester}")
        click.echo(f"  ★ {c.rating}/10 ({c.review_count} reviews)")
        click.echo(f"  Difficulty: {c.difficulty[0]} ({c.difficulty[1]:.0f}%)")
        click.echo(f"  Workload:   {c.workload[0]} ({c.workload[1]:.0f}%)")
        click.echo(f"  Grading:    {c.grading[0]} ({c.grading[1]:.0f}%)")
        click.echo(f"  Takeaways:  {c.takeaways[0]} ({c.takeaways[1]:.0f}%)")
        click.echo(f"  {c.direct_url}")
    else:
        click.echo(f"✗ not found: {code}")

@cli.command("status")
def status_cmd():
    """Show cache status."""
    s = NCESScraper()
    st = s.status()
    if st.get('cached'):
        click.echo(f"✓ {st['count']} courses, age {st['age_hours']:.1f}h, sort={st['sort']}")
    else:
        click.echo("✗ no cache. Run: sustech nces refresh")
```

### NEW `sustech_survival/webui/blueprints/nces.py`

```python
from flask import Blueprint, jsonify, request
from sustech_survival.nces import NCESScraper

bp = Blueprint("nces", __name__)
_scraper = None

def _get_scraper():
    global _scraper
    if _scraper is None:
        _scraper = NCESScraper()
    return _scraper

@bp.route("/api/nces/code/<code>")
def api_nces_code(code):
    """Structured NCES data for a course code. Hover card uses this."""
    s = _get_scraper()
    c = s.lookup(code)
    if c is None:
        return jsonify({
            "available": False,
            "reason": "course not found in NCES",
            "search_url": f"https://ncesnext.com/search?q={code}",
        })
    return jsonify({
        "available": True,
        "code": c.code,
        "name": c.name,
        "teacher": c.teacher,
        "semester": c.semester,
        "rating": c.rating,
        "review_count": c.review_count,
        "dimensions": {
            "difficulty": {"label": c.difficulty[0], "pct": c.difficulty[1]},
            "workload":   {"label": c.workload[0],   "pct": c.workload[1]},
            "grading":    {"label": c.grading[0],    "pct": c.grading[1]},
            "takeaways":  {"label": c.takeaways[0],  "pct": c.takeaways[1]},
        },
        "detail_url": c.direct_url,
    })

@bp.route("/api/nces/status")
def api_nces_status():
    """Cache freshness for status display."""
    s = _get_scraper()
    return jsonify(s.status())
```

### MOD `sustech_survival/webui/app.py`

Register the new blueprint (alongside existing `tis`).

### MOD `sustech_survival/webui/blueprints/tis.py`

Remove the placeholder `/api/tis/nces` endpoint.

### MOD `sustech_survival/webui/templates/tis.html`

Replace iframe-based hover card with structured DOM rendering from `/api/nces/code/<code>`. Apply display priority: **name > teacher > class # > code**.

### MOD `pyproject.toml`

Add `[nces]` extra:

```toml
[project.optional-dependencies]
cli = ["click>=8.1", "rich>=13.0"]
playwright = ["playwright>=1.40"]
webui = ["flask>=2.3"]
nces = ["anubis-solver>=0.1"]  # NEW
all = ["sustech-survival[cli,playwright,webui,nces]"]
```

### MOD `sustech_survival/cli.py`

Add nces mount to unified dispatcher:

```python
from .cli import _mount
_mount("nces", cli)  # adds `sustech nces refresh/lookup/status`
```

### MOD `sustech_survival/webui/templates/landing.html`

Add NCES to the landing page modules list.

## Verification bar

1. `pip install -e ".[nces]"` — anubis-solver installs
2. `python -c "from sustech_survival.nces import NCESScraper; s = NCESScraper(); print(s.lookup('HUM032'))"` — solves Anubis, fetches, returns course
3. `sustech nces refresh` — CLI refreshes the cache (~3-5s for 6 pages)
4. `sustech nces lookup HUM032` — shows formatted output
5. `curl /api/nces/code/HUM032` — returns structured JSON
6. Open web UI, hover MSE306 → structured card appears with name+teacher+rating+dimensions (NOT iframe, NOT search page)
7. Display priority: name at top large, teacher+class on line 2, code small muted
8. `sustech nces --help` works on 4 Python versions
9. No regressions: solver, TIS endpoints, schedule grid, picked list all work

## Out of scope (defer)

- **Full OIDC Keycloak auth** for login-only reviews. The listing scraper covers the structured data the hover card needs (rating, dimensions, review count). Per-review text requires authenticated scraping, which needs the Keycloak dance implemented. Document this as a future enhancement.
- **Per-course detail scraping** (individual reviews, not aggregates). Same auth blocker.
- **Solver perf optimization** (user noted concern; defer to separate follow-up).

## Files touched (final count)

| Type | File |
|---|---|
| NEW | `src/sustech_survival/nces/__init__.py` |
| NEW | `src/sustech_survival/nces/auth.py` |
| NEW | `src/sustech_survival/nces/scraper.py` |
| NEW | `src/sustech_survival/nces/cli.py` |
| NEW | `src/sustech_survival/webui/blueprints/nces.py` |
| MOD | `src/sustech_survival/webui/app.py` (register blueprint) |
| MOD | `src/sustech_survival/webui/blueprints/tis.py` (drop `/api/tis/nces` stub) |
| MOD | `src/sustech_survival/webui/templates/tis.html` (hover card → `/api/nces/code/...`, drop iframe) |
| MOD | `src/sustech_survival/cli.py` (mount `nces` subcommand) |
| MOD | `pyproject.toml` (add `[nces]` extra) |