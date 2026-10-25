"""CAS and Primo keep their scoped TLS context — and keep verifying certs."""

import ssl
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from sustech_survival.exceptions import NetworkError
from sustech_survival.sso import LibAuth
from sustech_survival.sso._tls import LegacyTLSAdapter, campus_ssl_context, insecure_mode
from sustech_survival.sso.authorizer import Authorizer, AuthorizerError
from sustech_survival.sso.providers.cas import CASAuthorizer


@pytest.fixture
def auth():
    previous = Authorizer._instances.pop(LibAuth, None)
    instance = LibAuth()
    yield instance
    Authorizer._instances.pop(LibAuth, None)
    if previous is not None:
        Authorizer._instances[LibAuth] = previous


@pytest.fixture(autouse=True)
def _secure_by_default(monkeypatch):
    monkeypatch.delenv("SUSTECH_TLS_INSECURE", raising=False)


@pytest.mark.parametrize("factory", ["_build_cas_session", "_build_session"])
@pytest.mark.parametrize("proxy", [None, "http://proxy.invalid:8080", "https://proxy.invalid:8443"])
@pytest.mark.filterwarnings("ignore:.*get_connection.*:DeprecationWarning")
def test_actual_connection_pool_keeps_legacy_context(auth, factory, proxy):
    session = getattr(auth, factory)()
    adapter = session.get_adapter(auth.BASE_URL)
    assert isinstance(adapter, LegacyTLSAdapter)
    request = requests.Request("GET", auth.BASE_URL).prepare()
    pool = adapter.get_connection_with_tls_context(
        request, verify=True, proxies={"https": proxy} if proxy else {}
    )
    assert pool.conn_kw["ssl_context"] is adapter.ssl_context
    legacy_pool = adapter.get_connection(auth.BASE_URL, proxies={"https": proxy} if proxy else {})
    assert legacy_pool.conn_kw["ssl_context"] is adapter.ssl_context
    assert adapter.ssl_context.options & 0x4
    if proxy:
        assert adapter.proxy_manager_for(proxy) is adapter.proxy_manager_for(proxy)
    assert (
        "ssl_context"
        not in requests.Session().get_adapter(auth.BASE_URL).poolmanager.connection_pool_kw
    )
    session.close()


# -- verification policy ------------------------------------------------------

def test_certificates_are_verified_by_default():
    adapter = LegacyTLSAdapter()
    assert adapter.verify is True
    assert adapter.ssl_context.verify_mode == ssl.CERT_REQUIRED
    assert adapter.ssl_context.check_hostname is True
    # ... while the legacy-renegotiation option this adapter exists for stays on.
    assert adapter.ssl_context.options & 0x4


def test_pool_key_asks_for_a_required_certificate():
    adapter = LegacyTLSAdapter()
    request = requests.Request("GET", "https://cas.sustech.edu.cn/cas/login").prepare()
    _host, pool_kwargs = adapter.build_connection_pool_key_attributes(request, True)
    assert pool_kwargs["ssl_context"] is adapter.ssl_context
    assert pool_kwargs["cert_reqs"] == "CERT_REQUIRED"


def test_caller_verify_false_cannot_downgrade_the_policy():
    """Requests sets CERT_NONE for a falsy ``verify``; the adapter decides."""
    adapter = LegacyTLSAdapter()
    conn = SimpleNamespace()
    adapter.cert_verify(conn, "https://cas.sustech.edu.cn", verify=False, cert=None)
    assert conn.cert_reqs == "CERT_REQUIRED"


@pytest.mark.parametrize("value", ["1", "true", "YES", "on"])
def test_insecure_opt_in_disables_verification(monkeypatch, value):
    monkeypatch.setenv("SUSTECH_TLS_INSECURE", value)
    assert insecure_mode() is True
    adapter = LegacyTLSAdapter()
    assert adapter.verify is False
    assert adapter.ssl_context.verify_mode == ssl.CERT_NONE
    assert adapter.ssl_context.check_hostname is False
    conn = SimpleNamespace()
    adapter.cert_verify(conn, "https://cas.sustech.edu.cn", verify=True, cert=None)
    assert conn.cert_reqs == "CERT_NONE"


@pytest.mark.parametrize("value", ["", "0", "false", "off", "please"])
def test_only_explicit_opt_in_is_insecure(monkeypatch, value):
    monkeypatch.setenv("SUSTECH_TLS_INSECURE", value)
    assert insecure_mode() is False
    assert campus_ssl_context().verify_mode == ssl.CERT_REQUIRED


def test_primo_reuses_ticket_session_with_cookie_domains(auth):
    session = auth._build_cas_session()
    session.cookies.set("TGC", "test-cas-cookie", domain="cas.sustech.edu.cn", path="/cas")
    session.cookies.set("JSESSIONID", "test-primo-cookie", domain=auth._domain, path="/primaws")
    auth._set_session({"TGC": "test-cas-cookie", "JSESSIONID": "test-primo-cookie"})
    assert auth.session is session
    assert {(c.domain, c.path) for c in auth.session.cookies} == {
        ("cas.sustech.edu.cn", "/cas"),
        (auth._domain, "/primaws"),
    }


def test_ticket_tls_failure_names_target_without_leaking_or_relogging(auth, monkeypatch):
    monkeypatch.setattr("sustech_survival.sso.providers.cas._net_attempts", lambda _: 2)
    ticket = auth.SERVICE_URL + "&ticket=ST-PRIVATE-TEST"
    post = Mock(return_value=ticket)
    auth._post_cas = post
    auth._exchange_ticket = Mock(
        side_effect=requests.exceptions.SSLError(
            "UNSAFE_LEGACY_RENEGOTIATION_DISABLED " + ticket + " secret-cookie"
        )
    )
    with pytest.raises(NetworkError) as caught:
        auth._get_ticket_cookies("test-user", "test-password")
    message = str(caught.value)
    assert "CAS ticket exchange" in message and auth._domain in message
    assert "TLS legacy renegotiation disabled" in message
    assert all(
        secret not in message for secret in ["ST-PRIVATE", "secret-cookie", "test-password", "?"]
    )
    assert post.call_count == 1


@pytest.mark.parametrize(
    "html",
    [
        '<input name="execution" value="e1"><input name="captcha">',
        '<input name="execution" value="e1"><div class="g-recaptcha"></div>',
        '<input name="execution" value="e1"><input name="otp">',
    ],
)
def test_cas_challenges_stop_before_credentials(auth, html):
    session = Mock()
    session.get.return_value.text = html
    with pytest.raises(AuthorizerError, match="Interactive CAS challenge"):
        auth._post_cas(session, "test-user", "test-password")
    session.post.assert_not_called()


def test_cas_form_attribute_order_does_not_break_login(auth):
    session = Mock()
    session.get.return_value.text = "<input value='e1' type='hidden' name='execution'>"
    assert auth._fetch_execution(session) == "e1"


def test_different_cookie_cache_does_not_reuse_a_failed_or_old_cas_session(auth):
    old_session = auth._build_cas_session()
    old_session.cookies.set("JSESSIONID", "old-cookie", domain=auth._domain)
    auth._set_session({"JSESSIONID": "replacement-cookie"})
    assert auth.session is not old_session
    assert auth.session.cookies.get("JSESSIONID") == "replacement-cookie"
