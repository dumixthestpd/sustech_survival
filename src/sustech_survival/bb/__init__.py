# BB — SUSTech Blackboard Python API
# ─────────────────────────────────────────────────────────────────────────────
# Usage:
#   from sustech_survival import bb
#   bb.login()                           # CAS login via Playwright
#   bb.courses()                         # [(id, name), ...]
#   bb.pages('8157')                     # [(content_id, title, section), ...]
#   bb.items('598333', '8157')           # [Item, ...]
#   bb.search(text='homework')           # live scrape
#   bb.types()                           # item type stats
#   bb.download('612447')                # download files
#   bb.submit('612447', '/path/file.pdf') # submit assignment
# ─────────────────────────────────────────────────────────────────────────────

from pathlib import Path as _Path

# ── Re-export all specific classes and functions ──────────────────────────────
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

# ── Auth — via sso Authorizer ───────────────────────────────────────────────
# Credentials are read from <skill_root>/credentials.txt
# No manual credentials() call needed; auth is automatic via @require_auth

from .session import _auth as _bb_auth

def credentials():
    """Return the credentials file path. Reads from skill_root/credentials.txt."""
    return _bb_auth.creds_file


# ── Decorator for auth-gated functions ──────────────────────────────────────
def _import_require_auth():
    # Import late to avoid circular issues at module init
    from sustech_survival.sso import require_auth
    return require_auth

def _get_require_auth():
    try:
        from sustech_survival.sso import require_auth
        return require_auth
    except ImportError:
        # sso not yet importable — return a passthrough decorator
        return lambda svc: lambda f: f


# ── Courses ───────────────────────────────────────────────────────────────────

def courses(query=None, *, refresh=False):
    """List enrolled courses, optionally filtered. @require_auth for live scrape."""
    if refresh:
        refresh_courses_json()
    if query:
        return find_course(query)
    return list_courses()


# ── Pages ───────────────────────────────────────────────────────────────────

def pages(course_id):
    """Discover all content pages in a course."""
    return discover_course_pages(course_id)


# ── Items ───────────────────────────────────────────────────────────────────

def items(content_id, course_id=None):
    """Get all items inside a BB content page."""
    if course_id is None:
        course_id = resolve_course(content_id)
    return preview_page(content_id, course_id)


# ── Search — requires auth ──────────────────────────────────────────────────

def search(*,
           course=None, text=None, content_text=None,
           type_filter=None, has_attachments=False,
           hide_types=None, show_types=None):
    """
    Search and filter items across all courses (live scrape).
    Requires auth — uses @require_auth("bb").
    """
    from sustech_survival.sso import require_auth
    require_auth_fn = require_auth

    @require_auth_fn("bb")
    def _search():
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
    return _search()


# ── Types — requires auth ───────────────────────────────────────────────────

def types(course=None):
    """Get item type statistics (live scrape). Requires auth."""
    from sustech_survival.sso import require_auth

    @require_auth("bb")
    def _types():
        from query import type_stats_items
        return type_stats_items(course_filter=course)
    return _types()


# ── Download — requires auth ─────────────────────────────────────────────────

def download(content_id, out_dir=None):
    """Download all files from a BB content item. Requires auth."""
    from sustech_survival.sso import require_auth

    @require_auth("bb")
    def _download():
        _out_dir = out_dir if out_dir is not None else _Path.home() / "Downloads" / "bb"
        return download_content(content_id, str(_out_dir))
    return _download()


def preview(course_id, content_id, attempt_id):
    """Preview a submission attempt. Requires auth."""
    from sustech_survival.sso import require_auth

    @require_auth("bb")
    def _preview():
        return preview_attempt(course_id, content_id, attempt_id)
    return _preview()


# ── Submit — requires auth ──────────────────────────────────────────────────

def submit(content_id, file_path, *, course_id=None, comment=None):
    """
    Submit a file to a BB assignment.
    Requires auth — checks session before uploading.
    """
    from sustech_survival.sso import require_auth

    @require_auth("bb")
    def _submit():
        return submit_homework(content_id, file_path, course_id=course_id, comment=comment)
    return _submit()
