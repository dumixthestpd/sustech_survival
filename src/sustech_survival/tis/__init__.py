# tis — SUSTech Teaching Information System
# ─────────────────────────────────────────────────────────────────────────────
# Usage:
#   from sustech_survival import tis
#   tis.login()           # CAS login via requests (headless)
#   tis.courses()         # scrape courses from TIS → CSV
#   tis.check_login()     # check Chrome tabs for TIS session
# ─────────────────────────────────────────────────────────────────────────────

import os as _os
import sys as _sys
from pathlib import Path as _Path

_SKILL_ROOT = _Path(__file__).resolve().parent.parent.parent
_sys.path.insert(0, str(_SKILL_ROOT))

__all__ = ["login", "courses", "check_login"]

TIS_BASE = "https://tis.sustech.edu.cn"


def login(username=None, password=None):
    """
    Headless CAS login for TIS using requests.
    Reads credentials from <skill_root>/credentials.txt if not provided.
    """
    from tis.login import cas_login as _cas_login
    if username is None or password is None:
        creds_file = _SKILL_ROOT / "credentials.txt"
        with open(creds_file) as f:
            line = f.read().strip()
        if ':' not in line:
            raise ValueError(f"Invalid credentials format in {creds_file}")
        username, password = line.split(':', 1)

    return _cas_login(username, password, f"{TIS_BASE}/cas")


def courses(out_path=None):
    """
    Scrape enrolled courses from TIS via Chrome AppleScript.
    Saves to ~/.openclaw/workspace/sustech/26spring/courses.csv by default.
    """
    from tis.courses import main as _fetch
    if out_path:
        _os.environ['TIS_COURSES_CSV'] = out_path
    _fetch()


def check_login() -> bool:
    """Check if Chrome has an active TIS session."""
    import subprocess
    result = subprocess.run(
        ['osascript', '-e',
         'tell application "Google Chrome" to get URL of active tab of front window'],
        capture_output=True, text=True
    )
    url = result.stdout.strip()
    return 'tis.sustech.edu.cn' in url and 'session/invalid' not in url and 'cas.' not in url
