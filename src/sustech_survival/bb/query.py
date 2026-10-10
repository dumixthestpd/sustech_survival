from .. import _net
from .availability import is_explicitly_unavailable
from sustech_survival.exceptions import SessionExpired as _SessionExpired

"""
query — BB course/page discovery via REST API (no Playwright).

Key entry points:
  from sustech_survival.bb.courses import load_courses, find_course, discover_assignments_for_course

Use these functions — do NOT call termId-based endpoints directly.
"""

import json, re, sys, time
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse, urlsplit, urlunparse

import requests

BB_DIR = Path(__file__).parent
BB_BASE = "https://bb.sustech.edu.cn"

ITEM_TYPES = ["file", "video", "homework", "folder", "inline", "link", "text", "unknown"]

_TYPE_ICON = {
    "file": "[file]", "video": "[video]", "homework": "[hw]",
    "folder": "[folder]", "inline": "[img]", "link": "[link]",
    "text": "[text]", "unknown": "[?]",
}

# -- Session ------------------------------------------------------------------

class ContentNotAccessible(RuntimeError):
    """BB refused a content item's detail (HTTP 403).

    Happens for courses that are past or restricted: the course tree still
    lists (``discover_pages``), but the per-item detail endpoint refuses.
    Callers must surface this instead of treating it as "no items".
    """

def session():
    """Return an authenticated requests.Session from the SSO BBAuth layer."""
    from sustech_survival.sso import BBAuth
    bb_auth = BBAuth()
    ok, reason = bb_auth.ensure()
    if not ok:
        raise _SessionExpired(f"BB auth failed: {reason}")
    return bb_auth.session


_session = session  # alias: api()'s `session` param and `_session()` calls both resolve to the module factory


def api(path, session=None):
    """GET BB REST endpoint. Returns JSON. Dies on auth error."""
    if session is None:
        session = _session()
    r = session.get(BB_BASE + path, timeout=_net.service_timeout("bb"))
    if r.status_code == 401:
        raise _SessionExpired("BB session expired. Run `bb.py login` to refresh.")
    r.raise_for_status()
    return r.json()


# -- Course Discovery ---------------------------------------------------------

def _core_id(bb_id: str) -> str:
    """Strip BB wrapper: '_637881_1' → '637881'.

    Never lstrip/rstrip — rstrip('_1') eats trailing chars from ids that
    END in '1' (e.g. _637881_1 → 63788), corrupting lookups.
    """
    parts = bb_id.strip("_").split("_")
    return parts[0] if parts else ""


def discover_courses(term_id=None):
    """
    Return list of (course_id_str, course_name) for the current user's enrollments.

    Mirrors the "My Courses" tab in BB Learn
    (https://bb.sustech.edu.cn/webapps/portal/execute/tabs/tabAction?tab_tab_group_id=_2_1)
    by calling /users/me/courses — the same endpoint the page's XHR
    fetches to render the course list. Only courses the user is enrolled
    in are returned, in any term, regardless of termId.

    Args:
        term_id: DEPRECATED 2026-08-10 — accepted for backward compat but
            ignored. The previous /courses?termId={term_id} endpoint returned
            ALL courses in the term (term-wide catalog), not the user's
            enrollments — which is why resolve_course() walked the paginated
            course list. My Courses (tab_tab_group_id=_2_1) is
            enrollment-filtered, so termId is irrelevant. Pass None (default)
            for new callers.

    Returns:
        list of (course_id_str, course_name). course_id_str is the numeric
        part only, e.g. "8343". Empty if no session / REST fails.
    """
    try:
        me = api("/learn/api/public/v1/users/me")
        uid = me["id"]
        data = api(f"/learn/api/public/v1/users/{uid}/courses?expand=course&limit=200")
        return [(_core_id(c["courseId"]), (c.get("course") or {}).get("name", ""))
                for c in data.get("results", []) if c.get("courseId")]
    except Exception:
        return []


# -- Content Tree Walk --------------------------------------------------------

def _content_listing(path, sess):
    """Yield every content-list page, rejecting incomplete or unsafe pagination."""
    seen_pages = set()
    for _ in range(30):
        if path in seen_pages:
            raise ValueError("BB content pagination loop")
        seen_pages.add(path)
        data = api(path, sess)
        if not isinstance(data, dict) or not isinstance(data.get("results"), list):
            raise ValueError("BB content collection missing results")
        for item in data["results"]:
            if not isinstance(item, dict) or not item.get("id"):
                raise ValueError("BB content collection contains an invalid item")
            yield item
        next_page = (data.get("paging") or {}).get("nextPage")
        if not next_page:
            return
        parts = urlsplit(urljoin(BB_BASE + path, next_page))
        if parts.scheme != "https" or parts.netloc != "bb.sustech.edu.cn":
            raise ValueError("BB content pagination left the expected host")
        path = parts.path + ("?" + parts.query if parts.query else "")
    raise ValueError("BB content pagination exceeded 30 pages")


def walk_contents(course_id, parent_id=None, session=None, *, unavailable=None):
    """Walk content using one session, excluding explicit availability ``No``.

    Yields (content_id, title, content_handler, has_children, parent_id).
    ``unavailable``, if supplied, collects metadata for excluded items. Every
    fresh walk checks parent listings again; no historical deny list is used.
    Other availability states do not establish access. Read failures propagate
    rather than becoming an empty collection or a cacheable partial result.
    """
    sess = session if session is not None else _session()
    bid = f"_{course_id}_1"
    seen = set()

    def visit(parent):
        path = f"/learn/api/public/v1/courses/{bid}/contents"
        if parent:
            path += f"/{parent}/children"
        for item in _content_listing(path, sess):
            item_id = item["id"]
            if item_id in seen:
                continue
            seen.add(item_id)
            cid = _core_id(item_id)
            if is_explicitly_unavailable(item):
                if unavailable is not None:
                    unavailable.append({
                        "course_id": str(course_id), "content_id": cid,
                        "title": item.get("title", ""),
                        "has_children": bool(item.get("hasChildren")),
                        "reason": "availability_no",
                    })
                continue
            yield (
                cid, item.get("title", ""),
                (item.get("contentHandler") or {}).get("id", ""),
                item.get("hasChildren", False),
                parent,
            )
            if item.get("hasChildren"):
                yield from visit(item_id)

    yield from visit(parent_id)


# -- Page Discovery -----------------------------------------------------------


def _warn_unavailable(course_id, unavailable):
    if unavailable:
        print(f"BB course {course_id}: {len(unavailable)} content item(s) "
              "marked unavailable (availability=No); excluded from discovery", file=sys.stderr)


def discover_pages(course_id, *, refresh=False):
    """Return (content_id, title, root section) for discoverable course content.

    Explicitly unavailable items are excluded and counted on stderr. Cached
    listings use the normal BB TTL; ``refresh=True`` checks current state.
    Failed walks are never saved as an empty or partial discovery result.
    """
    try:
        from . import _cache
    except ImportError:
        import _cache

    # Separate from older listings that included unavailable detail targets.
    # Keeping the prefix/course order preserves per-course CLI invalidation.
    cache_args = (course_id, "availability_v1")
    if not refresh:
        data, ok = _cache.get("discover_pages", *cache_args)
        if ok and isinstance(data, dict) and isinstance(data.get("pages"), list):
            _warn_unavailable(course_id, data.get("unavailable", []))
            return data["pages"]

    sess = _session()
    section_map = {}
    unavailable = []
    results = []
    for cid, title, handler, has_children, parent_id in walk_contents(
            course_id, session=sess, unavailable=unavailable):
        section = section_map.get(_core_id(parent_id), "") if parent_id else ""
        if parent_id is None and handler == "resource/x-bb-folder":
            section_map[cid] = title
        else:
            section_map[cid] = section
        results.append((cid, title, section))

    _warn_unavailable(course_id, unavailable)
    try:
        _cache.set("discover_pages", {"pages": results, "unavailable": unavailable}, *cache_args)
    except Exception:
        pass
    return results


# -- Page Items ---------------------------------------------------------------

def classify_item_type(handler: str) -> str:
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


def extract_bbcswebdav(text: str) -> list:
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
        item = api(f"/learn/api/public/v1/courses/{bid}/contents/{cid}?_fields=id,title,body,contentHandler,hasChildren", sess)
    except Exception as e:
        # 403 = the site refuses this item's detail to us (past/restricted
        # course). Never swallow it into "0 items" — callers report it.
        status = getattr(getattr(e, "response", None), "status_code", None)
        if status == 403:
            raise ContentNotAccessible(
                f"content {content_id} in course {course_id}: 403 from BB "
                f"(the course is past or the item is restricted)"
            ) from e
        return []

    handler = item.get("contentHandler", {}).get("id", "")
    itype = classify_item_type(handler)
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
        webdav_urls = extract_bbcswebdav(body)
        for url in webdav_urls:
            row["files"].append((url.split("/")[-1].split("?")[0], url))

    # Attachments API: x-bb-document/x-bb-file/x-bb-assignment items can carry
    # real files (PDF/docx) that never appear in the body HTML.
    if itype in ("inline", "homework", "file"):
        try:
            att = api(
                f"/learn/api/public/v1/courses/{bid}/contents/{cid}/attachments"
                f"?_fields=id,fileName",
                sess,
            )
            for a in att.get("results", []):
                row["files"].append((
                    a.get("fileName", ""),
                    f"_bbatt:{a['id']}|{course_id}|{content_id}",
                ))
        except Exception:
            pass

    try:
        _cache.set("page_items", [row], content_id, course_id)
    except Exception:
        pass
    return [row]


# -- Course ID Resolver ------------------------------------------------------


def resolve_course(content_id):
    """Find which course owns a content_id → numeric course id (e.g. "8343").

    Order of search:

    1. The current user's **enrolled** courses (``/users/me/courses``) — covers
       every term the student is in, and needs no term id.
    2. Nothing else. A previous implementation also walked a hardcoded term
       catalog (``termId=_57_1`` = 2026 Spring), so every Fall-semester item
       failed to resolve even though the user was enrolled in the course.

    For content in a course the user is not enrolled in, pass the course
    explicitly instead: ``bb page <content_id> -c <course_id>``.

    Raises ValueError when no enrolled course claims the id.
    """
    try:
        from . import _cache
    except ImportError:
        import _cache

    data, ok = _cache.get("resolve_course", content_id)
    if ok and data:
        return data

    sess = _session()
    cid = f"_{content_id}_1"
    found = None

    try:
        me = api("/learn/api/public/v1/users/me", sess)
        enr = api(f"/learn/api/public/v1/users/{me['id']}/courses", sess)
        for e in enr.get("results", []):
            bid = e.get("courseId", "")
            if not bid:
                continue
            try:
                api(f"/learn/api/public/v1/courses/{bid}/contents/{cid}", sess)
            except Exception as err:
                # 403 still MEANS this course owns the item (BB refuses the
                # detail, not the ownership) — resolve it so the caller can
                # report "restricted" instead of "not found anywhere".
                if getattr(getattr(err, "response", None), "status_code", None) == 403:
                    found = _core_id(bid)
                    break
                continue
            found = _core_id(bid)
            break
    except Exception:
        pass

    if not found:
        raise ValueError(
            f"content_id {content_id} is not in any enrolled course — "
            f"pass the course explicitly: bb page {content_id} -c <course_id>"
        )

    try:
        _cache.set("resolve_course", found, content_id)
    except Exception:
        pass
    return found


# -- Full Discovery ------------------------------------------------------------

def discover_all_items(*, course_filter=None, text_filter=None,
                       type_filter=None, hide_types=None, show_types=None,
                       has_attachments=False, content_text=None,
                       progress=None, refresh=False, course_ids=None):
    """
    Discover all items across courses via REST.

    Filters (same as Playwright version):
      course_filter, text_filter, type_filter, hide_types, show_types,
      has_attachments, content_text

    course_ids: optional explicit iterable of numeric course ids — the item
    scan is restricted to those courses before any page is scraped.
    """
    all_courses = discover_courses()
    if course_filter:
        # Accept the numeric course ID that `bb courses` prints, as well as a
        # name substring — agents copy the ID, not the full English title.
        q = course_filter.lower()
        all_courses = [(c, n) for c, n in all_courses
                       if q in n.lower() or q in str(c).lower()]
    if course_ids is not None:
        # Explicit id set (e.g. "only this semester") — filters before any
        # page scraping, so an unrelated term costs nothing.
        allowed = {str(c) for c in course_ids}
        all_courses = [(c, n) for c, n in all_courses if str(c) in allowed]
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
    denied = {}          # course_id -> pages BB refused (403)
    done = 0
    for cid, cname, pg_id, pg_title in all_pages:
        try:
            items = scrape_page_items(pg_id, cid, cname)
            for item in items:
                item["course_name"] = cname
            all_items.extend(items)
        except ContentNotAccessible:
            denied[cid] = denied.get(cid, 0) + 1
        except Exception as e:
            print(f"Warning: page {pg_id}: {e}", file=sys.stderr)
        done += 1
        if progress and total > 0:
            progress(done, total)
        time.sleep(0.1)

    if denied:
        # Loud, not silent: these pages exist but BB will not show them, so
        # "0 items" would be a lie about the course's content.
        parts = ", ".join(f"{c} ({n} page(s))" for c, n in denied.items())
        print(f"⚠  content not accessible (HTTP 403) in: {parts} — "
              f"past/restricted course; totals exclude it", file=sys.stderr)

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


# -- Formatting ----------------------------------------------------------------

def format_item(u, verbose=False):
    """One-line search/stat row: course, CONTENT ID (for bb page/download),
    icon, title, attachment count — then the attachment names."""
    t = u.get("type", "?")
    icon = _TYPE_ICON.get(t, "?")
    files = u.get("files", []) or []
    title = u.get("title", "Untitled").replace("\n", " ")
    course = str(u.get("course", ""))[:7]
    cid = str(u.get("id", ""))
    att_tag = f"  📎 {len(files)}" if files else ""
    print(f"  {course:<7} {cid:<7} {icon} {title[:44]}{att_tag}")
    for fname, _path in files[:2]:
        print(f"                   📎 {fname[:66]}")
    if files and not verbose:
        print(f"                   → sustech bb download {cid}")
    if verbose and u.get("desc"):
        preview = u["desc"].replace("\n", " ")[:100].strip()
        print(f"                   💬 {preview}")
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


def type_stats_items(*args, **kwargs):
    """Compute item-type statistics. Alias for discover_all_items."""
    return discover_all_items(*args, **kwargs)


def print_stats(stats, courses=None):
    if courses is None:
        courses = {}
    # Backward compat: accept the raw item list from discover_all_items and
    # derive the aggregate stats dict here. Previously this expected a
    # precomputed dict and crashed with `AttributeError: 'list' has no .get`
    # when callers passed the discovery result directly.
    if isinstance(stats, list):
        items = stats
        type_counts: dict = {}
        for it in items:
            t = (it.get("type") if isinstance(it, dict) else None) or "?"
            type_counts[t] = type_counts.get(t, 0) + 1
        stats = {
            "total_courses": len({(it.get("course_name") if isinstance(it, dict) else None) for it in items if isinstance(it, dict)}),
            "total_items": len(items),
            "item_types": type_counts,
        }
    print(f"\n📊 BB Live Statistics")
    print(f"{'='*50}")
    print(f"  Courses with items:  {stats.get('total_courses', '?')}")
    print(f"  Total items:   {stats.get('total_items', '?')}")
    if "item_types" in stats:
        print(f"\n📂 Item Types:")
        for t, cnt in sorted(stats["item_types"].items(), key=lambda x: -x[1]):
            icon = _TYPE_ICON.get(t, "?")
            print(f"  {icon} {t:<12} {cnt:>4}")


# -- Backward compat shims ----------------------------------------------------

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
