# BB — SUSTech Blackboard Python API
# ─────────────────────────────────────────────────────────────────────────────
# Usage:
#   import bb
#   bb.credentials()          # auto-detect credentials.txt
#   bb.login()
#   bb.courses()              → [(id, name), ...]
#   bb.pages('8157')          → [(content_id, title, section), ...]
#   bb.items('598333', '8157') → [Item, ...]
#   bb.search(text='homework', type_filter=['homework'])
#   bb.types()
#   bb.download('612447')
#   bb.submit('612447', '/path/to/file.pdf')
# ─────────────────────────────────────────────────────────────────────────────

import sys as _sys
from pathlib import Path as _Path

# Re-export all specific classes and functions for advanced use
from .items import (
    Item, FileItem, VideoItem, HomeworkItem, InlineItem, LinkItem,
    TextItem, FolderItem, UnknownItem,
)
from .pages import (
    Page, preview_page, discover_course_pages, scrape_page,
    scrape_announcements,
)
from .download import (
    download_content, scrape_content_files, download_file,
    resolve_course, discover_attempt_ids, scrape_attempt_details,
    submit_homework, preview_attempt,
)
from .session import (
    BB_BASE,
    load_session, check_session, ensure_session, refresh, login,
)
from .courses import (
    list_courses, find_course, get_course_numeric_id,
    scrape_enrolled_courses, refresh_courses_json,
)

# ── Credentials ───────────────────────────────────────────────────────────────

_CREDENTIALS_FILE = None  # module-level credential path


def credentials(path=None):
    """
    Set the credentials file for CAS login.
    The file should contain: username:password

    If path is omitted, searches in order:
      1. ./credentials.txt       (current working directory)
      2. <bb_module_dir>/credentials.txt

    Example:
        bb.credentials()              # auto-detect
        bb.credentials('~/.my/creds')  # explicit path
    """
    global _CREDENTIALS_FILE

    if path is None:
        # Auto-detect: cwd first, then module dir
        for candidate in [
            _Path.cwd() / "credentials.txt",
            _Path.cwd() / "creds.txt",
            _Path(__file__).parent / "credentials.txt",
            _Path(__file__).parent / "creds.txt",
        ]:
            if candidate.exists():
                path = str(candidate)
                break
        else:
            raise FileNotFoundError(
                "credentials.txt not found in cwd or "
                f"{_Path(__file__).parent}"
            )
    else:
        path = str(_Path(path).expanduser().resolve())

    _CREDENTIALS_FILE = path
    _ensure_creds_in_session_dir(path)
    return path


def _ensure_creds_in_session_dir(creds_path):
    """Symlink or copy creds to the session dir so session.py can find them."""
    try:
        from .courses import BB_DIR
    except ImportError:
        from courses import BB_DIR
    dest = BB_DIR / "creds.txt"
    src = _Path(creds_path).resolve()
    if not dest.exists() or dest.resolve() != src:
        try:
            dest.symlink_to(src)
        except OSError:
            dest.write_text(src.read_text())


# ── Session ───────────────────────────────────────────────────────────────────

def login():
    """Perform CAS login and save session. Returns (bool, message)."""
    try:
        from .session import login as _login
    except ImportError:
        from session import login as _login
    ok = _login()
    return ok, "Login successful" if ok else "Login failed"


def session():
    """Check current session status. Returns (bool, reason)."""
    try:
        from .session import check_session as _check
    except ImportError:
        from session import check_session as _check
    return _check()


# ── Courses ───────────────────────────────────────────────────────────────────

def courses(query=None, *, refresh=False):
    """
    List enrolled courses, optionally filtered.
    Returns list of (course_id, name) tuples.

    Args:
        query:       filter by course name or ID
        refresh:     if True, re-scrapes from BB portal before listing
                     (updates courses.json cache too)
    """
    if refresh:
        refresh_courses_json()
    if query:
        return find_course(query)
    return list_courses()


# ── Pages ─────────────────────────────────────────────────────────────────────

def pages(course_id):
    """
    Discover all content pages in a course (sidebar scan).
    Returns list of (content_id, title, section) tuples.
    """
    return discover_course_pages(course_id)


# ── Items ─────────────────────────────────────────────────────────────────────

def items(content_id, course_id=None):
    """
    Get all items inside a BB content page.
    Returns list of Item objects (FileItem, HomeworkItem, etc.).
    Course ID is auto-resolved if omitted.
    """
    if course_id is None:
        course_id = resolve_course(content_id)
    return preview_page(content_id, course_id)


# ── Search ───────────────────────────────────────────────────────────────────

def search(*,
           course=None, text=None, content_text=None,
           type_filter=None, has_attachments=False,
           hide_types=None, show_types=None):
    """
    Search and filter items across all courses (live scrape).
    Returns list of item dicts.
    """
    from query import discover_all_items
    return discover_all_items(
        course_filter=course,
        text_filter=text,
        content_text=content_text,
        type_filter=type_filter,
        has_attachments=has_attachments,
        hide_types=hide_types,
        show_types=show_types,
    )


# ── Types ───────────────────────────────────────────────────────────────────

def types(course=None):
    """
    Get item type statistics (live scrape).
    Returns dict with item_types, course_counts, total_items, total_courses.
    """
    from query import type_stats_items
    return type_stats_items(course_filter=course)


# ── Download ─────────────────────────────────────────────────────────────────

def download(content_id, out_dir=None):
    """
    Download all files from a BB content item to out_dir.
    Returns list of (filename, local_path) tuples.
    """
    if out_dir is None:
        out_dir = _Path.home() / "Downloads" / "bb"
    return download_content(content_id, str(out_dir))


def preview(course_id, content_id, attempt_id):
    """
    Preview a submission attempt WITHOUT downloading.
    Returns file list (name, size, type), grade, comments, and comment image URLs.

    Args:
        course_id:   e.g. "8343" or "_8343_1"
        content_id: e.g. "612342"
        attempt_id: e.g. "_3025201_1" (use discover_attempt_ids first)

    Example:
        bb.preview("8343", "612342", "_3025201_1")
    """
    # Normalize course_id
    if course_id.startswith("_"):
        course_id = course_id.lstrip("_").rstrip("_").split("_")[0]
    return preview_attempt(course_id, content_id, attempt_id)


# ── Submit ────────────────────────────────────────────────────────────────────

def submit(content_id, file_path, *, course_id=None, comment=None):
    """
    Submit a file to a BB assignment.
    Returns True on success, raises on failure.

    Args:
        content_id:  homework content ID (e.g. "622821")
        file_path:   path to the file to upload
        course_id:   optional course ID (auto-resolved if omitted)
        comment:     optional comment text

    Example:
        bb.submit("622821", "/tmp/hw.pdf")
        bb.submit("622821", "/tmp/hw.pdf", course_id="8221")
    """
    from .download import submit_homework
    return submit_homework(content_id, file_path, course_id=course_id, comment=comment)
