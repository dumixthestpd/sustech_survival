"""Tests for the BB module import path.

The bug: `sustech_survival.bb.submit` resolves to the submit() function
inside the module (because a function and a module share the name),
breaking `import sustech_survival.bb.submit as m` and any test that
needs to monkeypatch module-level names.

The fix: rename submit() → submit_file() so direct module imports
work correctly.
"""
import pytest


class TestBbSubmitModuleImportable:
    def test_bb_submit_imports_as_module(self):
        """`import sustech_survival.bb.submit as m` should resolve to the MODULE."""
        import sustech_survival.bb.submit as m
        # A module has __file__ and __loader__; a function doesn't
        assert hasattr(m, "__file__"), \
            "sustech_survival.bb.submit should resolve to the MODULE, not the submit() function"
        # The module should expose submit_assignment
        assert hasattr(m, "submit_assignment"), \
            "module should expose submit_assignment"
        assert callable(m.submit_assignment)

    def test_no_named_submit_function_in_module(self):
        """The old submit() function should be renamed to submit_file()."""
        import sustech_survival.bb.submit as m
        # After rename: no top-level `submit` function (only submit_file)
        if hasattr(m, "submit"):
            # If something called 'submit' exists, it must not be the old wrapper
            # (it could be a list/dict — the check is that it's not callable as the old entry)
            import inspect
            assert not inspect.isfunction(m.submit) or m.submit.__name__ != "submit", \
                "Old submit() function should be renamed to submit_file()"

    def test_submit_file_function_exists(self):
        """submit_file() should exist as the renamed wrapper."""
        from sustech_survival.bb.submit import submit_file
        assert callable(submit_file)

    def test_module_exposes_other_expected_helpers(self):
        """All the AI-facing wrappers should still be reachable from the module."""
        import sustech_survival.bb.submit as m
        assert hasattr(m, "submit_file"), "submit_file wrapper"
        assert hasattr(m, "submit_assignment"), "submit_assignment primitive"
        assert hasattr(m, "check_attempts"), "check_attempts"
        assert hasattr(m, "find_assignment"), "find_assignment"
        assert hasattr(m, "list_upcoming"), "list_upcoming"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
