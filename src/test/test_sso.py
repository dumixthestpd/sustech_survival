import pytest, warnings


class TestGetAuthDeprecation:
    """get_auth() should emit DeprecationWarning; direct import preferred."""

    def test_get_auth_bb_deprecated(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            from sustech_survival.sso import get_auth
            get_auth("bb")
        assert len(w) == 1
        assert issubclass(w[0].category, DeprecationWarning)
        assert "BBAuth" in str(w[0].message)

    def test_get_auth_tis_deprecated(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            from sustech_survival.sso import get_auth
            get_auth("tis")
        assert len(w) == 1
        assert issubclass(w[0].category, DeprecationWarning)
        assert "TISAuth" in str(w[0].message)

    def test_get_auth_lib_deprecated(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            from sustech_survival.sso import get_auth
            get_auth("lib")
        assert len(w) == 1
        assert issubclass(w[0].category, DeprecationWarning)
        assert "LibAuth" in str(w[0].message)


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