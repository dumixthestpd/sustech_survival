"""
Tests for the shared credential helpers + `sustech sso credentials` CLI.

Fully offline — no network, no real credentials. Uses temp dirs and the
monkeypatched SUSTECH_CREDENTIALS env var.
"""
from __future__ import annotations

import os

import pytest

from sustech_survival.sso import authorizer
from sustech_survival.sso.authorizer import (
    AuthorizerError, resolve_creds_path, write_credentials, read_credentials,
)


# ── write_credentials / read_credentials ───────────────────────────────────

def test_write_read_roundtrip(tmp_path):
    p = write_credentials("12410000", "secret", path=tmp_path / "creds.txt")
    assert p.exists()
    assert p.read_text().strip() == "12410000:secret"
    sid, pw = read_credentials(p)
    assert sid == "12410000" and pw == "secret"


def test_write_creates_parent_dirs(tmp_path):
    p = write_credentials("sid", "pw", path=tmp_path / "deep" / "nested" / "c.txt")
    assert p.parent.exists() and p.exists()


def test_write_rejects_colon_or_newline(tmp_path):
    with pytest.raises(AuthorizerError):
        write_credentials("bad:colon", "pw", path=tmp_path / "c.txt")
    with pytest.raises(AuthorizerError):
        write_credentials("sid", "pw\npw", path=tmp_path / "c.txt")


def test_read_missing_raises(tmp_path):
    with pytest.raises(AuthorizerError):
        read_credentials(tmp_path / "nope.txt")


def test_read_bad_format_raises(tmp_path):
    p = tmp_path / "c.txt"
    p.write_text("no-colon-here", encoding="utf-8")
    with pytest.raises(AuthorizerError):
        read_credentials(p)


def test_resolve_creds_path_env(monkeypatch, tmp_path):
    monkeypatch.setenv("SUSTECH_CREDENTIALS", str(tmp_path / "x.txt"))
    assert resolve_creds_path() == tmp_path / "x.txt"


def test_resolve_creds_path_defaults_to_xdg(monkeypatch):
    monkeypatch.delenv("SUSTECH_CREDENTIALS", raising=False)
    # Path.home() default — just assert it's under a path named credentials.txt
    p = resolve_creds_path()
    assert p.name == "credentials.txt"


# ── CLI: `sustech sso credentials` ─────────────────────────────────────────

def test_cli_status(monkeypatch, tmp_path):
    from click.testing import CliRunner
    from sustech_survival.cli.main import sso_credentials
    monkeypatch.setenv("SUSTECH_CREDENTIALS", str(tmp_path / "creds.txt"))
    r = CliRunner().invoke(sso_credentials, ["--status"])
    assert r.exit_code == 0
    assert "creds.txt" in r.output
    assert "Exists: False" in r.output


def test_cli_write(monkeypatch, tmp_path):
    from click.testing import CliRunner
    from sustech_survival.cli.main import sso_credentials
    target = tmp_path / "creds.txt"
    monkeypatch.setenv("SUSTECH_CREDENTIALS", str(target))
    r = CliRunner().invoke(
        sso_credentials, ["--sid", "12410000", "--password", "cli-pass"])
    assert r.exit_code == 0
    assert target.read_text().strip() == "12410000:cli-pass"


def test_cli_write_prompts_hidden(monkeypatch, tmp_path):
    """Without --password, it should prompt (hidden); here we feed stdin."""
    from click.testing import CliRunner
    from sustech_survival.cli.main import sso_credentials
    target = tmp_path / "creds.txt"
    monkeypatch.setenv("SUSTECH_CREDENTIALS", str(target))
    r = CliRunner().invoke(
        sso_credentials, ["--sid", "12410000"],
        input="prompted-pw\nprompted-pw\n")
    assert r.exit_code == 0
    assert target.read_text().strip() == "12410000:prompted-pw"
    assert "password" in r.output.lower() or "prompt" in r.output.lower()
