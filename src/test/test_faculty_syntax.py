"""Syntax + import check for sustech_survival.faculty.

Run:
    python -m pytest src/test/test_faculty_syntax.py -v
"""
import sys
import ast
from pathlib import Path

SRC = Path(__file__).parent.parent
sys.path.insert(0, str(SRC))


def test_faculty_files_parse():
    pkg = SRC / "sustech_survival" / "faculty"
    for py in sorted(pkg.glob("*.py")):
        src = py.read_text()
        try:
            ast.parse(src)
        except SyntaxError as e:
            raise AssertionError(f"{py.name}: {e}")


def test_faculty_public_surface():
    import sustech_survival.faculty as f
    for name in ["faculty", "Faculty", "FacultyClient", "DEPARTMENTS"]:
        assert hasattr(f, name), f"missing public name: {name}"
    # client methods
    for m in ("list", "get", "search", "render"):
        assert callable(getattr(f.faculty, m)), f"faculty.{m} not callable"
    # departments is a list of 50+ strings
    assert isinstance(f.DEPARTMENTS, list)
    assert len(f.DEPARTMENTS) >= 50
    assert all(isinstance(d, str) for d in f.DEPARTMENTS)
