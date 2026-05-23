# lib — SUSTech Library (Primo) search + auth
# ─────────────────────────────────────────────────────────────────────────────
# Usage:
#   from sustech_survival import lib
#   lib.login()           # CAS login via Playwright / requests
#   lib.check()           # check session validity
#   lib.refresh()         # re-auth via requests
#   lib.ensure()          # check + auto-refresh
# ─────────────────────────────────────────────────────────────────────────────

__all__ = ["login", "check", "refresh", "ensure"]

from pathlib import Path as _Path

_SKILL_DIR = str(_Path(__file__).resolve().parent.parent.parent)

from sustech_survival.sso import LibAuth

_auth = LibAuth(skill_dir=_SKILL_DIR)


def login(*, headless: bool = False):
    return _auth.login(headless=headless)


def check() -> tuple[bool, str]:
    return _auth.check()


def refresh() -> bool:
    return _auth.refresh()


def ensure() -> tuple[bool, str]:
    return _auth.ensure()
