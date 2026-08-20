"""
Tests for the skin layer's web features: skin discovery, per-skin page
serving, the single /static/<path> handler (shared-asset regression) and
per-skin theme serving for INSTALLED skins.

The module ships ONLY the ``default`` fallback skin; every other skin is
installed to the user's home dot-directory (~/.sustech_survival/skins/) and
is served from there. These tests use ``create_app``'s Flask test client, so
they require Flask.
"""
from __future__ import annotations

import json

import pytest

import sustech_survival.webui.loader as loader
from sustech_survival.webui.app import create_app

# The only skin shipped inside the package (fallback when nothing is
# installed to home). Other skins are installed to ~/.sustech_survival/skins/.
PACKAGE_SKINS = ["default"]


@pytest.fixture()
def package_only(monkeypatch, tmp_path):
    """Hide the user skin cache so tests only see the shipped package skin."""
    monkeypatch.setattr(loader, "_USER_SKINS", tmp_path / "empty-user-skins")
    return loader


def _make_skin(base, name, *, landing_tokens, tis_tokens, transit_tokens):
    """Build a minimal but valid skin dir (manifest + index + tis + transit)
    the way an installed home skin is structured."""
    d = base / name
    (d / "transit" / "static").mkdir(parents=True)
    (d / "manifest.json").write_text(json.dumps({
        "name": name, "version": "1.0.0", "requires": "2026.8.0",
        "entry": "index.html", "api": [],
    }), encoding="utf-8")
    (d / "index.html").write_text(
        f"<style>:root{{{landing_tokens}}}</style><h1>{name}</h1>",
        encoding="utf-8")
    (d / "tis.html").write_text(
        f"<style>:root{{{tis_tokens}}}</style>", encoding="utf-8")
    (d / "transit" / "index.html").write_text("<h1>transit</h1>", encoding="utf-8")
    (d / "transit" / "static" / "style.css").write_text(
        transit_tokens, encoding="utf-8")
    return d


@pytest.fixture()
def installed_home(monkeypatch, tmp_path):
    """Simulate home-installed skins: a temp user cache holding a light skin
    (official palette) and a dark skin (orange palette)."""
    usr = tmp_path / "user-skins"
    usr.mkdir()
    _make_skin(usr, "my_light",
               landing_tokens="--org:#dc6400;--bg0:#faf8f3;--teal:#003030",
               tis_tokens="--accent:#dc6400;--bg:#f5f6fa",
               transit_tokens=":root{--primary: #dc6400;--bg: #f5f6fa}")
    _make_skin(usr, "my_dark",
               landing_tokens="--org:#ed7005;--bg0:#17130d;--teal:#1f1a10",
               tis_tokens="--accent:#ed7005;--bg:#17130d",
               transit_tokens=":root{--primary: #ed7005;--bg: #17130d}")
    monkeypatch.setattr(loader, "_USER_SKINS", usr)
    return usr


# ── Skin registry (package default + installed) ───────────────────────────

def test_shipped_default_registered(package_only):
    names = [s.name for s in loader.installed_skins()]
    assert "default" in names


def test_find_default_skin(package_only):
    s = loader.find_skin("default")
    assert s.name == "default"
    assert s.index.exists()


def test_default_manifest_valid(package_only):
    s = loader.find_skin("default")
    mf = loader._read_manifest(s.root)
    assert mf["name"] == "default"
    assert (s.root / mf["entry"]).is_file()


def test_installed_skins_found_via_home(installed_home):
    """Skins installed to the (home) user cache are treated as installed."""
    names = [s.name for s in loader.installed_skins()]
    assert "my_light" in names
    assert "my_dark" in names


# ── Theme tokens are served for installed skins ───────────────────────────

def _get(app, path):
    return app.test_client().get(path)


def test_installed_dark_landing_serves_theme(installed_home):
    app = create_app(skin="my_dark")
    r = _get(app, "/")
    assert r.status_code == 200
    assert "--org:#ed7005" in r.data.decode("utf-8", "replace")


def test_installed_light_landing_serves_theme(installed_home):
    app = create_app(skin="my_light")
    r = _get(app, "/")
    assert r.status_code == 200
    body = r.data.decode("utf-8", "replace")
    assert "--org:#dc6400" in body
    assert "--bg0:#faf8f3" in body
    assert "--teal:#003030" in body


def test_default_landing_served(package_only):
    app = create_app(skin="default")
    assert _get(app, "/").status_code == 200


# ── Per-skin page serving (installed skins) ────────────────────────────────

@pytest.mark.parametrize("name", ["my_light", "my_dark"])
def test_installed_skin_pages_serve(installed_home, name):
    app = create_app(skin=name)
    c = app.test_client()
    assert c.get("/tis").status_code == 200
    assert c.get("/transit").status_code == 200


def test_installed_skin_tis_is_themed(installed_home):
    app = create_app(skin="my_light")
    r = _get(app, "/tis")
    assert r.status_code == 200
    body = r.data.decode("utf-8", "replace")
    assert "--accent:#dc6400" in body
    assert "--bg:#f5f6fa" in body


def test_installed_skin_transit_style_themed(installed_home):
    app = create_app(skin="my_light")
    r = _get(app, "/static/style.css")
    assert r.status_code == 200
    body = r.data.decode("utf-8", "replace")
    assert "--primary: #dc6400" in body
    assert "--bg: #f5f6fa" in body


# ── Shared static handler (route-conflict regression) ──────────────────────

def test_shared_tis_js_served_for_installed_skin(installed_home):
    """Regression: /static/tis/tis.js must resolve for installed (custom)
    skins even though the transit blueprint no longer owns a competing
    /static route."""
    app = create_app(skin="my_light")
    r = _get(app, "/static/tis/tis.js")
    assert r.status_code == 200
    assert r.data[:2] == b"/*"       # the shared JS, not a 404 page


def test_shared_tis_js_served_for_default(package_only):
    app = create_app(skin="default")
    assert _get(app, "/static/tis/tis.js").status_code == 200


def test_missing_static_404s(installed_home):
    app = create_app(skin="my_light")
    assert _get(app, "/static/does-not-exist.js").status_code == 404


# ── Incorrect skin name raises with the available list ─────────────────────

def test_unknown_skin_raises_keyerror(installed_home):
    with pytest.raises(KeyError) as e:
        create_app(skin="does-not-exist")
    msg = str(e.value)
    assert "my_light" in msg
    assert "my_dark" in msg


# ── Default skin saved in ~/.sustech_survival/config.json ─────────────────

def test_configured_default_skin_used(installed_home, monkeypatch, tmp_path):
    """create_app() with no explicit skin uses webui.skin from config.json."""
    from sustech_survival import _cache
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    monkeypatch.setattr(_cache, "config_file", lambda root=None: cfg_dir / "config.json")
    _cache.update_config(webui={"skin": "my_dark"})
    app = create_app()                      # no explicit skin
    assert app.config["SKIN"] == "my_dark"
    app2 = create_app(skin="my_light")      # explicit wins
    assert app2.config["SKIN"] == "my_light"
