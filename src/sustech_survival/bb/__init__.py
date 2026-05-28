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

__all__ = ["ddl", "query", "download", "submit", "check_attempts", "find_assignment", "list_upcoming"]

from sustech_survival.bb import query, download
from sustech_survival.bb.ddl import run as _ddl_run
from sustech_survival.bb.submit import submit, check_attempts, find_assignment, list_upcoming

def ddl(days: int = 7, course_id: str = None):
    """Print upcoming BB assignment deadlines. See docs/bb.md."""
    _ddl_run(days=days, course_id=course_id)
