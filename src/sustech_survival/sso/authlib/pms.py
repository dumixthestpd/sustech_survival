"""PMS authentication through its dynamic SSO entry and the shared CAS provider.

The direct RSA print-account login remains an explicit alternative; campus CAS
credentials are used by ensure() through the website's SSO flow.
"""

import json
from typing import Optional, Tuple
from urllib.parse import parse_qs, urljoin, urlsplit

import requests
from bs4 import BeautifulSoup
from Crypto.Cipher import PKCS1_v1_5 as PKCS1Padding
from Crypto.PublicKey import RSA

from sustech_survival import _net
from sustech_survival.exceptions import NetworkError

from ...pms.pms import OFF_CAMPUS_HINT, _looks_off_campus
from ..authorizer import UA, AuthorizerError
from ..providers.cas import CASAuthorizer

PMS_BASE = "https://pms.sustech.edu.cn"
PMS_SERVICE = f"{PMS_BASE}/client/new/cprintPc/printDoc.html"
PMS_API = f"{PMS_BASE}/api"


class PMSAuth(CASAuthorizer):
    """In-memory PMS SSO session, retaining cookies from the SSO bootstrap."""

    SERVICE = "pms"
    BASE_URL = PMS_BASE
    SERVICE_URL = PMS_SERVICE
    SUBMIT_VALUE = ""

    def check(self) -> Tuple[bool, str]:
        """Read Auth/Check without starting another login or disclosing identity."""
        self._check_needs_login = not bool(self._session_cache)
        if not self._session_cache:
            return False, "No PMS session; login needed"
        try:
            r = self._api_session().post(
                f"{PMS_API}/client/Auth/Check", timeout=_net.service_timeout("pms")
            )
            if _looks_off_campus(r):
                return False, OFF_CAMPUS_HINT
            if r.status_code == 401:
                self._check_needs_login = True
                return False, "PMS session expired (HTTP 401)"
            r.raise_for_status()
            data = r.json()
            if not isinstance(data, dict):
                raise ValueError
        except requests.RequestException as exc:
            return False, f"PMS Auth/Check failed ({type(exc).__name__})"
        except ValueError:
            return False, f"Non-JSON/invalid response from Auth/Check (HTTP {r.status_code})"
        if data.get("code") == 0 and isinstance(data.get("result"), dict):
            return True, "Logged in to PMS"
        self._check_needs_login = data.get("code") == 4294967295
        return False, f"PMS authentication unavailable (code={data.get('code')})"

    def ensure(self) -> Tuple[bool, str]:
        """Reuse a verified session, or complete one normal dynamic CAS login."""
        ok, reason = self.check()
        if ok or not self._check_needs_login:
            return ok, reason
        if not self._refresh():
            return False, self._refresh_error_message()
        return self.check()

    def _get_ticket_cookies(self, username: str, password: str) -> dict:
        # Use the same cookie jar for SSoPage, authcenter, CAS and the callback.
        sess = self._build_cas_session()
        sess.headers.update({"User-Agent": UA})
        try:
            r = sess.get(
                f"{PMS_API}/client/Auth/SSoPage",
                params={"backurl": PMS_SERVICE},
                timeout=_net.service_timeout("pms"),
            )
            if _looks_off_campus(r):
                raise AuthorizerError(OFF_CAMPUS_HINT)
            r.raise_for_status()
            try:
                data = r.json()
            except ValueError:
                raise AuthorizerError("PMS SSO entry returned non-JSON content") from None
            if (
                not isinstance(data, dict)
                or data.get("code") != 0
                or not isinstance(data.get("result"), str)
            ):
                raise AuthorizerError("PMS SSO entry is unavailable")
            entry = urljoin(PMS_BASE, data["result"])
            for _ in range(6):
                target = urlsplit(entry)
                if (
                    target.scheme == "https"
                    and target.netloc == "cas.sustech.edu.cn"
                    and target.path == "/cas/login"
                ):
                    break
                if target.scheme != "https" or target.netloc != "pms.sustech.edu.cn":
                    raise AuthorizerError("Unexpected PMS SSO host; stopped")
                r = sess.get(entry, allow_redirects=False, timeout=_net.service_timeout("pms"))
                if _looks_off_campus(r):
                    raise AuthorizerError(OFF_CAMPUS_HINT)
                r.raise_for_status()
                if r.status_code not in self.REDIRECT_STATUS or not r.headers.get("Location"):
                    raise AuthorizerError("Interactive or unsupported PMS SSO page; stopped")
                entry = urljoin(entry, r.headers["Location"])
            else:
                raise AuthorizerError("PMS SSO redirect limit reached")
            services = parse_qs(target.query).get("service", [])
            callback = urlsplit(services[0]) if len(services) == 1 else None
            if (
                not callback
                or callback.scheme != "https"
                or callback.netloc != "pms.sustech.edu.cn"
            ):
                raise AuthorizerError("Unexpected PMS CAS callback; stopped")
            # The callback includes dynamic state. Never hard-code or log it.
            self.SERVICE_URL = services[0]
            try:
                ticket_url = self._post_cas(sess, username, password)
            except AuthorizerError:
                raise AuthorizerError(
                    "PMS CAS login failed or requires interactive authentication"
                ) from None
            destination = urlsplit(ticket_url)
            if destination.scheme != "https" or destination.netloc != "pms.sustech.edu.cn":
                raise AuthorizerError("Unexpected PMS ticket destination; stopped")
            self._exchange_ticket(sess, ticket_url)
            cookies = {
                c.name: c.value
                for c in sess.cookies
                if c.domain.lstrip(".") == "pms.sustech.edu.cn"
            }
            if not cookies:
                raise AuthorizerError("PMS SSO did not establish a session")
            self._pms_session = sess
            return cookies
        except requests.RequestException as exc:
            raise NetworkError(f"PMS SSO request failed ({type(exc).__name__})") from None

    def _fetch_execution(self, sess: requests.Session) -> str:
        r = sess.get(self._cas_url, headers=self._headers, timeout=self._login_timeout())
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        if soup.select(
            'input[name*="captcha" i], input[id*="captcha" i], .g-recaptcha, .h-captcha, iframe[src*="recaptcha"], input[name="otp"]'
        ):
            raise AuthorizerError("Interactive CAS challenge; stopped before credential POST")
        node = soup.select_one('input[name="execution"]')
        if not node or not node.get("value"):
            raise AuthorizerError("CAS login form unavailable; stopped before credential POST")
        return node["value"]

    def _build_session(self) -> requests.Session:
        # Preserve cookie domains/paths and rotations from the live SSO session.
        if getattr(self, "_pms_session", None) is not None:
            return self._pms_session
        return super()._build_session()

    # -- Direct login (RSA + token) --------------------------------------------

    def login_password(self, username: Optional[str] = None, password: Optional[str] = None) -> str:
        """Login with print-system username + password (RSA-encrypted).

        Returns the szTrueName (Chinese display name) on success.
        Raises AuthorizerError on failure.
        """
        username = username or self.username
        password = password or self.password
        if not username or not password:
            raise AuthorizerError("PMSAuth.login_password() needs username+password")

        sess = requests.Session()
        sess.headers.update({"User-Agent": UA, "Referer": PMS_SERVICE})

        # Step 1: get auth token
        r = sess.post(
            f"{PMS_API}/client/Auth/GetAuthToken", timeout=_net.timeouts().service_timeout("pms")
        )
        if _looks_off_campus(r):
            raise AuthorizerError(OFF_CAMPUS_HINT)
        tok = r.json()
        if tok.get("code") != 0:
            raise AuthorizerError(f"GetAuthToken failed: {tok.get('message')}")
        sz_token = tok["szToken"]

        # Step 2: get public key + nonce
        r = sess.get(
            f"{PMS_API}/client/Auth/PublicKey", timeout=_net.timeouts().service_timeout("pms")
        )
        if _looks_off_campus(r):
            raise AuthorizerError(OFF_CAMPUS_HINT)
        pk = r.json()
        if pk.get("code") != 0:
            raise AuthorizerError(f"PublicKey failed: {pk.get('message')}")
        public_key_pem = pk["result"]["publicKey"]
        nonce_str = pk["result"]["nonceStr"]

        # Step 3: encrypt password + nonce with RSA PKCS#1 v1.5
        encrypted = _rsa_encrypt(public_key_pem, password + ";" + nonce_str)

        # Step 4: POST login
        payload = {
            "szLogonName": username,
            "szPassword": encrypted,
            "szToken": sz_token,
        }
        r = sess.post(
            f"{PMS_API}/client/Auth/Login",
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
            timeout=_net.timeouts().service_timeout("pms"),
        )
        if _looks_off_campus(r):
            raise AuthorizerError(OFF_CAMPUS_HINT)
        out = r.json()
        if out.get("code") != 0:
            raise AuthorizerError(
                f"Login failed: {out.get('message', 'unknown')} " f"(code={out.get('code')})"
            )

        # Pull OSESSIONID (and any other auth cookies) into the in-memory cache
        cookies_dict = {c.name: c.value for c in sess.cookies}
        self._pms_session = sess
        self._set_session(cookies_dict)

        result = out.get("result") or {}
        return result.get("szTrueName", username)

    # -- CAS SSO login --------------------------------------------------------

    def login_via_cas(self, headless: bool = False) -> str:
        """Complete the normal SSO flow without browser automation.

        ``headless`` is retained for compatibility; no browser is launched.
        """
        ok, reason = self.ensure()
        if not ok:
            raise AuthorizerError(reason)
        return reason

    # -- Refresh ----------------------------------------------------------------

    def refresh(self) -> bool:
        """Refresh session via ticket cookies (no disk)."""
        return self._refresh()

    # -- Internal helpers ------------------------------------------------------

    def _api_session(self) -> requests.Session:
        """A requests.Session pre-loaded with the in-memory cookies + JSON headers."""
        sess = self.session
        sess.headers.update(
            {
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "X-Requested-With": "XMLHttpRequest",
            }
        )
        return sess


# -- Crypto helper ------------------------------------------------------------


def _rsa_encrypt(public_key_pem: str, plaintext: str) -> str:
    """Encrypt `plaintext` with RSA public key, return base64-encoded ciphertext.

    Matches JSEncrypt.encrypt() 鈥?PKCS#1 v1.5 padding, base64 output.
    PMS uses 1024-bit keys; output is ~172 base64 chars.

    The server returns the key as raw base64 (no PEM headers). We accept
    either form.
    """
    import base64

    pem = _to_pem(public_key_pem)
    key = RSA.import_key(pem)
    cipher = PKCS1Padding.new(key)
    ciphertext = cipher.encrypt(plaintext.encode("utf-8"))
    return base64.b64encode(ciphertext).decode("ascii")


def _to_pem(key: str) -> str:
    """Normalize a public key to PEM format. Accepts:
    - Full PEM: '-----BEGIN PUBLIC KEY-----\\n<base64>\\n-----END PUBLIC KEY-----'
    - Raw base64 (PMS default): wraps with the BEGIN/END markers.
    """
    if "BEGIN PUBLIC KEY" in key:
        return key
    # Wrap raw base64 in PEM markers, breaking lines at 64 chars per RFC 7468
    b64 = "".join(key.split())
    lines = [b64[i : i + 64] for i in range(0, len(b64), 64)]
    body = "\n".join(lines)
    return f"-----BEGIN PUBLIC KEY-----\n{body}\n-----END PUBLIC KEY-----"


# -- Module-level singleton ---------------------------------------------------

_auth = PMSAuth()  # credentials resolved by the shared Authorizer on demand
