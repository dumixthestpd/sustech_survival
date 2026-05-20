# tis — SUSTech Teaching Information System
# ─────────────────────────────────────────────────────────────────────────────
# Usage:
#   from sustech_survival import tis
#   tis.login()             # CAS login (headless)
#   tis.grades()            # fetch + display TIS grades + GPA
#   tis.courses()           # show enrolled courses from TIS (grade API)
#   from sustech_survival.bb import ddl
#   ddl()                   # show upcoming BB assignment deadlines
# ─────────────────────────────────────────────────────────────────────────────

import sys
from pathlib import Path as _Path

_SKILL_ROOT = _Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_SKILL_ROOT / "src"))

__all__ = ["login", "grades", "courses"]


def login(username=None, password=None):
    """Headless CAS login for TIS. Returns cookies dict or None."""
    from sustech_survival.tis.login import cas_login as _cas_login
    if username is None or password is None:
        creds_file = _SKILL_ROOT / "credentials.txt"
        with open(creds_file) as f:
            line = f.read().strip()
        if ':' not in line:
            raise ValueError(f"Invalid credentials in {creds_file}")
        username, password = line.split(':', 1)
    return _cas_login(username, password, "https://tis.sustech.edu.cn/cas")


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
