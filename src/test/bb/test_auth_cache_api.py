"""Regression tests for BB helpers after the SSO cache API cleanup."""
from __future__ import annotations

import importlib
from types import SimpleNamespace
from unittest.mock import MagicMock

import requests


def _fake_auth(*, populated: bool = True):
    session = requests.Session()
    session.cookies.set("JSESSIONID", "redacted-session")
    cache = {"JSESSIONID": "redacted-session"} if populated else {}
    return SimpleNamespace(
        _session_cache=cache,
        session=session,
        refresh=MagicMock(return_value=True),
    )


def test_submit_session_helper_uses_private_cache(monkeypatch):
    module = importlib.import_module("sustech_survival.bb.submit")
    fake = _fake_auth()
    monkeypatch.setattr(module, "BBAuth", lambda: fake)

    session = module._bb_session()

    assert session.cookies.get("JSESSIONID") == "redacted-session"


def test_submit_session_helper_refreshes_empty_private_cache(monkeypatch):
    module = importlib.import_module("sustech_survival.bb.submit")
    fake = _fake_auth(populated=False)
    monkeypatch.setattr(module, "BBAuth", lambda: fake)

    module._bb_session()

    fake.refresh.assert_called_once_with()


def test_items_discovery_helper_uses_private_cache(monkeypatch):
    module = importlib.import_module("sustech_survival.bb.items")
    fake = _fake_auth()
    import sustech_survival.sso as sso

    monkeypatch.setattr(sso, "BBAuth", lambda: fake)

    session = module._bb_session_for_discovery()

    assert session.cookies.get("JSESSIONID") == "redacted-session"
