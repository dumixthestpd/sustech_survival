"""
bb download — Download BB course materials and submitted assignments.

Pure REST (no Playwright) for everything this module does:
  • Course/content discovery
  • Course ID resolution
  • Submitted attempt metadata (via gradebook API)
  • x-bb-document content file URLs (bbcswebdav) — see download_file()

Note: the gradebook REST API does NOT expose the URLs of the files a
student submitted to an assignment (only attempt metadata: id, created,
score, feedback). The old Playwright scraper that recovered those URLs
(`bb._playwright.scrape_attempt_files_via_browser`) was removed, so
`scrape_attempt_details` returns `files=[]` and `download_submission`
reports attempts without downloading files.

API:
  from download import download_content, resolve_course
"""
import json, re, sys, os, argparse
from pathlib import Path
from urllib.parse import unquote

import requests

from sustech_survival import _cache

# -- Session ------------------------------------------------------------------

BB_BASE = "https://bb.sustech.edu.cn"


def _default_out_dir(kind: str) -> Path:
    """Default download output directory.

    Precedence: explicit ``out_dir`` (caller) > ``config.json`` key
    (``downloads_dir`` or ``bb.downloads_dir``) > ``~/.sustech_survival/
    downloads/<kind>``. This keeps BB downloads inside the project's home
    dot-directory instead of the OS Downloads folder by default.
    """
    cfg = _cache.load_config()
    d = cfg.get("downloads_dir") or (cfg.get("bb") or {}).get("downloads_dir")
    if d:
        return Path(d).expanduser()
    return _cache.config_root() / "downloads" / kind


def session():
    """Return requests.Session with BB cookies.

    Goes through BBAuth (not raw file IO) so the session lives at
    <skill_root>/.cache/sso/bb/session.json — auto-migrated from
    legacy bb/session.json on first access.
    """
    from sustech_survival.sso import BBAuth
    auth = BBAuth()
    raw = auth.load()  # deprecation warning + migration logic lives here
    s = requests.Session()
    for name, value in raw.items():
        s.cookies.set(name, value, domain=".bb.sustech.edu.cn", path="/")
    return s


from sustech_survival.exceptions import SessionExpired as _SessionExpired


def api(path, session=None):
    if session is None:
        session = session()
    r = session.get(BB_BASE + path, timeout=15)
    if r.status_code == 401:
        raise _SessionExpired("BB session expired. Run `bb.py login`.")
    r.raise_for_status()
    return r.json()


# -- Course/Content Resolution -------------------------------------------------


def resolve_course(content_id):
    """
    Find which course owns a content_id.
    Returns course_id string e.g. "8343".
    """
    sess = session()
    cids = [f"_{content_id}_1"]

    # Walk the paginated course list (term _57_1) to find the owning course.
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


# -- Content Item Fetcher -----------------------------------------------------

def normalize_bb_id(raw):
    """Ensure BB-format with single underscore wrapper: _xxx_1.

    Accepts both numeric ('8343') and BB-format ('_8343_1') IDs,
    returns consistent BB-format string.
    """
    if raw.startswith("_"):
        return raw  # already BB-format, return as-is
    return f"_{raw}_1"


def get_content_item(course_id, content_id, sess=None):
    """Fetch a single content item. Returns dict or None."""
    if sess is None:
        sess = session()
    bid = normalize_bb_id(course_id)
    cid = normalize_bb_id(content_id)
    try:
        return api(f"/learn/api/public/v1/courses/{bid}/contents/{cid}", sess)
    except Exception:
        return None


# -- bbcswebdav URL extractor ------------------------------------------------

def extract_bbcswebdav_urls(html_body):
    """Extract bbcswebdav download URLs from HTML body content."""
    if not html_body:
        return []
    return re.findall(r'bbcswebdav/[^\s"\'<>&\)]+', html_body)


# -- Content File Scraper (REST) ----------------------------------------------

def scrape_content_files(content_id):
    """
    Return (title, files) for a content page using REST API.

    file entries are (name, url_or_path):
      • For x-bb-document items: bbcswebdav URLs extracted from body HTML
      • For x-bb-file items: (fileName, content_id) — no direct REST download URL

    Raises ValueError if content_id not in any known course.
    """
    course_id = resolve_course(content_id)
    item = get_content_item(course_id, content_id)
    if not item:
        raise ValueError(f"Cannot fetch content {content_id}")

    title = item.get("title", "")
    handler = item.get("contentHandler", {}).get("id", "")
    body = item.get("body", "") or ""

    files = []

    if handler == "resource/x-bb-document":
        # Inline content — extract bbcswebdav URLs from HTML body
        urls = extract_bbcswebdav_urls(body)
        for url in urls:
            name = url.split("/")[-1].split("?")[0]
            name = unquote(name)
            files.append((name, url))

    elif handler == "resource/x-bb-file":
        # File item — REST gives filename only, not download URL
        fname = item.get("contentHandler", {}).get("file", {}).get("fileName", "")
        if fname:
            files.append((unquote(fname), f"_bbfile:{content_id}"))

    elif handler == "resource/x-bb-assignment":
        # Assignment — might have inline attachments in body
        urls = extract_bbcswebdav_urls(body)
        for url in urls:
            name = url.split("/")[-1].split("?")[0]
            files.append((unquote(name), url))

    return title, files


# -- File Downloader -----------------------------------------------------------

def download_file(out_path, url_or_path, session_cookies):
    """Download a file from a URL or special path."""
    if url_or_path.startswith("_bbfile:"):
        raise ValueError(f"Cannot download x-bb-file content directly: {url_or_path}")
    full_url = url_or_path if url_or_path.startswith("http") else BB_BASE + url_or_path
    resp = requests.get(full_url, cookies=session_cookies, timeout=30, stream=True)
    resp.raise_for_status()
    with open(out_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=65536):
            f.write(chunk)
    return out_path


def slugify(name):
    """Minimal slugify for filenames."""
    name = re.sub(r"[^\w\s.-]", "_", name)
    return re.sub(r"\s+", "_", name).strip("_")[:200]


def download_content(content_id, out_dir=None):
    """
    Download all files from a BB content page.

    Returns list of saved file paths.
    """
    title, files = scrape_content_files(content_id)
    if not files:
        print(f"[download_content] No files: {title}")
        return []

    out_dir = Path(out_dir) if out_dir else _default_out_dir("BB-content")
    out_dir.mkdir(parents=True, exist_ok=True)

    sess = session()
    session_cookies = {c.name: c.value for c in sess.cookies}

    saved = []
    for name, url_or_path in files:
        out_path = out_dir / slugify(name)
        try:
            if url_or_path.startswith("_bbfile:"):
                print(f"  ⚠ {name}: direct download not available via REST")
                continue
            download_file(out_path, url_or_path, session_cookies)
            size = out_path.stat().st_size
            print(f"  ✓ {title}: {name} ({size:,})")
            saved.append(str(out_path))
        except Exception as e:
            print(f"  ✗ {name}: {e}")

    return saved


# -- Gradebook Attempt Discovery (REST) ---------------------------------------

def get_assignment_attempts(course_id, column_id):
    """
    Return list of (attempt_id, attempt_num, created_timestamp) for a grade column.
    Uses gradebook REST API — no Playwright.
    """
    sess = session()
    bid = course_id if course_id.startswith("_") else f"_{course_id}_1"
    col_id = column_id if column_id.startswith("_") else f"_{column_id}_1"
    try:
        data = api(f"/learn/api/public/v1/courses/{bid}/gradebook/columns/{col_id}/attempts", sess)
        results = []
        for i, att in enumerate(data.get("results", [])):
            results.append((
                att["id"].lstrip("_").rstrip("_1"),
                i + 1,
                att.get("created", "")[:19].replace("T", " "),
            ))
        return results
    except Exception:
        return []


def discover_attempt_ids(ctx, numeric_cid, content_id):
    """
    Return list of (attempt_id, (attempt_num, created_timestamp)) for a content item.
    Uses gradebook REST API — no Playwright needed for discovery.
    ctx is accepted for API compatibility but not used (REST handles it).
    """
    column_id = get_column_id_for_content(numeric_cid, content_id)
    if not column_id:
        return []
    return get_assignment_attempts(numeric_cid, column_id)


def scrape_attempt_details(ctx, numeric_cid, content_id, attempt_id):
    """
    Return dict of attempt details for display (REST metadata only).
    ctx is accepted for API compatibility but not used (no browser).
    Returns: {
        id, attempt_num, created, graded, score, feedback,
        files: [(filename, url_or_path)]
    }
    `files` is always [] — the gradebook REST API does not expose
    submitted-file URLs (the old Playwright scraper was removed).
    """
    column_id = get_column_id_for_content(numeric_cid, content_id)
    if not column_id:
        return {}

    # REST: get attempt metadata
    sess = session()
    bid = f"_{numeric_cid}_1"
    col_id = f"_{column_id}_1"
    try:
        data = api(f"/learn/api/public/v1/courses/{bid}/gradebook/columns/{col_id}/attempts", sess)
    except Exception:
        return {}

    att_data = None
    att_id_stripped = attempt_id.lstrip("_")
    for att in data.get("results", []):
        if att["id"].lstrip("_").rstrip("_1") == att_id_stripped:
            att_data = att
            break

    result = {
        "id": attempt_id,
        "attempt_num": "?",
        "created": "",
        "graded": False,
        "score": "",
        "feedback": "",
        "files": [],
    }
    if att_data:
        result["id"] = att_data["id"]
        result["created"] = att_data.get("created", "")[:19].replace("T", " ")
        display_order = data["results"].index(att_data) + 1
        result["attempt_num"] = str(display_order)
        score_obj = att_data.get("score", {})
        if isinstance(score_obj, dict):
            display_score = score_obj.get("display")
            if display_score is not None:
                result["score"] = str(display_score)
                result["graded"] = True
        elif score_obj is not None:
            result["score"] = str(score_obj)
            result["graded"] = True

    # The gradebook REST API does not expose submitted-file URLs — the old
    # Playwright scraper (bb._playwright) was removed, so `files` stays empty.
    result["files"] = []

    return result


def get_column_id_for_content(course_id, content_id, sess=None):
    """Get gradebook column ID for an assignment content item."""
    if sess is None:
        sess = session()
    item = get_content_item(course_id, content_id, sess)
    if not item:
        return None
    return item.get("contentHandler", {}).get("gradeColumnId", "").lstrip("_").rstrip("_1")


# -- Submission Download (gradebook REST metadata only) ----------------------

def download_submission(course_id, content_id, column_id=None, out_dir=None):
    """
    List submitted attempts for an assignment (gradebook REST metadata only).

    The gradebook REST API exposes attempt metadata (id, created, score,
    feedback) but NOT the URLs of the submitted files. The old Playwright
    scraper that recovered those URLs was removed, so this function reports
    the attempts and returns [] — actual file download is not available
    via REST.

    Returns [] (no files downloadable without a browser).
    """
    out_dir = Path(out_dir) if out_dir else _default_out_dir("BB-submissions")
    out_dir.mkdir(parents=True, exist_ok=True)

    # Resolve column_id from content_id if not provided
    if column_id is None:
        column_id = get_column_id_for_content(course_id, content_id)
        if not column_id:
            print(f"⚠ No gradebook column for content {content_id}")
            return []

    attempts = get_assignment_attempts(course_id, column_id)
    if not attempts:
        print(f"No submission attempts for content {content_id}")
        return []

    print("  ℹ️  Gradebook REST exposes attempt metadata only — submitted file")
    print("     URLs are not available via REST (the Playwright scraper was")
    print("     removed), so files cannot be downloaded. Attempts:")
    for aid, anum, ts in attempts:
        print(f"  Attempt {anum} ({ts})")

    return []

# NOTE: the standalone argparse CLI was removed 2026-08-10 during the
# CLI unification. Use `sustech bb download` (defined in
# sustech_survival/bb/cli.py) — it wraps `download_content` /
# `discover_attempt_ids` / `scrape_attempt_details` from this module.

