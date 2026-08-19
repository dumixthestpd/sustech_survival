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

import pytest
from click.testing import CliRunner

import sustech_survival.webui.loader as loader
from sustech_survival.cli.main import (
    webui_skins,
    webui_install,
    webui_serve,
)

# Shipped package skins (user cache is hidden by the fixture below).
PACKAGE_SKINS = ["default", "sustech_orange", "sustech_official_light"]


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


def test_webui_skins_json(isolated, runner):
    r = runner.invoke(webui_skins, ["--json"])
    assert r.exit_code == 0
    data = json.loads(r.output)
    names = [d["name"] for d in data]
    for expected in PACKAGE_SKINS:
        assert expected in names
    for d in data:
        assert "version" in d
        assert "entry" in d
        assert "path" in d


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
    assert "alpha" in r.output.splitlines()[1]  # first listed line after the header


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
    assert "sustech_orange" in r.output  # lists the available skins
    assert "sustech_official_light" in r.output
