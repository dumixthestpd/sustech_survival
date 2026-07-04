# BB — Blackboard Learn
# ─────────────────────────────────────────────────────────────────────────────
# Usage:
#   from sustech_survival.bb import ddl
#   ddl()        → print upcoming BB assignment deadlines
#   ddl(days=7)  → deadlines within N days
#
# REST-based modules (no Playwright):
#   from sustech_survival.bb import query, download
#   query.discover_courses()   → list of (course_id, name)
#   query.discover_pages(cid) → list of (content_id, title, section)
#   query.resolve_course(cid) → course_id string
#   download.scrape_content_files(cid) → (title, [(name, url)])
#   download.download_content(cid) → list of saved paths
# ─────────────────────────────────────────────────────────────────────────────

import sys
from pathlib import Path as _Path

_SKILL_ROOT = _Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_SKILL_ROOT / "src"))

__all__ = ["ddl", "query", "download", "submit_file", "submit_assignment", "check_attempts", "find_assignment", "list_upcoming"]

from sustech_survival.bb import query, download
from sustech_survival.bb.ddl import run as _ddl_run

# submit requires playwright (optional dependency). Lazy-import so the
# package loads without playwright installed — submit funcs raise on call
# if playwright is truly needed.
def __getattr__(name):
    if name in ("submit_file", "submit_assignment", "check_attempts",
                "find_assignment", "list_upcoming"):
        from sustech_survival.bb import submit as _submit
        return getattr(_submit, name)
    raise AttributeError(name)

# Note (2026-06-08): we used to do `from .submit import submit, ...` here,
# but that bound the `submit` function to the `bb` package namespace and
# shadowed the `sustech_survival.bb.submit` SUBMODULE. Anyone doing
# `import sustech_survival.bb.submit as m` got the function, not the
# module, breaking monkeypatching and any code that needed the module.
# Renamed the function to `submit_file` to break the collision.

def ddl(days: int = 7, course_id: str = None):
    """Print upcoming BB assignment deadlines. See docs/bb.md."""
    _ddl_run(days=days, course_id=course_id)
