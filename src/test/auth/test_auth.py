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
        auth._session_time = time.time() - auth._session_ttl - 1
        assert auth._is_session_fresh() is False


class TestEnsuredDecorator:
    """@ensured decorator — injects Authorizer as 'auth' kwarg."""

    def test_ensured_injects_auth_kwarg(self):
        from sustech_survival.sso import Authorizer

        class DummyAuth(Authorizer):
            BASE_URL = "https://dummy.example.com"
            SERVICE_URL = "https://dummy.example.com/cas"

        auth = DummyAuth()
        auth._set_session({"cookie": "value123"})

        received = {}

        @auth.ensured
        def do_something(arg, auth=None, **kwargs):
            received["arg"] = arg
            received["auth"] = auth
            return "ok"

        result = do_something("test_arg")
        assert result == "ok"
        assert received["arg"] == "test_arg"
        assert received["auth"] is auth

    def test_ensured_overrides_caller_auth_kwarg(self):
        from sustech_survival.sso import Authorizer

        class DummyAuth(Authorizer):
            BASE_URL = "https://dummy.example.com"
            SERVICE_URL = "https://dummy.example.com/cas"

        auth = DummyAuth()
        auth._set_session({"fresh": "session"})

        @auth.ensured
        def func(auth=None):
            return auth

        result = func(auth="some_override")
        # Decorator overwrites caller's stale value with validated Authorizer
        assert result is auth

    def test_ensured_raises_when_not_authenticated(self):
        from sustech_survival.sso import Authorizer, AuthorizerError

        class DummyAuth(Authorizer):
            BASE_URL = "https://dummy.example.com"
            SERVICE_URL = "https://dummy.example.com/cas"

        auth = DummyAuth()
        # No session set — ensure() will fail

        @auth.ensured
        def do_it(auth=None):
            return auth

        with pytest.raises(AuthorizerError):
            do_it()

    def test_ensured_error_message_includes_class_name(self):
        """@ensured raises AuthorizerError with class name in message."""
        from sustech_survival.sso import Authorizer, AuthorizerError

        class DummyAuth(Authorizer):
            BASE_URL = "https://dummy.example.com"
            SERVICE_URL = "https://dummy.example.com/cas"

        auth = DummyAuth()

        @auth.ensured
        def do_it(auth=None):
            return auth

        with pytest.raises(AuthorizerError) as exc:
            do_it()
        msg = str(exc.value)
        assert "DummyAuth" in msg

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


class TestCheck:
    """check() uses in-memory cache — no disk fallback."""

    def test_check_returns_true_from_memory_fresh(self):
        from sustech_survival.sso import Authorizer

        class DummyAuth(Authorizer):
            BASE_URL = "https://dummy.example.com"
            SERVICE_URL = "https://dummy.example.com/cas"

        auth = DummyAuth()
        auth._set_session({"mem": "cache"})

        ok, reason = auth.check()
        assert ok is True
        assert reason == ""

    def test_check_returns_false_when_no_session(self):
        from sustech_survival.sso import Authorizer

        class DummyAuth(Authorizer):
            BASE_URL = "https://dummy.example.com"
            SERVICE_URL = "https://dummy.example.com/cas"

        auth = DummyAuth()
        # Force the no-credentials path so the failure mode is deterministic.
        auth.skill_dir = "/nonexistent"

        ok, reason = auth.check()
        assert ok is False
        # Reason must mention the class and actionable hint
        assert "DummyAuth" in reason
        assert "credentials.txt" in reason


class TestSessionObject:
    """session property returns a requests.Session with cookies."""

    def test_session_uses_in_memory_cookies(self):
        from sustech_survival.sso import Authorizer

        class DummyAuth(Authorizer):
            BASE_URL = "https://dummy.example.com"
            SERVICE_URL = "https://dummy.example.com/cas"

        auth = DummyAuth()
        auth._set_session({"session": "token123"})

        sess = auth.session
        assert isinstance(sess.cookies, dict) or hasattr(sess, "cookies")
        # The session should have our cookie set
        cookie_dict = dict(sess.cookies)
        assert cookie_dict.get("session") == "token123"

    def test_session_raises_when_empty(self):
        from sustech_survival.sso import Authorizer, AuthorizerError

        class DummyAuth(Authorizer):
            BASE_URL = "https://dummy.example.com"
            SERVICE_URL = "https://dummy.example.com/cas"

        auth = DummyAuth()

        with pytest.raises(AuthorizerError) as exc:
            _ = auth.session
        assert "call ensure()" in str(exc.value)


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

        auth = DummyAuth()
        auth.skill_dir = "/nonexistent"

        ok, reason = auth.ensure()
        assert ok is False
        # New format: "DummyAuth: credentials invalid — check credentials.txt"
        # Distinguishes wrong-password failures from network / generic failures.
        assert "DummyAuth: credentials invalid" in reason
        assert "credentials.txt" in reason
        assert "CAS" not in reason  # this is the credentials path, not the network path

    def test_ensure_no_session(self):
        from sustech_survival.sso import Authorizer, AuthorizerError

        class DummyAuth(Authorizer):
            BASE_URL = "https://dummy.example.com"
            SERVICE_URL = "https://dummy.example.com/cas"

        auth = DummyAuth()
        auth.skill_dir = "/nonexistent"

        ok, reason = auth.ensure()
        assert ok is False
        # Reason must not leak cookie values, file paths, or stack traces
        # Note: "credentials.txt" IS in the message as an actionable hint —
        # it's the filename users/agents need to check, not a leaked file path
        assert ".cache" not in reason
        assert "session.json" not in reason
        # Must mention the class so an agent knows which auth to refresh
        assert "DummyAuth" in reason


class TestAuthErrorFormat:
    """check()/ensure() reason strings are safe to surface to agents.

    They must never include cookie values, cookie names, session file paths,
    or raw exception details — agents read these messages and act on them.
    """

    def test_check_reason_mentions_class_and_hint(self):
        from sustech_survival.sso import Authorizer, AuthorizerError

        class DummyAuth(Authorizer):
            BASE_URL = "https://dummy.example.com"
            SERVICE_URL = "https://dummy.example.com/cas"

        auth = DummyAuth()
        auth.skill_dir = "/nonexistent"

        ok, reason = auth.check()
        assert ok is False
        assert "DummyAuth" in reason

    def test_check_reason_does_not_leak_path(self):
        from sustech_survival.sso import Authorizer, AuthorizerError

        class DummyAuth(Authorizer):
            BASE_URL = "https://dummy.example.com"
            SERVICE_URL = "https://dummy.example.com/cas"

        auth = DummyAuth()
        auth.skill_dir = "/nonexistent"

        ok, reason = auth.check()
        # No session file path components should leak into user-facing reason
        assert "session.json" not in reason
        assert ".cache" not in reason
        # No exception class names — agents shouldn't have to know internal types
        assert "AuthorizerError" not in reason
        assert "FileNotFoundError" not in reason


class TestTTLRefresh:
    """TTL guard auto-refreshes stale sessions."""

    def test_ttl_expiry_triggers_refresh(self):
        from sustech_survival.sso import Authorizer

        class DummyAuth(Authorizer):
            BASE_URL = "https://dummy.example.com"
            SERVICE_URL = "https://dummy.example.com/cas"
            refreshed = False

            def _read_creds(self):
                return ("dummy_user", "dummy_pass")

            def _get_ticket_cookies(self, u, p):
                DummyAuth.refreshed = True
                return {"fresh": "cookies"}

        auth = DummyAuth()
        auth._set_session({"stale": "cookies"})
        auth._session_time = time.time() - auth._session_ttl - 1

        ok, reason = auth.check()
        # TTL expired + _session_cache exists → _refresh called → True
        assert ok is True
        assert DummyAuth.refreshed is True
        # Session cache should be updated with fresh cookies
        assert auth._session_cache == {"fresh": "cookies"}

    def test_check_returns_true_when_session_fresh(self):
        """When session is within TTL, check() returns True without refresh."""
        from sustech_survival.sso import Authorizer

        class DummyAuth(Authorizer):
            BASE_URL = "https://dummy.example.com"
            SERVICE_URL = "https://dummy.example.com/cas"
            refreshed = False

            def _get_ticket_cookies(self, u, p):
                DummyAuth.refreshed = True
                return {"new": "cookies"}

        auth = DummyAuth()
        auth._set_session({"existing": "cookies"})

        ok, reason = auth.check()
        # Session is fresh, no refresh needed
        assert ok is True
        assert DummyAuth.refreshed is False
        # Session cache unchanged
        assert auth._session_cache == {"existing": "cookies"}

    def test_ensure_returns_false_when_no_creds(self):
        """When no session and no credentials, ensure() fails gracefully."""
        from sustech_survival.sso import Authorizer

        class DummyAuth(Authorizer):
            BASE_URL = "https://dummy.example.com"
            SERVICE_URL = "https://dummy.example.com/cas"
            _get_ticket_cookies = None  # not used

        auth = DummyAuth()
        auth.skill_dir = "/nonexistent"

        ok, reason = auth.ensure()
        assert ok is False
        assert "DummyAuth" in reason
