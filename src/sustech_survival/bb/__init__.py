# BB — Blackboard Learn
# ─────────────────────────────────────────────────────────────────────────────
# Usage:
#   from sustech_survival.bb import ddl
#   ddl()        → print upcoming assignment deadlines
#   ddl(days=7)  → deadlines within N days
# ─────────────────────────────────────────────────────────────────────────────

import sys
from pathlib import Path as _Path

_SKILL_ROOT = _Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_SKILL_ROOT / "src"))

__all__ = ["ddl"]


def ddl(days: int = 7, course_id: str = None):
    """
    Print upcoming BB assignment deadlines.

    Args:
        days: Only show deadlines within N days (default 7).
        course_id: Filter to a specific BB course ID (e.g. '_8053_1').
    """
    from sustech_survival.bb._ddl import run as _run
    _run(days=days, course_id=course_id)
