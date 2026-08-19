"""
Tests for the skin layer's web features: skin discovery, per-skin page
serving, the single /static/<path> handler (shared-asset regression) and
the per-skin theme markers.

Covers the sustech_orange skin (renamed from 'presentation') and the new
sustech_official_light skin built on the official SUSTech palette.

These use ``create_app``'s Flask test client, so they require Flask.
"""
from __future__ import annotations

import pytest

import sustech_survival.webui.loader as loader
from sustech_survival.webui.app import create_app

# Skins shipped with the package. Present regardless of user cache.
PACKAGE_SKINS = ["default", "sustech_orange", "sustech_official_light"]


@pytest.fixture()
def package_only(monkeypatch, tmp_path):
    """Hide the user skin cache so tests only see the shipped package skins."""
    monkeypatch.setattr(loader, "_USER_SKINS", tmp_path / "empty-user-skins")
    monkeypatch.setattr(loader, "_PKG_SKINS", loader._PKG_SKINS)
    # reload so installed_skins() reads the patched globals
    return loader


# ── Skin registry ──────────────────────────────────────────────────────────

def test_shipped_skins_registered(package_only):
    names = [s.name for s in loader.installed_skins()]
    for expected in PACKAGE_SKINS:
        assert expected in names, f"shipped skin {expected!r} missing from {names}"


def test_find_skin_by_name(package_only):
    for name in PACKAGE_SKINS:
        s = loader.find_skin(name)
        assert s.name == name
        assert s.index.exists()


def test_skins_carry_valid_manifest(package_only):
    for name in PACKAGE_SKINS:
        s = loader.find_skin(name)
        mf = loader._read_manifest(s.root)
        assert mf["name"] == name
        assert (s.root / mf["entry"]).is_file()


# ── Theme markers (per-skin) ───────────────────────────────────────────────

def _get(app, path):
    return app.test_client().get(path)


def test_sustech_orange_landing_is_dark(package_only):
    app = create_app(skin="sustech_orange")
    r = _get(app, "/")
    assert r.status_code == 200
    body = r.data.decode("utf-8", "replace")
    # the dark presentation theme's signature accent
    assert "--org:#ed7005" in body


def test_official_light_landing_is_light(package_only):
    app = create_app(skin="sustech_official_light")
    r = _get(app, "/")
    assert r.status_code == 200
    body = r.data.decode("utf-8", "replace")
    # official SUSTech palette: orange primary + light background + dark ink teal
    assert "--org:#dc6400" in body
    assert "--bg0:#faf8f3" in body
    assert "--teal:#003030" in body


def test_default_landing_served(package_only):
    app = create_app(skin="default")
    r = _get(app, "/")
    assert r.status_code == 200


# ── Per-skin page serving ──────────────────────────────────────────────────

@pytest.mark.parametrize("skin,has_tis,has_transit", [
    ("sustech_orange", True, True),
    ("sustech_official_light", True, True),
])
def test_custom_skin_pages_serve(package_only, skin, has_tis, has_transit):
    app = create_app(skin=skin)
    c = app.test_client()
    if has_tis:
        assert c.get("/tis").status_code == 200
    if has_transit:
        assert c.get("/transit").status_code == 200


def test_custom_skin_tis_is_themed(package_only):
    app = create_app(skin="sustech_official_light")
    r = _get(app, "/tis")
    assert r.status_code == 200
    body = r.data.decode("utf-8", "replace")
    assert "--accent:#dc6400" in body   # official orange accent
    assert "--bg:#f5f6fa" in body       # light background


def test_custom_skin_transit_style_themed(package_only):
    app = create_app(skin="sustech_official_light")
    r = _get(app, "/static/style.css")
    assert r.status_code == 200
    body = r.data.decode("utf-8", "replace")
    assert "--primary: #dc6400" in body
    assert "--bg: #f5f6fa" in body


# ── Shared static handler (route-conflict regression) ──────────────────────

def test_shared_tis_js_served_for_custom_skin(package_only):
    """Regression: /static/tis/tis.js must resolve for custom skins even
    though the transit blueprint no longer owns a competing /static route."""
    app = create_app(skin="sustech_official_light")
    r = _get(app, "/static/tis/tis.js")
    assert r.status_code == 200
    assert r.data[:2] == b"/*"       # the shared JS, not a 404 page


def test_shared_tis_js_served_for_default(package_only):
    app = create_app(skin="default")
    assert _get(app, "/static/tis/tis.js").status_code == 200


def test_missing_static_404s(package_only):
    app = create_app(skin="sustech_official_light")
    assert _get(app, "/static/does-not-exist.js").status_code == 404


# ── Incorrect skin name raises with the available list ─────────────────────

def test_unknown_skin_raises_keyerror(package_only):
    with pytest.raises(KeyError) as e:
        create_app(skin="does-not-exist")
    msg = str(e.value)
    assert "sustech_orange" in msg
    assert "sustech_official_light" in msg
