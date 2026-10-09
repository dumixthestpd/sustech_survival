"""Legacy browser logins resolve shared credentials before opening a browser."""

import sys
from types import ModuleType

import pytest

from sustech_survival.sso import cred_clear, cred_set
from sustech_survival.sso.authlib.cnki import CNKIAuth
from sustech_survival.sso.authlib.rsc import RSCAuthorizer
from sustech_survival.sso.authlib.wos import WoSAuth


@pytest.mark.parametrize(
    "auth_type,method",
    [
        (CNKIAuth, "login"),
        (RSCAuthorizer, "login"),
        (WoSAuth, "login"),
    ],
)
def test_browser_login_uses_in_memory_credentials_before_browser(
    monkeypatch, tmp_path, auth_type, method
):
    class BrowserReached(Exception):
        pass

    def stop_before_browser():
        raise BrowserReached

    monkeypatch.setenv("SUSTECH_CREDENTIALS", str(tmp_path / "missing.txt"))
    playwright = ModuleType("playwright")
    playwright.__path__ = []
    sync_api = ModuleType("playwright.sync_api")
    sync_api.sync_playwright = stop_before_browser
    monkeypatch.setitem(sys.modules, "playwright", playwright)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api)
    cred_set("sid", "pw:part")
    try:
        auth = auth_type(skill_dir=str(tmp_path / "obsolete"))
        with pytest.raises(BrowserReached):
            getattr(auth, method)()
    finally:
        cred_clear()
