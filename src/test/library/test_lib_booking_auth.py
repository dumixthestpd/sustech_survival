"""Offline regression tests for the IC library booking authenticator."""
from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from sustech_survival.lib.booking.auth import LibBookingAuth
from sustech_survival.sso.authorizer import Authorizer


@pytest.fixture
def auth(tmp_path: Path):
    """Give each test an isolated LibBookingAuth singleton instance."""
    previous = Authorizer._instances.pop(LibBookingAuth, None)
    instance = LibBookingAuth(skill_dir=str(tmp_path))
    instance._session_cache = {}
    instance._user_info = None
    yield instance
    Authorizer._instances.pop(LibBookingAuth, None)
    if previous is not None:
        Authorizer._instances[LibBookingAuth] = previous


def test_refresh_uses_current_private_cas_api(auth):
    """Dynamic authcenter login must use the renamed CAS hooks."""
    original_service_url = auth.SERVICE_URL
    auth.read_creds = MagicMock(return_value=("sid", "password"))
    auth._resolve_cas_service_url = MagicMock(
        return_value="https://cas.sustech.edu.cn/cas/login?service=dynamic"
    )
    auth._get_ticket_cookies = MagicMock(
        return_value={"ic-cookie": "redacted-cookie", "TGC": "redacted-tgc"}
    )
    auth._fetch_user_info = MagicMock(return_value={"trueName": "Test User"})

    assert auth.refresh() is True

    auth._get_ticket_cookies.assert_called_once_with("sid", "password")
    assert auth.SERVICE_URL == original_service_url
    assert auth._session_cache == {
        "ic-cookie": "redacted-cookie",
        "TGC": "redacted-tgc",
    }
    assert auth._user_info == {"trueName": "Test User"}


def test_check_reads_private_session_cache(auth):
    """The booking-specific check follows Authorizer's private cache API."""
    assert auth.check() == (False, "No session — login needed.")

    auth._session_cache = {"TGC": "redacted-tgc"}
    assert auth.check() == (False, "No ic-cookie in session — login needed.")

    auth._session_cache = {
        "ic-cookie": "redacted-cookie",
        "TGC": "redacted-tgc",
    }
    assert auth.check() == (True, "Session has 2 cookies")


def test_session_builder_applies_cached_cookie(auth):
    """The internal session hook must retain cookies for userInfo calls."""
    auth._session_cache = {"ic-cookie": "redacted-cookie"}

    session = auth.session

    assert session.headers["User-Agent"]
    assert session.cookies.get("ic-cookie") == "redacted-cookie"
    # Existing callers of the old public helper receive the same fixed
    # session rather than a cookie-less requests.Session.
    assert auth.build_session().cookies.get("ic-cookie") == "redacted-cookie"


def test_lib_booking_initialization_reuses_private_cache(monkeypatch):
    """The singleton client must copy cookies after the new auth API."""
    client_module = importlib.import_module("sustech_survival.lib.booking.client")
    auth_module = importlib.import_module("sustech_survival.lib.booking.auth")
    fake_auth = SimpleNamespace(
        _session_cache={
            "ic-cookie": "redacted-cookie",
            "TGC": "redacted-tgc",
        },
        ensure=MagicMock(return_value=(True, "ok")),
    )
    previous = client_module._BOOKING_INSTANCE
    client_module._BOOKING_INSTANCE = None
    monkeypatch.setattr(auth_module, "LibBookingAuth", lambda: fake_auth)
    try:
        client = client_module.lib_booking()
        cookies = client.s.cookies.get_dict()
    finally:
        client_module._BOOKING_INSTANCE = previous

    assert cookies["ic-cookie"] == "redacted-cookie"
    assert cookies["TGC"] == "redacted-tgc"
    fake_auth.ensure.assert_called_once_with()
