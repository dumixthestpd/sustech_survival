# ── Public API ────────────────────────────────────────────────────────────────

from .authorizer import Authorizer, AuthorizerError, CAS_BASE, UA, register_auth, get_auth, require_auth
from .providers.cas import CASAuthorizer
from .providers.shibboleth import ShibbolethAuthorizer

__all__ = [
    "Authorizer",
    "AuthorizerError",
    "CAS_BASE",
    "UA",
    "CASAuthorizer",
    "ShibbolethAuthorizer",
    "TISAuth",
    "BBAuth",
    "LibAuth",
    "Credentials",      # backwards compat — redirects to Authorizer.username/password
    "register_auth",
    "get_auth",
    "require_auth",
]

# Backwards-compat shim: Credentials was merged into Authorizer.
Credentials = Authorizer


# ── Find skill root for session storage ────────────────────────────────────────
# sso/__init__.py lives at:  sustch_survival/sso/__init__.py
# We walk up 3 levels to reach the skill root.
#   sso → sustch_survival → src → skill_root
from pathlib import Path as _Path
import requests as _requests

_SSO_PATH = _Path(__file__).resolve()
_SKILL_ROOT = _SSO_PATH.parent.parent.parent.parent
del _SSO_PATH


# =============================================================================
# TISAuth — Teaching Information System (CAS + XHR)
# =============================================================================

class TISAuth(CASAuthorizer):
    BASE_URL = "https://tis.sustech.edu.cn"
    SERVICE_URL = "https://tis.sustech.edu.cn/cas"
    SESSION_SUBDIR = "tis"
    XHR_MODE = True
    SUBMIT_VALUE = ""

    @property
    def session(self) -> _requests.Session:
        """A requests.Session with current cookies pre-loaded."""
        cookies = self.load()
        sess = _requests.Session()
        for name, value in cookies.items():
            sess.cookies.set(name, value)
        return sess

    @property
    def session_file(self):
        return _SKILL_ROOT / "sso" / "tis" / "session.json"


# =============================================================================
# BBAuth — Blackboard Learn (CAS, resets cached courses on refresh)
# =============================================================================

class BBAuth(CASAuthorizer):
    BASE_URL = "https://bb.sustech.edu.cn"
    SERVICE_URL = "https://bb.sustech.edu.cn/webapps/bb-sso-BBLEARN/index.jsp"
    SESSION_SUBDIR = "bb"

    @property
    def session_file(self):
        return _SKILL_ROOT / "sso" / "bb" / "session.json"

    def _reset_cached_data(self):
        """Delete cached course data so it gets refreshed on next access."""
        skill_bb = _SKILL_ROOT / "bb"
        for f in (skill_bb / "courses.json", skill_bb / "structure.json"):
            if f.exists():
                f.unlink()

    def refresh(self) -> bool:
        ok = super().refresh()
        if ok:
            self._reset_cached_data()
        return ok

    def login(self, *, headless: bool = False):
        ok = super().login(headless=headless)
        if ok:
            self._reset_cached_data()
        return ok


# =============================================================================
# LibAuth — SUSTech Library Primo (CAS)
# =============================================================================

class LibAuth(CASAuthorizer):
    BASE_URL = "https://sustc.primo.exlibrisgroup.com.cn"
    SERVICE_URL = "https://sustc.primo.exlibrisgroup.com.cn/infra/casRedirect?ctx=/primaws"
    SESSION_SUBDIR = "lib"

    @property
    def session_file(self):
        return _SKILL_ROOT / "sso" / "lib" / "session.json"


# Register singletons for backwards compatibility with get_auth()
register_auth("tis", TISAuth(skill_dir=str(_SKILL_ROOT)))
register_auth("bb", BBAuth(skill_dir=str(_SKILL_ROOT)))
register_auth("lib", LibAuth(skill_dir=str(_SKILL_ROOT)))


# ── Auto-register external authlib services ───────────────────────────────────
# Importing authlib triggers lazy-loading of external services (wos, rsc, etc.)
from . import authlib  # noqa: F401
