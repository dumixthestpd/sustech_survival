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
    "Credentials",      # backwards compat — redirects to Authorizer.username/password
    "register_auth",
    "get_auth",
    "require_auth",
    "ensured",
]

# Backwards-compat shim: Credentials was merged into Authorizer.
Credentials = Authorizer


# ── Find skill root for session storage ────────────────────────────────────────
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
    def requests_session(self) -> _requests.Session:
        """
        A requests.Session with current in-memory cookies and TIS-required headers.

        Cookie header is set directly (not via cookie jar) because the original
        Set-Cookie semantics (Secure, HttpOnly, SameSite=None) are lost when
        cookies are re-set via sess.cookies.set() in a fresh session — causing
        the server to reject them. Setting the raw Cookie header reproduces the
        working browser behavior.

        User-Agent MUST match the browser UA used during CAS login (TIS validates
        that the session's User-Agent is consistent with the one that obtained
        the cookies — python-requests UA gets 403).
        """
        cookie_header = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        sess = _requests.Session()
        sess.headers["User-Agent"] = UA
        sess.headers["Cookie"] = cookie_header
        if self.XHR_MODE:
            sess.headers["X-Requested-With"] = "XMLHttpRequest"
        return sess

    @property
    def session_file(self):
        return _SKILL_ROOT / "sso" / "tis" / "session.json"

    def _probe_session(self) -> bool:
        """
        TIS-specific probe: use a lightweight API call instead of root URL.
        The TIS root URL returns 200 even without auth (redirects to login page).
        """
        try:
            sess = self.requests_session
            r = sess.get(
                f"{self.BASE_URL}/personnelEvaluation/listObtainPersonnelEvaluationTasks",
                params={"yhdm": self.username, "rwmc": "", "sfyp": "0", "pageNum": "1", "pageSize": "1"},
                timeout=5,
            )
            return r.status_code == 200
        except Exception:
            return False


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

    @property
    def requests_session(self) -> _requests.Session:
        """
        A requests.Session with current in-memory BB cookies and the correct User-Agent.

        Cookies are attached to the .bb.sustech.edu.cn domain, matching the browser
        behavior that BB expects.
        """
        sess = _requests.Session()
        sess.headers["User-Agent"] = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        for name, value in self.cookies.items():
            sess.cookies.set(name, value, domain=".bb.sustech.edu.cn", path="/")
        return sess


# =============================================================================
# LibAuth — SUSTech Library Primo (CAS)
# =============================================================================

class LibAuth(CASAuthorizer):
    BASE_URL = "https://sustc.primo.exlibrisgroup.com.cn"
    SERVICE_URL = "https://sustc.primo.exlibrisgroup.com.cn/infra/casRedirect?ctx=/primaws"
    SESSION_SUBDIR = "lib"

    @property
    def session_file(self):
        return self.submodule_dir / "session.json"

    @property
    def requests_session(self):
        """
        A requests.Session with in-memory cookies + LegacyAdapter so Primo SSL works.
        """
        import ssl
        _OP_LEGACY = getattr(ssl, 'OP_LEGACY_SERVER_CONNECT', 0x4)
        legacy_ctx = ssl.create_default_context()
        legacy_ctx.options |= _OP_LEGACY

        from requests.adapters import HTTPAdapter
        from requests.adapters import (
            _urllib3_request_context, prepend_scheme_if_needed,
            select_proxy, parse_url
        )

        class LegacyAdapter(HTTPAdapter):
            def get_connection_with_tls_context(
                self, request, verify, proxies=None, cert=None, poolmanager=None
            ):
                proxy = select_proxy(request.url, proxies)
                host_params, pool_kwargs = _urllib3_request_context(
                    request, verify, cert, self.poolmanager,
                )
                pool_kwargs["ssl_context"] = legacy_ctx
                pool_kwargs["ssl_context"].check_hostname = False
                if proxy:
                    proxy = prepend_scheme_if_needed(proxy, "http")
                    proxy_url = parse_url(proxy)
                    if not proxy_url.host:
                        from requests.exceptions import InvalidProxyURL
                        raise InvalidProxyURL("Malformed proxy URL")
                    proxy_manager = self.proxy_manager_for(proxy)
                    return proxy_manager.connection_from_host(**host_params, pool_kwargs=pool_kwargs)
                return self.poolmanager.connection_from_host(**host_params, pool_kwargs=pool_kwargs)

        sess = _requests.Session()
        sess.mount("https://", LegacyAdapter())
        self._apply_cookies(sess, self.cookies)
        return sess


# =============================================================================
# WSAuth — Student Exchange / Abroad Portal (ws.sustech.edu.cn)
# =============================================================================

class WSAuth(WSProvider):
    """
    Convenience subclass of WSProvider matching the naming convention of
    TISAuth, BBAuth, LibAuth.  Use ``WSAuth()`` or ``get_auth("ws")``.
    """
    pass


# Register singletons for backwards compatibility with get_auth()
register_auth("tis", TISAuth(skill_dir=str(_SKILL_ROOT)))
register_auth("bb", BBAuth(skill_dir=str(_SKILL_ROOT)))
register_auth("lib", LibAuth(skill_dir=str(_SKILL_ROOT)))
register_auth("ws", WSAuth(skill_dir=str(_SKILL_ROOT)))


# Export ensured from Authorizer
ensured = Authorizer.ensured


# ── Auto-register external authlib services ────────────────────────────────────
# Importing authlib triggers lazy-loading of external services (wos, rsc, etc.)
from . import authlib  # noqa: F401
