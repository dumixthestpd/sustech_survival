"""``sustech nces lookup`` must resolve through the search API.

It called ``NCESScraper.lookup()``, which never existed, so the command raised
``AttributeError`` on every run. ``search_course()`` is the real entry point and
also tells us whether a teacher pin matched.
"""
from __future__ import annotations

from click.testing import CliRunner

from sustech_survival.nces.cli import cli as nces_cli
from sustech_survival.nces.scraper import NCESCourse


def _course(teacher: str = "周秀梅") -> NCESCourse:
    return NCESCourse(
        nces_id=4321,
        code="HUM032",
        name="写作与交流",
        teacher=teacher,
        semester="2026-2027-1",
        semesters=["2026-2027-1"],
        rating=10.0,
        review_count=39,
        difficulty=("简单", 20.0),
        workload=("适中", 50.0),
        grading=("给分好", 80.0),
        takeaways=("收获大", 90.0),
        direct_url="https://ncesnext.com/course/HUM032",
    )


def _stub(monkeypatch, teacher="", *returns):
    from sustech_survival.nces import scraper as scraper_mod

    calls = []

    def _search(self, code, teacher_arg="", xn="", xq=""):
        calls.append((code, teacher_arg))
        return returns

    monkeypatch.setattr(scraper_mod.NCESScraper, "search_course", _search)
    return calls


def test_lookup_prints_the_resolved_section(monkeypatch):
    _stub(monkeypatch, "", _course(), True, [])
    result = CliRunner().invoke(nces_cli, ["lookup", "HUM032"])
    assert result.exit_code == 0, result.output
    assert "写作与交流" in result.output and "周秀梅" in result.output
    assert "10.0/10" in result.output


def test_lookup_lists_the_other_sections(monkeypatch):
    _stub(monkeypatch, "", _course(), True, [_course("李四")])
    output = CliRunner().invoke(nces_cli, ["lookup", "HUM032"]).output
    assert "other sections of HUM032: 李四" in output


def test_lookup_reports_a_missing_course(monkeypatch):
    _stub(monkeypatch, "", None, False, [])
    result = CliRunner().invoke(nces_cli, ["lookup", "NOPE999"])
    assert result.exit_code != 0
    assert "course not found" in result.output


def test_lookup_pins_a_teacher(monkeypatch):
    calls = _stub(monkeypatch, "周秀梅", _course(), True, [])
    output = CliRunner().invoke(
        nces_cli, ["lookup", "HUM032", "--teacher", "周秀梅"]
    ).output
    assert calls == [("HUM032", "周秀梅")]
    assert "other sections" not in output
