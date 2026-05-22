# tis — SUSTech Teaching Information System
# ─────────────────────────────────────────────────────────────────────────────
# Usage:
#   from sustech_survival import tis
#   tis.login()             # CAS login (headless via SSO auth layer)
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
    """
    Headless CAS login for TIS via SSO auth layer.
    Returns requests.Session with valid TIS cookies, or None on failure.
    """
    import requests
    from sustech_survival.sso.authorizer import get_auth

    auth = get_auth("tis")
    ok, msg = auth.check()
    if ok:
        # Session valid — load cookies and return a session
        raw = auth.load()
        sess = requests.Session()
        sess.headers["User-Agent"] = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        for k, v in raw.items():
            sess.cookies.set(k, v, domain="tis.sustech.edu.cn")
        return sess

    # Session invalid/missing — refresh via SSO auth layer (reads credentials.txt)
    ok = auth.refresh()
    if not ok:
        return None

    raw = auth.load()
    sess = requests.Session()
    sess.headers["User-Agent"] = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    for k, v in raw.items():
        sess.cookies.set(k, v, domain="tis.sustech.edu.cn")
    return sess


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
