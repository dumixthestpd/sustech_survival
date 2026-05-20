# =============================================================================
# CAS Provider — Central Authentication Service v3.0
# =============================================================================
# Direct CAS login: fetch execution token → POST credentials → exchange ticket.
# Used by: SUSTech BB, TIS, Lib, and any other CAS-protected service.
#
# Flow:
#   GET  /cas/login?service=<encoded>
#        ← extract hidden "execution" token
#   POST /cas/login  (username, password, execution, _eventId=submit)
#        → 302 with ?ticket=...
#   GET  <service>?ticket=...  →  Set-Cookie: JSESSIONID
#
# Some CAS deployments (TIS) return cookies on the ticket URL itself rather
# than on the subsequent service redirect.
# =============================================================================

import re
import requests
from ..base import Authorizer, AuthorizerError, CAS_BASE, UA


class CASAuthorizer(Authorizer):
    """
    CAS 3.0 ticket-granting authentication.

    Supports headless login for any CAS-compatible IdP. Handles both patterns:
      - Most services: cookies arrive on the final redirect to SERVICE_URL
      - TIS pattern:   cookies arrive on the GET to the ticket URL itself

    Additional class attributes:
        SUBMIT_VALUE   — value for submit button. None = omit, "\u63d0\u4ea4" = "提交"
        IDP_CAS_BASE   — override CAS endpoint (e.g. for federated IdPs)

    Usage:
        class MyCASAuth(CASAuthorizer):
            BASE_URL    = "https://app.example.com"
            SERVICE_URL = "https://app.example.com/cas-redirect"
            SUBMIT_VALUE = "\u63d0\u4ea4"  # Chinese "submit"
    """

    SUBMIT_VALUE: str = "\u63d0\u4ea4"  # Chinese "提交" — works for BB/Lib; None to skip
    IDP_CAS_BASE: str = CAS_BASE        # Override for non-SUSTech CAS servers

    @property
    def cas_url(self) -> str:
        encoded = quote(self.SERVICE_URL, safe="")
        return f"{self.IDP_CAS_BASE}?service={encoded}"

    # ── CAS internals ─────────────────────────────────────────────────────────

    def _fetch_execution(self, sess: requests.Session) -> str:
        r = sess.get(self.cas_url, headers=self._headers, timeout=10)
        m = re.search(r'name="execution" value="([^"]+)"', r.text)
        if not m:
            raise AuthorizerError(
                f"No execution token found at {self.cas_url}\n"
                "CAS may be down or SERVICE_URL may be wrong."
            )
        return m.group(1)

    def _post_cas(self, sess: requests.Session, username: str, password: str) -> str:
        exec_token = self._fetch_execution(sess)
        data = {
            "username": username,
            "password": password,
            "execution": exec_token,
            "_eventId": "submit",
        }
        if self.SUBMIT_VALUE:
            data["submit"] = self.SUBMIT_VALUE

        r = sess.post(
            self.cas_url,
            data=data,
            allow_redirects=False,
            headers=self._headers,
            timeout=10,
        )
        if r.status_code not in self.REDIRECT_STATUS:
            raise AuthorizerError(
                f"CAS POST failed: HTTP {r.status_code}\n"
                f"Response snippet: {r.text[:200]}"
            )
        loc = r.headers.get("Location", "")
        if not loc:
            raise AuthorizerError("No Location header in CAS response.")
        if "cas.sustech.edu.cn" in loc and "ticket" not in loc:
            raise AuthorizerError("CAS rejected credentials (wrong username/password).")
        return loc

    def _exchange_ticket(self, sess: requests.Session, ticket_url: str) -> dict:
        """
        Exchange CAS ticket for session cookies.
        Handles both patterns:
          - cookies on the ticket URL itself (TIS pattern)
          - cookies on the subsequent redirect to SERVICE_URL (BB/Lib pattern)
        Uses allow_redirects=True to follow the full chain and capture all cookies.
        """
        r = sess.get(ticket_url, allow_redirects=True, headers=self._headers, timeout=10)
        cookies = {c.name: c.value for c in sess.cookies}
        return cookies

    def get_ticket_cookies(self, username: str, password: str) -> dict:
        """
        Full headless CAS flow. Returns cookie dict for save()/cookies_for_requests().
        """
        sess = requests.Session()
        sess.headers['User-Agent'] = UA
        ticket_url = self._post_cas(sess, username, password)
        cookies = self._exchange_ticket(sess, ticket_url)
        if not cookies:
            raise AuthorizerError("No cookies received after CAS ticket exchange.")
        return cookies


# Needed by cas_url property
from urllib.parse import quote