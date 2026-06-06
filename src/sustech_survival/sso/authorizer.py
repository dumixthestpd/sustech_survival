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
# Quick start:
#   from sustech_survival.sso import Authorizer, AuthorizerError
#   from sustech_survival.sso.providers.cas import CASAuthorizer
#   ok, reason = my_auth.check()
#   ok, reason = my_auth.ensure()
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

    Subclasses MUST define at minimum:
        BASE_URL    — the service's root URL
        SERVICE_URL — where the IdP/SSO redirects after auth

    Subclasses MAY define:
        SESSION_SUBDIR — subdirectory under skill_root for session files.
                          Default: "" (root)
        XHR_MODE        — add X-Requested-With header. Default: False
        REDIRECT_STATUS — tuple of valid redirect status codes. Default: (302, 303)

    Credentials:
        All authorizers read username + password from
        <skill_root>/credentials.txt (format: username:password).
        Access via auth.username / auth.password properties.

    Usage:
        auth = MyServiceAuth()
        ok, reason = auth.check()       # verify session
        ok, reason = auth.ensure()      # check + auto-refresh
        auth.refresh()                  # headless re-auth
        auth.login()                    # Playwright headful login
        cookies = auth.load()           # get saved cookie dict
    """

    BASE_URL: str = ""
    SERVICE_URL: str = ""
    XHR_MODE: bool = False
    REDIRECT_STATUS: tuple = (302, 303)
    SESSION_SUBDIR: str = ""  # subdirectory under skill_root for session files

    def __init__(self, *, skill_dir: Optional[str] = None, submodule_dir: Optional[str] = None):
        self.skill_dir = skill_dir
        self.submodule_dir = submodule_dir
        self.session_cache: dict = {}
        self.session_time: float = 0.0  # time.time() of last successful auth
        self.SESSION_TTL: int = 25 * 60  # 25 minutes — server-side session limit

    def resolve_skill_dir(self) -> Path:
        """Walk up from authorizer.py looking for credentials.txt to find skill root."""
        here = Path(__file__).resolve().parent  # sso/
        for parent in [here, here.parent, here.parent.parent, here.parent.parent.parent]:
            if (parent / "credentials.txt").exists():
                return parent
            if (parent / "sustech_survival").exists() and parent.name == "src":
                continue
        return here.parent.parent.parent

    # ── In-memory session (no disk) ─────────────────────────────────────────

    @property
    def cookies(self) -> dict:
        """
        Returns the raw in-memory cookie dict.
        Call ensure() first to validate — raises AuthorizerError if empty.
        """
        if not self.session_cache:
            raise AuthorizerError(
                f"[{self.__class__.__name__}] No session — call ensure() first"
            )
        return self.session_cache

    def set_session(self, cookies: dict):
        """Store cookies in memory + record timestamp. No disk writes."""
        self.session_cache = cookies
        import time
        self.session_time = time.time()

    def is_session_fresh(self) -> bool:
        """Check if in-memory session is still within TTL."""
        import time
        return (
            bool(self.session_cache)
            and (time.time() - self.session_time) < self.SESSION_TTL
        )

    # ── Paths ────────────────────────────────────────────────────────────────

    # Note: skill_dir and submodule_dir are plain attributes set in
    # __init__ via the resolve helpers. They are public because tests
    # (and the user's _skill_dir / _submodule_dir access patterns from
    # the old API) need to be able to override them. skill_root is
    # kept as a property alias for skill_dir (legacy callers expect
    # the property form).

    @property
    def skill_root(self) -> Path:
        # Coerce str→Path; fall back to upward search if unset
        if self.skill_dir:
            if isinstance(self.skill_dir, str):
                self.skill_dir = Path(self.skill_dir)
            return self.skill_dir
        self.skill_dir = self.resolve_skill_dir()
        return self.skill_dir

    @property
    def session_file(self) -> Path:
        # Coerce str→Path; compute from SESSION_SUBDIR if unset
        if not self.submodule_dir:
            if self.SESSION_SUBDIR:
                self.submodule_dir = self.skill_root / ".cache" / "sso" / self.SESSION_SUBDIR
            else:
                self.submodule_dir = self.skill_root / ".cache" / "sso"
        elif isinstance(self.submodule_dir, str):
            self.submodule_dir = Path(self.submodule_dir)
        return self.submodule_dir / "session.json"

    @property
    def creds_file(self) -> Path:
        return self.skill_root / "credentials.txt"

    @property
    def cas_url(self) -> str:
        encoded = quote(self.SERVICE_URL, safe="")
        return f"{getattr(self, 'IDP_CAS_BASE', CAS_BASE)}?service={encoded}"

    @property
    def domain(self) -> str:
        return urlparse(self.BASE_URL).netloc

    # ── Headers ──────────────────────────────────────────────────────────────

    @property
    def headers(self) -> dict:
        h = {"User-Agent": UA}
        if self.XHR_MODE:
            h["X-Requested-With"] = "XMLHttpRequest"
        return h

    # ── Credentials ─────────────────────────────────────────────────────────

    def read_creds(self) -> tuple[str, str]:
        """Read (username, password) from credentials.txt."""
        try:
            with open(self.creds_file) as f:
                line = f.read().strip()
        except FileNotFoundError:
            raise AuthorizerError(
                f"Credentials not found: {self.creds_file}\n"
                "Copy credentials.example.txt → credentials.txt and fill in."
            )
        if ':' not in line:
            raise AuthorizerError(f"Invalid format in {self.creds_file} (need username:password)")
        return line.split(':', 1)

    @property
    def username(self) -> str:
        """Short-cut for read_creds()[0]."""
        return self.read_creds()[0]

    @property
    def password(self) -> str:
        """Short-cut for read_creds()[1]."""
        return self.read_creds()[1]

    # ── Session I/O ──────────────────────────────────────────────────────────

    def load(self) -> dict:
        """
        Load session cookies from disk. DEPRECATED — session is in-memory
        only. Use ensure() + the cookies / requests_session property, or
        the @ensured decorator.

        For backwards compat: if the new hidden path is empty but a
        legacy visible path still has a session, it is auto-migrated
        to the new path on first access. After migration, callers
        can stop using load() entirely.
        """
        import warnings
        warnings.warn(
            "load() is deprecated — session is in-memory only. "
            "Use ensure() + .session property, or @ensured decorator.",
            DeprecationWarning,
            stacklevel=2,
        )

        # New hidden path takes priority
        if self.session_file.exists():
            with open(self.session_file) as f:
                return json.load(f)

        # Migration: try legacy visible paths
        legacy = self.legacy_session_paths()
        for p in legacy:
            if p.exists():
                with open(p) as f:
                    raw = json.load(f)
                # Copy to new path so the migration is a one-time event
                self.session_file.parent.mkdir(parents=True, exist_ok=True)
                with open(self.session_file, "w") as f:
                    json.dump(raw, f)
                return raw

        # Nothing found — raise so the caller can prompt re-login
        raise FileNotFoundError(
            f"No session for {self.__class__.__name__} — call {self.__class__.__name__}.refresh() or .login()"
        )

    def legacy_session_paths(self) -> list:
        """
        Return the legacy visible session paths this auth used to read/write
        before the move to <skill_root>/.cache/sso/<service>/session.json.

        Ordered: base-class default path first, then the sso/<service>/
        override path that subclasses used to ship. Callers iterate and
        pick the first one that exists.
        """
        sub = self.SESSION_SUBDIR
        if not sub:
            return []
        return [
            self.skill_root / sub / "session.json",          # base-class default
            self.skill_root / "sso" / sub / "session.json", # old override location
        ]

    def save(self, cookies: dict):
        import warnings
        warnings.warn(
            "save() is deprecated — session is in-memory only. "
            "Refresh keeps session in memory; no disk writes.",
            DeprecationWarning,
            stacklevel=2,
        )

    def cookies_for_requests(self, raw: dict) -> dict:
        return {k: v for k, v in raw.items()}

    def apply_cookies(self, sess: requests.Session, raw: dict):
        for k, v in raw.items():
            sess.cookies.set(k, v, domain=self.domain, path="/")

    # ── CAS ticket grinding (CASAuthorizer handles override) ───────────────────

    def get_ticket_cookies(self, username: str, password: str) -> dict:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement headless CAS auth. "
            "Use login() for browser-based auth."
        )

    # ── Session check (in-memory) ───────────────────────────────────────────

    @property
    def session(self) -> requests.Session:
        """
        DEPRECATED alias for `requests_session`. Use `requests_session` going forward.
        Returns a requests.Session pre-loaded with in-memory cookies.
        Call ensure() first or this will be empty.
        """
        import warnings
        warnings.warn(
            ".session is deprecated — use .requests_session instead",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.requests_session

    @property
    def requests_session(self) -> requests.Session:
        """
        A requests.Session pre-loaded with in-memory cookies and default headers.
        Call ensure() first to populate _session_cache.

        Subclasses (TISAuth, BBAuth) override this to add service-specific headers.
        """
        raw = self.session_cache
        sess = requests.Session()
        self.apply_cookies(sess, raw)
        return sess

    def check(self) -> tuple[bool, str]:
        """
        Verify in-memory session is valid. Auto-refreshes if expired.
        Returns (True, '') on success, (False, reason) on failure.

        The reason string is safe to surface to agents — it never
        includes cookie values, cookie names, session file paths, or
        raw exception details. Callers should display it verbatim.
        """
        cls = self.__class__.__name__
        # TTL check first — fast path for repeated calls within a CLI session
        if self.is_session_fresh():
            return True, ""

        # TTL expired: validate in-memory session with a server probe before
        # trusting it. This catches the case where CAS ticket expired server-side
        # before our local TTL.
        if self.session_cache:
            ok = self.probe_session()
            if ok:
                # Re-record timestamp so next calls use fast path
                import time
                self.session_time = time.time()
                return True, ""
            # Probe failed — fall through to refresh

        # Fall back to disk cache for backwards compat during transition
        if self.session_file.exists():
            try:
                with open(self.session_file) as f:
                    raw = json.load(f)
                self.set_session(raw)
                # Don't trust disk cache without probing
                ok = self.probe_session()
                if ok:
                    import time
                    self.session_time = time.time()
                    return True, ""
            except Exception:
                pass

        # No valid session — try headless refresh
        if self.refresh():
            return True, ""
        return False, (
            f"{cls} session expired, run {cls}.refresh() "
            f"(or {cls}.login() if refresh fails)"
        )

    def probe_session(self) -> bool:
        """
        Lightweight probe to check if current in-memory session is still valid.
        Subclasses override with a service-specific probe endpoint.
        Returns True if server accepts the session, False if 401/unauthorized.
        """
        try:
            sess = self.requests_session
            r = sess.get(f"{self.BASE_URL}/", timeout=5, allow_redirects=False)
            return r.status_code not in (401, 403)
        except Exception:
            return False

    def refresh(self) -> bool:
        """
        Re-authenticate using credentials.txt. Populates _session_cache in memory.
        Subclasses with headless support override get_ticket_cookies().

        Does NOT log cookie names — only the count — to avoid leaking
        which auth cookies are present.
        """
        try:
            username, password = self.read_creds()
        except AuthorizerError as e:
            print(f"❌ Auth refresh skipped: {e}")
            return False

        try:
            cookies = self.get_ticket_cookies(username, password)
            self.set_session(cookies)
            cls = self.__class__.__name__
            print(f"✅ {cls} session refreshed ({len(cookies)} cookies)")
            return True
        except (NotImplementedError, AuthorizerError) as e:
            print(f"❌ Auth refresh not supported: {e}")
            return False

    def ensure(self) -> tuple[bool, str]:
        """Check session, auto-refresh if expired. Returns (True, '') or (False, reason).

        The reason string is forwarded verbatim from check() and is safe to
        surface to agents — no cookie values, no cookie names, no file paths.
        """
        ok, reason = self.check()
        if ok:
            return True, ""
        # Strip the old 'credentials'/'no session' hint logic: the new check()
        # message already tells the agent which method to call.
        return False, reason

    def login(self, *, headless: bool = False):
        """Playwright headful login — stores cookies in memory only."""
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            ctx = browser.new_context()
            page = ctx.new_page()
            page.goto(self.cas_url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(1000)

            # Detect captcha — tell caller to use refresh() instead
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
            self.set_session(cookies)
            cls = self.__class__.__name__
            print(f"✅ {cls} login complete ({len(cookies)} cookies)")
            return True

    # ── @ensured decorator ───────────────────────────────────────────────────

    def ensured(self, func: Callable) -> Callable:
        """
        Decorator: validates session before call AND injects cookies as a kwarg.

        Usage:
            @bb_auth.ensured
            def download_content(content_id, session=None, **kwargs):
                # session is a validated dict — ready to pass to requests
                r = requests.get(url, cookies=session)

        The decorated function receives 'session=<cookie_dict>' in kwargs,
        which overwrites any caller-provided 'session' argument.
        """
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            ok, reason = self.ensure()
            if not ok:
                raise AuthorizerError(f"[{self.__class__.__name__}] {reason}")
            kwargs["session"] = self.cookies
            return func(*args, **kwargs)
        return wrapper


# ── Auth registry & decorator ─────────────────────────────────────────────────

_auth_registry: dict[str, Authorizer] = {}


def register_auth(name: str, auth: Authorizer):
    """Register an Authorizer singleton by service name."""
    _auth_registry[name] = auth


def get_auth(name: str) -> Authorizer:
    """
    Get or create an Authorizer by service name.

    DEPRECATED — import the auth class directly instead:
        from sustech_survival.sso import TISAuth

    This function exists only for backwards compatibility with existing code.
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


def require_auth(service: str) -> Callable:
    """
    Decorator: ensures Authorizer.ensure() passes before the wrapped function runs.

    Usage:
        @require_auth("bb")
        def download_content(content_id, out_dir=None):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            auth = _auth_registry.get(service)
            if auth is None:
                raise AuthorizerError(f"No Authorizer registered for service '{service}'")
            ok, reason = auth.ensure()
            if not ok:
                raise AuthorizerError(f"Auth failed for {service}: {reason}")
            return func(*args, **kwargs)
        return wrapper
    return decorator
