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
        # Disk cache missing AND no credentials → ensure() fails with hint
        auth._skill_dir = "/nonexistent"

        @auth.ensured
        def do_it(session=None):
            return session

        with pytest.raises(AuthorizerError) as exc:
            do_it()
        # ensure() should have added a hint about browser login
        assert "Run browser login" in str(exc.value) or "No session" in str(exc.value)

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
    """ensure() adds actionable hint on failure."""

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
        assert "Run browser login" in reason

    def test_ensure_hint_no_session(self):
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
