"""Offline regression coverage for PMS's dynamic CAS handshake."""

import importlib
import json
import sys
from types import ModuleType
from urllib.parse import quote

import pytest
import requests

from sustech_survival.pms import PMSError
from sustech_survival.sso import cred_clear, cred_set
from sustech_survival.sso.authlib.pms import PMS_BASE, PMS_SERVICE, PMSAuth


def response(url, payload=None, status=200, text="", location=None):
    r = requests.Response()
    r.url = url
    r.status_code = status
    r._content = json.dumps(payload).encode() if payload is not None else text.encode()
    if location:
        r.headers["Location"] = location
    return r


class SSO:
    callback = PMS_BASE + "/authcenter/callback?state=dynamic-value"

    def __init__(self, challenge=False):
        self.headers = {}
        self.cookies = requests.cookies.RequestsCookieJar()
        self.calls = []
        self.challenge = challenge

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        if url.endswith("/SSoPage"):
            assert kwargs["params"] == {"backurl": PMS_SERVICE}
            self.cookies.set("bootstrap", "memory-only", domain="pms.sustech.edu.cn")
            return response(url, {"code": 0, "result": "/authcenter/toLoginPage"})
        if url.endswith("/toLoginPage"):
            return response(
                url,
                status=302,
                location="https://cas.sustech.edu.cn/cas/login?service="
                + quote(self.callback, safe=""),
            )
        if "cas.sustech.edu.cn/cas/login?" in url:
            assert self.cookies.get("bootstrap") == "memory-only"
            assert quote(self.callback, safe="") in url
            form = '<input name="execution" value="execution-value">'
            if self.challenge:
                form += '<input name="captcha">'
            return response(url, text=form)
        if url.startswith(self.callback):
            assert self.cookies.get("bootstrap") == "memory-only"
            self.cookies.set("OSESSIONID", "authenticated", domain="pms.sustech.edu.cn")
            return response(url)
        raise AssertionError("Unexpected GET")

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        if "cas.sustech.edu.cn/cas/login?" in url:
            assert kwargs["data"]["execution"] == "execution-value"
            return response(url, status=302, location=self.callback + "&ticket=one-use")
        if url.endswith("/Auth/Check"):
            return response(url, {"code": 0, "result": {}})
        raise AssertionError("Unexpected POST")


@pytest.fixture
def auth(monkeypatch):
    a = PMSAuth()
    monkeypatch.setattr(a, "_session_cache", {})
    monkeypatch.setattr(a, "_pms_session", None, raising=False)
    monkeypatch.setattr(a, "_read_creds", lambda: ("fake-student", "fake-password"))
    return a


def test_default_ensure_follows_dynamic_sso_with_bootstrap_cookies(auth, monkeypatch):
    session = SSO()
    monkeypatch.setattr(auth, "_build_cas_session", lambda: session)
    ok, _ = auth.ensure()
    assert ok
    assert auth.session is session
    assert auth.SERVICE_URL == session.callback
    assert "OSESSIONID" in auth._session_cache
    login_posts = [x for x in session.calls if x[0] == "POST" and "/cas/login?" in x[1]]
    assert len(login_posts) == 1
    assert auth.ensure()[0]
    assert len([x for x in session.calls if x[0] == "POST" and "/cas/login?" in x[1]]) == 1


def test_captcha_stops_before_credentials_post(auth, monkeypatch):
    session = SSO(challenge=True)
    monkeypatch.setattr(auth, "_build_cas_session", lambda: session)
    assert not auth.ensure()[0]
    assert not any(x[0] == "POST" for x in session.calls)


def test_failed_login_is_not_repeated_by_ensure(auth, monkeypatch):
    calls = []
    monkeypatch.setattr(auth, "_refresh", lambda: calls.append("login") or False)
    assert not auth.ensure()[0]
    assert calls == ["login"]


def test_network_failure_does_not_start_another_login(auth, monkeypatch):
    session = SSO()

    def failed(*args, **kwargs):
        raise requests.Timeout("fake timeout")

    session.get = failed
    monkeypatch.setattr(auth, "_build_cas_session", lambda: session)
    assert not auth.ensure()[0]
    assert auth._session_cache == {}


def test_check_failure_does_not_refresh_on_upstream_error(auth, monkeypatch):
    monkeypatch.setattr(auth, "_session_cache", {"cookie": "fake"})
    session = SSO()
    session.post = lambda url, **kwargs: response(url, {"code": 500, "message": "unavailable"})
    monkeypatch.setattr(auth, "_api_session", lambda: session)
    monkeypatch.setattr(auth, "_refresh", lambda: pytest.fail("unexpected login"))
    assert not auth.ensure()[0]


def test_expired_session_uses_one_normal_sso_login(auth, monkeypatch):
    stale = SSO()
    stale.post = lambda url, **kwargs: response(url, {"code": 4294967295})
    monkeypatch.setattr(auth, "_session_cache", {"expired": "fake"})
    monkeypatch.setattr(auth, "_pms_session", stale)
    fresh = SSO()
    monkeypatch.setattr(auth, "_build_cas_session", lambda: fresh)
    assert auth.ensure()[0]
    assert auth.session is fresh
    assert len([x for x in fresh.calls if x[0] == "POST" and "/cas/login?" in x[1]]) == 1


def test_offcampus_check_does_not_start_a_login(auth, monkeypatch):
    session = SSO()
    session.post = lambda url, **kwargs: response(
        url, status=403, text="Access forbidden, please contact administrator."
    )
    monkeypatch.setattr(auth, "_session_cache", {"session": "fake"})
    monkeypatch.setattr(auth, "_pms_session", session)
    monkeypatch.setattr(auth, "_refresh", lambda: pytest.fail("unexpected login"))
    assert not auth.ensure()[0]


def test_cached_default_client_is_updated_after_authorizer_relogin(auth, monkeypatch):
    module = importlib.import_module("sustech_survival.pms.pms")
    monkeypatch.setattr(auth, "ensure", lambda: (True, "ok"))
    first = SSO()
    monkeypatch.setattr(auth, "_session_cache", {"session": "fake"})
    monkeypatch.setattr(auth, "_pms_session", first)
    monkeypatch.setattr(module, "_pms_client", None)
    client = module.pms()
    second = SSO()
    monkeypatch.setattr(auth, "_pms_session", second)
    assert module.pms() is client
    assert client.session is second


def test_unexpected_callback_host_stops_before_cas_post(auth, monkeypatch):
    session = SSO()
    session.callback = "https://example.org/callback"
    monkeypatch.setattr(auth, "_build_cas_session", lambda: session)
    assert not auth.ensure()[0]
    assert not any(x[0] == "POST" for x in session.calls)


def test_default_client_preserves_auth_failure(auth, monkeypatch):
    module = importlib.import_module("sustech_survival.pms.pms")
    monkeypatch.setattr(auth, "ensure", lambda: (False, "PMS is unavailable"))
    with pytest.raises(PMSError, match="PMS is unavailable"):
        module._build_default_client()


def test_cas_convenience_uses_shared_credentials_without_browser(monkeypatch, tmp_path):
    auth = PMSAuth()
    monkeypatch.setattr(auth, "_session_cache", {})
    monkeypatch.setattr(auth, "_pms_session", None, raising=False)
    monkeypatch.setenv("SUSTECH_CREDENTIALS", str(tmp_path / "missing"))
    calls = []

    def ticket(username, password):
        calls.append((username, password))
        return {"OSESSIONID": "fake-session"}

    module = ModuleType("playwright.sync_api")
    module.sync_playwright = lambda: pytest.fail("PMS must not open a browser")
    monkeypatch.setitem(sys.modules, "playwright.sync_api", module)
    monkeypatch.setattr(auth, "_get_ticket_cookies", ticket)
    monkeypatch.setattr(auth, "_api_session", lambda: SSO())
    cred_set("fake-student", "fake-password:part")
    try:
        assert auth.login_via_cas() == "Logged in to PMS"
        assert calls == [("fake-student", "fake-password:part")]
    finally:
        cred_clear()
