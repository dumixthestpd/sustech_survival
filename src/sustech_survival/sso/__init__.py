"""
sustech_survival.sso — Unified SSO across SUSTech ecosystem.

----------------------------------------------------------------------
 Authorizer subclass patterns — READ BEFORE BUILDING A NEW SERVICE
----------------------------------------------------------------------

All CAS services authenticate via one of three patterns. Choose the
right one before writing a single line of auth code.

PATTERN 1 — Static SERVICE_URL (most services)
-----------------------------------------------
  class MyAuth(CASAuthorizer):
      BASE_URL = "https://service.sustech.edu.cn"
      SERVICE_URL = "https://service.sustech.edu.cn/callback"
      SUBMIT_VALUE = ""       # TIS/BB style, or "提交" for ehall apps
  # Done.

PATTERN 2 — CAS + secondary token handshake
---------------------------------------------
  class MyAuth(CASAuthorizer):
      BASE_URL = ...
      def _refresh(self):
          cookies = self._get_ticket_cookies(...)
          token = self._secondary_handshake(token)
          self._set_session(cookies)

PATTERN 3 — Dynamic SERVICE_URL (authcenter-mediated SSO)
----------------------------------------------------------
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

See ``sustech_survival.sso.authorizer.Authorizer`` for the base class API
and the ``CASAuthorizer``/``ShibbolethAuthorizer`` subclasses for worked
examples of each pattern.
"""

# -- Public API ----------------------------------------------------------------

from .authorizer import (
    Authorizer, AuthorizerError, CAS_BASE, UA, require_auth,
    cred_set, cred_clear,
    resolve_creds_path, write_credentials, read_credentials,
)
from .providers.cas import CASAuthorizer
from .providers.shibboleth import ShibbolethAuthorizer
from .providers.wifi import WiFiAuth
from .providers.ws import WSProvider

__all__ = [
    "Authorizer",
    "AuthorizerError",
    "CAS_BASE",
    "UA",
    "CASAuthorizer",
    "ShibbolethAuthorizer",
    "WiFiAuth",
    "TISAuth",
    "BBAuth",
    "LibAuth",
    "PMSAuth",
    "require_auth",
    "ensured",
    "cred_set",
    "cred_clear",
    "resolve_creds_path",
    "write_credentials",
    "read_credentials",
]


# -- Find skill root ----------------------------------------------------------
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

    # Uniform minimum interval (seconds) between TIS requests.
    # TIS rate-lips rapid successive calls ("查询请求频率过高").
    # Enforced here at the session owner so every caller is throttled
    # automatically — no per-call-site sleeps or wrappers needed.
    REQUEST_INTERVAL = 0.5
    _last_request_at: float = 0.0

    def _throttle(self) -> None:
        import time as _time
        if self.REQUEST_INTERVAL > 0:
            elapsed = _time.monotonic() - type(self)._last_request_at
            if elapsed < self.REQUEST_INTERVAL:
                _time.sleep(self.REQUEST_INTERVAL - elapsed)
        type(self)._last_request_at = _time.monotonic()

    def get(self, path: str, **kwargs) -> _requests.Response:
        self._throttle()
        return super().get(path, **kwargs)

    def post(self, path: str, **kwargs) -> _requests.Response:
        self._throttle()
        return super().post(path, **kwargs)

    def _is_stale_response(self, response: _requests.Response) -> bool:
        """Detect expired TIS session.

        Signal 1: Non-XHR endpoints redirect to CAS login (302/303).
        Signal 2: XHR endpoints return the CAS login page as HTML when
        the session is dead (Content-Type: text/html instead of JSON).
        """
        if response.status_code in self.REDIRECT_STATUS:
            loc = response.headers.get("Location", "")
            if "cas.sustech.edu.cn" in loc:
                return True
        ct = response.headers.get("Content-Type", "")
        if ct and "text/html" in ct:
            snippet = getattr(response, "text", "")[:1000].lower()
            if "统一身份认证" in snippet or "cas/login" in snippet:
                return True
        return False

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

    def _is_stale_response(self, response: _requests.Response) -> bool:
        """BB REST API returns HTTP 401 when the session is expired."""
        return response.status_code == 401

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
        """Session with SSL context that tolerates Primo's ancient TLS."""
        import ssl
        _OP_LEGACY = getattr(ssl, 'OP_LEGACY_SERVER_CONNECT', 0x4)
        legacy_ctx = ssl.create_default_context()
        legacy_ctx.options |= _OP_LEGACY
        legacy_ctx.check_hostname = False
        legacy_ctx.verify_mode = ssl.CERT_NONE

        from requests.adapters import HTTPAdapter

        class LegacyAdapter(HTTPAdapter):
            def init_poolmanager(self, *args, **kwargs):
                kwargs["ssl_context"] = legacy_ctx
                return super().init_poolmanager(*args, **kwargs)

            def get_connection_with_tls_context(
                self, request, verify, proxies=None, cert=None
            ):
                return super().get_connection_with_tls_context(
                    request, verify=False, proxies=proxies, cert=cert
                )

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


# Export ensured from Authorizer
ensured = Authorizer.ensured


# -- Auto-register external authlib services ------------------------------------
# PMSAuth needs pycryptodome (optional dep). Lazy-import so the SSO
# package doesn't hard-fail without it.
from . import authlib  # noqa: F401
def __getattr__(name):
    if name == "PMSAuth":
        from .authlib.pms import PMSAuth as _PMSAuth
        return _PMSAuth
    raise AttributeError(name)
