"""
Tests for the skin-driven API exposure model.

The registry has three contracts:
  1. **Discovery** — ``discover_module_apis()`` finds every submodule's
     ``api.py`` without breaking on missing ones.
  2. **Mounting** — ``mount_skin_apis()`` registers only the endpoints the
     skin asked for and warns loudly when a requested module is absent.
  3. **Collector** — ``CollectorRegistry`` enforces the dotted-name
     convention so an ``api.py`` can't accidentally land an endpoint in the
     wrong module's namespace.
"""
from __future__ import annotations

import pytest

from sustech_survival.webui import api_registry as reg
from sustech_survival.webui.api_registry import (
    CollectorRegistry,
    EndpointSpec,
    ModuleApi,
    discover_module_apis,
    mount_skin_apis,
)


# -- CollectorRegistry: name + prefix enforcement --------------------------

class TestCollectorRegistry:
    def test_get_collects_one_endpoint(self):
        c = CollectorRegistry("foo")
        @c.get("foo.hello", "/foo/hello")
        def hello():
            return "hi"
        api = c.to_module_api()
        assert api.name == "foo"
        assert len(api.endpoints) == 1
        ep = api.endpoints[0]
        assert ep.name == "foo.hello"
        assert ep.methods == ("GET",)
        assert ep.path == "/foo/hello"
        assert ep.handler is hello

    def test_post_collects_post_method(self):
        c = CollectorRegistry("foo")
        @c.post("foo.echo", "/foo/echo")
        def echo():
            return None
        ep = c.to_module_api().endpoints[0]
        assert ep.methods == ("POST",)

    def test_endpoint_decorator_with_explicit_methods(self):
        c = CollectorRegistry("foo")
        @c.endpoint("foo.multi", methods=["GET", "POST"], path="/foo/multi")
        def multi():
            return None
        ep = c.to_module_api().endpoints[0]
        assert set(ep.methods) == {"GET", "POST"}

    def test_endpoint_rejects_empty_methods(self):
        c = CollectorRegistry("foo")
        with pytest.raises(ValueError, match="methods must be non-empty"):
            c.endpoint("foo.bad", methods=[], path="/x")

    def test_endpoint_rejects_undotted_name(self):
        c = CollectorRegistry("foo")
        with pytest.raises(ValueError, match="must be dotted"):
            c.endpoint("nodots", methods=["GET"], path="/x")

    def test_different_prefix_is_accepted(self):
        """The collector's module name follows the endpoint prefix, not
        the package dir name. ``selectcourse/api.py`` registers
        ``tis.*`` endpoints, so its effective name is ``tis`` — that
        way the skin manifest can refer to it as ``tis`` and the
        discovery dict is keyed by the same prefix."""
        c = CollectorRegistry("selectcourse")
        @c.get("tis.hello", "/tis/hello")
        def hello():
            return None
        api = c.to_module_api()
        assert api.name == "tis"
        assert api.endpoints[0].name == "tis.hello"

    def test_set_name_overrides_inferred(self):
        c = CollectorRegistry("selectcourse")
        @c.get("tis.x", "/x")
        def x(): pass
        c.set_name("tis")
        assert c.to_module_api().name == "tis"


# -- mount_skin_apis: only what the skin asks for is registered ----------

class _FakeApp:
    """Minimal Flask URL-rule accumulator.

    ``mount_skin_apis`` only needs ``add_url_rule``; we record what it
    called so the test can assert the registered set without spinning up
    a real Flask app.
    """

    def __init__(self):
        self.rules: list[dict] = []

    def add_url_rule(self, path, endpoint, view_func, methods):
        self.rules.append({
            "path": path, "endpoint": endpoint,
            "view_func": view_func, "methods": list(methods),
        })


def _api(name, path, methods=("GET",)):
    """Build an EndpointSpec with a no-op handler."""
    return EndpointSpec(name=name, methods=methods, path=path,
                        handler=lambda: None)


def _module(name, *endpoints):
    return ModuleApi(name=name, endpoints=list(endpoints))


class TestMountSkinApis:
    def test_bare_module_name_pulls_all_its_endpoints(self):
        app = _FakeApp()
        discovered = {
            "tis": _module("tis",
                           _api("tis.info", "/api/tis/info"),
                           _api("tis.courses", "/api/tis/courses")),
            "transit": _module("transit",
                               _api("transit.live", "/api/transit/live")),
        }
        mounted, missing = mount_skin_apis(app, ["tis"], discovered)
        assert sorted(mounted) == ["tis.courses", "tis.info"]
        assert missing == []
        assert sorted(r["endpoint"] for r in app.rules) == \
            ["tis.courses", "tis.info"]

    def test_dotted_name_pulls_exactly_one_endpoint(self):
        app = _FakeApp()
        discovered = {
            "tis": _module("tis",
                           _api("tis.info", "/api/tis/info"),
                           _api("tis.courses", "/api/tis/courses")),
        }
        mounted, missing = mount_skin_apis(app, ["tis.info"], discovered)
        assert mounted == ["tis.info"]
        assert missing == []
        assert [r["endpoint"] for r in app.rules] == ["tis.info"]

    def test_mixed_module_and_endpoint_names(self):
        app = _FakeApp()
        discovered = {
            "tis": _module("tis",
                           _api("tis.info", "/api/tis/info"),
                           _api("tis.courses", "/api/tis/courses")),
            "nces": _module("nces",
                            _api("nces.status", "/api/nces/status")),
        }
        mounted, missing = mount_skin_apis(
            app, ["tis", "nces.status"], discovered)
        # "tis" → all tis.* endpoints; "nces.status" → only that one
        assert sorted(mounted) == ["nces.status", "tis.courses", "tis.info"]
        assert missing == []

    def test_unknown_module_is_reported_missing(self):
        app = _FakeApp()
        discovered = {
            "tis": _module("tis", _api("tis.info", "/api/tis/info")),
        }
        mounted, missing = mount_skin_apis(
            app, ["tis", "bogus"], discovered)
        # tis is satisfied, bogus is reported missing
        assert mounted == ["tis.info"]
        assert missing == ["bogus"]

    def test_unknown_dotted_endpoint_is_reported_missing(self):
        app = _FakeApp()
        discovered = {
            "tis": _module("tis", _api("tis.info", "/api/tis/info")),
        }
        mounted, missing = mount_skin_apis(
            app, ["tis.nonexistent"], discovered)
        assert mounted == []
        assert missing == ["tis.nonexistent"]

    def test_methods_are_passed_through(self):
        app = _FakeApp()
        discovered = {
            "tis": _module("tis", _api("tis.add", "/api/tis/add",
                                       methods=("POST",))),
        }
        mount_skin_apis(app, ["tis.add"], discovered)
        rule = app.rules[0]
        assert rule["methods"] == ["POST"]

    def test_empty_manifest_mounts_nothing(self):
        app = _FakeApp()
        discovered = {
            "tis": _module("tis", _api("tis.info", "/api/tis/info")),
        }
        mounted, missing = mount_skin_apis(app, [], discovered)
        assert mounted == []
        assert missing == []
        assert app.rules == []


# -- discover_module_apis: walks sustech_survival.*.api without breaking --

class TestDiscoverModuleApis:
    def test_finds_real_modules(self):
        """The shipped selectcourse, transit, nces modules all have
        api.py — discovery should find them. They are keyed by their
        effective name (the endpoint prefix) — ``tis`` for the
        selectcourse package — not by the package dir name."""
        found = discover_module_apis()
        for name in ("tis", "transit", "nces"):
            assert name in found, f"missing module: {name}"
            api = found[name]
            assert api.name == name
            assert api.endpoints, f"{name} registered no endpoints"

    def test_each_module_endpoint_prefix_matches_module_name(self):
        """Endpoints under a discovered module all use that module's
        prefix as the dotted-name root. (selectcourse → tis, transit
        → transit, nces → nces.)"""
        found = discover_module_apis()
        for mod_name, mod_api in found.items():
            for ep in mod_api.endpoints:
                prefix = ep.name.split(".", 1)[0]
                assert prefix == mod_name, (
                    f"{mod_name} registered endpoint {ep.name!r} with "
                    f"wrong prefix {prefix!r}")

    def test_skips_submodules_without_api(self):
        """A submodule without api.py is silently skipped, not an error."""
        found = discover_module_apis()
        # lib / cli / context / sso etc. — none ship api.py
        for name in ("lib", "cli", "context", "sso", "webui"):
            assert name not in found, (
                f"{name} should not have been discovered as an api module")

    def test_skips_underscore_prefixed_submodules(self):
        """Private modules (_*) are skipped."""
        found = discover_module_apis()
        assert not any(n.startswith("_") for n in found)


# -- end-to-end: a Flask app gets only the requested endpoints ----------

class TestEndToEndMounting:
    """Build a real Flask app, mount the default skin's manifest, and
    verify which routes are reachable. This is the contract that
    actually ships."""

    def test_default_skin_mounts_all_three_module_namespaces(self):
        from flask import Flask
        from sustech_survival.webui.app import create_app
        app = create_app(skin="default")
        rules = {(r.endpoint or "") for r in app.url_map.iter_rules()}
        # Every endpoint from the three modules should be reachable.
        for name in ("tis.info", "tis.courses", "tis.enrolled",
                     "transit.live", "nces.status"):
            assert name in rules, (
                f"default skin's manifest should have mounted {name!r}, "
                f"but it's missing from {sorted(rules)}")

    def test_empty_api_manifest_mounts_no_endpoints(self):
        """A skin that asks for no APIs still gets the head's own routes
        (/, /static, etc.) but no module endpoints."""
        from sustech_survival.webui.app import create_app
        # Test by creating a temporary skin with api=[].
        import json, tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            (base / "static").mkdir()
            (base / "index.html").write_text("<h1>x</h1>", encoding="utf-8")
            (base / "manifest.json").write_text(json.dumps({
                "name": "slim", "version": "1.0.0",
                "entry": "index.html", "api": [],
            }), encoding="utf-8")
            app = create_app(skin_path=str(base))
            rules = {(r.endpoint or "") for r in app.url_map.iter_rules()}
            # No module endpoints mounted, but the head's own routes are
            # there (no `tis.info`, etc.).
            assert "tis.info" not in rules
            assert "transit.live" not in rules
            assert "nces.status" not in rules