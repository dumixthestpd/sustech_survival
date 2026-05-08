# =============================================================================
# SSO — Shared CAS Authentication for SUSTech Services
# =============================================================================
# Single login/refresh/check module used by bb, tis, and lib.
#
# Usage:
#   from sso import Authorizer, require_auth
#
#   auth = BBAuthorizer()    # per-service singleton
#   @require_auth("bb")
#   def download_content(...):
#       ...
# =============================================================================

import json
import re
import sys
import functools
import requests
from pathlib import Path
from typing import Callable, Optional

__all__ = ["Authorizer", "AuthorizerError", "require_auth", "CAS_BASE", "UA"]


# ── Constants ────────────────────────────────────────────────────────────────

CAS_BASE = "https://cas.sustech.edu.cn/cas/login"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


# ── Exceptions ───────────────────────────────────────────────────────────────

class AuthorizerError(Exception):
    """Raised when auth fails."""


# ── Authorizer ───────────────────────────────────────────────────────────────

class Authorizer:
    """
    Shared CAS authentication handler.

    Subclasses MUST define class-level attributes:
        BASE_URL    — the web app's base URL (e.g. "https://bb.sustech.edu.cn")
        SERVICE_URL — CAS service param for CAS login

    Subclasses MAY define:
        SESSION_FILE — Path to session JSON. Default: <submodule_dir>/session.json
        _DOMAIN      — Cookie domain. Default: extracted from BASE_URL

    Usage:
        auth = BBAuthorizer()
        ok, reason = auth.check()       # verify session
        ok, reason = auth.ensure()      # check + auto-refresh
        auth.refresh()                  # requests-based re-auth
        auth.login()                    # Playwright headful login
        cookies = auth.load()           # get cookie dict
    """

    BASE_URL: str = ""
    SERVICE_URL: str = ""

    def __init__(self, *, skill_dir: Optional[str] = None, submodule_dir: Optional[str] = None):
        self._skill_dir = Path(skill_dir) if skill_dir else None
        self._submodule_dir = Path(submodule_dir) if submodule_dir else None

    # ── Paths ───────────────────────────────────────────────────────────────

    @property
    def skill_root(self) -> Path:
        if self._skill_dir:
            return self._skill_dir
        # sustech_survival/sso.py → sustech_survival/
        self._skill_dir = Path(__file__).resolve().parent
        return self._skill_dir

    @property
    def submodule_dir(self) -> Path:
        if self._submodule_dir:
            return self._submodule_dir
        return self.skill_root

    @property
    def session_file(self) -> Path:
        return self.submodule_dir / "session.json"

    @property
    def creds_file(self) -> Path:
        return self.skill_root / "credentials.txt"

    @property
    def cas_url(self) -> str:
        return f"{CAS_BASE}?service={self.SERVICE_URL}"

    @property
    def _domain(self) -> str:
        """Cookie domain, derived from BASE_URL."""
        from urllib.parse import urlparse
        return urlparse(self.BASE_URL).netloc

    # ── Credentials ─────────────────────────────────────────────────────────

    def read_creds(self) -> tuple[str, str]:
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

    # ── Session I/O ──────────────────────────────────────────────────────────

    def load(self) -> dict:
        with open(self.session_file) as f:
            return json.load(f)

    def save(self, cookies: dict):
        with open(self.session_file, 'w') as f:
            json.dump(cookies, f)

    def cookies_for_requests(self, raw: dict) -> dict:
        """Return cookie dict suitable for requests.Session.set_cookie."""
        return {k: v for k, v in raw.items()}

    # ── CAS ticket grinding ──────────────────────────────────────────────────

    def _fetch_execution(self, sess: requests.Session) -> str:
        r = sess.get(self.cas_url, timeout=10)
        m = re.search(r'name="execution" value="([^"]+)"', r.text)
        if not m:
            raise AuthorizerError(f"No execution token at {self.cas_url}")
        return m.group(1)

    def _post_cas(self, sess: requests.Session, username: str, password: str) -> str:
        exec_token = self._fetch_execution(sess)
        r = sess.post(
            self.cas_url,
            data={
                "username": username,
                "password": password,
                "execution": exec_token,
                "_eventId": "submit",
                "submit": "\u63d0\u4ea4",  # "提交"
            },
            allow_redirects=False,
            timeout=10,
        )
        if r.status_code not in (302, 303):
            raise AuthorizerError(f"CAS POST failed: {r.status_code}")
        loc = r.headers.get("Location", "")
        if loc.startswith("https://cas.sustech.edu.cn"):
            raise AuthorizerError("Wrong credentials")
        if not loc:
            raise AuthorizerError("No redirect from CAS")
        return loc

    def _apply_cookies(self, sess: requests.Session, raw: dict):
        for k, v in raw.items():
            sess.cookies.set(k, v, domain=self._domain, path="/")

    # ── Public API ──────────────────────────────────────────────────────────

    def check(self) -> tuple[bool, str]:
        """Check if session is valid. Auto-refreshes via CAS if expired. Returns (True, '') or (False, reason)."""
        try:
            raw = self.load()
        except FileNotFoundError:
            # No session file — try login immediately (credentials may be present)
            if self.refresh():
                return True, ""
            return False, f"No session: {self.session_file.name}"
        except Exception as e:
            return False, f"Session corrupt: {e}"

        try:
            sess = requests.Session()
            self._apply_cookies(sess, raw)
            r = sess.get(
                self.BASE_URL + "/",
                headers={"Accept": "text/html"},
                timeout=10,
                allow_redirects=False,
            )
            if r.status_code in (302, 303):
                loc = r.headers.get("Location", "")
                if "cas.sustech.edu.cn" in loc or "/login" in loc.lower():
                    # Session expired — try auto-refresh via CAS before declaring failure
                    if self.refresh():
                        return True, ""
                    return False, "Session expired and auto-refresh failed. Check credentials.txt."
            return True, ""
        except Exception as e:
            return False, f"Could not reach {self.BASE_URL}: {e}"

    def refresh(self) -> bool:
        """Re-authenticate via CAS requests. Returns True on success."""
        try:
            username, password = self.read_creds()
        except AuthorizerError as e:
            print(f"❌ CAS refresh skipped: {e}")
            return False

        sess = requests.Session()
        sess.headers['User-Agent'] = UA
        try:
            loc = self._post_cas(sess, username, password)
        except AuthorizerError as e:
            print(f"❌ CAS refresh failed: {e}")
            return False

        r = sess.get(loc, timeout=10)
        cookies = {c.name: c.value for c in sess.cookies}
        if not cookies:
            print("❌ No cookies received")
            return False

        self.save(cookies)
        print(f"✅ {len(cookies)} cookies saved: {list(cookies.keys())}")
        return True

    def ensure(self) -> tuple[bool, str]:
        """
        Check session validity. Auto-refreshes via CAS if expired.
        Returns (True, '') on success, (False, reason) on failure.
        
        Note: check() now handles auto-refresh internally, so this is just
        a convenience wrapper that adds actionable hints on failure.
        """
        ok, reason = self.check()  # check() auto-refreshes if expired
        if ok:
            return True, ""
        # check() already tried refresh; reason is the final failure cause
        if "credentials" in reason.lower() or "wrong" in reason.lower():
            hint = " CAS credentials are invalid. Fix credentials.txt at skill root bb/credentials.txt or run 'sustech bb session login' for browser-based login."
        elif "no session" in reason.lower():
            hint = " Run 'sustech bb session login' to open a browser for CAS login."
        else:
            hint = " Try 'sustech bb session login' (browser) or check credentials.txt."
        return False, reason + hint

    def login(self, *, headless: bool = False):
        """Playwright headful login — opens browser for manual CAS login."""
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            ctx = browser.new_context()
            page = ctx.new_page()
            page.goto(self.cas_url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(1000)
            print(f"Browser opened — log in via CAS for {self.BASE_URL}")
            print("Waiting for redirect...")
            try:
                page.wait_for_url(f"**/{self.BASE_URL}**", timeout=0)
            except Exception:
                pass
            page.wait_for_timeout(2000)
            cookies = {c['name']: c['value'] for c in ctx.cookies()}
            self.save(cookies)
            print(f"✅ {len(cookies)} cookies saved: {list(cookies.keys())}")
            return True


# ── Auth decorator ───────────────────────────────────────────────────────────

# Global registry: service name → Authorizer singleton
_auth_registry: dict[str, Authorizer] = {}


def register_auth(name: str, auth: Authorizer):
    """
    Register an Authorizer singleton. Called by submodules at import time.
    Also updates THIS module's registry so sso.require_auth works consistently.
    """
    _auth_registry[name] = auth
    # Also update sys.modules['sso'] registry so bare imports and
    # package imports share the same registry.
    import sys
    if 'sso' in sys.modules:
        sys.modules['sso']._auth_registry[name] = auth
    if 'sustech_survival.sso' in sys.modules:
        sys.modules['sustech_survival.sso']._auth_registry[name] = auth


def get_auth(name: str) -> Authorizer:
    """Get a registered Authorizer by service name."""
    return _auth_registry[name]


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
