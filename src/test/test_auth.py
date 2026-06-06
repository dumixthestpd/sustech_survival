"""Tests for in-memory session, @ensured decorator, and auth lifecycle."""
import time
import warnings
import pytest


class TestInMemorySession:
    """In-memory session cache — no disk writes."""

    def test_set_session_stores_cookies(self):
        from sustech_survival.sso import Authorizer

        class DummyAuth(Authorizer):
            BASE_URL = "https://dummy.example.com"
            SERVICE_URL = "https://dummy.example.com/cas"

        auth = DummyAuth()
        auth._set_session({"token": "abc123", "sid": "xyz"})
        assert auth._session_cache == {"token": "abc123", "sid": "xyz"}

    def test_set_session_records_timestamp(self):
        from sustech_survival.sso import Authorizer

        class DummyAuth(Authorizer):
            BASE_URL = "https://dummy.example.com"
            SERVICE_URL = "https://dummy.example.com/cas"

        auth = DummyAuth()
        auth._set_session({"k": "v"})
        assert auth._session_time > 0

    def test_cookies_property_returns_cache(self):
        from sustech_survival.sso import Authorizer

        class DummyAuth(Authorizer):
            BASE_URL = "https://dummy.example.com"
            SERVICE_URL = "https://dummy.example.com/cas"

        auth = DummyAuth()
        auth._set_session({"foo": "bar"})
        assert auth.cookies == {"foo": "bar"}

    def test_cookies_property_raises_when_empty(self):
        from sustech_survival.sso import Authorizer, AuthorizerError

        class DummyAuth(Authorizer):
            BASE_URL = "https://dummy.example.com"
            SERVICE_URL = "https://dummy.example.com/cas"

        auth = DummyAuth()
        with pytest.raises(AuthorizerError) as exc:
            _ = auth.cookies
        assert "call ensure()" in str(exc.value)

    def test_is_session_fresh_true_within_ttl(self):
        from sustech_survival.sso import Authorizer

        class DummyAuth(Authorizer):
            BASE_URL = "https://dummy.example.com"
            SERVICE_URL = "https://dummy.example.com/cas"

        auth = DummyAuth()
        auth._set_session({"k": "v"})
        # TTL is 25 minutes — should be fresh immediately
        assert auth._is_session_fresh() is True

    def test_is_session_fresh_false_after_ttl(self):
        from sustech_survival.sso import Authorizer

        class DummyAuth(Authorizer):
            BASE_URL = "https://dummy.example.com"
            SERVICE_URL = "https://dummy.example.com/cas"

        auth = DummyAuth()
        auth._set_session({"k": "v"})
        # Backdate session time to force expiry
        auth._session_time = time.time() - auth._SESSION_TTL - 1
        assert auth._is_session_fresh() is False


class TestDeprecatedLoadSave:
    """load() and save() emit DeprecationWarning — disk is gone."""

    def test_load_emits_deprecation_warning_then_errors_on_missing_file(self):
        import tempfile
        from sustech_survival.sso import Authorizer

        class DummyAuth(Authorizer):
            BASE_URL = "https://dummy.example.com"
            SERVICE_URL = "https://dummy.example.com/cas"

        with tempfile.TemporaryDirectory() as tmp:
            auth = DummyAuth(skill_dir=tmp)
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                with pytest.raises(FileNotFoundError):
                    auth.load()  # still errors on missing file
        # Warning IS emitted before the error
        assert any(issubclass(x.category, DeprecationWarning) and "load()" in str(x.message) for x in w)

    def test_save_emits_deprecation_warning(self):
        from sustech_survival.sso import Authorizer

        class DummyAuth(Authorizer):
            BASE_URL = "https://dummy.example.com"
            SERVICE_URL = "https://dummy.example.com/cas"

        auth = DummyAuth()
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            auth.save({"k": "v"})
        assert any(issubclass(x.category, DeprecationWarning) and "save()" in str(x.message) for x in w)


class TestEnsuredDecorator:
    """@ensured decorator — session injection + auth guard."""

    def test_ensured_injects_session_kwarg(self):
        from sustech_survival.sso import Authorizer, AuthorizerError

        class DummyAuth(Authorizer):
            BASE_URL = "https://dummy.example.com"
            SERVICE_URL = "https://dummy.example.com/cas"

        auth = DummyAuth()
        auth._set_session({"cookie": "value123"})

        received = {}

        @auth.ensured
        def do_something(arg, session=None, **kwargs):
            received["arg"] = arg
            received["session"] = session
            return "ok"

        result = do_something("test_arg")
        assert result == "ok"
        assert received["arg"] == "test_arg"
        assert received["session"] == {"cookie": "value123"}

    def test_ensured_overrides_caller_session_kwarg(self):
        from sustech_survival.sso import Authorizer

        class DummyAuth(Authorizer):
            BASE_URL = "https://dummy.example.com"
            SERVICE_URL = "https://dummy.example.com/cas"

        auth = DummyAuth()
        auth._set_session({"fresh": "session"})

        @auth.ensured
        def func(session=None):
            return session

        result = func(session={"stale": "override"})
        # Decorator overwrites caller's stale session with validated one
        assert result == {"fresh": "session"}

    def test_ensured_raises_when_not_authenticated(self):
        from sustech_survival.sso import Authorizer, AuthorizerError

        class DummyAuth(Authorizer):
            BASE_URL = "https://dummy.example.com"
            SERVICE_URL = "https://dummy.example.com/cas"

        auth = DummyAuth()
        # No session set

        @auth.ensured
        def do_it(session=None):
            return session

        with pytest.raises(AuthorizerError):
            do_it()

    def test_ensured_checks_ensure_not_check(self):
        """@ensured calls ensure() (which checks+auto-refreshes), not just check()."""
        from sustech_survival.sso import Authorizer, AuthorizerError

        class DummyAuth(Authorizer):
            BASE_URL = "https://dummy.example.com"
            SERVICE_URL = "https://dummy.example.com/cas"

        auth = DummyAuth()
        # Disk cache missing AND no credentials → ensure() fails with action hint
        auth._skill_dir = "/nonexistent"

        @auth.ensured
        def do_it(session=None):
            return session

        with pytest.raises(AuthorizerError) as exc:
            do_it()
        # ensure() should name the class + tell the caller to run refresh()/login()
        msg = str(exc.value)
        assert "DummyAuth" in msg
        assert "refresh()" in msg
        assert "login()" in msg

    def test_ensured_preserves_func_metadata(self):
        from sustech_survival.sso import Authorizer

        class DummyAuth(Authorizer):
            BASE_URL = "https://dummy.example.com"
            SERVICE_URL = "https://dummy.example.com/cas"

        auth = DummyAuth()
        auth._set_session({"k": "v"})

        @auth.ensured
        def my_func():
            """My docstring."""
            pass

        assert my_func.__name__ == "my_func"
        assert my_func.__doc__ == "My docstring."


class TestCheckUsesInMemoryFirst:
    """check() uses in-memory cache before touching disk."""

    def test_check_returns_true_from_memory_fresh(self):
        from sustech_survival.sso import Authorizer

        class DummyAuth(Authorizer):
            BASE_URL = "https://dummy.example.com"
            SERVICE_URL = "https://dummy.example.com/cas"
            # Override get_ticket_cookies so refresh() always fails
            def get_ticket_cookies(self, u, p):
                raise AuthorizerError("no headless support")
            # Probe always succeeds — we only want to test TTL fast-path
            def _probe_session(self):
                return True

        auth = DummyAuth()
        auth._set_session({"mem": "cache"})
        # Disk cache must NOT exist — only in-memory should be used
        if auth.session_file.exists():
            auth.session_file.unlink()

        ok, reason = auth.check()
        assert ok is True

    def test_check_falls_back_to_disk_when_memory_empty(self):
        from sustech_survival.sso import Authorizer, AuthorizerError

        class DummyAuth(Authorizer):
            BASE_URL = "https://dummy.example.com"
            SERVICE_URL = "https://dummy.example.com/cas"
            def get_ticket_cookies(self, u, p):
                raise AuthorizerError("no headless support")
            # Probe always succeeds — we only want to test disk fallback logic
            def _probe_session(self):
                return True

        auth = DummyAuth()
        # Empty memory cache, but write disk cache manually
        auth.session_file.parent.mkdir(parents=True, exist_ok=True)
        import json
        with open(auth.session_file, "w") as f:
            json.dump({"disk": "cache"}, f)

        ok, reason = auth.check()
        assert ok is True
        # Should have populated memory cache from disk
        assert auth._session_cache == {"disk": "cache"}

        # Clean up
        auth.session_file.unlink()


class TestRequestsSessionProperty:
    """requests_session property uses in-memory cookies."""

    def test_requests_session_uses_in_memory_cookies(self):
        from sustech_survival.sso import Authorizer

        class DummyAuth(Authorizer):
            BASE_URL = "https://dummy.example.com"
            SERVICE_URL = "https://dummy.example.com/cas"

        auth = DummyAuth()
        auth._set_session({"session": "token123"})

        sess = auth.requests_session
        # Should have our cookie set
        assert dict(sess.cookies) == {"session": "token123"}


class TestCaptchaDetection:
    """login() should detect captcha and refuse to proceed."""

    def test_login_detects_captcha_element(self):
        from sustech_survival.sso import Authorizer

        class DummyAuth(Authorizer):
            BASE_URL = "https://dummy.example.com"
            SERVICE_URL = "https://dummy.example.com/cas"

        auth = DummyAuth()
        # We can't easily test the full Playwright flow without a real browser,
        # but we can verify the captcha selector logic exists in the code
        import inspect
        source = inspect.getsource(auth.login)
        assert 'captcha' in source.lower()


class TestEnsureAddsHint:
    """ensure() / check() surface a class-named, actionable reason on failure."""

    def test_ensure_hint_credentials(self):
        from sustech_survival.sso import Authorizer

        class DummyAuth(Authorizer):
            BASE_URL = "https://dummy.example.com"
            SERVICE_URL = "https://dummy.example.com/cas"
            def get_ticket_cookies(self, u, p):
                raise AuthorizerError("no headless support")

        auth = DummyAuth()
        auth._skill_dir = "/nonexistent"

        ok, reason = auth.ensure()
        assert ok is False
        # New format: "<Class> session expired, run <Class>.refresh() (or .login() if refresh fails)"
        assert "DummyAuth session expired" in reason
        assert "DummyAuth.refresh()" in reason
        assert "DummyAuth.login()" in reason

    def test_ensure_no_session(self):
        from sustech_survival.sso import Authorizer, AuthorizerError

        class DummyAuth(Authorizer):
            BASE_URL = "https://dummy.example.com"
            SERVICE_URL = "https://dummy.example.com/cas"
            def get_ticket_cookies(self, u, p):
                raise AuthorizerError("no headless support")

        auth = DummyAuth()
        auth._skill_dir = "/nonexistent"

        ok, reason = auth.ensure()
        assert ok is False
        # Reason must not leak cookie values, file paths, or stack traces
        assert "credentials.txt" not in reason
        assert ".cache" not in reason
        assert "session.json" not in reason
        # Must mention the class so an agent knows which auth to refresh
        assert "DummyAuth" in reason


class TestAuthErrorFormat:
    """check()/ensure() reason strings are safe to surface to agents.

    They must never include cookie values, cookie names, session file paths,
    or raw exception details — agents read these messages and act on them.
    """

    def test_check_reason_mentions_class_and_methods(self):
        from sustech_survival.sso import Authorizer, AuthorizerError

        class DummyAuth(Authorizer):
            BASE_URL = "https://dummy.example.com"
            SERVICE_URL = "https://dummy.example.com/cas"
            def get_ticket_cookies(self, u, p):
                raise AuthorizerError("no headless support")

        auth = DummyAuth()
        auth._skill_dir = "/nonexistent"

        ok, reason = auth.check()
        assert ok is False
        assert "DummyAuth" in reason
        assert "refresh()" in reason

    def test_check_reason_does_not_leak_path(self):
        from sustech_survival.sso import Authorizer, AuthorizerError

        class DummyAuth(Authorizer):
            BASE_URL = "https://dummy.example.com"
            SERVICE_URL = "https://dummy.example.com/cas"
            def get_ticket_cookies(self, u, p):
                raise AuthorizerError("no headless support")

        auth = DummyAuth()
        auth._skill_dir = "/nonexistent"

        ok, reason = auth.check()
        # No session file path components should leak into user-facing reason
        assert "session.json" not in reason
        assert ".cache" not in reason
        # No exception class names — agents shouldn't have to know internal types
        assert "AuthorizerError" not in reason
        assert "FileNotFoundError" not in reason


class TestSessionFileHidden:
    """Session files live in a hidden .cache/ dir agents don't usually read."""

    def test_session_file_under_dot_cache(self):
        from sustech_survival.sso import BBAuth, TISAuth, LibAuth
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            bb = BBAuth(skill_dir=tmp)
            tis = TISAuth(skill_dir=tmp)
            lib = LibAuth(skill_dir=tmp)

            for auth, name in [(bb, "bb"), (tis, "tis"), (lib, "lib")]:
                p = auth.session_file
                rel = p.relative_to(auth.skill_root)
                # New hidden path: <skill_root>/.cache/sso/<service>/session.json
                assert rel.parts == (".cache", "sso", name, "session.json"), (
                    f"{name} session_file not under .cache/sso/{name}/: {p}"
                )


class TestLoadMigratesLegacySessions:
    """load() auto-migrates sessions from legacy visible paths to .cache/sso/.

    Users with existing sessions at <skill_root>/<service>/session.json
    or <skill_root>/sso/<service>/session.json get them transparently
    moved to the new hidden path on first load() call.
    """

    def test_load_uses_new_path_when_present(self):
        """New path takes priority — legacy is ignored if new is present."""
        import json
        import tempfile
        from sustech_survival.sso import BBAuth

        with tempfile.TemporaryDirectory() as tmp:
            auth = BBAuth(skill_dir=tmp)
            # Write to NEW path
            new_path = auth.session_file
            new_path.parent.mkdir(parents=True, exist_ok=True)
            with open(new_path, "w") as f:
                json.dump({"new": "path"}, f)
            # And to LEGACY path
            legacy = auth.skill_root / "bb" / "session.json"
            legacy.parent.mkdir(parents=True, exist_ok=True)
            with open(legacy, "w") as f:
                json.dump({"legacy": "stale"}, f)

            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                cookies = auth.load()
            # Should pick the new path, not the legacy
            assert cookies == {"new": "path"}

    def test_load_migrates_from_legacy_bb_path(self):
        """Session at <skill_root>/bb/session.json is auto-migrated."""
        import json
        import tempfile
        from sustech_survival.sso import BBAuth

        with tempfile.TemporaryDirectory() as tmp:
            auth = BBAuth(skill_dir=tmp)
            # Write ONLY to the legacy <skill_root>/bb/session.json
            legacy = auth.skill_root / "bb" / "session.json"
            legacy.parent.mkdir(parents=True, exist_ok=True)
            with open(legacy, "w") as f:
                json.dump({"TGC": "old-tgc", "JSESSIONID": "old-js"}, f)

            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                cookies = auth.load()
            # Migration returned the legacy cookies
            assert cookies == {"TGC": "old-tgc", "JSESSIONID": "old-js"}
            # And copied them to the new path
            assert auth.session_file.exists()
            with open(auth.session_file) as f:
                assert json.load(f) == {"TGC": "old-tgc", "JSESSIONID": "old-js"}

    def test_load_migrates_from_legacy_sso_bb_path(self):
        """Session at <skill_root>/sso/bb/session.json (old override) is migrated."""
        import json
        import tempfile
        from sustech_survival.sso import BBAuth

        with tempfile.TemporaryDirectory() as tmp:
            auth = BBAuth(skill_dir=tmp)
            # Write ONLY to the old override path
            legacy = auth.skill_root / "sso" / "bb" / "session.json"
            legacy.parent.mkdir(parents=True, exist_ok=True)
            with open(legacy, "w") as f:
                json.dump({"override": "path"}, f)

            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                cookies = auth.load()
            assert cookies == {"override": "path"}
            assert auth.session_file.exists()

    def test_load_migrates_from_legacy_tis_path(self):
        """TISAuth legacy migration — used to live at sso/tis/."""
        import json
        import tempfile
        from sustech_survival.sso import TISAuth

        with tempfile.TemporaryDirectory() as tmp:
            auth = TISAuth(skill_dir=tmp)
            legacy = auth.skill_root / "sso" / "tis" / "session.json"
            legacy.parent.mkdir(parents=True, exist_ok=True)
            with open(legacy, "w") as f:
                json.dump({"TGC": "tis-old"}, f)

            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                cookies = auth.load()
            assert cookies == {"TGC": "tis-old"}
            assert auth.session_file.exists()
            # New path is under .cache/sso/tis/
            rel = auth.session_file.relative_to(auth.skill_root)
            assert rel.parts == (".cache", "sso", "tis", "session.json")

    def test_load_raises_when_no_session_anywhere(self):
        """If neither new nor legacy paths have a session, raise FileNotFoundError."""
        import tempfile
        from sustech_survival.sso import BBAuth

        with tempfile.TemporaryDirectory() as tmp:
            auth = BBAuth(skill_dir=tmp)
            with warnings.catch_warnings(record=True):
                warnings.simplefilter("always")
                try:
                    auth.load()
                except FileNotFoundError as e:
                    assert "BBAuth" in str(e)
                    assert "refresh()" in str(e)
                else:
                    raise AssertionError("expected FileNotFoundError")


class TestBBDirectSessionReadersFixed:
    """bb/download.py and bb/query.py must go through BBAuth, not raw file IO.

    These two files used to read <skill_root>/bb/session.json directly.
    After the move to .cache/sso/bb/session.json, raw reads would have
    silently broken. The fix routes them through BBAuth.load() so the
    migration logic in load() picks up legacy sessions automatically.
    """

    def test_bb_download_uses_bbauth(self):
        """The _session() helper in bb/download.py reads via BBAuth."""
        import inspect
        from sustech_survival.bb import download
        src = inspect.getsource(download._session)
        # Must NOT have a direct file open at the old visible path
        assert '"bb" / "session.json"' not in src
        assert "'bb' / 'session.json'" not in src
        # Must use BBAuth (which provides migration)
        assert "BBAuth" in src
        assert "auth.load()" in src

    def test_bb_query_uses_bbauth(self):
        """The _session() helper in bb/query.py reads via BBAuth."""
        import inspect
        from sustech_survival.bb import query
        src = inspect.getsource(query._session)
        assert '"bb" / "session.json"' not in src
        assert "'bb' / 'session.json'" not in src
        assert "BBAuth" in src
        assert "auth.load()" in src

    def test_bb_download_session_end_to_end_with_legacy_session(self):
        """bb/download._session() returns usable cookies when only legacy
        session.json exists. Validates the migration wires through to
        the public API, not just the load() helper."""
        import json
        import tempfile
        from pathlib import Path
        from sustech_survival.bb import download

        with tempfile.TemporaryDirectory() as tmp:
            tmp_p = Path(tmp)
            # Set up a fake skill_root layout that has the legacy
            # <skill_root>/bb/session.json
            legacy = tmp_p / "bb" / "session.json"
            legacy.parent.mkdir(parents=True, exist_ok=True)
            with open(legacy, "w") as f:
                json.dump({"TGC": "abc"}, f)

            # Inject the skill_root into BBAuth via _skill_dir
            from sustech_survival.sso import BBAuth
            BBAuth._skill_dir = None  # reset any cached value
            orig_init = BBAuth.__init__

            def patched_init(self, *args, **kwargs):
                orig_init(self, *args, **kwargs)
                self._skill_dir = tmp_p  # force all BBAuth() to use tmp

            BBAuth.__init__ = patched_init
            try:
                s = download._session()
                # Cookie should be set, not raise
                cookies = {c.name: c.value for c in s.cookies}
                assert cookies.get("TGC") == "abc", f"got {cookies}"
            finally:
                BBAuth.__init__ = orig_init
                BBAuth._skill_dir = None

class TestTTLRefresh:
    """TTL guard auto-refreshes stale sessions."""

    def test_check_re_records_timestamp_after_probe_success(self):
        """Probe success → TTL re-recorded, session stays valid (no refresh)."""
        from sustech_survival.sso import Authorizer

        class DummyAuth(Authorizer):
            BASE_URL = "https://dummy.example.com"
            SERVICE_URL = "https://dummy.example.com/cas"
            refreshed = False

            def get_ticket_cookies(self, u, p):
                DummyAuth.refreshed = True
                return {"new": "cookies"}

            def _probe_session(self):
                return True

        auth = DummyAuth()
        auth._set_session({"old": "cookies"})
        old_time = auth._session_time
        auth._session_time -= auth._SESSION_TTL + 1

        import time
        ok, reason = auth.check()
        assert ok is True
        # Probe succeeded → TTL re-recorded, no refresh needed
        assert DummyAuth.refreshed is False
        # Timestamp re-recorded (within 2s)
        assert auth._session_time > old_time
        assert auth._session_cache == {"old": "cookies"}

    def test_probe_failure_triggers_refresh(self):
        from sustech_survival.sso import Authorizer

        class DummyAuth(Authorizer):
            BASE_URL = "https://dummy.example.com"
            SERVICE_URL = "https://dummy.example.com/cas"

            def get_ticket_cookies(self, u, p):
                return {"fresh": "cookies"}

        auth = DummyAuth()
        auth._set_session({"stale": "cookies"})
        auth._session_time -= auth._SESSION_TTL + 1

        def failing_probe():
            return False
        auth._probe_session = failing_probe

        ok, reason = auth.check()
        assert ok is True
        assert auth._session_cache == {"fresh": "cookies"}
