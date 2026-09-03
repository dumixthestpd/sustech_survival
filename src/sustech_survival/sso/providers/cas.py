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

import re
import ssl
import requests
from ..authorizer import Authorizer, AuthorizerError, CAS_BASE, UA
from sustech_survival.exceptions import InvalidCredentials, NetworkError
from sustech_survival._net import timeout as _net_timeout, attempts as _net_attempts

# Constant used only inside the scoped legacy CAS SSL context below. It is NOT
# applied process-wide: the legacy-TLS tweak belongs to the CAS session alone,
# never to unrelated urllib3/requests traffic in the process (a former
# import-time monkeypatch of urllib3.util.ssl_.create_urllib3_context was removed
# for exactly that reason 鈥?it weakened TLS for every connection).
_OP_LEGACY = getattr(ssl, 'OP_LEGACY_SERVER_CONNECT', 0x4)

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
        sess = self._build_cas_session()
        sess.headers['User-Agent'] = UA
        # Retry the whole flow on network flakiness (timeout / dropped
        # connection). Each attempt builds a fresh session, so this is safe.
        # Attempt count is configurable (config.json timeouts.cas_attempts).
        last_err: Exception | None = None
        for _attempt in range(_net_attempts("cas_attempts")):
            try:
                ticket_url = self._post_cas(sess, username, password)
                cookies = self._exchange_ticket(sess, ticket_url)
                if not cookies:
                    raise AuthorizerError(
                        "No cookies received after CAS ticket exchange.")
                return cookies
            except (requests.ConnectionError, requests.Timeout) as e:
                last_err = e
                # Rebuild the session (the old one may hold a half-open conn).
                sess = self._build_cas_session()
                sess.headers['User-Agent'] = UA
                continue
            except InvalidCredentials:
                raise
            except AuthorizerError:
                raise
        raise NetworkError(f"Cannot reach CAS at {self._cas_url}: {last_err}")

    def _fetch_execution(self, sess: requests.Session) -> str:
        r = sess.get(self._cas_url, headers=self._headers, timeout=self._login_timeout())
        m = re.search(r'name="execution" value="([^"]+)"', r.text)
        if not m:
            raise AuthorizerError(
                f"No execution token found at {self._cas_url}\n"
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
            self._cas_url,
            data=data,
            allow_redirects=False,
            headers=self._headers,
            timeout=self._login_timeout(),
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
        """Build a requests Session for CAS login. Handles Primo's ancient TLS."""
        legacy_ctx = ssl.create_default_context()
        legacy_ctx.options |= _OP_LEGACY
        legacy_ctx.check_hostname = False
        legacy_ctx.verify_mode = ssl.CERT_NONE

        from requests.adapters import HTTPAdapter

        class LegacyAdapter(HTTPAdapter):
            def init_poolmanager(self, *args, **kwargs):
                kwargs["ssl_context"] = legacy_ctx
                return super().init_poolmanager(*args, **kwargs)

            def get_connection_with_tls_context(
                self, request, verify, proxies=None, cert=None
            ):
                # requests adapter hardcodes cert_reqs=CERT_REQUIRED; we need
                # verify=False so our custom SSL context (with legacy renegotiation
                # and cert validation disabled) isn't overridden.
                return super().get_connection_with_tls_context(
                    request, verify=False, proxies=proxies, cert=cert
                )

        sess = requests.Session()
        sess.mount("https://", LegacyAdapter())
        return sess


# Needed by _cas_url property
from urllib.parse import quote

