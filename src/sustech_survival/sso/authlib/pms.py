# =============================================================================
# PMS (联创打印管理系统) — Unifound cloud print authorizer
# =============================================================================
# PMS does NOT use SUSTech CAS directly. Its login flow is custom:
#
#   1. POST /api/client/Auth/GetAuthToken     → { szToken }
#   2. GET  /api/client/Auth/PublicKey         → { publicKey, nonceStr }
#   3. Encrypt `password + ";" + nonceStr` with the RSA public key (PKCS#1 v1.5)
#   4. POST /api/client/Auth/Login            { szLogonName, szPassword, szToken }
#      → sets `OSESSIONID` cookie on the pms.sustech.edu.cn domain
#
# However, the page is also CAS-fronted: visiting any PMS URL while unauth'd
# redirects through https://cas.sustech.edu.cn/cas/login and the back-end
# links your CAS identity to your print account at first login (creates
# the account if needed). If the print account doesn't exist, /Auth/Check
# returns the message "云打印系统内没有您的账号信息，请联系图书馆技术部处理".
#
# This authorizer handles BOTH paths:
#   - login_password()      — direct username/password (requires print account)
#   - login_via_cas()       — full CAS SSO flow; lets PMS auto-link account
#
# After either path, call `auth.check()` to confirm the session is alive
# before doing anything else.
# =============================================================================

import json
import time
from pathlib import Path
from typing import Optional, Tuple

import requests
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5 as PKCS1Padding

from ..authorizer import Authorizer, AuthorizerError, UA, register_auth


PMS_BASE = "https://pms.sustech.edu.cn"
PMS_SERVICE = f"{PMS_BASE}/client/new/cprintPc/"
PMS_API = f"{PMS_BASE}/api"


class PMSAuth(Authorizer):
    """Headless login for the SUSTech 联创 PMS cloud print system.

    Subclass of Authorizer — does NOT inherit from CASAuthorizer.
    PMS uses its own RSA-encrypted login API rather than standard CAS.

    Storage: in-memory only (session_cache). Use refresh() to re-populate
    from session.json after a fresh process start (auto-applied via ensure()).
    """

    BASE_URL = PMS_BASE
    SERVICE_URL = PMS_SERVICE

    # ── Paths ────────────────────────────────────────────────────────────────

    @property
    def submodule_dir(self) -> Path:
        return self.skill_root / "pms"

    @property
    def session_file(self) -> Path:
        return self.submodule_dir / "session.json"

    # ── Session management ────────────────────────────────────────────────────

    def check(self) -> Tuple[bool, str]:
        """Is the current session still authenticated? Calls /Auth/Check."""
        sess = self._api_session()
        r = sess.post(
            f"{PMS_API}/client/Auth/Check",
            timeout=10,
        )
        try:
            data = r.json()
        except Exception:
            return False, f"Non-JSON response from /Auth/Check (HTTP {r.status_code})"

        if data.get("code") == 0:
            name = (data.get("result") or {}).get("szTrueName", "<unknown>")
            return True, f"Logged in as {name}"
        return False, data.get("message", "Not authenticated")

    def ensure(self) -> Tuple[bool, str]:
        """check() + auto-refresh from disk + auto-login if needed."""
        # Always try disk first on a fresh process
        if not self.is_session_fresh():
            self.refresh()  # loads from disk if present
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

    # ── Direct login (RSA + token) ────────────────────────────────────────────

    def login_password(
        self, username: Optional[str] = None, password: Optional[str] = None
    ) -> str:
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
        r = sess.post(f"{PMS_API}/client/Auth/GetAuthToken", timeout=10)
        tok = r.json()
        if tok.get("code") != 0:
            raise AuthorizerError(f"GetAuthToken failed: {tok.get('message')}")
        sz_token = tok["szToken"]

        # Step 2: get public key + nonce
        r = sess.get(f"{PMS_API}/client/Auth/PublicKey", timeout=10)
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
            timeout=10,
        )
        out = r.json()
        if out.get("code") != 0:
            raise AuthorizerError(
                f"Login failed: {out.get('message', 'unknown')} "
                f"(code={out.get('code')})"
            )

        # Pull OSESSIONID (and any other auth cookies) into the in-memory cache
        cookies_dict = {c.name: c.value for c in sess.cookies}
        self.set_session(cookies_dict)
        self._save_session()

        result = out.get("result") or {}
        return result.get("szTrueName", username)

    # ── CAS SSO login ────────────────────────────────────────────────────────

    def login_via_cas(self, headless: bool = False) -> str:
        """Full CAS SSO flow via Playwright. Use when print account doesn't exist
        yet — the PMS back-end will auto-link the CAS identity on first login.
        """
        from playwright.sync_api import sync_playwright

        cf = Path(self.creds_file)
        if not cf.exists():
            raise AuthorizerError(f"No credentials at {cf}")
        line = cf.read_text().strip()
        if ":" not in line:
            raise AuthorizerError("credentials.txt malformed (no ':' separator)")
        username, password = [s.strip() for s in line.split(":", 1)]

        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=headless)
        ctx = browser.new_context()
        page = ctx.new_page()
        try:
            page.goto(PMS_SERVICE, wait_until="commit", timeout=30000)
            page.wait_for_load_state("networkidle", timeout=15000)

            if "cas.sustech.edu.cn" in page.url:
                page.fill('input[type="text"], input[name="username"]', username)
                page.fill('input[type="password"], input[name="password"]', password)
                btn = page.get_by_role("button", name="登录")
                if not btn.count():
                    btn = page.locator("button:has-text('登录')").first
                btn.click()
                page.wait_for_load_state("networkidle", timeout=20000)

            # Drain any further redirects
            for _ in range(5):
                page.wait_for_timeout(1500)
                if page.url.startswith(PMS_SERVICE) and "cas.sustech.edu.cn" not in page.url:
                    break

            cookies = {c["name"]: c["value"] for c in ctx.cookies(PMS_BASE)}
            self.set_session(cookies)
            self._save_session()

            ok, msg = self.check()
            if not ok:
                raise AuthorizerError(f"CAS login landed but not authed: {msg}")
            return msg
        finally:
            browser.close()
            pw.stop()

    # ── Persistence ──────────────────────────────────────────────────────────

    def _save_session(self) -> None:
        self.submodule_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "saved_at": time.time(),
            "cookies": self.session_cache,
        }
        self.session_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2))

    def refresh(self) -> bool:
        """Load saved session from disk into in-memory cache.

        Returns True if a saved session was found, False otherwise.
        """
        sf = self.session_file
        if not sf.exists():
            return False
        payload = json.loads(sf.read_text())
        cookies = payload.get("cookies") or {}
        if cookies:
            self.set_session(cookies)
        return True

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _api_session(self) -> requests.Session:
        """A requests.Session pre-loaded with the in-memory cookies + JSON headers."""
        sess = self.requests_session  # uses apply_cookies() internally
        sess.headers.update({
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
        })
        return sess


# ── Crypto helper ────────────────────────────────────────────────────────────

def _rsa_encrypt(public_key_pem: str, plaintext: str) -> str:
    """Encrypt `plaintext` with RSA public key, return base64-encoded ciphertext.

    Matches JSEncrypt.encrypt() — PKCS#1 v1.5 padding, base64 output.
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
    lines = [b64[i:i + 64] for i in range(0, len(b64), 64)]
    body = "\n".join(lines)
    return f"-----BEGIN PUBLIC KEY-----\n{body}\n-----END PUBLIC KEY-----"


# ── Module-level singleton ───────────────────────────────────────────────────

_auth = PMSAuth()  # resolves skill_root by walking up looking for credentials.txt
register_auth("pms", _auth)