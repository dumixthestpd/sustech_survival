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

__all__ = [
    "Authorizer",
    "AuthorizerError",
    "register_auth",
    "get_auth",
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

    Credentials: read from <skill_root>/credentials.txt (format: username:password).
    Access via auth.username / auth.password properties.

    Usage:
        auth = MyServiceAuth()
        ok, reason = auth.ensure()       # check + auto-refresh
        data = auth.get("/api/endpoint")  # GET, BASE_URL prepended automatically
        result = auth.post("/api/data", json={"key": "value"})
        # Or raw session for full control:
        r = auth.session.get("https://other-domain/api")

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
        self._initialized = True

    # ── Public API — no HTTP leak ─────────────────────────────────────────

    def get(self, path: str, **kwargs) -> requests.Response:
        """GET path relative to BASE_URL. Cookies, headers, UA already set."""
        return self.session.get(self._url(path), **kwargs)

    def post(self, path: str, **kwargs) -> requests.Response:
        """POST path relative to BASE_URL. Cookies, headers, UA already set."""
        return self.session.post(self._url(path), **kwargs)

    def ensure(self) -> tuple[bool, str]:
        """Check session, auto-refresh if expired. Returns (True, '') or (False, reason)."""
        ok, reason = self.check()
        if ok:
            return True, ""
        return False, reason

    def check(self) -> tuple[bool, str]:
        """Verify in-memory session is valid. Auto-refreshes if expired."""
        cls = self.__class__.__name__

        # Fast path: session within TTL
        if self._is_session_fresh():
            return True, ""

        # Session exists but TTL expired — refresh
        if self._session_cache:
            return self._refresh(), ""

        # No session at all — try fresh auth
        if self._refresh():
            return True, ""

        return False, (
            f"{cls} session not available — ensure credentials.txt exists and CAS is reachable"
        )

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

    @property
    def requests_session(self) -> requests.Session:
        """DEPRECATED — use .session instead."""
        import warnings
        warnings.warn(
            ".requests_session is deprecated — use .session instead",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.session

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

    def _refresh(self) -> bool:
        """
        Authenticate using credentials.txt. Populates _session_cache in memory.
        Subclasses with headless support override _get_ticket_cookies().
        """
        try:
            username, password = self._read_creds()
        except AuthorizerError as e:
            print(f"❌ Auth refresh skipped: {e}")
            return False
        try:
            cookies = self._get_ticket_cookies(username, password)
            self._set_session(cookies)
            self._cached_session = None  # invalidate stale session object
            cls = self.__class__.__name__
            print(f"✅ {cls} session refreshed ({len(cookies)} cookies)")
            return True
        except (NotImplementedError, AuthorizerError) as e:
            print(f"❌ Auth refresh not supported: {e}")
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
                f"Credentials not found: {self._creds_file}\n"
                "Copy credentials.example.txt → credentials.txt and fill in."
            )
        if ':' not in line:
            raise AuthorizerError(f"Invalid format in {self._creds_file} (need username:password)")
        return line.split(':', 1)

    def _resolve_skill_dir(self) -> Path:
        """Walk up looking for credentials.txt."""
        here = Path(__file__).resolve().parent
        for parent in [here, here.parent, here.parent.parent, here.parent.parent.parent]:
            if (parent / "credentials.txt").exists():
                return parent
            if (parent / "sustech_survival").exists() and parent.name == "src":
                continue
        return here.parent.parent.parent

    @property
    def _creds_file(self) -> Path:
        if self.skill_dir:
            if isinstance(self.skill_dir, str):
                self.skill_dir = Path(self.skill_dir)
            return self.skill_dir / "credentials.txt"
        self.skill_dir = self._resolve_skill_dir()
        return self.skill_dir / "credentials.txt"

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


# ── Auth registry (DEPRECATED — use class-based @require_auth instead) ───────

_auth_registry: dict[str, Authorizer] = {}


def register_auth(name: str, auth: Authorizer):
    """Register an Authorizer singleton by service name. DEPRECATED."""
    import warnings
    warnings.warn(
        "register_auth() is deprecated — use @require_auth(ClassName) instead",
        DeprecationWarning,
        stacklevel=2,
    )
    _auth_registry[name] = auth


def get_auth(name: str) -> Authorizer:
    """
    Get an Authorizer by service name. DEPRECATED.

    Import the auth class directly instead:
        from sustech_survival.sso import TISAuth
    """
    import warnings
    from sustech_survival.sso import TISAuth, BBAuth, LibAuth

    _class_map = {"bb": BBAuth, "tis": TISAuth, "lib": LibAuth}
    cls = _class_map.get(name)
    if cls is None:
        raise AuthorizerError(
            f"Unknown service {name!r}. Known: {list(_class_map.keys())}. "
            "Import the auth class directly: from sustech_survival.sso import TISAuth"
        )
    warnings.warn(
        f"get_auth({name!r}) is deprecated — use {cls.__name__}() directly instead",
        DeprecationWarning,
        stacklevel=2,
    )
    return cls()


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
