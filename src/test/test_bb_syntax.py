import ast, pytest
from pathlib import Path

SRC = Path(__file__).parent.parent.parent / "src" / "sustech_survival" / "bb"


class TestSyntaxClean:
    """All bb/ modules should compile without SyntaxError."""

    @pytest.mark.parametrize("filename", [
        "session.py", "items.py", "courses.py", "pages.py",
        "submit.py", "cli.py", "download.py",
    ])
    def test_file_compiles(self, filename):
        path = SRC / filename
        if not path.exists():
            pytest.skip(f"{filename} not found")
        with open(path, "rb") as f:
            src = f.read()
        # Should not raise SyntaxError
        ast.parse(src)


class TestItemsSyntax:
    """items.py had a duplicate docstring — ensure it's gone."""

    def test_items_compiles(self):
        import sustech_survival.bb.items as m
        assert m is not None

    def test_item_class_docstring_valid(self):
        import sustech_survival.bb.items as m
        # The Item class should have a valid docstring
        assert m.Item.__doc__ is not None
        assert "Base class for all BB item types" in m.Item.__doc__