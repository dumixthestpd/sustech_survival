# =============================================================================
# SSO — Generic Authentication Framework
# =============================================================================
# Protocol-agnostic base class + built-in provider implementations.
#
# Protocol hierarchy:
#   sso/
#     base.py        — Authorizer abstract base + error types
#     providers/
#       cas.py       — CAS (Central Authentication Service) v3.0
#       shibboleth.py — Shibboleth SP (Service Provider) via WAYF/DS
#     sustech/
#       bb.py        — SUSTech Blackboard
#       tis.py       — SUSTech Teaching Information System
#       lib.py       — SUSTech Library (Primo)
#       wos.py       — Web of Science (Shibboleth)
#
# Quick start:
#   from sustech_survival.sso import CASAuthorizer, ShibbolethAuthorizer
#   from sustech_survival.sso.sustech import bb, tis, lib, wos
#
#   ok, reason = bb.ensure()
#   ok, reason = wos.ensure()   # Shibboleth flow
#
# =============================================================================

import json
import re
import sys
import functools
import requests
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import quote, urlparse
from abc import ABC, abstractmethod

__all__ = ["Authorizer", "AuthorizerError", "CAS_BASE", "UA"]


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
        SERVICE_URL — where the IdP/SSO redirects after auth (or where we send the CAS ticket)

    Subclasses MAY define:
        SESSION_FILE     — path to session JSON. Default: <submodule_dir>/session.json
        CREDENTIALS_FILE — path to credentials. Default: <skill_root>/credentials.txt
        XHR_MODE         — add X-Requested-With header. Default: False
        REDIRECT_STATUS  — tuple of valid redirect status codes. Default: (302, 303)

    Workflow for a new service:
      1. Create sustech_survival/sso/providers/<protocol>.py with a subclass
         e.g. CASAuthorizer or ShibbolethAuthorizer.
      2. Create sustech_survival/sso/sustech/<service>.py that configures it.
      3. Register with register_auth() in sustech_survival/sso/sustech/__init__.py.

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
    SESSION_SUBDIR: str = ""  # subdirectory under skill_root for session/creds files

    def __init__(self, *, skill_dir: Optional[str] = None, submodule_dir: Optional[str] = None):
        self._skill_dir = Path(skill_dir) if skill_dir else None
        self._submodule_dir = Path(submodule_dir) if submodule_dir else None

    # ── Paths ────────────────────────────────────────────────────────────────

    @property
    def skill_root(self) -> Path:
        if self._skill_dir:
            return self._skill_dir
        # Search upward from base.py for credentials.txt to find skill root
        # __file__ = .../src/sustech_survival/sso/base.py
        here = Path(__file__).resolve().parent  # sso/
        for parent in [here, here.parent, here.parent.parent, here.parent.parent.parent]:
            if (parent / "credentials.txt").exists():
                self._skill_dir = parent
                return self._skill_dir
            if (parent / "sustech_survival").exists() and (parent).name == "src":
                continue
        # Fallback
        self._skill_dir = here.parent.parent.parent
        return self._skill_dir

    @property
    def submodule_dir(self) -> Path:
        if self._submodule_dir:
            return self._submodule_dir
        if self.SESSION_SUBDIR:
            return self.skill_root / self.SESSION_SUBDIR
        return self.skill_root

    @property
    def session_file(self) -> Path:
        return self.submodule_dir / "session.json"

    @property
    def creds_file(self) -> Path:
        return self.skill_root / "credentials.txt"

    @property
    def cas_url(self) -> str:
        """
        CAS login URL with properly encoded service parameter.
        Default implementation encodes SERVICE_URL. Override if the service
        requires a non-standard CAS endpoint.
        """
        encoded = quote(self.SERVICE_URL, safe="")
        return f"{getattr(self, 'IDP_CAS_BASE', CAS_BASE)}?service={encoded}"

    @property
    def _domain(self) -> str:
        return urlparse(self.BASE_URL).netloc

    # ── Headers ──────────────────────────────────────────────────────────────

    @property
    def _headers(self) -> dict:
        h = {"User-Agent": UA}
        if self.XHR_MODE:
            h["X-Requested-With"] = "XMLHttpRequest"
        return h

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
        self.session_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.session_file, 'w') as f:
            json.dump(cookies, f)

    def cookies_for_requests(self, raw: dict) -> dict:
        return {k: v for k, v in raw.items()}

    def _apply_cookies(self, sess: requests.Session, raw: dict):
        for k, v in raw.items():
            sess.cookies.set(k, v, domain=self._domain, path="/")

    # ── CAS ticket grinding (CASAuthorizer handles override) ───────────────────

    def get_ticket_cookies(self, username: str, password: str) -> dict:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement headless CAS auth. "
            "Use login() for browser-based auth."
        )

    # ── Session check ────────────────────────────────────────────────────────

    def check(self) -> tuple[bool, str]:
        """
        Verify session is valid. Auto-refreshes if expired.
        Returns (True, '') on success, (False, reason) on failure.
        """
        try:
            raw = self.load()
        except FileNotFoundError:
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
            if r.status_code in self.REDIRECT_STATUS:
                loc = r.headers.get("Location", "")
                if "cas.sustech.edu.cn" in loc or "/login" in loc.lower():
                    if self.refresh():
                        return True, ""
                    return False, "Session expired and auto-refresh failed."
            return True, ""
        except Exception as e:
            return False, f"Could not reach {self.BASE_URL}: {e}"

    def refresh(self) -> bool:
        """
        Re-authenticate using credentials.txt. Subclasses with headless support
        override get_ticket_cookies(); this method dispatches to it.
        """
        try:
            username, password = self.read_creds()
        except AuthorizerError as e:
            print(f"❌ Auth refresh skipped: {e}")
            return False

        try:
            cookies = self.get_ticket_cookies(username, password)
            self.save(cookies)
            print(f"✅ {len(cookies)} cookies saved: {list(cookies.keys())}")
            return True
        except (NotImplementedError, AuthorizerError) as e:
            print(f"❌ Auth refresh not supported: {e}")
            return False

    def ensure(self) -> tuple[bool, str]:
        """Check session, auto-refresh if expired. Returns (True, '') or (False, reason)."""
        ok, reason = self.check()
        if ok:
            return True, ""
        if "credentials" in reason.lower() or "no session" in reason.lower():
            hint = " Run browser login: sustech <service> session login"
        else:
            hint = ""
        return False, reason + hint

    def login(self, *, headless: bool = False):
        """Playwright headful login for services without headless support."""
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


# ── Auth registry & decorator ─────────────────────────────────────────────────

_auth_registry: dict[str, Authorizer] = {}


def register_auth(name: str, auth: Authorizer):
    """Register an Authorizer singleton by service name."""
    _auth_registry[name] = auth


def get_auth(name: str) -> Authorizer:
    return _auth_registry.get(name)


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