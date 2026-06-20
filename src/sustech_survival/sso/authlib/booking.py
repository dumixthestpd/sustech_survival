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
import time
import uuid
from pathlib import Path
from typing import Optional, Tuple

import requests

from ..authorizer import Authorizer, AuthorizerError, UA, register_auth


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

    Storage: in-memory only (session_cache). Persisted to
    `tis/booking/session.json` (relative to skill_dir) via the refresh/save
    pair — survives process restart but expires with the server-side TGC.
    """

    BASE_URL = BOOKING_BASE
    SERVICE_URL = BOOKING_SERVICE

    # ── Paths ────────────────────────────────────────────────────────────────

    @property
    def submodule_dir(self) -> Path:
        return self.skill_root / "booking"

    @property
    def session_file(self) -> Path:
        return self.submodule_dir / "session.json"

    # ── Session management ────────────────────────────────────────────────────

    def check(self) -> Tuple[bool, str]:
        """Is the current session still authenticated?

        Lightweight local check: do we have cookies + a cached token? The actual
        API token may have been rotated server-side, but the next real API call
        will fail with a 401/403 if so — and the caller (BookingClient) auto-
        re-logs-in on auth errors. Re-validating via GetUserProfile with the
        OLD ticket would fail because tickets are single-use.
        """
        if not self.session_cache:
            return False, "No session — login needed."
        if not self._cached_token():
            return False, "No cached token — login needed."
        return True, f"Session has {len(self.session_cache)} cookies + token"

    def ensure(self) -> Tuple[bool, str]:
        """check() + auto-refresh from disk + auto-login if needed."""
        # Refresh from disk first on a fresh process
        self.refresh()
        ok, reason = self.check()
        if ok:
            return True, reason
        if self.username and self.password:
            try:
                self.login_password(self.username, self.password)
                return self.check()
            except Exception as e:
                return False, f"Auto-refresh failed: {e}"
        return False, reason

    # ── Login ────────────────────────────────────────────────────────────────

    def login_password(
        self, username: Optional[str] = None, password: Optional[str] = None
    ) -> str:
        """Full CAS + token handshake. Returns the Chinese display name."""
        username = username or self.username
        password = password or self.password
        if not username or not password:
            raise AuthorizerError("BookingAuth.login_password() needs username+password")

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

        # Step 3: follow ticket → cookies land on booking.sustech.edu.cn
        r = sess.get(ticket_url, allow_redirects=True, timeout=10)
        cookies = {c.name: c.value for c in sess.cookies}
        if not cookies:
            raise AuthorizerError("No cookies after ticket exchange.")

        # Step 4: secondary handshake — GetUserProfile with ticket
        sess.headers["X-Requested-With"] = "XMLHttpRequest"
        ticket_match = re.search(r"ticket=([^&]+)", ticket_url)
        if not ticket_match:
            raise AuthorizerError("Could not extract ticket from CAS Location header.")
        ticket = ticket_match.group(1)
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
        name = hs_data["Data"].get("name", username)

        # Persist cookies + token + user info
        self.set_session(cookies)
        self._cache_token(token)
        self._user_info = hs_data["Data"]  # cache for whoami()
        self._save_session()

        return name

    # ── Token storage ────────────────────────────────────────────────────────
    #
    # The auth token is NOT in the cookie jar — it's a JSON field returned by
    # GetUserProfile. We store it in a sidecar file alongside session.json so
    # it survives process restart.

    def _token_file(self) -> Path:
        return self.submodule_dir / "token.json"

    def _cache_token(self, token: str) -> None:
        self._token = token

    def _cached_token(self) -> str:
        return getattr(self, "_token", "") or ""

    def _save_session(self) -> None:
        self.submodule_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "saved_at": time.time(),
            "cookies": self.session_cache,
        }
        self.session_file.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2)
        )
        tf = self._token_file()
        tf.write_text(json.dumps({
            "token": self._cached_token(),
            "user_info": getattr(self, "_user_info", {}),
        }))

    def refresh(self) -> bool:
        """Load saved session (cookies + token + user info) from disk."""
        ok = False
        sf = self.session_file
        if sf.exists():
            try:
                payload = json.loads(sf.read_text())
                cookies = payload.get("cookies") or {}
                if cookies:
                    self.set_session(cookies)
                    ok = True
            except Exception:
                pass
        tf = self._token_file()
        if tf.exists():
            try:
                tdata = json.loads(tf.read_text())
                if tdata.get("token"):
                    self._cache_token(tdata["token"])
                if tdata.get("user_info"):
                    self._user_info = tdata["user_info"]
            except Exception:
                pass
        return ok

    # ── requests.Session factory ─────────────────────────────────────────────

    def _api_session(self) -> requests.Session:
        """Session pre-loaded with cookies + JSON headers + Authorization token."""
        sess = self.requests_session
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
register_auth("booking", _auth)
