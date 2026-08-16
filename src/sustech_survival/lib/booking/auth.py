"""
sustech_survival.lib.booking.auth — CAS + authcenter handshake for IC library booking.

Subclass of CASAuthorizer (NOT raw Authorizer). The CAS service URL is
dynamic — generated per-login via the authcenter /auth/address endpoint.
We override refresh() to inject that pre-CAS step before delegating to
the parent get_ticket_cookies().

Full 6-hop chain:
    1. GET /ic-web/auth/address → authcenter URL
    2. GET /authcenter/toLoginPage → 302 to CAS with UUID service URL
    3–4. CAS login (standard — handled by CASAuthorizer.post_cas)
    5–6. Ticket exchange + redirect following → ic-cookie (handled by
         CASAuthorizer.exchange_ticket via get_ticket_cookies)

DIFFERENT FROM:
  - ehall MAIN (ehall.sustech.edu.cn) — needs JSESSIONID, not this flow.
  - ehall 书院活动 booking (booking.sustech.edu.cn) — separate host, uses
    CAS + secondary GetUserProfile token handshake (pattern 3).
  - TIS / BB / LibAuth — direct CAS ticket exchange to a static SERVICE_URL
    (pattern 1).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional, Tuple

import requests

from ...sso import AuthorizerError, UA
from ...sso.providers.cas import CASAuthorizer

# -- Constants ----------------------------------------------------------------

BOOKING_BASE = "https://booking.lib.sustech.edu.cn"
BOOKING_API = f"{BOOKING_BASE}/ic-web"
BOOKING_FINAL = "https://booking.lib.sustech.edu.cn/ic/home"
ERR_PAGE = "https://booking.lib.sustech.edu.cn/#/error"

# Off-campus signal: SUSTech firewall returns this exact body on 403
# before any auth runs. Same pattern as pms + ehall-booking.
OFF_CAMPUS_BODY = "Access forbidden, please contact administrator."
OFF_CAMPUS_HINT = (
    "IC library booking server blocked the request (HTTP 403: 'Access "
    "forbidden, please contact administrator.'). You are most likely NOT "
    "on the SUSTech campus network — connect to campus Wi-Fi / wired, or "
    "this module will not work."
)


def _looks_off_campus(r: requests.Response) -> bool:
    return r.status_code == 403 and OFF_CAMPUS_BODY in (r.text or "")


# -- LibBookingAuth -----------------------------------------------------------


class LibBookingAuth(CASAuthorizer):
    """CASAuthorizer subclass for IC library booking (authcenter pattern).

    The CAS service URL is NOT static — it's generated per-login via the
    authcenter /auth/address endpoint. We override refresh() to resolve
    that dynamic URL, then delegate to the parent's CAS flow (which goes
    through post_cas() → exchange_ticket() → get_ticket_cookies()) —
    NO hand-rolled CAS code.

    The session cookie is `ic-cookie` (set on the final redirect hop of the
    authcenter relay chain), which exchange_ticket() captures automatically
    because it follows all redirects with allow_redirects=True.

    Do NOT confuse with `sustech_survival.booking.BookingAuth` (ehall
    35-venue booking on `booking.sustech.edu.cn`) — different host,
    different auth flow, different session cookie name.
    """

    BASE_URL = BOOKING_BASE
    SUBMIT_VALUE = ""  # TIS-style (CAS expects empty submit value)

    # -- Paths ----------------------------------------------------------------

    @property
    def submodule_dir(self) -> Path:
        return self.skill_dir / "lib" / "booking"

    @property
    def session_file(self) -> Path:
        return self.submodule_dir / "session.json"

    def build_session(self) -> requests.Session:
        """Override: plain session (no LegacyAdapter — broken on py3.12)."""
        sess = requests.Session()
        sess.headers["User-Agent"] = UA
        return sess

    # -- Authcenter pre-CAS step (the only new code needed) -----------------

    def _resolve_cas_service_url(self) -> str:
        """Steps 1–2: GET /auth/address → follow authcenter → get CAS URL with UUID.

        Returns the real CAS login URL, e.g.:
          https://cas.sustech.edu.cn/cas/login?service=https%3A%2F%2F...
        """
        sess = requests.Session()
        sess.headers["User-Agent"] = UA

        r = sess.get(
            f"{BOOKING_API}/auth/address",
            params={
                "finalAddress": BOOKING_FINAL,
                "errPageUrl": ERR_PAGE,
                "manager": "false",
                "consoleType": "16",
            },
            timeout=10,
        )
        if _looks_off_campus(r):
            raise AuthorizerError(OFF_CAMPUS_HINT)
        body = r.json()
        if body.get("code") != 0:
            raise AuthorizerError(
                f"auth/address failed: {body.get('message')} "
                f"(code={body.get('code')})"
            )
        auth_url = body["data"]
        if "authcenter/toLoginPage" not in auth_url:
            raise AuthorizerError(
                f"auth/address returned unexpected URL: {auth_url[:200]}"
            )

        r = sess.get(auth_url, allow_redirects=False, timeout=10)
        if r.status_code not in (301, 302):
            raise AuthorizerError(
                f"authcenter/toLoginPage expected 302, got {r.status_code}"
            )
        cas_url = r.headers.get("Location", "")
        if "cas.sustech.edu.cn" not in cas_url:
            raise AuthorizerError(
                f"authcenter did not redirect to CAS: {cas_url[:200]}"
            )
        return cas_url

    # -- refresh() — the single override point -----------------------------

    def refresh(self) -> bool:
        """Resolve dynamic SERVICE_URL, then delegate to parent CAS flow.

        The parent refresh() calls get_ticket_cookies() which does the
        standard CAS 3.0 flow (fetch execution → POST creds → exchange
        ticket). `exchange_ticket()` follows all redirects with
        allow_redirects=True, which captures the ic-cookie from the
        final authcenter relay hop automatically.

        Returns True on success (ic-cookie present). False on failure.
        """
        try:
            username, password = self.read_creds()
        except AuthorizerError as e:
            print(f"❌ LibBookingAuth refresh skipped: {e}")
            return False

        try:
            # Steps 1–2: resolve the dynamic CAS service URL
            cas_service_url = self._resolve_cas_service_url()

            # Set the dynamic URL, then delegate to parent CAS flow
            old = self.SERVICE_URL
            self.SERVICE_URL = cas_service_url
            try:
                cookies = self.get_ticket_cookies(username, password)
            finally:
                self.SERVICE_URL = old

            # Verify the correct session cookie was set
            if "ic-cookie" not in cookies:
                raise AuthorizerError(
                    "CAS exchange did not return ic-cookie. Auth rejected?"
                )

            self.set_session(cookies)
            self._user_info = self._fetch_user_info()
            print(
                f"✅ LibBookingAuth session refreshed "
                f"({len(cookies)} cookies, ic-cookie ✓)"
            )
            return True
        except (AuthorizerError, Exception) as e:
            print(f"❌ LibBookingAuth refresh failed: {e}")
            return False

    # -- Session management --------------------------------------------------

    def check(self) -> Tuple[bool, str]:
        """Lightweight local check: do we have ic-cookie + cached user info?

        Does NOT re-validate against the server. The `ic-cookie` is opaque
        and there's no cheap probe endpoint; the next real API call will
        return 401/403 if the cookie is dead, and the client auto-relogs
        via `_looks_auth_error` + retry.
        """
        if not self.session_cache:
            return False, "No session — login needed."
        if "ic-cookie" not in self.session_cache:
            return False, "No ic-cookie in session — login needed."
        return True, f"Session has {len(self.session_cache)} cookies"

    def ensure(self) -> Tuple[bool, str]:
        """check() + auto-refresh if needed. In-memory only — no disk I/O."""
        ok, reason = self.check()
        if ok:
            return True, reason
        if self.username and self.password:
            try:
                self.refresh()
                return self.check()
            except Exception as e:
                return False, f"Auto-refresh failed: {e}"
        return False, "No credentials — login needed."

    def login_password(
        self, username: Optional[str] = None, password: Optional[str] = None
    ) -> str:
        """Alias for refresh() — called by BookingClient auto-relogin.

        The client's _call() method calls login_password() when it detects
        an auth error (code=300). This method takes the same arguments as
        CASAuthorizer.login_password() would, but delegates to refresh()
        which reads credentials from credentials.txt automatically.
        """
        self.refresh()
        ui = self._cached_user_info()
        return ui.get("trueName", "") if ui else (username or "")

    # -- User info cache (post-auth enrichment) ------------------------------

    def _fetch_user_info(self) -> Optional[dict]:
        """GET /auth/userInfo with the just-set ic-cookie."""
        sess = self.session
        sess.headers["User-Agent"] = UA
        try:
            r = sess.get(f"{BOOKING_API}/auth/userInfo", timeout=10)
            if r.status_code != 200:
                return None
            body = r.json()
            if body.get("code") != 0:
                return None
            return body.get("data")
        except Exception:
            return None

    def _cached_user_info(self) -> Optional[dict]:
        return getattr(self, "_user_info", None)

    # -- Persistence ---------------------------------------------------------

    def _save_session(self, user_info: Optional[dict] = None) -> None:
        """No-op — in-memory only (iron law #12). Kept for backward compat."""
        pass

    def refresh_from_disk(self) -> bool:
        """No-op — in-memory only (iron law #12). Kept for backward compat."""
        return False


# -- Helpers ------------------------------------------------------------------

_SENSITIVE_USER_FIELDS = frozenset(
    {"idCard", "cardNo", "cardId", "handPhone", "email", "token", "uuid"}
)


def _redact_user_info(user: dict) -> dict:
    """Return a copy of `user` with sensitive fields redacted to '***'."""
    redacted = dict(user)
    for k in _SENSITIVE_USER_FIELDS:
        if k in redacted:
            redacted[k] = "***"
    return redacted


# -- Registry -----------------------------------------------------------------


def register() -> None:
    """Register this auth under the name 'lib-booking' for get_auth() lookup."""
    from ...sso import SKILL_ROOT

