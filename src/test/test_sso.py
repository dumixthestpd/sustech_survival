import pytest, warnings


class TestRemovedDeprecatedAPI:
    """get_auth was removed; register_auth is a no-op shim for backward compat."""

    def test_get_auth_removed(self):
        import sustech_survival.sso as sso
        assert not hasattr(sso, "get_auth")

    def test_register_auth_is_noop(self):
        import sustech_survival.sso as sso
        # register_auth still exists but is a no-op — calling it should not error
        assert hasattr(sso, "register_auth")
        result = sso.register_auth("test", None)
        assert result is None  # no-op returns None


class TestDirectAuthImports:
    """Direct {TIS,BB,Lib}Auth imports should NOT emit get_auth deprecation warnings."""

    def test_tis_auth_no_warning(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            from sustech_survival.sso import TISAuth
            _ = TISAuth()
        deprec = [x for x in w if issubclass(x.category, DeprecationWarning) and "get_auth" in str(x.message)]
        assert len(deprec) == 0

    def test_bb_auth_no_warning(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            from sustech_survival.sso import BBAuth
            _ = BBAuth()
        deprec = [x for x in w if issubclass(x.category, DeprecationWarning) and "get_auth" in str(x.message)]
        assert len(deprec) == 0

    def test_lib_auth_no_warning(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            from sustech_survival.sso import LibAuth
            _ = LibAuth()
        deprec = [x for x in w if issubclass(x.category, DeprecationWarning) and "get_auth" in str(x.message)]
        assert len(deprec) == 0


class TestLibDirectImport:
    """lib/login.py should import LibAuth directly, not via get_auth()."""

    def test_lib_login_uses_lib_auth_directly(self):
        from sustech_survival.lib.login import auth_singleton
        assert auth_singleton.__class__.__name__ == "LibAuth"