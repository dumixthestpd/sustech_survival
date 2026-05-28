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