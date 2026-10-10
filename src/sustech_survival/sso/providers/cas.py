# =============================================================================
# CAS Provider 鈥?Central Authentication Service v3.0
# =============================================================================
# Direct CAS login: fetch execution token 鈫?POST credentials 鈫?exchange ticket.
# Used by: SUSTech BB, TIS, Lib, and any other CAS-protected service.
#
# Flow (all private 鈥?consumers see only Authorizer.ensure()):
#   _fetch_execution() 鈫?_post_cas() 鈫?_exchange_ticket()
#
# No public methods. Authorizer base class handles the lifecycle.
# =============================================================================

from urllib.parse import urlsplit

import requests
from bs4 import BeautifulSoup

from sustech_survival._net import attempts as _net_attempts
from sustech_survival.exceptions import InvalidCredentials, NetworkError

from .._tls import LegacyTLSAdapter
from ..authorizer import Authorizer, AuthorizerError, CAS_BASE, UA

# CAS/TIS are slow and flaky on VPN/off-campus links: a 10s read timeout
# produced frequent false "CAS timeout" failures during session refresh
# (observed live 2026-09-02). Timeouts/attempts are configurable via the
# root config.json `timeouts` map (see sustech_survival._net) 鈥?defaults:
# 30s per step, 2 attempts. Operators with a slow TIS can raise them. 


class CASAuthorizer(Authorizer):
    """
    CAS 3.0 ticket-granting authentication.

    Supports headless login for any CAS-compatible IdP. Handles both patterns:
      - Most services: cookies arrive on the final redirect to SERVICE_URL
      - TIS pattern:   cookies arrive on the GET to the ticket URL itself

    Additional class attributes:
        SUBMIT_VALUE   鈥?value for submit button. None = omit, "鎻愪氦" = Chinese "submit"
        _idp_cas_base  鈥?override CAS endpoint (e.g. for federated IdPs)
    """

    SUBMIT_VALUE: str = "鎻愪氦"  # works for BB/Lib; None to skip
    _idp_cas_base: str = CAS_BASE

    # -- Private CAS flow -----------------------------------------------------

    def _get_ticket_cookies(self, username: str, password: str) -> dict:
        """Full headless CAS flow. Returns cookie dict.

        Raises ``InvalidCredentials`` if CAS rejects the username/password,
        ``NetworkError`` if CAS is unreachable, or ``AuthorizerError`` for
        unexpected response formats.
        """
        last_error = "CAS authentication failed"
        for _attempt in range(_net_attempts("cas_attempts")):
            sess = self._build_cas_session()
            sess.headers["User-Agent"] = UA
            stage, target = "CAS login", self._cas_url
            try:
                ticket_url = self._post_cas(sess, username, password)
                stage, target = "CAS ticket exchange", ticket_url
                cookies = self._exchange_ticket(sess, ticket_url)
                if not cookies:
                    raise AuthorizerError("No cookies received after CAS ticket exchange.")
                return cookies
            except requests.RequestException as exc:
                # Exception strings can contain the ticket, cookies or proxy credentials.
                request = getattr(exc, "request", None)
                host = urlsplit(getattr(request, "url", None) or target).hostname or "unknown host"
                kind = type(exc).__name__
                if isinstance(exc, requests.exceptions.SSLError):
                    kind = (
                        "TLS legacy renegotiation disabled"
                        if "UNSAFE_LEGACY_RENEGOTIATION_DISABLED" in str(exc)
                        else "TLS handshake/certificate failure"
                    )
                response = getattr(exc, "response", None)
                if response is not None:
                    kind += f", HTTP {response.status_code}"
                last_error = f"{stage} failed at {host} ({kind})"
                if isinstance(exc, requests.exceptions.SSLError) or not isinstance(
                    exc, (requests.ConnectionError, requests.Timeout)
                ):
                    sess.close()
                    raise NetworkError(last_error) from None
                # Retry only transient connection failures, with a fresh session.
                sess.close()
        raise NetworkError(last_error) from None

    def _fetch_execution(self, sess: requests.Session) -> str:
        r = sess.get(self._cas_url, headers=self._headers, timeout=self._login_timeout())
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        if soup.select(
            'input[name*="captcha" i], input[id*="captcha" i], .g-recaptcha, '
            '.h-captcha, iframe[src*="recaptcha"], input[name="otp"]'
        ):
            raise AuthorizerError("Interactive CAS challenge; stopped before credential POST")
        node = soup.select_one('input[name="execution"]')
        if not node or not node.get("value"):
            raise AuthorizerError("CAS login form unavailable; stopped before credential POST")
        return node["value"]

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
            self._cas_url,
            data=data,
            allow_redirects=False,
            headers=self._headers,
            timeout=self._login_timeout(),
        )
        if r.status_code not in self.REDIRECT_STATUS:
            raise AuthorizerError(
                f"CAS POST failed: HTTP {r.status_code}"
            )
        loc = r.headers.get("Location", "")
        if not loc:
            raise AuthorizerError("No Location header in CAS response.")
        if "cas.sustech.edu.cn" in loc and "ticket" not in loc:
            raise InvalidCredentials(
                "CAS rejected credentials 鈥?wrong username or password.\n"
                f"Check credentials.txt at {self._creds_file}"
            )
        return loc

    def _exchange_ticket(self, sess: requests.Session, ticket_url: str) -> dict:
        r = sess.get(ticket_url, allow_redirects=True, headers=self._headers, timeout=self._login_timeout())
        cookies = {c.name: c.value for c in sess.cookies}
        return cookies

    def _build_cas_session(self) -> requests.Session:
        """Build a CAS session with the same TLS policy through proxies."""
        sess = requests.Session()
        sess.mount("https://", LegacyTLSAdapter())
        return sess


# Needed by _cas_url property
from urllib.parse import quote

