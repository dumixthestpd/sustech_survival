import pytest


class TestSessionModule:
    """bb/session.py should have clean exports — no dead wrappers."""

    def test_session_has_bb_base(self):
        from sustech_survival.bb.session import BB_BASE
        assert BB_BASE == "https://bb.sustech.edu.cn"

    def test_session_has_auth(self):
        from sustech_survival.bb.session import _auth
        assert _auth is not None

    def test_session_has_slugify(self):
        from sustech_survival.bb.session import slugify
        assert slugify("Experiment 6 (Viscosity)") == "Experiment-6-Viscosity"

    def test_no_load_session(self):
        import sustech_survival.bb.session as m
        assert not hasattr(m, "load_session") or not callable(getattr(m, "load_session", None)) or getattr(m, "load_session", None).__module__ == "sustech_survival.sso.authorizer"

    def test_no_check_session(self):
        import sustech_survival.bb.session as m
        assert not hasattr(m, "check_session") or "session" not in getattr(m, "check_session", lambda: None).__name__.lower()


class TestBBAuthImport:
    """BB modules should import BBAuth directly, not via get_auth()."""

    def test_bb_cli_uses_bb(self):
        from sustech_survival.bb.cli import _bb
        assert _bb.__class__.__name__ == "BBAuth"

    def test_bb_pages_uses_bb(self):
        from sustech_survival.bb.pages import _bb
        assert _bb.__class__.__name__ == "BBAuth"

    def test_bb_submit_uses_bb(self):
        from sustech_survival.bb.submit import _bb
        assert _bb.__class__.__name__ == "BBAuth"