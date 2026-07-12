# =============================================================================
# CAS Provider — Central Authentication Service v3.0
# =============================================================================
# Direct CAS login: fetch execution token → POST credentials → exchange ticket.
# Used by: SUSTech BB, TIS, Lib, and any other CAS-protected service.
#
# Flow (all private — consumers see only Authorizer.ensure()):
#   _fetch_execution() → _post_cas() → _exchange_ticket()
#
# No public methods. Authorizer base class handles the lifecycle.
# =============================================================================

import re
import ssl
import urllib3.util.ssl_ as _us_ssl
_orig = _us_ssl.create_urllib3_context
_OP_LEGACY = getattr(ssl, 'OP_LEGACY_SERVER_CONNECT', 0x4)
def patched(protocol=None):
    ctx = _orig(protocol)
    ctx.options |= _OP_LEGACY
    return ctx
_us_ssl.create_urllib3_context = patched
import requests
from ..authorizer import Authorizer, AuthorizerError, CAS_BASE, UA
from sustech_survival.exceptions import InvalidCredentials, NetworkError


class CASAuthorizer(Authorizer):
    """
    CAS 3.0 ticket-granting authentication.

    Supports headless login for any CAS-compatible IdP. Handles both patterns:
      - Most services: cookies arrive on the final redirect to SERVICE_URL
      - TIS pattern:   cookies arrive on the GET to the ticket URL itself

    Additional class attributes:
        SUBMIT_VALUE   — value for submit button. None = omit, "提交" = Chinese "submit"
        _idp_cas_base  — override CAS endpoint (e.g. for federated IdPs)
    """

    SUBMIT_VALUE: str = "提交"  # works for BB/Lib; None to skip
    _idp_cas_base: str = CAS_BASE

    # ── Private CAS flow ─────────────────────────────────────────────────────

    def _get_ticket_cookies(self, username: str, password: str) -> dict:
        """Full headless CAS flow. Returns cookie dict.

        Raises ``InvalidCredentials`` if CAS rejects the username/password,
        ``NetworkError`` if CAS is unreachable, or ``AuthorizerError`` for
        unexpected response formats.
        """
        sess = self._build_cas_session()
        sess.headers['User-Agent'] = UA
        try:
            ticket_url = self._post_cas(sess, username, password)
            cookies = self._exchange_ticket(sess, ticket_url)
        except requests.ConnectionError as e:
            raise NetworkError(f"Cannot reach CAS at {self._cas_url}: {e}")
        except requests.Timeout as e:
            raise NetworkError(f"CAS timeout at {self._cas_url}: {e}")
        except InvalidCredentials:
            raise
        if not cookies:
            raise AuthorizerError("No cookies received after CAS ticket exchange.")
        return cookies

    def _fetch_execution(self, sess: requests.Session) -> str:
        r = sess.get(self._cas_url, headers=self._headers, timeout=10)
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
            raise InvalidCredentials(
                "CAS rejected credentials — wrong username or password.\n"
                f"Check credentials.txt at {self._creds_file}"
            )
        return loc

    def _exchange_ticket(self, sess: requests.Session, ticket_url: str) -> dict:
        r = sess.get(ticket_url, allow_redirects=True, headers=self._headers, timeout=10)
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
