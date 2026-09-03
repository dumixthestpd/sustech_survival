"""
Regression tests for `sustech tis schedule` — the personal-timetable CLI.

Bug (2026-09-02, user report): `sustech tis schedule` with no arguments
crashed with a raw ``ValueError: invalid literal for int() with base 10:
''`` traceback. Root cause: `tis/schedule.py current_week()` did a bare
``int(sess.post(...).text)`` on TIS's `querydangqianzc` endpoint. Before
the term starts TIS returns an EMPTY body (every row is still 待生效 /
pending activation, so there is no "current week" yet); a stale session
returns a JSON "please log in again" page. Both crashed the CLI instead
of producing a usable message.

The fix parses defensively: a bare integer string returns the week, an
empty body raises a clear APIError pointing at `--zc N` / `--all`, and a
JSON auth page raises an APIError suggesting `sustech tis session
refresh`. These tests mock the session — no live TIS calls.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sustech_survival.exceptions import APIError
from sustech_survival.tis import schedule as schedule_mod
from sustech_survival.tis import cli as tis_cli


class _FakeResp:
    def __init__(self, text: str):
        self.text = text

    def json(self):
        return json.loads(self.text or "{}")


class _FakeSession:
    """One canned body for every POST — enough for the week lookup."""

    def __init__(self, text: str):
        self._text = text

    def post(self, url, data=None, **kw):
        return _FakeResp(self._text)


@pytest.fixture()
def fake_week_response(monkeypatch):
    """Point schedule.session() at a canned responder and bypass auth."""

    def _install(body: str):
        monkeypatch.setattr(schedule_mod, "_auth_instance", object())
        monkeypatch.setattr(schedule_mod, "session", lambda: _FakeSession(body))

    return _install


# -- current_week() ----------------------------------------------------------

def test_current_week_returns_int_for_numeric_body(fake_week_response):
    fake_week_response("5")
    assert schedule_mod.current_week() == 5


def test_current_week_empty_body_raises_actionable_error(fake_week_response):
    """The real pre-term case: TIS answers querydangqianzc with an empty
    body (schedule rows still 待生效). Must NOT raise ValueError."""
    fake_week_response("")
    with pytest.raises(APIError) as ei:
        schedule_mod.current_week()
    msg = str(ei.value)
    assert "--zc" in msg and "--all" in msg


def test_current_week_auth_page_suggests_session_refresh(fake_week_response):
    """Stale session: TIS returns a JSON 'please log in again' page."""
    fake_week_response('{"content":"\u8bf7\u7528\u6237\u91cd\u65b0\u767b\u5f55\u9875\u9762"}')
    with pytest.raises(APIError) as ei:
        schedule_mod.current_week()
    assert "session refresh" in str(ei.value)


def test_current_week_garbage_body_raises_api_error_not_valueerror(fake_week_response):
    fake_week_response("<html>gateway error</html>")
    with pytest.raises(APIError):
        schedule_mod.current_week()


# -- current_semester() ------------------------------------------------------

def test_current_semester_valid_shape(fake_week_response):
    fake_week_response('{"XN":"2026-2027","XQ":"1","XNXQ":"2026\u79cb\u5b63","XNXQ_EN":"2026Fall"}')
    assert schedule_mod.current_semester()["XN"] == "2026-2027"


def test_current_semester_auth_page_raises_clear_error(fake_week_response):
    """A stale-session error page lacks XN/XQ — must not KeyError."""
    fake_week_response('{"content":"please log in again"}')
    with pytest.raises(APIError) as ei:
        schedule_mod.current_semester()
    assert "session" in str(ei.value).lower()


def test_current_semester_empty_raises_clear_error(fake_week_response):
    fake_week_response("")
    with pytest.raises(APIError):
        schedule_mod.current_semester()


# -- `sustech tis schedule` CLI (no args) ------------------------------------

def test_schedule_cmd_no_current_week_prints_hint_not_traceback(fake_week_response):
    """Regression for the exact user report: `sustech tis schedule` with
    no --zc while TIS has no current week must exit 1 with a readable
    message — never a raw ValueError traceback."""
    fake_week_response("")   # term not started → empty body
    runner = CliRunner()
    result = runner.invoke(tis_cli.cli, ["schedule"])
    assert result.exit_code == 1
    assert "Traceback" not in result.output
    assert "--zc" in result.output
    assert "--all" in result.output


def test_schedule_cmd_stale_session_prints_refresh_hint(fake_week_response):
    fake_week_response('{"content":"\u8bf7\u7528\u6237\u91cd\u65b0\u767b\u5f55\u9875\u9762"}')
    runner = CliRunner()
    result = runner.invoke(tis_cli.cli, ["schedule"])
    assert result.exit_code == 1
    assert "Traceback" not in result.output
    assert "session refresh" in result.output
