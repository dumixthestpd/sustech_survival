# =============================================================================
# BB Session — CAS authentication for Blackboard
# =============================================================================

import sys as _sys
from pathlib import Path as _Path

# sustech_survival/sso.py — ensure package root is importable when running standalone
_PKG_ROOT = str(_Path(__file__).resolve().parent.parent.parent)
if _PKG_ROOT not in _sys.path:
    _sys.path.insert(0, _PKG_ROOT)

BB_DIR = _Path(__file__).resolve().parent
# Skill root is the parent of src/ (which is the skill dir)
SKILL_ROOT = BB_DIR.parent.parent.parent

SESSION_FILE = BB_DIR / "session.json"
COURSES_FILE = BB_DIR / "courses.json"
STRUCTURE_FILE = BB_DIR / "structure.json"

# ── Import BBAuth from authlib ────────────────────────────────────────────────
from sustech_survival.sso import BBAuth

# Module-level singleton
_auth = BBAuth(skill_dir=str(SKILL_ROOT))

# ── Convenience wrappers ─────────────────────────────────────────────────────

from sustech_survival.sso.authorizer import Authorizer

Authorizer.username = property(lambda self: _auth.username, lambda self, v: setattr(_auth, 'username', v))
Authorizer.password = property(lambda self: _auth.password, lambda self, v: setattr(_auth, 'password', v))


def session(*, force: bool = False):
    """
    Return a requests.Session with BB cookies attached.
    Auto-refreshes if the session is expired.
    """
    return _auth.session(force=force)


def login(*, headless: bool = False):
    """
    CAS login via Playwright (headless=True) or requests (headless=False).
    Returns True on success.
    """
    return _auth.login(headless=headless)


def check() -> tuple[bool, str]:
    """
    Check if current session is valid.
    Returns (True, "") if valid, (False, reason) if not.
    """
    return _auth.check()


def refresh() -> bool:
    """
    Force a fresh CAS ticket exchange.
    Returns True on success.
    """
    return _auth.refresh()


def ensure() -> tuple[bool, str]:
    """
    check() + auto-refresh if expired.
    Returns (True, "") on success, (False, reason) on failure.
    """
    return _auth.ensure()
