"""
sustech_survival.sso — Unified SSO across SUSTech ecosystem.

──────────────────────────────────────────────────────────────────────
 Authorizer subclass patterns — READ BEFORE BUILDING A NEW SERVICE
──────────────────────────────────────────────────────────────────────

All CAS services authenticate via one of three patterns. Choose the
right one before writing a single line of auth code.

PATTERN 1 — Static SERVICE_URL (most services)
───────────────────────────────────────────────
  class MyAuth(CASAuthorizer):
      BASE_URL = "https://service.sustech.edu.cn"
      SERVICE_URL = "https://service.sustech.edu.cn/callback"
      SUBMIT_VALUE = ""       # TIS/BB style, or "提交" for ehall apps
  # Done.

PATTERN 2 — CAS + secondary token handshake
─────────────────────────────────────────────
  class MyAuth(CASAuthorizer):
      BASE_URL = ...
      def _refresh(self):
          cookies = self._get_ticket_cookies(...)
          token = self._secondary_handshake(token)
          self._set_session(cookies)

PATTERN 3 — Dynamic SERVICE_URL (authcenter-mediated SSO)
──────────────────────────────────────────────────────────
  class MyAuth(CASAuthorizer):
      BASE_URL = ...
      def _refresh(self):
          dynamic_url = self._resolve_authcenter_url()
          self.SERVICE_URL = dynamic_url
          cookies = self._get_ticket_cookies(...)
          self._set_session(cookies)

RULES:
  ❌ Never override _get_ticket_cookies(). Override _refresh() instead.
  ❌ Never subclass Authorizer directly for a CAS service.

See ~/.hermes/skills/sustech-dev/SKILL.md § "Authorizer subclass design"
for the full reference with worked examples.
"""

# ── Public API ────────────────────────────────────────────────────────────────

from .authorizer import Authorizer, AuthorizerError, CAS_BASE, UA, register_auth, get_auth, require_auth
from .providers.cas import CASAuthorizer
from .providers.shibboleth import ShibbolethAuthorizer
from .providers.ws import WSProvider

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
    "PMSAuth",
    "register_auth",
    "get_auth",
    "require_auth",
    "ensured",
]


# ── Find skill root ──────────────────────────────────────────────────────────
from pathlib import Path as _Path
import requests as _requests

SKILL_ROOT = _Path(__file__).resolve().parent.parent.parent.parent


# =============================================================================
# TISAuth — Teaching Information System (CAS + XHR)
# =============================================================================

class TISAuth(CASAuthorizer):
    BASE_URL = "https://tis.sustech.edu.cn"
    SERVICE_URL = "https://tis.sustech.edu.cn/cas"
    XHR_MODE = True
    SUBMIT_VALUE = ""

    def _build_session(self) -> _requests.Session:
        """
        TIS needs a raw Cookie header (not cookie jar) because Set-Cookie
        semantics (Secure, HttpOnly, SameSite=None) are lost on re-set.
        """
        cookie_header = "; ".join(f"{k}={v}" for k, v in self._session_cache.items())
        sess = _requests.Session()
        sess.headers["User-Agent"] = UA
        sess.headers["Cookie"] = cookie_header
        if self.XHR_MODE:
            sess.headers["X-Requested-With"] = "XMLHttpRequest"
        return sess


# =============================================================================
# BBAuth — Blackboard Learn (CAS, resets cached courses on refresh)
# =============================================================================

class BBAuth(CASAuthorizer):
    BASE_URL = "https://bb.sustech.edu.cn"
    SERVICE_URL = "https://bb.sustech.edu.cn/webapps/bb-sso-BBLEARN/index.jsp"

    def _refresh(self) -> bool:
        ok = super()._refresh()
        if ok:
            self._reset_cached_data()
        return ok

    def login(self, *, headless: bool = False):
        ok = super().login(headless=headless)
        if ok:
            self._reset_cached_data()
        return ok

    def _reset_cached_data(self):
        """Delete cached course data so it gets refreshed on next access."""
        skill_bb = SKILL_ROOT / "bb"
        for f in (skill_bb / "courses.json", skill_bb / "structure.json"):
            if f.exists():
                f.unlink()

    def _build_session(self) -> _requests.Session:
        """BB cookies are scoped to .bb.sustech.edu.cn domain."""
        sess = _requests.Session()
        sess.headers["User-Agent"] = UA
        for name, value in self._session_cache.items():
            sess.cookies.set(name, value, domain=".bb.sustech.edu.cn", path="/")
        return sess


# =============================================================================
# LibAuth — SUSTech Library Primo (CAS + SSL legacy)
# =============================================================================

class LibAuth(CASAuthorizer):
    BASE_URL = "https://sustc.primo.exlibrisgroup.com.cn"
    SERVICE_URL = "https://sustc.primo.exlibrisgroup.com.cn/infra/casRedirect?ctx=/primaws"

    def _build_session(self):
        """Session with LegacyAdapter so Primo SSL works."""
        import ssl
        _OP_LEGACY = getattr(ssl, 'OP_LEGACY_SERVER_CONNECT', 0x4)
        legacy_ctx = ssl.create_default_context()
        legacy_ctx.options |= _OP_LEGACY

        from requests.adapters import HTTPAdapter

        class LegacyAdapter(HTTPAdapter):
            def init_poolmanager(self, *args, **kwargs):
                kwargs["ssl_context"] = legacy_ctx
                return super().init_poolmanager(*args, **kwargs)

        sess = _requests.Session()
        sess.mount("https://", LegacyAdapter())
        self._apply_cookies(sess, self._session_cache)
        return sess


# =============================================================================
# WSAuth — Student Exchange / Abroad Portal (ws.sustech.edu.cn)
# =============================================================================

class WSAuth(WSProvider):
    """Convenience subclass matching the TISAuth/BBAuth/LibAuth naming convention."""
    pass


# Register singletons for backwards compatibility
register_auth("tis", TISAuth(skill_dir=str(SKILL_ROOT)))
register_auth("bb", BBAuth(skill_dir=str(SKILL_ROOT)))
register_auth("lib", LibAuth(skill_dir=str(SKILL_ROOT)))
register_auth("ws", WSAuth(skill_dir=str(SKILL_ROOT)))


# Export ensured from Authorizer
ensured = Authorizer.ensured


# ── Auto-register external authlib services ────────────────────────────────────
from . import authlib  # noqa: F401
from .authlib.pms import PMSAuth as PMSAuth  # noqa: F401
