# lib — SUSTech Library (Primo) search + auth
# ─────────────────────────────────────────────────────────────────────────────
# Usage:
#   from sustech_survival import lib
#   lib.login()           # CAS login via Playwright / requests
#   lib.check()           # check session validity
#   lib.refresh()         # re-auth via requests
#   lib.ensure()          # check + auto-refresh
# ─────────────────────────────────────────────────────────────────────────────

from pathlib import Path as _Path

from ..sso import Authorizer, register_auth
from .login import LibAuth as _LibAuth

LIB_DIR = _Path(__file__).resolve().parent
# Skill root is the parent of src/ (which is the skill dir)
SKILL_ROOT = LIB_DIR.parent.parent.parent

__all__ = ["login", "check", "refresh", "ensure"]

_auth = _LibAuth(skill_dir=str(SKILL_ROOT), submodule_dir=str(LIB_DIR))
register_auth("lib", _auth)


def login(*, headless: bool = False):
    return _auth.login(headless=headless)


def check() -> tuple[bool, str]:
    return _auth.check()


def refresh() -> bool:
    return _auth.refresh()


def ensure() -> tuple[bool, str]:
    return _auth.ensure()
