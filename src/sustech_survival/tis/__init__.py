# tis — SUSTech Teaching Information System
# ─────────────────────────────────────────────────────────────────────────────
# Usage:
#   from sustech_survival.sso import TISAuth
#   from sustech_survival.tis.eval import auto_fill
#
#   auth = TISAuth()
#   auth.refresh()      # always refresh — check() doesn't detect TIS expiry
#   raw = auth.load()
#   auth._apply_cookies(sess, raw)
#   auto_fill(sess)    # auto-detects yhdm from session
# ─────────────────────────────────────────────────────────────────────────────

import sys
from pathlib import Path as _Path

_SKILL_ROOT = _Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_SKILL_ROOT / "src"))

__all__ = ["grades", "courses", "eval", "Evaluation", "EvaluationSession"]

# Lazy-imported to avoid circular deps
def __getattr__(name: str):
    if name == "Evaluation":
        from sustech_survival.tis.eval import Evaluation
        return Evaluation
    if name == "EvaluationSession":
        from sustech_survival.tis.eval import EvaluationSession
        return EvaluationSession
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def grades(semester: str = None, export: str = None):
    """
    Print TIS grades with GPA summary.

    Args:
        semester: Filter by semester, e.g. '2025秋季' (default: all).
        export: 'csv' to export to ~/.openclaw/workspace/sustech/grades.csv
    """
    from sustech_survival.tis.grades import run as _run
    _run(semester=semester, export=export)


def courses(semester: str = None, format: str = "table"):
    """
    Show enrolled courses from TIS.

    Args:
        semester: e.g. '2025秋季', '2026春季' (default: all).
        format: 'table' (default) or 'csv'.
    """
    from sustech_survival.tis.courses import run as _run
    _run(semester=semester, format=format)
