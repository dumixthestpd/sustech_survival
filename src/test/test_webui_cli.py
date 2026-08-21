"""
Tests for the ``sustech webui`` skin CLI commands: listing installed skins,
installing a skin into the user cache, and the up-front ``--skin``
validation done by ``serve`` (without actually starting a server).

These exercise the Click command objects directly via ``CliRunner``, the same
pattern the other CLI tests use. They monkeypatch the user skin cache so they
never touch the real ``~/.config``.
"""
from __future__ import annotations

import json
import sys

import pytest
from click.testing import CliRunner

import sustech_survival.webui.loader as loader
from sustech_survival.cli.main import (
    webui_cmd,
    webui_skins,
    webui_install,
    webui_serve,
    webui_set_skin,
    webui_skin_cmd,
)
from sustech_survival import _cache


# The only skin shipped inside the package (fallback). Other skins are
# installed to ~/.sustech_survival/skins/ and found via the user cache,
# which the fixture hides.
PACKAGE_SKINS = ["default"]


@pytest.fixture()
def isolated(monkeypatch, tmp_path):
    """Hide the user skin cache so tests only see the shipped package skins."""
    user = tmp_path / "user-skins"
    user.mkdir()
    monkeypatch.setattr(loader, "_USER_SKINS", user)
    return user


@pytest.fixture()
def runner():
    return CliRunner()


# ── webui skins ────────────────────────────────────────────────────────────

def test_webui_skins_lists_each_package_skin(isolated, runner):
    r = runner.invoke(webui_skins, [])
    assert r.exit_code == 0
    for name in PACKAGE_SKINS:
        assert name in r.output



def test_webui_skins_shows_user_skins_first(isolated, runner, monkeypatch):
    """A skin in the user cache is listed before package skins."""
    # install "my-skin" into the (temp) user cache so it shadows nothing but
    # shows up first, mirroring loader precedence (user -> package).
    alpha = isolated.parent / "alpha-skin"
    (alpha / "static").mkdir(parents=True)
    (alpha / "manifest.json").write_text(
        json.dumps({"name": "alpha", "version": "1.0.0", "entry": "index.html"}),
        encoding="utf-8")
    (alpha / "index.html").write_text("<h1>hi</h1>", encoding="utf-8")
    loader.install_skin(alpha)
    r = runner.invoke(webui_skins, [])
    assert r.exit_code == 0
    # "alpha" must be the FIRST skin row (tab-separated table). Row 0 is the
    # "name\tversion\tpath" header; row 1 is the first data row.
    rows = [ln for ln in r.output.splitlines() if "\t" in ln]
    assert len(rows) >= 2          # header + at least one skin
    assert rows[0].startswith("name\t")
    assert rows[1].startswith("alpha\t")


# ── webui install ──────────────────────────────────────────────────────────

def test_webui_install_default_copies_into_user_cache(isolated, runner):
    r = runner.invoke(webui_install, ["default"])
    assert r.exit_code == 0
    assert (isolated / "default" / "manifest.json").exists()


def test_webui_install_from_path(isolated, runner):
    src = isolated.parent / "spoiler"
    (src / "static").mkdir(parents=True)
    (src / "manifest.json").write_text(
        json.dumps({"name": "spoiler", "version": "0.2.0", "entry": "index.html"}),
        encoding="utf-8")
    (src / "index.html").write_text("<h1>x</h1>", encoding="utf-8")
    r = runner.invoke(webui_install, ["--path", str(src)])
    assert r.exit_code == 0
    assert (isolated / "spoiler" / "manifest.json").exists()


def test_webui_install_rejects_invalid_path(isolated, runner):
    bad = isolated.parent / "not-a-skin"
    bad.mkdir()
    r = runner.invoke(webui_install, ["--path", str(bad)])
    assert r.exit_code == 1
    assert "not a valid skin" in r.output


def test_webui_install_rejects_missing_dir(isolated, runner):
    r = runner.invoke(webui_install, ["--path", str(isolated.parent / "nope")])
    assert r.exit_code == 1
    assert "not a directory" in r.output


# ── webui serve --skin validation (does NOT start a server) ────────────────

def test_webui_serve_unknown_skin_exits_with_list(isolated, runner):
    """serve validates --skin up front; an unknown name exits 1 before running."""
    r = runner.invoke(webui_serve, ["--skin", "does-not-exist"])
    assert r.exit_code == 1
    assert "does-not-exist" in r.output
    assert "default" in r.output  # lists the available (package fallback) skin


# ── webui serve --skin-path validation (does NOT start a server) ───────────

def test_webui_serve_skin_path_valid_proceeds_to_run(isolated, runner, monkeypatch):
    """--skin-path points at a valid skin dir; validation passes and serve
    proceeds to run() (which we stub out so the test doesn't start a server)."""
    src = isolated.parent / "vc-skin"
    (src / "static").mkdir(parents=True)
    (src / "manifest.json").write_text(
        json.dumps({"name": "vc-skin", "version": "0.1.0", "entry": "index.html"}),
        encoding="utf-8")
    (src / "index.html").write_text("<h1>x</h1>", encoding="utf-8")

    captured = {}
    # _webui_serve_impl does `from ..webui.app import run` locally, so stub the
    # run symbol on webui.app (where it lives) to avoid starting a real server.
    from sustech_survival.webui import app as webui_app
    def fake_run(**kwargs):
        captured.update(kwargs)
        return 0
    monkeypatch.setattr(webui_app, "run", fake_run)

    r = runner.invoke(webui_serve, ["--skin-path", str(src)])
    assert r.exit_code == 0
    # the resolved path was threaded into run() (create_app receives skin_path)
    assert captured["skin_path"] == str(src)


def test_webui_serve_skin_path_invalid_exits(isolated, runner):
    """--skin-path pointing at a non-skin dir exits 1 with an actionable msg,
    before any server is started."""
    bad = isolated.parent / "not-a-skin"
    bad.mkdir()  # no manifest.json / entry
    r = runner.invoke(webui_serve, ["--skin-path", str(bad)])
    assert r.exit_code == 1
    assert "cannot serve --skin-path" in r.output


def test_webui_serve_skin_path_unknown_skin_path_not_a_dir(isolated, runner):
    """--skin-path to a missing directory exits 1 with a clear message."""
    r = runner.invoke(webui_serve,
                      ["--skin-path", str(isolated.parent / "does-not-exist")])
    assert r.exit_code == 1
    assert "cannot serve --skin-path" in r.output


# ── webui set-skin (persist default skin in config.json) ───────────────────

def test_webui_set_skin_persists(isolated, runner, monkeypatch, tmp_path):
    """`sustech webui set-skin <name>` writes webui.skin into config.json."""
    from sustech_survival import _cache
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    monkeypatch.setattr(_cache, "config_file", lambda root=None: cfg_dir / "config.json")
    r = runner.invoke(webui_set_skin, ["default"])
    assert r.exit_code == 0
    assert _cache.load_config().get("webui", {}).get("skin") == "default"


def test_webui_set_skin_unknown_exits(isolated, runner):
    """Unknown skin name exits 1 with the available list."""
    r = runner.invoke(webui_set_skin, ["does-not-exist"])
    assert r.exit_code == 1
    assert "does-not-exist" in r.output


# ── `sustech webui` alone must NOT serve (help only) ───────────────────────

def test_webui_no_subcommand_shows_help_not_serve(isolated, runner, monkeypatch):
    """Bare `sustech webui` must not start a server — it shows help (exit 2)
    and never calls run()."""
    from sustech_survival.webui import app as webui_app
    called = []

    def fake_run(**kwargs):
        called.append(kwargs)
        return 0

    monkeypatch.setattr(webui_app, "run", fake_run)
    r = runner.invoke(webui_cmd, [])
    assert r.exit_code == 2                 # usage error: no subcommand given
    assert "Usage:" in r.output
    assert "serve" in r.output              # help lists the subcommands
    assert called == []                     # run() was never invoked


def test_webui_module_no_args_prints_usage(monkeypatch, capsys):
    """`python -m sustech_survival.webui` with no args prints usage and does
    not serve."""
    import sustech_survival.webui.__main__ as m
    monkeypatch.setattr(sys, "argv", ["sustech_survival.webui"])
    rc = m.main()
    assert rc == 2
    assert "usage:" in capsys.readouterr().out


# ── `sustech webui skin set/delete` ─────────────────────────────────────────

def test_webui_skin_set_and_delete(isolated, runner, monkeypatch, tmp_path):
    """The new skin group can set the default and delete a user skin."""
    from sustech_survival import _cache as cache
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    monkeypatch.setattr(cache, "config_file", lambda root=None: cfg_dir / "config.json")

    src = isolated.parent / "alpha-skin"
    (src / "static").mkdir(parents=True)
    (src / "manifest.json").write_text(
        json.dumps({"name": "alpha", "version": "1.0.0", "entry": "index.html"}),
        encoding="utf-8")
    (src / "index.html").write_text("<h1>alpha</h1>", encoding="utf-8")
    loader.install_skin(src)

    r = runner.invoke(webui_skin_cmd, ["set", "alpha"])
    assert r.exit_code == 0
    assert cache.load_config()["webui"]["skin"] == "alpha"

    r = runner.invoke(webui_skin_cmd, ["delete", "alpha"])
    assert r.exit_code == 0
    assert not (isolated / "alpha").exists()


def test_context_command_uses_correct_module(monkeypatch):
    """`sustech context` must import sustech_survival.context, not cli.context."""
    from sustech_survival import context as context_mod
    from sustech_survival.cli.main import context_cmd

    class FakeContext:
        def __init__(self):
            self.ok = True
        def to_dict(self, level):
            return {"ok": True}
        def to_str(self, level):
            return "ok"

    monkeypatch.setattr(context_mod, "Context", FakeContext)
    runner = CliRunner()
    r = runner.invoke(context_cmd, [])
    assert r.exit_code == 0
    assert r.output.strip() == "ok"


