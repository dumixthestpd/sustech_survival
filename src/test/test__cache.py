"""
Tests for sustech_survival._cache — the uniform cache layout helper.

These tests are offline. They cover the public surface used by every
module that needs to persist anything to disk:

- ``cache_path(module, *parts)`` — path resolution under
  ``~/.sustech_survival/cache/<module>/...``
- ``save_json`` / ``load_json`` — atomic write + safe read
- ``http_get_with_etag`` — 200 / 304 / error handling

The HTTP helper is exercised against ``http.server`` on localhost so the
tests don't depend on network availability.
"""
from __future__ import annotations

import json
import os
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from sustech_survival import _cache


# -- cache_path ---------------------------------------------------


class TestCachePath:
    def test_returns_tmp_root_for_module(self):
        p = _cache.cache_path("calendar")
        assert p.parent == _cache.tmp_root()
        assert p.name == "calendar"

    def test_appends_parts(self):
        p = _cache.cache_path("calendar", "2026", "general.json")
        assert p == _cache.cache_path("calendar") / "2026" / "general.json"

    def test_single_part(self):
        p = _cache.cache_path("bb", "submit.json")
        assert p == _cache.tmp_root() / "bb" / "submit.json"

    def test_no_parts_returns_module_dir(self):
        assert _cache.cache_path("bb") == _cache.tmp_root() / "bb"

    def test_does_not_create_directory(self, tmp_path):
        # Module subdir shouldn't exist before any write — read-only probes
        # must not have side effects.
        module = "_test_no_create_dir"
        p = _cache.cache_path(module, "deep", "nested", "file.json")
        assert not p.parent.exists()
        assert not p.exists()

    @pytest.mark.parametrize("bad", ["", ".", "..", "a/b", "a\\b"])
    def test_invalid_module_name_raises(self, bad):
        with pytest.raises(ValueError):
            _cache.cache_path(bad)


# -- save_json / load_json ----------------------------------------


class TestSaveLoadJson:
    def test_round_trip(self, tmp_path):
        target = tmp_path / "x.json"
        data = {"a": 1, "b": [1, 2, 3], "中文": "value"}
        _cache.save_json(target, data)
        assert _cache.load_json(target) == data

    def test_creates_parent_dirs(self, tmp_path):
        target = tmp_path / "deep" / "nested" / "dir" / "x.json"
        assert not target.parent.exists()
        _cache.save_json(target, {"k": "v"})
        assert target.exists()

    def test_no_tmp_file_left_on_success(self, tmp_path):
        target = tmp_path / "x.json"
        _cache.save_json(target, {"k": "v"})
        siblings = list(target.parent.iterdir())
        assert siblings == [target]

    def test_no_tmp_file_left_on_failure(self, tmp_path):
        # An object json can't encode must raise, but the tmp file should
        # be cleaned up.
        target = tmp_path / "x.json"
        class NotSerializable:
            pass
        with pytest.raises(TypeError):
            _cache.save_json(target, {"bad": NotSerializable()})
        siblings = list(target.parent.iterdir())
        assert siblings == [], f"unexpected siblings: {siblings}"

    def test_load_missing_returns_none(self, tmp_path):
        assert _cache.load_json(tmp_path / "absent.json") is None

    def test_load_corrupt_returns_none(self, tmp_path):
        target = tmp_path / "x.json"
        target.write_text("{ this is not valid json")
        assert _cache.load_json(target) is None

    def test_save_pretty_prints_and_sorts(self, tmp_path):
        # Cached JSONs should be human-diffable.
        target = tmp_path / "x.json"
        _cache.save_json(target, {"b": 1, "a": 2})
        content = target.read_text(encoding="utf-8")
        # sort_keys=True: 'a' before 'b' on the first line.
        assert content.index('"a"') < content.index('"b"')
        # indent=2: newlines between fields.
        assert "\n" in content


# -- sha1 ---------------------------------------------------------


class TestSha1:
    def test_sha1_bytes_known_value(self):
        assert _cache.sha1_bytes(b"hello") == (
            "aaf4c61ddcc5e8a2dabede0f3b482cd9aea9434d"
        )

    def test_sha1_file(self, tmp_path):
        target = tmp_path / "x.bin"
        target.write_bytes(b"hello")
        assert _cache.sha1_file(target) == (
            "aaf4c61ddcc5e8a2dabede0f3b482cd9aea9434d"
        )

    def test_sha1_file_missing(self, tmp_path):
        assert _cache.sha1_file(tmp_path / "absent") is None


# -- http_get_with_etag -------------------------------------------


class _RecordingHandler(BaseHTTPRequestHandler):
    """Track every request's headers so tests can assert them."""

    requests: list = []  # populated by tests

    def log_message(self, format, *args):
        pass  # silence test output

    def do_GET(self):  # noqa: N802 (BaseHTTPRequestHandler API)
        # Record the If-None-Match header (or its absence).
        inm = self.headers.get("If-None-Match")
        type(self).requests.append({"path": self.path, "if_none_match": inm})
        # Behaviour controlled by a module-level dict the test sets up.
        state = _STATE
        if state.get("mode") == "304":
            self.send_response(304)
            self.end_headers()
            return
        body = state["body"]
        etag = state["etag"]
        self.send_response(200)
        if etag:
            self.send_header("ETag", etag)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


_STATE: dict = {"mode": "200", "body": b"{}", "etag": None}


@pytest.fixture
def http_server():
    """Spin up a localhost HTTP server on a free port."""
    # Find a free port.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    # Reset request log.
    _RecordingHandler.requests = []
    server = HTTPServer(("127.0.0.1", port), _RecordingHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()
    thread.join(timeout=2)


class TestHttpGetWithEtag:
    def test_200_returns_body_and_etag(self, http_server):
        _STATE.update(mode="200", body=b'{"hello":"world"}', etag='"abc123"')
        body, etag, status = _cache.http_get_with_etag(f"{http_server}/x.json")
        assert status == 200
        assert body == b'{"hello":"world"}'
        assert etag == '"abc123"'

    def test_no_etag_in_request_without_if_none_match(self, http_server):
        _STATE.update(mode="200", body=b"{}", etag='"e1"')
        _cache.http_get_with_etag(f"{http_server}/x.json")
        assert _RecordingHandler.requests[0]["if_none_match"] is None

    def test_if_none_match_sent_when_etag_provided(self, http_server):
        _STATE.update(mode="200", body=b"{}", etag='"e2"')
        _cache.http_get_with_etag(f"{http_server}/x.json", etag='"old-etag"')
        assert _RecordingHandler.requests[0]["if_none_match"] == '"old-etag"'

    def test_304_returns_none_body_and_echoes_etag(self, http_server):
        _STATE.update(mode="304", body=b"", etag=None)
        body, etag, status = _cache.http_get_with_etag(
            f"{http_server}/x.json", etag='"my-etag"'
        )
        assert status == 304
        assert body is None
        assert etag == '"my-etag"'


# -- ensure_cachedir ----------------------------------------------


class TestEnsureCachedir:
    def test_creates_missing_dir(self, tmp_path):
        target = tmp_path / "a" / "b" / "c"
        result = _cache.ensure_cachedir(target)
        assert result == target
        assert target.is_dir()

    def test_existing_dir_is_noop(self, tmp_path):
        target = tmp_path / "already"
        target.mkdir()
        # Should not raise.
        assert _cache.ensure_cachedir(target) == target


# -- clear_cache (module scale) ----------------------------------


class TestClearCache:
    def test_wipes_everything_for_module(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SUSTECH_CACHE_DIR", str(tmp_path))
        # Populate two modules.
        _cache.save_json(_cache.cache_path("mod_a", "x.json"), {"n": 1})
        _cache.save_json(_cache.cache_path("mod_a", "sub", "y.json"), {"n": 2})
        _cache.save_json(_cache.cache_path("mod_b", "z.json"), {"n": 3})
        # Wipe only mod_a.
        removed = _cache.clear_cache("mod_a")
        assert removed == 2
        assert not _cache.cache_path("mod_a").exists()
        # mod_b untouched.
        assert _cache.cache_path("mod_b", "z.json").exists()

    def test_no_op_when_module_unknown(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SUSTECH_CACHE_DIR", str(tmp_path))
        assert _cache.clear_cache("never_existed") == 0

    def test_invalid_module_name_rejected(self):
        with pytest.raises(ValueError):
            _cache.clear_cache("a/b")


# -- default root + root= kwarg ---------------------------------


class TestCacheRootKwarg:
    def test_default_root_is_home_dotdir_cache(self, monkeypatch, tmp_path):
        """Default cache root is ~/.sustech_survival/cache — home-based, not
        cwd-based (no /__sustech_cache__), one unified dot-directory."""
        monkeypatch.delenv("SUSTECH_HOME", raising=False)
        monkeypatch.delenv("SUSTECH_CACHE_DIR", raising=False)
        monkeypatch.delenv("SUSTECH_CONFIG_DIR", raising=False)
        monkeypatch.setattr(_cache, "user_home", lambda: tmp_path)
        assert _cache.tmp_root() == tmp_path / ".sustech_survival" / "cache"
        assert _cache.cache_path("sometest") == \
            tmp_path / ".sustech_survival" / "cache" / "sometest"

    def test_config_root_default_is_home_dotdir(self, monkeypatch, tmp_path):
        """config_root() defaults to ~/.sustech_survival; env override wins."""
        monkeypatch.delenv("SUSTECH_HOME", raising=False)
        monkeypatch.delenv("SUSTECH_CONFIG_DIR", raising=False)
        monkeypatch.delenv("SUSTECH_CACHE_DIR", raising=False)
        monkeypatch.setattr(_cache, "user_home", lambda: tmp_path)
        assert _cache.config_root() == tmp_path / ".sustech_survival"
        # cache lives *inside* the config dir by default
        assert _cache.tmp_root().parent == _cache.config_root()

    def test_config_root_env_override(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SUSTECH_CONFIG_DIR", str(tmp_path / "cfg"))
        assert _cache.config_root() == tmp_path / "cfg"
        # skins + default cache both hang off the configured dir
        assert _cache.tmp_root() == tmp_path / "cfg" / "cache"

    def test_env_override_absolute(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SUSTECH_CACHE_DIR", str(tmp_path))
        assert _cache.tmp_root() == tmp_path

    def test_env_override_relative_resolves_against_cwd(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SUSTECH_CACHE_DIR", "rel_cache")
        monkeypatch.chdir(tmp_path)
        assert _cache.tmp_root() == tmp_path / "rel_cache"

    def test_explicit_root_kwarg_beats_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SUSTECH_CACHE_DIR", str(tmp_path / "env_dir"))
        explicit = tmp_path / "kwarg_dir"
        assert _cache.tmp_root(root=explicit) == explicit
        assert _cache.cache_path("mod", "x.json", root=explicit) == explicit / "mod" / "x.json"
        assert _cache.cache_path("mod", root=explicit) == explicit / "mod"

    def test_clear_cache_honours_env_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SUSTECH_CACHE_DIR", str(tmp_path))
        target = tmp_path / "sel" / "f.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{}", encoding="utf-8")
        n = _cache.clear_cache("sel")
        assert n == 1
        assert not (tmp_path / "sel").exists()


# -- SUSTECH_HOME: one changeable anchor for the whole tree -----------------


class TestHomeRoot:
    def test_home_root_defaults_to_user_home(self, monkeypatch, tmp_path):
        monkeypatch.delenv("SUSTECH_HOME", raising=False)
        monkeypatch.setattr(_cache, "user_home", lambda: tmp_path)
        assert _cache.home_root() == tmp_path

    def test_home_root_env_override(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SUSTECH_HOME", str(tmp_path / "anchor"))
        assert _cache.home_root() == tmp_path / "anchor"
        # the whole tree follows: cache + skins hang off the anchor
        assert _cache.config_root() == tmp_path / "anchor" / ".sustech_survival"
        assert _cache.tmp_root() == tmp_path / "anchor" / ".sustech_survival" / "cache"

    def test_home_root_relative_resolves_against_home(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SUSTECH_HOME", "data")
        monkeypatch.setattr(_cache, "user_home", lambda: tmp_path)
        assert _cache.home_root() == tmp_path / "data"


# -- config_file / load_config ----------------------------------------------


class TestConfigFile:
    def test_config_file_is_config_json_under_root(self, monkeypatch, tmp_path):
        monkeypatch.delenv("SUSTECH_HOME", raising=False)
        monkeypatch.delenv("SUSTECH_CONFIG_DIR", raising=False)
        monkeypatch.setattr(_cache, "user_home", lambda: tmp_path)
        assert _cache.config_file() == tmp_path / ".sustech_survival" / "config.json"

    def test_load_config_missing_returns_empty(self, monkeypatch, tmp_path):
        monkeypatch.setattr(_cache, "config_file",
                            lambda root=None: tmp_path / "nope.json")
        assert _cache.load_config() == {}

    def test_load_config_reads_file(self, monkeypatch, tmp_path):
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps({"downloads_dir": "D:/out", "bb": {"x": 1}}),
                       encoding="utf-8")
        monkeypatch.setattr(_cache, "config_file",
                            lambda root=None: cfg)
        assert _cache.load_config() == {"downloads_dir": "D:/out", "bb": {"x": 1}}

    def test_load_config_corrupt_returns_empty(self, monkeypatch, tmp_path):
        cfg = tmp_path / "config.json"
        cfg.write_text("{not json", encoding="utf-8")
        monkeypatch.setattr(_cache, "config_file",
                            lambda root=None: cfg)
        assert _cache.load_config() == {}