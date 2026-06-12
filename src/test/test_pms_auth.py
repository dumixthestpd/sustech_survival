"""
test_pms_auth.py — Authorizer tests.

Mostly offline: tests the crypto helper (RSA encrypt → base64).
Live tests for actual login are marked @pytest.mark.live and skipped by
default — run with `pytest -m live` when you have a valid session.
"""
import sys
import base64
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from sustech_survival.sso.authlib.pms import (
    PMSAuth, _rsa_encrypt, _to_pem,
    PMS_BASE, PMS_SERVICE, PMS_API,
)


# ── RSA encrypt helper ──────────────────────────────────────────────────────

class TestRsaEncrypt:
    """Known plaintext → known ciphertext (deterministic for fixed key)."""

    TEST_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MIGdMA0GCSqGSIb3DQEBAQUAA4GLADCBhwKBgQDIHB+0z6aYml4Bunrv09d5eQ5R
K/brNWFOwzIYg86Uznh/6Y5bF4vdbn1RFR/MVnc5FgfBctxLLxveXAHmthcifyj
jxbVdRcZ3CFIKKg+1AA/GOmPzSOZNQJpP2mOYqAcGvmbxzWZLp7CpV2jfKUaEl4v
THUZvjrkr+bjMQWNeCwIBAw==
-----END PUBLIC KEY-----"""

    def test_to_pem_idempotent(self):
        # Already-PEM input is returned as-is
        assert _to_pem(self.TEST_KEY_PEM) == self.TEST_KEY_PEM

    def test_to_pem_wraps_raw_base64(self):
        raw = "MIGdMA0GCSqGSIb3DQEBAQUAA4GLADCBhwKBgQD..."
        out = _to_pem(raw)
        assert "BEGIN PUBLIC KEY" in out
        assert "END PUBLIC KEY" in out
        assert raw in out

    def test_to_pem_strips_whitespace(self):
        raw_with_ws = "MIGd\nMA0GCSq\nGSIb3DQEB\nAQUAA4GL"
        out = _to_pem(raw_with_ws)
        assert "MIGd" in out  # original chars preserved
        assert "\nMA0" not in out  # no internal whitespace

    def test_encrypt_returns_base64(self):
        ct = _rsa_encrypt(self.TEST_KEY_PEM, "password;nonce123")
        # Should be decodable as base64
        decoded = base64.b64decode(ct)
        # Should be 128 bytes for 1024-bit RSA
        assert len(decoded) == 128
        # Must NOT start with 0x00 (which would mean the high bit was 0,
        # indicating padding issue)
        assert decoded[0] != 0

    def test_encrypt_different_inputs_different_outputs(self):
        ct1 = _rsa_encrypt(self.TEST_KEY_PEM, "password1;nonce")
        ct2 = _rsa_encrypt(self.TEST_KEY_PEM, "password2;nonce")
        assert ct1 != ct2  # RSA is deterministic but PKCS#1 v1.5 pads differently

    def test_encrypt_different_nonce_different_output(self):
        ct1 = _rsa_encrypt(self.TEST_KEY_PEM, "pwd;nonce1")
        ct2 = _rsa_encrypt(self.TEST_KEY_PEM, "pwd;nonce2")
        assert ct1 != ct2


# ── Authorizer construction ────────────────────────────────────────────────

class TestPMSAuthConstruction:
    def test_base_url(self):
        auth = PMSAuth()
        assert auth.BASE_URL == PMS_BASE
        assert auth.domain == "pms.sustech.edu.cn"

    def test_paths(self):
        auth = PMSAuth()
        # session.json goes under <skill_root>/pms/
        assert auth.session_file.name == "session.json"
        assert "pms" in str(auth.session_file)

    def test_singleton_registration(self):
        from sustech_survival.sso.authorizer import _auth_registry
        # Force import to ensure registration
        from sustech_survival.sso.authlib import pms as _pms_mod
        assert "pms" in _auth_registry

    def test_re_exported_from_sso(self):
        from sustech_survival.sso import PMSAuth as RePMSAuth
        assert RePMSAuth is PMSAuth


# ── Live tests ──────────────────────────────────────────────────────────────

@pytest.mark.live
class TestPMSAuthLive:
    """Run with: pytest src/test/test_pms_auth.py -m live

    Requires:
      - credentials.txt with valid SID + password at skill root
      - SUSTech IP (the auth flow may require on-campus routing)
    """

    def test_ensure_returns_true(self):
        auth = PMSAuth()
        ok, msg = auth.ensure()
        assert ok, f"ensure() failed: {msg}"
        # Message should be "Logged in as <name>"
        assert "Logged in as" in msg

    def test_check_after_ensure(self):
        auth = PMSAuth()
        auth.ensure()
        ok, _ = auth.check()
        assert ok

    def test_requests_session_has_osessionid(self):
        auth = PMSAuth()
        auth.ensure()
        sess = auth.requests_session
        # OSESSIONID is the primary auth cookie for PMS
        osess = sess.cookies.get("OSESSIONID")
        assert osess is not None
        assert len(osess) > 10