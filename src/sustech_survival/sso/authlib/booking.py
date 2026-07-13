# =============================================================================
# BookingAuth — ehall 场地预约 sub-app (booking.sustech.edu.cn)
# =============================================================================
# Lives on its own host behind SUSTech CAS, but does NOT use the ehall MAIN
# host's JSESSIONID auth — instead it uses a CAS + secondary token handshake:
#
#   1. CAS login (POST /cas/login with submit="提交") — same as TIS, but the
#      SUBMIT_VALUE for ehall sub-apps is the Chinese "提交", NOT empty
#   2. GET /redirect?ticket=ST-... — cookies land on booking.sustech.edu.cn
#   3. POST /api/SystemApi/GetUserProfile
#        body: {MessageType:1001, MessageID:<uuid>, Data:{Url, St:ticket}}
#        → returns Data.Token (UUID)
#   4. All subsequent API calls attach: Authorization: <Token>
#
# The Authorizer base class ships a LegacyAdapter that breaks on newer
# urllib3 (see reference `ehall-booking-venue-2026-06-15.md`); we override
# get_ticket_cookies() with a hand-rolled session that doesn't need it.
# =============================================================================

import json
import re
import uuid
from typing import Optional, Tuple

import requests

from ..authorizer import Authorizer, AuthorizerError, UA


BOOKING_BASE = "https://booking.sustech.edu.cn"
BOOKING_SERVICE = f"{BOOKING_BASE}/redirect"
BOOKING_API = f"{BOOKING_BASE}/api/SystemApi"

# Off-campus signal: SUSTech firewall returns this exact body on 403 before
# any auth runs. (Same pattern as `pms.py` — see references/sustech-firewall-off-campus-403.md.)
OFF_CAMPUS_BODY = "Access forbidden, please contact administrator."
OFF_CAMPUS_HINT = (
    "Booking server blocked the request (HTTP 403: 'Access forbidden, "
    "please contact administrator.'). You are most likely NOT on the "
    "SUSTech campus network — connect to campus Wi-Fi / wired, or this "
    "module will not work."
)


def _looks_off_campus(r: requests.Response) -> bool:
    return r.status_code == 403 and OFF_CAMPUS_BODY in (r.text or "")


class BookingAuth(Authorizer):
    """Headless login for the ehall 场地预约 sub-app (booking.sustech.edu.cn).

    Subclass of Authorizer — does NOT inherit from CASAuthorizer (the
    LegacyAdapter inside CASAuthorizer.get_ticket_cookies throws on newer
    urllib3). We hand-roll the CAS POST + token handshake here.

    Storage: in-memory only (_session_cache + self._token).
    """

    BASE_URL = BOOKING_BASE
    SERVICE_URL = BOOKING_SERVICE

    # ── Session management ────────────────────────────────────────────────────

    def check(self) -> Tuple[bool, str]:
        """Is the current session still authenticated?

        Lightweight local check: do we have cookies + a cached token? The actual
        API token may have been rotated server-side, but the next real API call
        will fail with a 401/403 if so — and the caller (BookingClient) auto-
        re-logs-in on auth errors. Re-validating via GetUserProfile with the
        OLD ticket would fail because tickets are single-use.
        """
        if not self._session_cache:
            return False, "No session — login needed."
        if not self._cached_token():
            return False, "No cached token — login needed."
        return True, f"Session has {len(self._session_cache)} cookies + token"

    def ensure(self) -> Tuple[bool, str]:
        """check() + auto-login if needed (no disk I/O)."""
        ok, reason = self.check()
        if ok:
            return True, reason
        if self._refresh():
            return self.check()
        return False, reason

    # ── Login (public convenience) ────────────────────────────────────────────

    def login_password(
        self, username: Optional[str] = None, password: Optional[str] = None
    ) -> str:
        """Full CAS + token handshake. Returns the Chinese display name.

        Convenience wrapper around _refresh() that accepts explicit
        username/password (overriding the credentials file).
        """
        username = username or self.username
        password = password or self.password
        if not username or not password:
            raise AuthorizerError("BookingAuth.login_password() needs username+password")

        if self._refresh_with_creds(username, password):
            return getattr(self, "_user_info", {}).get("name", username)
        raise AuthorizerError("BookingAuth login failed.")

    # ── Refresh (overrides base) ─────────────────────────────────────────────

    def _refresh(self) -> bool:
        """Read credentials from file and perform full CAS + token handshake."""
        try:
            username, password = self._read_creds()
        except AuthorizerError as e:
            print(f"❌ BookingAuth refresh skipped: {e}")
            return False
        return self._refresh_with_creds(username, password)

    def _refresh_with_creds(self, username: str, password: str) -> bool:
        """Shared CAS + token handshake used by both _refresh() and login_password()."""
        try:
            # Step 1-3: CAS login → ticket → cookies on booking domain
            cookies, ticket = self._get_ticket_cookies(username, password)
            self._set_session(cookies)

            # Step 4: secondary handshake — GetUserProfile to obtain API token
            self._do_token_handshake(ticket)

            cls = self.__class__.__name__
            print(f"✅ {cls} session refreshed ({len(cookies)} cookies)")
            return True
        except (AuthorizerError, Exception) as e:
            print(f"❌ BookingAuth refresh failed: {e}")
            return False

    def _get_ticket_cookies(self, username: str, password: str) -> Tuple[dict, str]:
        """CAS login handshake. Returns (cookies_dict, ticket_string).

        Steps 1-3 of the auth flow:
          1. CAS GET → fetch execution token
          2. CAS POST → receive ticket via Location redirect
          3. Follow ticket redirect → cookies land on booking.sustech.edu.cn
        """
        sess = requests.Session()
        sess.headers["User-Agent"] = UA

        # Step 1: CAS GET → fetch execution token
        r = sess.get(
            "https://cas.sustech.edu.cn/cas/login",
            params={"service": BOOKING_SERVICE},
            timeout=10,
        )
        m = re.search(r'name="execution" value="([^"]+)"', r.text)
        if not m:
            raise AuthorizerError("No execution token at CAS login page.")
        exec_token = m.group(1)

        # Step 2: CAS POST → ticket. SUBMIT_VALUE="提交" for ehall sub-apps.
        r = sess.post(
            "https://cas.sustech.edu.cn/cas/login",
            params={"service": BOOKING_SERVICE},
            data={
                "username": username,
                "password": password,
                "execution": exec_token,
                "_eventId": "submit",
                "submit": "提交",       # Chinese — NOT empty (TIS uses "")
            },
            allow_redirects=False,
            timeout=10,
        )
        if r.status_code not in (301, 302):
            raise AuthorizerError(
                f"CAS POST failed: HTTP {r.status_code}\n"
                f"Body: {r.text[:200]}"
            )
        ticket_url = r.headers.get("Location", "")
        if not ticket_url or "ticket=" not in ticket_url:
            raise AuthorizerError("CAS did not return a ticket (auth rejected).")

        # Extract ticket string from URL
        ticket_match = re.search(r"ticket=([^&]+)", ticket_url)
        if not ticket_match:
            raise AuthorizerError("Could not extract ticket from CAS Location header.")
        ticket = ticket_match.group(1)

        # Step 3: follow ticket → cookies land on booking.sustech.edu.cn
        r = sess.get(ticket_url, allow_redirects=True, timeout=10)
        cookies = {c.name: c.value for c in sess.cookies}
        if not cookies:
            raise AuthorizerError("No cookies after ticket exchange.")

        return cookies, ticket

    def _do_token_handshake(self, ticket: str) -> None:
        """Secondary GetUserProfile handshake. Stores token + user_info in memory.

        Must be called AFTER _set_session() so that self.session is available
        (carries the cookies needed for the handshake).
        """
        sess = self.session
        sess.headers["X-Requested-With"] = "XMLHttpRequest"
        hs = sess.post(
            f"{BOOKING_API}/GetUserProfile",
            json={
                "MessageType": 1001,
                "MessageID": str(uuid.uuid4()),
                "Data": {"Url": BOOKING_SERVICE, "St": ticket},
            },
            timeout=10,
        )
        if _looks_off_campus(hs):
            raise AuthorizerError(OFF_CAMPUS_HINT)
        hs_data = hs.json()
        if not hs_data.get("IsSuccess"):
            raise AuthorizerError(
                f"Handshake failed: {hs_data.get('Message', 'unknown')} "
                f"(code={hs_data.get('ErrorCode')})"
            )

        token = hs_data["Data"]["Token"]
        self._cache_token(token)
        self._user_info = hs_data["Data"]  # cache for whoami()

    # ── Token storage (in-memory only) ───────────────────────────────────────
    #
    # The auth token is NOT in the cookie jar — it's a JSON field returned by
    # GetUserProfile. We store it in memory only (no disk I/O).

    def _cache_token(self, token: str) -> None:
        self._token = token

    def _cached_token(self) -> str:
        return getattr(self, "_token", "") or ""

    # ── requests.Session factory ─────────────────────────────────────────────

    def _api_session(self) -> requests.Session:
        """Session pre-loaded with cookies + JSON headers + Authorization token."""
        sess = self.session
        sess.headers.update({
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/json",
        })
        token = self._cached_token()
        if token:
            sess.headers["Authorization"] = token
        return sess


# ── Module-level singleton ──────────────────────────────────────────────────

_auth = BookingAuth()  # resolves skill_root by walking up looking for credentials.txt
