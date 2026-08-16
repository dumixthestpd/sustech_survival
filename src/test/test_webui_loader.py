"""
Dedicated tests for sustech_survival.webui.loader — the skin loader.

Offline. We monkeypatch the module-level _USER_SKINS / _PKG_SKINS path globals
to controlled dirs so no user config is touched and tmp_path isn't required.
"""
from __future__ import annotations

import json
import pathlib

import pytest

import sustech_survival.webui.loader as loader


@pytest.fixture()
def _tmp_skins(monkeypatch, tmp_path):
    """Control skin dirs under a temp path without touching real HOME."""
    usr = tmp_path / "user-skins"
    pkg = tmp_path / "pkg-skins"
    usr.mkdir(parents=True, exist_ok=True)
    pkg.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(loader, "_USER_SKINS", usr)
    monkeypatch.setattr(loader, "_PKG_SKINS", pkg)
    return usr, pkg


def _make_skin(base, name, *, version="1.0.0", entry="index.html"):
    d = base / name
    (d / "static").mkdir(parents=True, exist_ok=True)
    (d / "manifest.json").write_text(
        json.dumps({"name": name, "version": version, "entry": entry}),
        encoding="utf-8")
    (d / entry).write_text("<h1>hi</h1>", encoding="utf-8")
    return d


# ── default_skin ───────────────────────────────────────────────────────────

def test_default_skin_points_into_package():
    p = loader.default_skin()
    assert p.name == "default"
    assert p.is_dir()


# ── installed_skins / find_skin ────────────────────────────────────────────

def test_installed_skins_user_before_package(_tmp_skins):
    usr, pkg = _tmp_skins
    _make_skin(pkg, "default")
    _make_skin(usr, "my-skin")
    skins = loader.installed_skins()
    names = [s.name for s in skins]
    # user cache listed first, then package
    assert names[0] == "my-skin"
    assert "default" in names


def test_installed_skins_skips_invalid(_tmp_skins):
    usr, pkg = _tmp_skins
    _make_skin(usr, "good")
    # a dir with no manifest / no entry is not a valid skin
    (usr / "broken").mkdir(exist_ok=True)
    (usr / "broken").joinpath("manifest.json").write_text(
        json.dumps({"name": "broken", "entry": "missing.html"}), encoding="utf-8")
    names = [s.name for s in loader.installed_skins()]
    assert "good" in names
    assert "broken" not in names


def test_find_skin_returns_matching(_tmp_skins):
    usr, pkg = _tmp_skins
    _make_skin(usr, "alpha")
    _make_skin(usr, "beta")
    s = loader.find_skin("beta")
    assert s.name == "beta"
    assert s.index.exists()


def test_find_skin_raises_keyerror_with_available(_tmp_skins):
    usr, pkg = _tmp_skins
    _make_skin(usr, "alpha")
    with pytest.raises(KeyError) as e:
        loader.find_skin("nope")
    assert "alpha" in str(e.value)


def test_find_skin_keyerror_when_none_installed(_tmp_skins):
    usr, pkg = _tmp_skins  # both empty
    with pytest.raises(KeyError):
        loader.find_skin("anything")


def test_skin_dataclass_fields(_tmp_skins):
    usr, pkg = _tmp_skins
    _make_skin(usr, "alpha", version="2.1.0")
    s = loader.find_skin("alpha")
    assert s.version == "2.1.0"
    assert s.entry == "index.html"
    assert s.root.name == "alpha"


# ── install_skin ───────────────────────────────────────────────────────────

def test_install_skin_copies_into_user_cache(_tmp_skins):
    usr, pkg = _tmp_skins
    _make_skin(pkg, "default")
    # install the default skin into the user cache (so it can be modded)
    dst = loader.install_skin("default", default=True)
    assert dst.parent == usr
    assert (dst / "manifest.json").exists()


def test_install_skin_rejects_invalid(_tmp_skins):
    usr, pkg = _tmp_skins
    bad = pkg / "bad"
    bad.mkdir(exist_ok=True)  # no manifest
    with pytest.raises(ValueError):
        loader.install_skin(bad, default=False)
