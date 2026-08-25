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


def test_resolve_creds_path_defaults_to_home(monkeypatch, tmp_path):
    """With no env and no cwd file, credentials default to the user's home
    dot-directory: ~/.sustech_survival/credentials.txt (not cwd)."""
    monkeypatch.delenv("SUSTECH_CREDENTIALS", raising=False)
    monkeypatch.delenv("SUSTECH_HOME", raising=False)
    monkeypatch.setattr(authorizer._cache, "user_home", lambda: tmp_path)
    old = os.getcwd()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir(parents=True, exist_ok=True)
    os.chdir(elsewhere)
    try:
        p = resolve_creds_path()
        assert p == tmp_path / ".sustech_survival" / "credentials.txt"
        assert p.name == "credentials.txt"
    finally:
        os.chdir(old)

def test_resolve_creds_path_home_override(monkeypatch, tmp_path):
    """$SUSTECH_HOME relocates the whole tree, credentials included."""
    monkeypatch.delenv("SUSTECH_CREDENTIALS", raising=False)
    monkeypatch.setenv("SUSTECH_HOME", str(tmp_path / "anchor"))
    assert resolve_creds_path() == tmp_path / "anchor" / ".sustech_survival" / "credentials.txt"


def test_resolve_creds_path_env_wins_over_home(monkeypatch, tmp_path):
    """SUSTECH_CREDENTIALS points at an explicit file, even when a home
    dot-directory default would also exist."""
    monkeypatch.setenv("SUSTECH_CREDENTIALS", str(tmp_path / "env.txt"))
    monkeypatch.setattr(authorizer._cache, "user_home", lambda: tmp_path)
    assert resolve_creds_path() == tmp_path / "env.txt"


# ── cred_set / cred_clear in-memory override ────────────────────────────────

def test_cred_set_in_memory_override(monkeypatch, tmp_path):
    """cred_set() beats cwd file and env var — no file, no user dir."""
    import sustech_survival.sso.authorizer as A
    # Stale sources exist below cred_set in precedence
    cwd_creds = tmp_path / "credentials.txt"
    cwd_creds.write_text("00000000:from-file", encoding="utf-8")
    monkeypatch.setenv("SUSTECH_CREDENTIALS", str(tmp_path / "env.txt"))
    monkeypatch.setenv("SUSTECH_HOME", str(tmp_path))  # ensure no Path.home() usage
    old = os.getcwd()
    os.chdir(tmp_path)
    try:
        A.cred_set("12410000", "from-memory")
        try:
            sid, pw = read_credentials()
            assert (sid, pw) == ("12410000", "from-memory")
        finally:
            A.cred_clear()
    finally:
        os.chdir(old)


def test_cred_set_cleared_then_file_used(monkeypatch, tmp_path):
    import sustech_survival.sso.authorizer as A
    env_creds = tmp_path / "env-creds.txt"
    env_creds.write_text("12410000:from-file", encoding="utf-8")
    monkeypatch.setenv("SUSTECH_CREDENTIALS", str(env_creds))
    try:
        A.cred_set("1", "mem")
        A.cred_clear()
        sid, pw = read_credentials()
        assert (sid, pw) == ("12410000", "from-file")
    finally:
        A.cred_clear()


def test_cred_set_rejects_bad_values():
    import sustech_survival.sso.authorizer as A
    with pytest.raises(AuthorizerError):
        A.cred_set("bad:colon", "pw")
    with pytest.raises(AuthorizerError):
        A.cred_set("sid", "pw\npw")
    A.cred_clear()


# ── CLI: `sustech sso creds set` / `sustech sso creds status` ────────────

def test_cli_creds_status(monkeypatch, tmp_path):
    from click.testing import CliRunner
    from sustech_survival.cli.main import sso_creds_status
    import sustech_survival.sso.authorizer as A
    monkeypatch.setattr(A, "resolve_creds_path", lambda: tmp_path / "creds.txt")
    r = CliRunner().invoke(sso_creds_status, [])
    assert r.exit_code == 0
    assert "creds.txt" in r.output
    assert "Exists: False" in r.output


def test_cli_creds_set_pass(monkeypatch, tmp_path):
    from click.testing import CliRunner
    from sustech_survival.cli.main import sso_creds_set
    import sustech_survival.sso.authorizer as A
    target = tmp_path / "creds.txt"
    monkeypatch.setattr(A, "write_credentials",
                        lambda sid, pw, path=None: target.write_text(f"{sid}:{pw}\n", encoding="utf-8") or target)
    r = CliRunner().invoke(
        sso_creds_set, ["--sid", "12410000", "--pass", "cli-pass"])
    assert r.exit_code == 0
    assert target.read_text().strip() == "12410000:cli-pass"


def test_cli_creds_set_password_alias(monkeypatch, tmp_path):
    """--password is accepted as an alias of --pass."""
    from click.testing import CliRunner
    from sustech_survival.cli.main import sso_creds_set
    import sustech_survival.sso.authorizer as A
    target = tmp_path / "creds.txt"
    monkeypatch.setattr(A, "write_credentials",
                        lambda sid, pw, path=None: target.write_text(f"{sid}:{pw}\n", encoding="utf-8") or target)
    r = CliRunner().invoke(
        sso_creds_set, ["--sid", "12410000", "--password", "cli-pass"])
    assert r.exit_code == 0
    assert target.read_text().strip() == "12410000:cli-pass"


def test_cli_creds_set_prompts_hidden(monkeypatch, tmp_path):
    """Without --pass, it prompts (hidden); here we feed stdin."""
    from click.testing import CliRunner
    from sustech_survival.cli.main import sso_creds_set
    import sustech_survival.sso.authorizer as A
    target = tmp_path / "creds.txt"
    monkeypatch.setattr(A, "write_credentials",
                        lambda sid, pw, path=None: target.write_text(f"{sid}:{pw}\n", encoding="utf-8") or target)
    r = CliRunner().invoke(
        sso_creds_set, ["--sid", "12410000"],
        input="prompted-pw\nprompted-pw\n")
    assert r.exit_code == 0
    assert target.read_text().strip() == "12410000:prompted-pw"
    assert "password" in r.output.lower() or "prompt" in r.output.lower()
