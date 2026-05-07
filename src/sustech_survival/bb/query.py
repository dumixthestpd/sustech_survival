#!/usr/bin/env python3
"""
Query — fully dynamic BB queries with caching.
Discovers courses and pages live, scrapes items in real-time.
Cached results stored in bb/cache/ with 1-hour TTL.
"""
import json, re, sys, warnings, time
from pathlib import Path
from urllib.parse import unquote

warnings.filterwarnings("ignore")

try:
    from . import _cache  # bb package
except ImportError:
    import _cache  # standalone execution

BB_DIR = Path(__file__).parent
BB_BASE = "https://bb.sustech.edu.cn"

# Valid item types (for filtering display)
ITEM_TYPES = ["file", "video", "homework", "folder", "inline", "link", "text", "unknown"]

_TYPE_ICON = {
    "file": "📄", "video": "🎬", "homework": "📝",
    "folder": "📁", "inline": "🖼", "link": "🔗",
    "text": "📃", "unknown": "❓",
}

# ── Session ─────────────────────────────────────────────────────────────────

def _load_session():
    """Load BB session cookies."""
    from .session import load_session
    raw, pw = load_session()
    return pw


# ── Course discovery ─────────────────────────────────────────────────────────

def discover_courses():
    """
    Get enrolled courses from courses.json (the canonical list).
    Returns list of (course_id_str, course_name) e.g. ('8157', 'EAP Spring 2026').
    Falls back to portal scraping if courses.json is missing.
    """
    courses_file = BB_DIR / "courses.json"
    if courses_file.exists():
        with open(courses_file) as f:
            data = json.load(f)
        return [(c["id"], c.get("name", c.get("title", "Unknown")))
                for c in data.get("courses", [])]
    # Fallback: discover from portal
    return _discover_courses_from_portal()


def _discover_courses_from_portal():
    """
    Fallback: discover courses directly from BB portal page.
    Returns list of (course_id_str, course_name).
    """
    cookies = _load_session()
    url = f"{BB_BASE}/webapps/portal/execute/tabs/tabAction?tab_tab_group_id=_1_1"

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context()
        ctx.add_cookies(cookies)
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(1000)

        courses = []
        seen = set()

        for a in page.query_selector_all("a[href*='course_id=']"):
            href = a.get_attribute("href") or ""
            title = a.inner_text().strip()
            if not title or "course_id=" not in href:
                continue
            m = re.search(r"course_id=(_?\d+)", href)
            if not m:
                continue
            cid = m.group(1).lstrip("_")
            if cid in seen:
                continue
            seen.add(cid)
            title = re.sub(r"\s*\(.*?\)\s*$", "", title).strip()
            if title:
                courses.append((cid, title))

        browser.close()
        return courses


# ── Page discovery (sidebar only — fast) ─────────────────────────────────────

def discover_pages(course_id, *, refresh=False):
    """
    Fast sidebar-only discovery of all content pages in a course.
    Cached for 1 hour; pass refresh=True to bust the cache.
    Returns list of (content_id, title, section) tuples.
    """
    if not refresh:
        data, ok = _cache.get("discover_pages", course_id)
        if ok:
            return data
    cookies = _load_session()
    url = (
        f"{BB_BASE}/webapps/blackboard/content/listContent.jsp"
        f"?course_id={course_id}&content_id={course_id}"
    )

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context()
        ctx.add_cookies(cookies)
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(800)

        results = []
        current_section = ""
        seen = set()

        sidebar = page.query_selector("#courseMenuPalette_contents") or page

        for li in sidebar.query_selector_all("li"):
            cls = li.get_attribute("class") or ""
            if "subhead" in cls:
                h3 = li.query_selector("h3 span")
                current_section = h3.inner_text().strip() if h3 else ""
            elif "clearfix" in cls:
                a = li.query_selector("a")
                if not a:
                    continue
                href = a.get_attribute("href") or ""
                title = a.inner_text().strip()
                if not title or "content_id=" not in href:
                    continue
                m = re.search(r"content_id=_(\d+)_", href)
                if not m:
                    continue
                cid = m.group(1)
                if cid in seen:
                    continue
                seen.add(cid)
                results.append((cid, title, current_section))

        browser.close()
        _cache.set("discover_pages", results, course_id)
        return results


# ── Page scraper (single page → list of item dicts) ─────────────────────────

def scrape_page_items(content_id, course_id, course_name):
    """
    Scrape a single BB content page and return its items as dicts.
    Returns list of dicts with keys: sub_id, title, type, bb_url, description, files.
    """
    try:
        from pages import preview_page
        items = preview_page(content_id, course_id)
        result = []
        for it in items:
            # ── Parse deadline → machine-readable %Y-%m-%d %H:%M ──
            raw_dl = getattr(it, "deadline", "") or ""
            ddl = ""
            if raw_dl:
                try:
                    # Input: "Wednesday, May 6, 2026 11:59 PM"
                    from email.utils import parsedate_to_datetime
                    dt = parsedate_to_datetime(raw_dl)
                    ddl = dt.strftime("%Y-%m-%d %H:%M")
                except Exception:
                    ddl = raw_dl  # fallback: keep raw

            # ── Files: [filename, webdav_path] ──
            files = [f[0] if isinstance(f, (list, tuple)) else f for f in getattr(it, "files", []) or []]
            paths = [f[1] if isinstance(f, (list, tuple)) and len(f) > 1 else "" for f in getattr(it, "files", []) or []]

            # ── Slim ext_urls: strip tracking, keep scheme+host+path ──
            import re, urllib.parse
            raw_exts = getattr(it, "ext_urls", []) or []
            ext = []
            for u in raw_exts:
                url = u[1] if isinstance(u, (list, tuple)) else u
                try:
                    p = urllib.parse.urlparse(url)
                    # strip query params like ?g=, ?p=, ?preview= etc.
                    clean = urllib.parse.urlunparse((p.scheme, p.netloc, p.path, "", "", ""))
                    ext.append(clean)
                except Exception:
                    ext.append(url)

            # ── Full description ──
            desc = getattr(it, "description", "") or ""

            row = {
                "id":      it.sub_id,
                "course":  course_id,
                "title":   it.title,
                "type":    it.TYPE,
                "desc":    desc,
                "files":   list(zip(files, paths)),
                "ext":     ext,
                "ddl":     ddl,
                "n":       getattr(it, "submission_count", 0) or 0,
            }
            result.append(row)
        return result
    except Exception as e:
        return []


# ── Full dynamic discovery ───────────────────────────────────────────────────

def discover_all_items(*, course_filter=None, text_filter=None,
                       type_filter=None, hide_types=None, show_types=None,
                       has_attachments=False, content_text=None,
                       progress=None, refresh=False):
    """
    Discover all items from all courses dynamically.

    Args:
        course_filter: substring match in course title
        text_filter: substring match in item title
        type_filter: list of item types to include
        hide_types: list of item types to exclude
        show_types: list — if set, only show these types
        has_attachments: only items with attachments
        content_text: substring match in item description
        progress: optional callback(total_pages, completed) for progress updates

    Returns list of item dicts.
    """
    # 1. Discover all courses
    all_courses = discover_courses()

    # 2. Apply course filter early
    if course_filter:
        q = course_filter.lower()
        all_courses = [(cid, name) for cid, name in all_courses
                       if q in name.lower()]

    if not all_courses:
        return []

    # 3. Discover all pages per course (sidebar only — fast)
    all_pages = []  # (course_id, course_name, content_id, title)
    for cid, cname in all_courses:
        try:
            pages = discover_pages(cid, refresh=refresh)
            for pg_id, pg_title, section in pages:
                all_pages.append((cid, cname, pg_id, pg_title))
        except Exception as e:
            print(f"Warning: could not discover pages for course {cid}: {e}", file=sys.stderr)

    total_pages = len(all_pages)
    if progress and total_pages > 0:
        progress(0, total_pages)

    # 4. Scrape each page sequentially (Playwright is not thread-safe)
    all_items = []
    completed = 0

    for page_info in all_pages:
        cid, cname, pg_id, pg_title = page_info
        try:
            # Try cache first
            data, ok = _cache.get("page_items", pg_id, cid)
            if ok:
                items = data if data else []
            else:
                items = scrape_page_items(pg_id, cid, cname)
                _cache.set("page_items", items, pg_id, cid)
            all_items.extend(items)
        except Exception as e:
            print(f"Warning: scrape failed for page {pg_id}: {e}", file=sys.stderr)
        completed += 1
        if progress and total_pages > 0:
            progress(completed, total_pages)
        time.sleep(0.3)

    # 5. Apply filters
    if type_filter:
        type_filter = [t.lower() for t in type_filter]
        all_items = [u for u in all_items if u.get("type", "").lower() in type_filter]

    if hide_types:
        hide_lower = [t.lower() for t in hide_types]
        all_items = [u for u in all_items if u.get("type", "").lower() not in hide_lower]

    if show_types:
        show_lower = [t.lower() for t in show_types]
        all_items = [u for u in all_items if u.get("type", "").lower() in show_lower]

    if text_filter:
        q = text_filter.lower()
        all_items = [u for u in all_items if q in u.get("title", "").lower()]

    if content_text:
        q = content_text.lower()
        all_items = [u for u in all_items if q in u.get("desc", "").lower()]

    if has_attachments:
        all_items = [u for u in all_items if u.get("files") or u.get("ext")]

    return all_items


def type_stats_items(*, course_filter=None, progress=None):
    """
    Compute per-type and per-course item counts dynamically.
    """
    items = discover_all_items(course_filter=course_filter, progress=progress)

    type_counts = {}
    course_counts = {}

    for u in items:
        t = u.get("type", "unknown")
        type_counts[t] = type_counts.get(t, 0) + 1
        cid = u["course"]
        course_counts[cid] = course_counts.get(cid, 0) + 1

    return {
        "item_types": type_counts,
        "course_counts": course_counts,
        "total_items": len(items),
        "total_courses": len(set(u["course_id"] for u in items)),
    }


# ── Formatting ───────────────────────────────────────────────────────────────

def format_item(u, verbose=False):
    """Format a single item dict for display."""
    t = u.get("type", "?")
    icon = _TYPE_ICON.get(t, "?")
    att_count = len(u.get("files", []))
    att_tag = f" 📎{att_count}" if att_count else ""
    type_tag = f" [{t}]"
    title = u.get("title", "Untitled").replace("\n", " ")
    course = u.get("course", "")[:30]
    print(f"  {course:<30} {type_tag:<14} {icon} {title[:40]}{att_tag}")
    if verbose:
        if u.get("desc"):
            preview = u["desc"].replace("\n", " ")[:100].strip()
            print(f"    💬 {preview}")
        if u.get("ext"):
            for url in u["ext"]:
                print(f"    🔗 {url[:70]}")
        if u.get("files"):
            for fname, fpath in u["files"]:
                print(f"    📄 {fname}  [{fpath[:60]}]")


def print_stats(stats, courses=None):
    """Print type statistics. Looks up course names from courses.json."""
    if courses is None:
        courses_file = BB_DIR / "courses.json"
        if courses_file.exists():
            with open(courses_file) as f:
                data = json.load(f)
            courses = {c["id"]: c.get("name", c.get("title", c["id"]))
                       for c in data.get("courses", [])}
        else:
            courses = {}

    print(f"\n📊 BB Live Statistics")
    print(f"{'='*50}")
    print(f"  Total courses:  {stats['total_courses']}")
    print(f"  Total items:   {stats['total_items']}")

    print(f"\n📂 Item Types:")
    for t, cnt in sorted(stats["item_types"].items(), key=lambda x: -x[1]):
        icon = _TYPE_ICON.get(t, "?")
        print(f"  {icon} {t:<12} {cnt:>4}")

    if stats["course_counts"]:
        print(f"\n📚 Items per Course:")
        for cid, cnt in sorted(stats["course_counts"].items(), key=lambda x: -x[1]):
            cname = courses.get(cid, cid)
            print(f"  {cid:<8} {cnt:>3}  {cname[:40]}")


# ── Backward compat shims (bb.py imports these) ───────────────────────────────

def load_structure():
    """Deprecated — no-op, kept for import compatibility."""
    return {}

def build_item_index(data):
    """Deprecated — returns (empty, empty)."""
    return [], {}

def search_items(data, **kwargs):
    """Deprecated — dispatches to discover_all_items."""
    return discover_all_items(**kwargs)

def type_stats(data):
    """Deprecated — dispatches to type_stats_items."""
    return type_stats_items()
