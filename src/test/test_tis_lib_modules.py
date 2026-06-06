"""Test TIS module: direct TISAuth usage, no get_auth(), no dead session wrappers."""
import warnings


class TestTISGradesDirectImport:
    """tis/grades.py should import TISAuth directly."""

    def test_grades_imports_tis_auth(self):
        from sustech_survival.tis.grades import TISAuth as _T
        assert _T is not None

    def test_grades_has_make_session(self):
        from sustech_survival.tis.grades import _make_session
        assert callable(_make_session)

    def test_grades_no_get_auth(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            import sustech_survival.tis.grades as m
            deprec = [x for x in w if issubclass(x.category, DeprecationWarning) and "get_auth" in str(x.message)]
            assert len(deprec) == 0, f"get_auth deprecation in grades: {deprec}"


class TestTISCoursesDirectImport:
    """tis/courses.py should import TISAuth directly."""

    def test_courses_imports_tis_auth(self):
        from sustech_survival.tis.courses import TISAuth as _T
        assert _T is not None

    def test_courses_has_make_session(self):
        from sustech_survival.tis.courses import _make_session
        assert callable(_make_session)

    def test_courses_no_get_auth(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            import sustech_survival.tis.courses as m
            deprec = [x for x in w if issubclass(x.category, DeprecationWarning) and "get_auth" in str(x.message)]
            assert len(deprec) == 0, f"get_auth deprecation in courses: {deprec}"


class TestTISEvalDirectImport:
    """tis/eval.py should import TISAuth directly."""

    def test_eval_no_get_auth(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            import sustech_survival.tis.eval as m
            deprec = [x for x in w if issubclass(x.category, DeprecationWarning) and "get_auth" in str(x.message)]
            assert len(deprec) == 0, f"get_auth deprecation in eval: {deprec}"


class TestTISEvalDeprecated:
    """tis/eval is deprecated — TIS 评教 window closed 2026-06-05.

    Both the package (eval/__init__.py) and the legacy shim (eval.py) must
    emit a DeprecationWarning on import explaining the closure.
    """

    def test_eval_deprecated_on_import(self):
        # Force a fresh module body via reload — earlier tests in this
        # session may have already imported the module and Python's
        # default warning filter deduplicates per (msg, category, module,
        # lineno), so a plain `import` would not re-emit.
        import importlib
        import importlib.util
        import sustech_survival.tis.eval as eval_mod  # noqa: F401

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            importlib.reload(eval_mod)

            deprec = [
                x for x in w
                if issubclass(x.category, DeprecationWarning)
                and "2026-06-05" in str(x.message)
            ]
            assert deprec, (
                "expected a DeprecationWarning mentioning the 2026-06-05 "
                f"closure; got: {[str(x.message) for x in w]}"
            )

            messages = [str(x.message) for x in w
                        if issubclass(x.category, DeprecationWarning)]
            assert any("TIS web UI" in m for m in messages), (
                "deprecation message should point users to the TIS web UI; "
                f"got: {messages}"
            )

        # The shim eval.py is shadowed by the package (Python prefers
        # packages over modules of the same name), so a normal import
        # never reaches it. Load the file directly to verify its warning.
        shim_path = eval_mod.__file__.replace("__init__.py", "..").replace(
            "eval/__init__.py", "eval.py"
        )
        # Fallback to sibling path resolution
        import os.path as _p
        shim_path = _p.normpath(_p.join(_p.dirname(eval_mod.__file__), "..", "eval.py"))

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            spec = importlib.util.spec_from_file_location(
                "_test_eval_shim", shim_path
            )
            shim = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(shim)
            shim_msgs = [str(x.message) for x in w
                         if issubclass(x.category, DeprecationWarning)]
            assert any("shim" in m and "2026-06-05" in m for m in shim_msgs), (
                f"expected the eval.py shim to emit its own DeprecationWarning; "
                f"got: {shim_msgs}"
            )


class TestTISExamsDirectImport:
    """tis/exams.py should use its own _login, not get_auth."""

    def test_exams_no_get_auth(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            import sustech_survival.tis.exams as m
            deprec = [x for x in w if issubclass(x.category, DeprecationWarning) and "get_auth" in str(x.message)]
            assert len(deprec) == 0, f"get_auth deprecation in exams: {deprec}"


class TestTISTimetableDirectImport:
    """tis/timetable.py should use its own _login, not get_auth."""

    def test_timetable_no_get_auth(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            import sustech_survival.tis.timetable as m
            deprec = [x for x in w if issubclass(x.category, DeprecationWarning) and "get_auth" in str(x.message)]
            assert len(deprec) == 0, f"get_auth deprecation in timetable: {deprec}"


class TestTISCampusScheduleDirectImport:
    """tis/campus_schedule.py should use its own _login, not get_auth."""

    def test_campus_schedule_no_get_auth(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            import sustech_survival.tis.campus_schedule as m
            deprec = [x for x in w if issubclass(x.category, DeprecationWarning) and "get_auth" in str(x.message)]
            assert len(deprec) == 0, f"get_auth deprecation in campus_schedule: {deprec}"


class TestLibModuleDirectImport:
    """lib/ module should import LibAuth directly, not via get_auth."""

    def test_lib_login_no_get_auth(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            import sustech_survival.lib.login as m
            deprec = [x for x in w if issubclass(x.category, DeprecationWarning) and "get_auth" in str(x.message)]
            assert len(deprec) == 0, f"get_auth deprecation in lib/login: {deprec}"

    def test_lib_login_uses_lib_auth(self):
        from sustech_survival.lib.login import _auth
        assert _auth.__class__.__name__ == "LibAuth"