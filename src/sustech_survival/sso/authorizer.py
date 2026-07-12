# =============================================================================
# SSO — Generic Authentication Framework
# =============================================================================
#   sso/
#     authorizer.py   — Authorizer base class + error types + registry
#     providers/
#       cas.py        — CAS (Central Authentication Service) v3.0
#       shibboleth.py — Shibboleth SP (Service Provider) via WAYF/DS
#     authlib/
#       __init__.py   — TISAuth, BBAuth, LibAuth (CAS headless)
#       wos.py        — Web of Science (Shibboleth)
#       rsc.py        — Royal Society of Chemistry
#       cnki.py       — CNKI
#       ...           — ieee, jstor, pubmed, acs, wiley, springer, scopus
#
# Authorizer is the only import you need. It hides all HTTP:
#
#   from sustech_survival.sso import TISAuth
#
#   auth = TISAuth()
#   ok, msg = auth.ensure()
#   if ok:
#       data = auth.get("/component/queryKsxxByXs").json()
#
# No raw cookies, no headers, no URL concatenation, no requests_session.
# =============================================================================

import json
import functools
import requests
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import quote, urlparse
from abc import ABC

from sustech_survival.exceptions import (
    InvalidCredentials,
    NetworkError,
    SessionExpired,
)

__all__ = [
    "Authorizer",
    "AuthorizerError",
    "register_auth",
    "require_auth",
    "CAS_BASE",
    "UA",
]


# ── Constants ────────────────────────────────────────────────────────────────

CAS_BASE = "https://cas.sustech.edu.cn/cas/login"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


# ── Exceptions ────────────────────────────────────────────────────────────────

class AuthorizerError(Exception):
    """Raised when auth fails."""


# ── Authorizer ───────────────────────────────────────────────────────────────

class Authorizer(ABC):
    """
    Abstract base for service-specific authentication handlers.

    Subclasses MUST define:
        BASE_URL    — the service's root URL (e.g. "https://tis.sustech.edu.cn")
        SERVICE_URL — where the IdP/SSO redirects after auth

    Credentials: read from credentials.txt (format: username:password).
    Resolution: SUSTECH_CREDENTIALS env var →
    ~/.config/sustech-survival/credentials.txt →
    ./credentials.txt → walk-up from package source.
    Access via auth.username / auth.password.

    Usage::

        auth = MyServiceAuth()
        ok, reason = auth.ensure()       # check + auto-refresh
        data = auth.get("/api/endpoint")  # GET, auto-detects stale session
        result = auth.post("/api/data")   # POST, auto-refreshes if needed
        r = auth.session.get("https://other-domain/api")  # raw session

    ``get()`` and ``post()`` transparently detect stale-session responses:
    HTTP 401, 302/303 redirect to CAS, or a response URL on
    ``cas.sustech.edu.cn``. On detection they refresh the CAS login once
    and retry. If refresh fails, they raise ``InvalidCredentials`` (wrong
    password), ``NetworkError`` (CAS down), or ``AuthorizerError`` (generic).

    ``ensure()`` → ``(True, '')`` on success, ``(False, reason)`` on failure
    where *reason* distinguishes the three failure types.

    No disk I/O. No cookie juggling. No header assembly.
    """

    BASE_URL: str = ""
    SERVICE_URL: str = ""
    XHR_MODE: bool = False
    REDIRECT_STATUS: tuple = (302, 303)

    # Per-subclass singleton cache. Each Authorizer subclass (BBAuth, TISAuth,
    # LibAuth, etc.) gets one shared instance so that ``TISAuth()`` from any
    # call site returns the same in-memory session.
    _instances: dict = {}

    def __new__(cls, *args, **kwargs):
        if cls not in Authorizer._instances:
            Authorizer._instances[cls] = super().__new__(cls)
        return Authorizer._instances[cls]

    def __init__(self, *, skill_dir: Optional[str] = None):
        if getattr(self, "_initialized", False):
            if skill_dir is not None and getattr(self, "skill_dir", None) != skill_dir:
                self._initialized = False
            else:
                return
        object.__setattr__(self, "skill_dir", skill_dir)
        self._session_cache: dict = {}
        self._session_time: float = 0.0
        self._session_ttl: int = 25 * 60  # 25 minutes — server-side session limit
        self._cached_session: Optional[requests.Session] = None
        self._last_refresh_error: Optional[Exception] = None
        self._initialized = True

    # ── Public API — no HTTP leak ─────────────────────────────────────────

    def get(self, path: str, **kwargs) -> requests.Response:
        """GET path relative to BASE_URL. Cookies, headers, UA already set.

        Auto-detects stale-session responses (override ``_is_stale_response()``
        per subclass): refreshes cookies once and retries the request transparently.
        Raises ``InvalidCredentials`` or ``NetworkError`` if refresh fails.
        """
        url = self._url(path)
        response = self.session.get(url, **kwargs)
        if self._is_stale_response(response):
            if self._refresh():
                response = self.session.get(url, **kwargs)
            else:
                self._raise_last_error()
        return response

    def post(self, path: str, **kwargs) -> requests.Response:
        """POST path relative to BASE_URL. Same stale-detection as ``get()``."""
        url = self._url(path)
        response = self.session.post(url, **kwargs)
        if self._is_stale_response(response):
            if self._refresh():
                response = self.session.post(url, **kwargs)
            else:
                self._raise_last_error()
        return response

    def _is_stale_response(self, response: requests.Response) -> bool:
        """Universal stale-session detection for all SUSTech CAS services.

        Returns ``True`` when the response indicates the session has expired
        or been revoked. Two universal signals are checked:

        1. **302/303 with Location → CAS** — direct redirect to the SUSTech
           CAS login page (TIS, Lib, WS, Booking, PMS, and any CAS-fronted
           service).
        2. **Final URL contains CAS** — ``requests`` follows the redirect, so
           the final ``response.url`` contains ``cas.sustech.edu.cn``.

        Subclasses may add service-specific checks — e.g. ``BBAuth`` also
        checks ``HTTP 401`` because BB's REST API returns this instead of a
        redirect. (Do NOT use 401 universally — some services return it for
        off-campus network issues, not session expiry.)
        """
        # Signal 1: redirect to CAS login (before follow)
        if response.status_code in self.REDIRECT_STATUS:
            loc = (response.headers.get("Location") or "").lower()
            if "cas.sustech.edu.cn" in loc:
                return True
        # Signal 2: redirect was already followed, final URL is on CAS
        if "cas.sustech.edu.cn" in (response.url or "").lower():
            return True
        return False

    def _raise_last_error(self):
        """Raise the last stored refresh error, or a generic one if unknown."""
        err = self._last_refresh_error
        if isinstance(err, (InvalidCredentials, NetworkError, AuthorizerError)):
            raise err
        raise AuthorizerError(
            f"[{self.__class__.__name__}] Session refresh failed (unknown reason)"
        )

    def _refresh_error_message(self) -> str:
        """Human-readable failure reason based on ``_last_refresh_error``."""
        cls = self.__class__.__name__
        err = self._last_refresh_error
        if isinstance(err, InvalidCredentials):
            return f"{cls}: credentials invalid — check credentials.txt"
        if isinstance(err, NetworkError):
            return f"{cls}: network error — {err}"
        if isinstance(err, AuthorizerError):
            return f"{cls}: {err}"
        return (
            f"{cls} session not available — "
            "ensure credentials.txt exists and CAS is reachable"
        )

    def ensure(self) -> tuple[bool, str]:
        """Check session, auto-refresh if expired. Returns (True, '') or (False, reason)."""
        return self.check()

    def check(self) -> tuple[bool, str]:
        """Verify in-memory session is valid. Auto-refreshes if expired.

        Return value is ``(True, '')`` on success, or ``(False, reason)`` where
        *reason* distinguishes ``credentials invalid``, ``network error``, and
        generic failure.
        """
        cls = self.__class__.__name__

        # Fast path: session within TTL
        if self._is_session_fresh():
            return True, ""

        # Session exists but TTL expired — refresh
        if self._session_cache:
            if self._refresh():
                return True, ""
            return False, self._refresh_error_message()

        # No session at all — try fresh auth
        if self._refresh():
            return True, ""

        return False, self._refresh_error_message()

    # ── Session (the requests.Session with cookies + headers) ────────────

    def _is_session_fresh(self) -> bool:
        import time
        return (
            bool(self._session_cache)
            and (time.time() - self._session_time) < self._session_ttl
        )

    @property
    def session(self) -> requests.Session:
        """
        A requests.Session with cookies, headers, and UA already configured.
        Call ensure() first to populate the session cache.
        """
        if not self._session_cache:
            raise AuthorizerError(
                f"[{self.__class__.__name__}] No session — call ensure() first"
            )
        return self._build_session()

    def _build_session(self) -> requests.Session:
        """Build a fresh requests.Session from cached cookies. Subclasses override."""
        sess = requests.Session()
        self._apply_cookies(sess, self._session_cache)
        return sess

    def _apply_cookies(self, sess: requests.Session, raw: dict):
        for k, v in raw.items():
            sess.cookies.set(k, v, domain=self._domain, path="/")

    @property
    def _domain(self) -> str:
        return urlparse(self.BASE_URL).netloc

    def _url(self, path: str) -> str:
        """Prepend BASE_URL to a relative path."""
        if path.startswith("http://") or path.startswith("https://"):
            return path  # absolute URL passed through
        base = self.BASE_URL.rstrip("/")
        path = path.lstrip("/")
        return f"{base}/{path}"

    # ── Auth lifecycle ───────────────────────────────────────────────────

    def refresh(self) -> bool:
        """Force a fresh CAS login using stored credentials.

        Reads ``credentials.txt``, grinds a new CAS ticket, and stores the
        result in memory.  Returns True on success.

        Subclasses that support headless auth override ``_get_ticket_cookies()``.
        """
        return self._refresh()

    def _refresh(self) -> bool:
        """
        Authenticate using credentials.txt. Populates _session_cache in memory.

        Returns ``True`` on success. On failure, stores the typed exception in
        ``_last_refresh_error`` (``InvalidCredentials``, ``NetworkError``, or
        ``AuthorizerError``) and returns ``False``.

        Subclasses with headless support override ``_get_ticket_cookies()``.
        Callers that need the error type should read ``_last_refresh_error``
        after a ``False`` return.
        """
        self._last_refresh_error = None
        try:
            username, password = self._read_creds()
        except AuthorizerError as e:
            self._last_refresh_error = InvalidCredentials(str(e))
            print(f"❌ Auth refresh skipped: {e}")
            return False
        try:
            cookies = self._get_ticket_cookies(username, password)
            self._set_session(cookies)
            self._cached_session = None  # invalidate stale session object
            cls = self.__class__.__name__
            print(f"✅ {cls} session refreshed ({len(cookies)} cookies)")
            return True
        except InvalidCredentials as e:
            self._last_refresh_error = e
            print(f"❌ {self.__class__.__name__} credentials rejected")
            return False
        except NetworkError as e:
            self._last_refresh_error = e
            print(f"❌ {self.__class__.__name__} network error: {e}")
            return False
        except NotImplementedError as e:
            self._last_refresh_error = AuthorizerError(str(e))
            print(f"❌ {self.__class__.__name__} auth not supported: {e}")
            return False
        except AuthorizerError as e:
            self._last_refresh_error = e
            print(f"❌ {self.__class__.__name__} auth failed: {e}")
            return False

    def _set_session(self, cookies: dict):
        """Store cookies in memory + record timestamp. No disk."""
        self._session_cache = cookies
        import time
        self._session_time = time.time()

    def _get_ticket_cookies(self, username: str, password: str) -> dict:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement headless auth. "
            "Use login() for browser-based auth."
        )

    # ── Headers ──────────────────────────────────────────────────────────────

    @property
    def _headers(self) -> dict:
        h = {"User-Agent": UA}
        if self.XHR_MODE:
            h["X-Requested-With"] = "XMLHttpRequest"
        return h

    # ── Credentials ─────────────────────────────────────────────────────────

    def _read_creds(self) -> tuple[str, str]:
        try:
            with open(self._creds_file) as f:
                line = f.read().strip()
        except FileNotFoundError:
            raise AuthorizerError(
                f"Credentials not found at {self._creds_file}\n"
                "Set SUSTECH_CREDENTIALS env var, or create "
                "~/.config/sustech-survival/credentials.txt (format: sid:password)"
            )
        if ':' not in line:
            raise AuthorizerError(f"Invalid format in {self._creds_file} (need username:password)")
        return line.split(':', 1)

    def _resolve_creds_file(self) -> Path:
        """Resolve credentials.txt location.

        Search order (first match wins):
          1. ``SUSTECH_CREDENTIALS`` env var — explicit path to a credentials file
          2. ``~/.config/sustech-survival/credentials.txt`` — XDG-style user config
          3. ``./credentials.txt`` — current working directory
          4. Walk up from this file looking for ``credentials.txt`` — dev/editable installs
        """
        import os

        # 1. Env var — explicit override
        env_path = os.environ.get("SUSTECH_CREDENTIALS")
        if env_path:
            return Path(env_path)

        # 2. XDG user config
        xdg = Path.home() / ".config" / "sustech-survival" / "credentials.txt"
        if xdg.exists():
            return xdg

        # 3. CWD
        cwd_creds = Path.cwd() / "credentials.txt"
        if cwd_creds.exists():
            return cwd_creds

        # 4. Walk up from package source (editable installs / dev tree)
        here = Path(__file__).resolve().parent
        for parent in [here, here.parent, here.parent.parent, here.parent.parent.parent]:
            if (parent / "credentials.txt").exists():
                return parent / "credentials.txt"

        # Default: XDG path (even if it doesn't exist yet — error message will guide)
        return xdg

    @property
    def _creds_file(self) -> Path:
        if self.skill_dir:
            if isinstance(self.skill_dir, str):
                self.skill_dir = Path(self.skill_dir)
            return self.skill_dir / "credentials.txt"
        return self._resolve_creds_file()

    def read_creds(self) -> tuple[str, str]:
        """Public wrapper for _read_creds (backward compat)."""
        return self._read_creds()

    @property
    def username(self) -> str:
        return self._read_creds()[0]

    @property
    def password(self) -> str:
        return self._read_creds()[1]

    # ── CAS URL ──────────────────────────────────────────────────────────────

    @property
    def _cas_url(self) -> str:
        encoded = quote(self.SERVICE_URL, safe="")
        return f"{getattr(self, '_idp_cas_base', CAS_BASE)}?service={encoded}"

    # ── Login (Playwright headful) ─────────────────────────────────────────

    def login(self, *, headless: bool = False):
        """Playwright headful login — stores cookies in memory only."""
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            ctx = browser.new_context()
            page = ctx.new_page()
            page.goto(self._cas_url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(1000)

            captcha = page.query_selector('[id*="captcha"], .g-recaptcha, [src*="captcha"]')
            if captcha:
                print("⚠️  Captcha detected at CAS page — use ensure() / refresh() instead")
                browser.close()
                return False

            print(f"Browser opened — log in via CAS for {self.BASE_URL}")
            print("Waiting for redirect...")
            try:
                page.wait_for_url(f"**/{self.BASE_URL}**", timeout=0)
            except Exception:
                pass
            page.wait_for_timeout(2000)
            cookies = {c['name']: c['value'] for c in ctx.cookies()}
            self._set_session(cookies)
            cls = self.__class__.__name__
            print(f"✅ {cls} login complete ({len(cookies)} cookies)")
            return True

    # ── @ensured decorator ───────────────────────────────────────────────────

    def ensured(self, func: Callable) -> Callable:
        """
        Decorator: validates session before call AND injects Authorizer as 'auth' kwarg.
        """
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            ok, reason = self.ensure()
            if not ok:
                raise AuthorizerError(f"[{self.__class__.__name__}] {reason}")
            kwargs["auth"] = self
            return func(*args, **kwargs)
        return wrapper


# ── Auth registry ─────────────────────────────────────────────────────────────
# register_auth() is a no-op shim kept for backward compatibility.
# Authorizer subclasses are already singletons via __new__, so the old
# string-keyed registry is unnecessary. Import the class directly:
#   from sustech_survival.sso import TISAuth
#   auth = TISAuth()        # singleton — same instance everywhere


def register_auth(name: str, auth: "Authorizer") -> None:
    """No-op — Authorizer subclasses are singletons via __new__.

    Previously registered instances in a global dict for get_auth() lookup.
    That dict is removed. This function remains as a no-op so existing
    authlib modules don't break on import.
    """
    pass


def require_auth(auth_class: type) -> Callable:
    """
    Decorator: ensures Authorizer.ensure() passes, injects Authorizer as 'auth' kwarg.

    Usage:
        @require_auth(TISAuth)
        def fetch_exams(self, course_id, auth=None):
            data = auth.get("/component/queryKsxxByXs").json()

    The 'auth' kwarg receives the Authorizer instance (singleton per class).
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            auth = auth_class()
            ok, reason = auth.ensure()
            if not ok:
                raise AuthorizerError(f"[{auth_class.__name__}] {reason}")
            kwargs.setdefault("auth", auth)
            return func(*args, **kwargs)
        return wrapper
    return decorator
