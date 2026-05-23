"""
query — BB course/page discovery via REST API (no Playwright).

Key changes from Playwright version:
  • discover_courses:      /courses?termId=_57_1  (no portal scraping)
  • discover_pages:       /courses/{id}/contents  (no sidebar scrape)
  • scrape_page_items:    /contents/{id}?fields=body  (no page navigation)
  • Course resolution:     walk /courses/{id}/contents tree via REST

Playwright still used for:
  • Submission attempt file URLs (gradebook API has no file URLs)
  • x-bb-file download URLs (REST gives fileName but no signed download URL)

Cache: 1-hour TTL in bb/cache/ (same as before).
"""

import json, re, sys, time
from pathlib import Path
from urllib.parse import unquote, urlparse, urlunparse

import requests

BB_DIR = Path(__file__).parent
BB_BASE = "https://bb.sustech.edu.cn"

ITEM_TYPES = ["file", "video", "homework", "folder", "inline", "link", "text", "unknown"]

_TYPE_ICON = {
    "file": "[file]", "video": "[video]", "homework": "[hw]",
    "folder": "[folder]", "inline": "[img]", "link": "[link]",
    "text": "[text]", "unknown": "[?]",
}

# ── Session ──────────────────────────────────────────────────────────────────

def _session():
    """Return requests.Session with BB cookies from SSO auth layer."""
    from sustech_survival.sso import BBAuth
    auth = BBAuth(skill_dir=str(BB_DIR.parent.parent.parent.parent))
    raw = auth.load()
    s = __import__('requests').Session()
    for name, value in raw.items():
        s.cookies.set(name, value, domain=".bb.sustech.edu.cn", path="/")
    return s


def _api(path, session=None):
    """GET BB REST endpoint. Returns JSON. Dies on auth error."""
    if session is None:
        session = _session()
    r = session.get(BB_BASE + path, timeout=15)
    if r.status_code == 401:
        print("❌ BB session expired. Run `bb.py login` to refresh.")
        sys.exit(1)
    r.raise_for_status()
    return r.json()


# ── Course Discovery ─────────────────────────────────────────────────────────

def discover_courses(term_id="_57_1"):
    """
    Return list of (course_id, course_name) for given term.

    course_id is in BB format e.g. "_8343_1" (use lstrip(' _').rstrip('_1')
    to get numeric part '8343' if needed).

    Falls back to [] if REST fails.
    """
    try:
        data = _api(f"/learn/api/public/v1/courses?termId={term_id}")
        return [(c["id"], c.get("name", ""))
                 for c in data.get("results", []) if c.get("name")]
    except Exception:
        return []


# ── Content Tree Walk ────────────────────────────────────────────────────────

def _walk_contents(course_id, parent_id=None, session=None):
    """
    Recursively walk /courses/{course_id}/contents tree via REST.
    Yields (content_id, title, content_handler, has_children, parent_id).

    course_id must be in BB format e.g. "_8343_1".
    content_id yielded is stripped (numeric part only, e.g. "610783").
    """
    bid = course_id if course_id.startswith("_") else f"_{course_id}_1"
    if parent_id:
        path = f"/learn/api/public/v1/courses/{bid}/contents/{parent_id}/children"
    else:
        path = f"/learn/api/public/v1/courses/{bid}/contents"

    try:
        data = _api(path, session)
    except Exception:
        return

    for item in data.get("results", []):
        cid = item["id"].lstrip("_").rstrip("_1")
        handler = item.get("contentHandler", {}).get("id", "")
        yield (
            cid,
            item.get("title", ""),
            handler,
            item.get("hasChildren", False),
            parent_id,
        )
        if item.get("hasChildren"):
            yield from _walk_contents(course_id, item["id"], session)


# ── Page Discovery ───────────────────────────────────────────────────────────

def discover_pages(course_id, *, refresh=False):
    """
    Return list of (content_id, title, section) for all content in a course.

    Uses REST API to walk the content tree — no Playwright needed.
    section is derived from parent folder title (items with no parent = root).
    """
    try:
        from . import _cache
    except ImportError:
        import _cache

    if not refresh:
        data, ok = _cache.get("discover_pages", course_id)
        if ok:
            return data

    sess = _session()
    bid = course_id if course_id.startswith("_") else f"_{course_id}_1"

    # Build parent_id → section name map from root-level folders
    section_map = {}  # content_id → section name
    try:
        root = _api(f"/learn/api/public/v1/courses/{bid}/contents", sess)
        for item in root.get("results", []):
            if item.get("contentHandler", {}).get("id") == "resource/x-bb-folder":
                cid = item["id"].lstrip("_").rstrip("_1")
                section_map[cid] = item.get("title", "")
    except Exception:
        pass

    results = []
    seen = set()
    for cid, title, handler, has_children, parent_id in _walk_contents(course_id, session=sess):
        if cid in seen:
            continue
        seen.add(cid)
        section = section_map.get(parent_id, "") if parent_id else ""
        results.append((cid, title, section))

    try:
        _cache.set("discover_pages", results, course_id)
    except Exception:
        pass
    return results


# ── Page Items ───────────────────────────────────────────────────────────────

def _classify_item_type(handler: str) -> str:
    """Map contentHandler ID to item type string."""
    if handler == "resource/x-bb-file":
        return "file"
    if handler == "resource/x-bb-folder":
        return "folder"
    if handler == "resource/x-bb-assignment":
        return "homework"
    if handler == "resource/x-bb-document":
        return "inline"
    return "unknown"


def _extract_bbcswebdav(text: str) -> list:
    """Extract bbcswebdav URLs from HTML text."""
    return re.findall(r'bbcswebdav/[^\s"\'<>]+', text)


def scrape_page_items(content_id, course_id, course_name):
    """
    Fetch a content item via REST and extract its metadata + inline files.

    Returns list of item dicts (one per content item).

    For inline items (x-bb-document with HTML body): extracts embedded
    bbcswebdav image URLs directly — no Playwright needed.
    For file items (x-bb-file): returns fileName but no download URL.
    For assignment items: returns title + body text.
    """
    try:
        from . import _cache
    except ImportError:
        import _cache

    # Check cache
    data, ok = _cache.get("page_items", content_id, course_id)
    if ok:
        return data if data else []

    sess = _session()
    bid = f"_{course_id}_1"
    cid = f"_{content_id}_1"

    try:
        item = _api(f"/learn/api/public/v1/courses/{bid}/contents/{cid}?_fields=id,title,body,contentHandler,hasChildren", sess)
    except Exception:
        return []

    handler = item.get("contentHandler", {}).get("id", "")
    itype = _classify_item_type(handler)
    title = item.get("title", "")
    body = item.get("body", "") or ""

    row = {
        "id": content_id,
        "course": course_id,
        "title": title,
        "type": itype,
        "desc": re.sub(r"<[^>]+>", "", body)[:200].strip(),
        "files": [],
        "ext": [],
        "ddl": "",
        "n": 0,
        "status": "",
    }

    # For inline/document items: extract bbcswebdav URLs from body HTML
    if itype == "inline" and body:
        webdav_urls = _extract_bbcswebdav(body)
        for url in webdav_urls:
            row["files"].append((url.split("/")[-1], url))

    try:
        _cache.set("page_items", [row], content_id, course_id)
    except Exception:
        pass
    return [row]


# ── Course ID Resolver ──────────────────────────────────────────────────────

# Known active courses for Spring 2026 (fallback if not in paginated course list)
_ACTIVE_COURSE_IDS = ["_8053_1", "_8157_1", "_8221_1", "_8328_1", "_8343_1"]


def resolve_course(content_id):
    """
    Find which course owns a content_id.

    Strategy:
      1. Check hardcoded active courses first (fast path for known courses)
      2. Walk paginated course list from term _57_1

    Returns course_id string (numeric, e.g. "8343") or raises ValueError.
    """
    sess = _session()
    cids = [f"_{content_id}_1"]

    # 1. Try hardcoded active courses (no pagination needed)
    for bid in _ACTIVE_COURSE_IDS:
        for cid in cids:
            try:
                r = sess.get(
                    f"{BB_BASE}/learn/api/public/v1/courses/{bid}/contents/{cid}",
                    timeout=5
                )
                if r.status_code == 200:
                    return bid.lstrip("_").rstrip("_1")
            except Exception:
                pass

    # 2. Search paginated course list
    offset = 0
    while True:
        try:
            data = sess.get(
                f"{BB_BASE}/learn/api/public/v1/courses?termId=_57_1&offset={offset}",
                timeout=10
            ).json()
        except Exception:
            break

        for c in data.get("results", []):
            bid = c["id"]
            for cid in cids:
                try:
                    r = sess.get(
                        f"{BB_BASE}/learn/api/public/v1/courses/{bid}/contents/{cid}",
                        timeout=5
                    )
                    if r.status_code == 200:
                        return bid.lstrip("_").rstrip("_1")
                except Exception:
                    pass

        paging = data.get("paging", {})
        if "nextPage" not in paging:
            break
        offset += 100

    raise ValueError(f"content_id {content_id} not found in any course")


# ── Full Discovery ────────────────────────────────────────────────────────────

def discover_all_items(*, course_filter=None, text_filter=None,
                       type_filter=None, hide_types=None, show_types=None,
                       has_attachments=False, content_text=None,
                       progress=None, refresh=False):
    """
    Discover all items across courses via REST.

    Filters (same as Playwright version):
      course_filter, text_filter, type_filter, hide_types, show_types,
      has_attachments, content_text
    """
    all_courses = discover_courses()
    if course_filter:
        q = course_filter.lower()
        all_courses = [(c, n) for c, n in all_courses if q in n.lower()]
    if not all_courses:
        return []

    all_pages = []
    for cid, cname in all_courses:
        try:
            pages = discover_pages(cid, refresh=refresh)
            for pg_id, pg_title, section in pages:
                all_pages.append((cid, cname, pg_id, pg_title))
        except Exception as e:
            print(f"Warning: {cid}: {e}", file=sys.stderr)

    total = len(all_pages)
    if progress and total > 0:
        progress(0, total)

    all_items = []
    done = 0
    for cid, cname, pg_id, pg_title in all_pages:
        try:
            items = scrape_page_items(pg_id, cid, cname)
            for item in items:
                item["course_name"] = cname
            all_items.extend(items)
        except Exception as e:
            print(f"Warning: page {pg_id}: {e}", file=sys.stderr)
        done += 1
        if progress and total > 0:
            progress(done, total)
        time.sleep(0.1)

    # Filters
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


# ── Formatting ────────────────────────────────────────────────────────────────

def format_item(u, verbose=False):
    t = u.get("type", "?")
    icon = _TYPE_ICON.get(t, "?")
    att_count = len(u.get("files", []))
    att_tag = f" +{att_count}" if att_count else ""
    type_tag = f"[{t}]"
    title = u.get("title", "Untitled").replace("\n", " ")
    course = u.get("course", "")[:30]
    print(f"  {course:<30} {type_tag:<12} {icon} {title[:40]}{att_tag}")
    if verbose and u.get("desc"):
        preview = u["desc"].replace("\n", " ")[:100].strip()
        print(f"    💬 {preview}")
    if u.get("status"):
        for line in u["status"].split("\n"):
            print(f"    {line}")
    if verbose:
        if u.get("ext"):
            for url in u["ext"]:
                print(f"    Link: {url[:70]}")
        if u.get("files"):
            for fname, fpath in u["files"]:
                print(f"    File: {fname}  [{fpath[:60]}]")


def print_stats(stats, courses=None):
    if courses is None:
        courses = {}
    print(f"\n📊 BB Live Statistics")
    print(f"{'='*50}")
    print(f"  Total courses:  {stats.get('total_courses', '?')}")
    print(f"  Total items:   {stats.get('total_items', '?')}")
    if "item_types" in stats:
        print(f"\n📂 Item Types:")
        for t, cnt in sorted(stats["item_types"].items(), key=lambda x: -x[1]):
            icon = _TYPE_ICON.get(t, "?")
            print(f"  {icon} {t:<12} {cnt:>4}")


# ── Backward compat shims ────────────────────────────────────────────────────

def load_structure():
    return {}

def build_item_index(data):
    return [], {}

def search_items(data, **kwargs):
    return discover_all_items(**kwargs)

def type_stats(data):
    return {"total_courses": 0, "total_items": 0, "item_types": {}, "course_counts": {}}

def discover_courses_fallback():
    """Deprecated alias."""
    return discover_courses()
