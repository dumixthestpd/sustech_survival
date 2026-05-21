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
    """See docs/bb.md."""
    from sustech_survival.bb._ddl import run as _run
    _run(days=days, course_id=course_id)
