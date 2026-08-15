"""Tests for selectcourse/course.py — SectionSpan, SectionTable, export_schedule_table.

These test the structured schedule export without needing TIS network —
they build synthetic Course objects and verify the renderer.
"""
from __future__ import annotations

import json
import pytest

from sustech_survival.selectcourse.course import (
    SectionSpan,
    SectionTable,
    Course,
    _format_weeks_label,
    export_schedule_table,
)


# ── Fixtures: synthetic data ─────────────────────────────────────────────


def _make_span(day=1, day_name="周一", p_start=3, p_end=4,
               weeks=(1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16),
               room="智华楼102", teacher="张三"):
    return SectionSpan(
        day=day, day_name=day_name, period_start=p_start, period_end=p_end,
        weeks=tuple(weeks),
        weeks_label=_format_weeks_label(list(weeks)),
        room=room, teacher=teacher,
    )


def _slot(day=1, p_start=3, p_end=4, room="智华楼102", teacher="张三",
          weeks=(1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16)):
    """Build a slot dict matching the shape of Course.slots_raw entries."""
    return {"day": day, "period_start": p_start, "period_end": p_end,
            "weeks": list(weeks), "room": room, "teacher": teacher}


def _make_course(code="MSE306", name="材料科学实验", section="001",
                 class_group="MSE306-01", teachers=("张三",), credits=2.0,
                 total_hours=32.0, nature="必修", campus="一教",
                 slots=None):
    """Build a Course with all required fields filled.

    Course.spans is a property that derives SectionSpan objects from
    slots_raw. export_schedule_table() reads .spans.
    """
    return Course(
        code=code, name=name, name_en=f"{name} (EN)",
        section_name=section, section_name_en=f"{section} (EN)",
        class_group=class_group, rwh=f"2025-2026-2-{code}-{class_group}",
        college="材料学院", category="大类基础",
        nature=nature, campus=campus,
        credits=credits, total_hours=total_hours,
        capacity=100, undergrad_seats=80, grad_seats=20,
        cultivation="本科",
        teachers=list(teachers),
        slots_raw=list(slots) if slots else [],
        task_type="专业任务", language="中文",
    )


# ── _format_weeks_label ───────────────────────────────────────────────────


class TestWeeksLabel:
    def test_empty(self):
        assert _format_weeks_label([]) == ""

    def test_single(self):
        assert _format_weeks_label([5]) == "5 周"

    def test_contiguous(self):
        assert _format_weeks_label([1, 2, 3, 4, 5]) == "1-5 周"

    def test_with_gap(self):
        assert _format_weeks_label([1, 2, 3, 4, 5, 6, 7, 8,
                                    10, 11, 12, 13, 14, 15, 16]) == "1-8,10-16 周"

    def test_odd_weeks(self):
        assert _format_weeks_label([1, 3, 5, 7, 9]) == "1,3,5,7,9 周"

    def test_unsorted_input(self):
        assert _format_weeks_label([5, 1, 3]) == "1,3,5 周"


# ── SectionSpan ──────────────────────────────────────────────────────────


class TestSectionSpan:
    def test_basic_fields(self):
        span = _slot(day=3, p_start=5, p_end=6, weeks=(1, 2, 3, 4, 5, 6, 7, 8))
        c = _make_course(slots=[span])
        s = c.spans[0]
        assert s.day == 3
        assert s.day_name == "周三"
        assert s.period_start == 5
        assert s.period_end == 6
        assert s.weeks_label == "1-8 周"

    def test_single_period(self):
        span = _slot(p_start=3, p_end=3)
        c = _make_course(slots=[span])
        s = c.spans[0]
        assert s.weeks_label == "1-16 周"

    def test_frozen(self):
        import dataclasses
        s = SectionSpan(day=1, day_name="周一", period_start=3, period_end=4,
                        weeks=(), weeks_label="", room="", teacher="")
        # Frozen dataclass: any field assignment raises FrozenInstanceError
        with pytest.raises(dataclasses.FrozenInstanceError):
            s.day = 5  # type: ignore[misc]


# ── SectionTable ─────────────────────────────────────────────────────────


class TestSectionTable:
    def _table(self, spans=None):
        return SectionTable(
            code="MSE306", name="材料科学实验",
            section_name="实验1", class_group="MSE306-01",
            teachers=("张三", "李四"), credits=2.0, total_hours=32.0,
            nature="必修", campus="一教",
            spans=spans or (_make_span(),),
        )

    def test_to_markdown_has_header(self):
        c = _make_course()
        t = c.export_sections_table()
        md = t.to_markdown()
        assert "## MSE306" in md
        assert "材料科学实验" in md
        assert "教师: 张三" in md

    def test_to_markdown_renders_spans(self):
        span = _slot(day=3, p_start=5, p_end=6, room="智华楼102")
        c = _make_course(slots=[span])
        md = c.export_sections_table().to_markdown()
        assert "周三 第5-6节" in md
        assert "智华楼102" in md

    def test_to_markdown_empty_spans(self):
        c = _make_course(slots=[])
        md = c.export_sections_table().to_markdown()
        assert "(no scheduled meetings)" in md

    def test_to_json_structure(self):
        span = _slot(day=1, p_start=3, p_end=4)
        c = _make_course(slots=[span])
        d = json.loads(c.export_sections_table().to_json())
        assert d["code"] == "MSE306"
        assert d["credits"] == 2.0
        assert len(d["spans"]) == 1
        assert d["spans"][0]["day"] == 1
        assert d["spans"][0]["day_name"] == "周一"
        assert d["spans"][0]["period_start"] == 3

    def test_to_json_unicode_safe(self):
        c = Course(
            code="SS143", name="写作与交流", name_en="Writing",
            section_name="讲座", section_name_en="Lecture",
            class_group="SS143-01", rwh="2025-2026-2-SS143-01",
            college="人文社科学院", category="通识",
            nature="必修", campus="一教",
            credits=2.0, total_hours=32.0,
            capacity=100, undergrad_seats=80, grad_seats=20,
            cultivation="本科",
            teachers=["王老师"],
            slots_raw=[_slot(room="人文社科教学楼B302", teacher="王老师")],
            task_type="通识必修", language="中文",
        )
        d = json.loads(c.export_sections_table().to_json())
        assert d["name"] == "写作与交流"
        assert d["teachers"] == ["王老师"]
        assert d["spans"][0]["room"] == "人文社科教学楼B302"


# ── export_schedule_table ────────────────────────────────────────────────


class TestExportScheduleTable:
    def test_markdown_default(self):
        c1 = _make_course(code="MSE306", name="材料实验",
                          slots=[_slot(day=3, p_start=5, p_end=6)])
        c2 = _make_course(code="SS143", name="写作与交流",
                          slots=[_slot(day=4, p_start=9, p_end=10)])
        out = export_schedule_table([c1, c2], format="markdown")
        # Markdown separates with --- divider
        assert "MSE306" in out and "SS143" in out
        assert "---" in out
        assert "周三 第5-6节" in out

    def test_json(self):
        c1 = _make_course(code="MSE306")
        out = export_schedule_table([c1], format="json")
        d = json.loads(out)
        assert isinstance(d, list)
        assert d[0]["code"] == "MSE306"
        assert isinstance(d[0]["spans"], list)

    def test_csv_header(self):
        out = export_schedule_table([], format="csv")
        # Even with no courses, header is emitted
        assert "code,name,section,class_group" in out

    def test_csv_rows(self):
        slot = _slot(day=1, p_start=3, p_end=4, room="智华楼102", teacher="张三")
        c1 = _make_course(code="MSE306", slots=[slot])
        out = export_schedule_table([c1], format="csv")
        lines = out.splitlines()
        assert len(lines) == 2  # header + 1 row
        assert "MSE306" in lines[1]
        assert "周一" in lines[1]
        assert "智华楼102" in lines[1]

    def test_csv_empty_spans_row(self):
        c1 = _make_course(code="MSE306", slots=[])
        out = export_schedule_table([c1], format="csv")
        lines = out.splitlines()
        # Course with no spans still gets one row (with empty fields)
        assert len(lines) == 2
        assert "MSE306" in lines[1]
        # Many fields empty
        assert lines[1].endswith(",,,,,") or lines[1].count(",") >= 8

    def test_multiple_spans_per_course(self):
        slot1 = _slot(day=1, p_start=3, p_end=4)
        slot2 = _slot(day=3, p_start=5, p_end=6)
        c1 = _make_course(code="MSE306", slots=[slot1, slot2])
        out = export_schedule_table([c1], format="csv")
        lines = out.splitlines()
        # header + 2 spans = 3 lines
        assert len(lines) == 3
        assert "周一" in lines[1]
        assert "周三" in lines[2]


# ── Integration with CLI command ─────────────────────────────────────────


class TestCLIExportTable:
    """The CLI command should accept the same formats as export_schedule_table()."""

    def test_cli_help_lists_format_options(self):
        from click.testing import CliRunner
        from sustech_survival.cli.main import selectcourse_cmd
        runner = CliRunner()
        result = runner.invoke(selectcourse_cmd, ["export-table", "--help"])
        assert result.exit_code == 0
        assert "--format" in result.output
        assert "markdown" in result.output
        assert "json" in result.output
        assert "csv" in result.output

    def test_cli_rejects_no_codes_no_keyword(self):
        from click.testing import CliRunner
        from sustech_survival.cli.main import selectcourse_export_table
        runner = CliRunner()
        result = runner.invoke(selectcourse_export_table, [])
        assert result.exit_code != 0
        assert "pass course codes" in result.output or "keyword" in result.output