"""
Tests for the new schedule-export surface.

- Course.spans  → list of SectionSpan (frozen dataclass)
- Course.export_sections_table() → SectionTable
- selectcourse.course.export_schedule_table()  → markdown/json/csv
- tis.timetable.render_table() → markdown grid

Verified to be in sync with parse_kcxx's output shape so callers don't
need to re-parse kcxx HTML.
"""
import datetime as _dt
import json

import pytest


# ── Test fixtures ──────────────────────────────────────────────


def _slot(day, ps, pe, weeks, room="", teacher=""):
    """Synthesize a slot dict that matches what parse_kcxx produces."""
    return {
        "day": day,
        "period_start": ps,
        "period_end": pe,
        "weeks": list(weeks),
        "week_list": list(weeks),   # both keys tolerated (see spans() code)
        "room": room,
        "teacher": teacher,
    }


def _course(slots_raw, **overrides):
    """Synthesize a Course object without going through TIS HTTP."""
    from sustech_survival.selectcourse.course import Course
    fields = dict(
        code="MSE306",
        name="材料表征",
        name_en="Materials Characterization",
        class_group="001",
        rwh="2025-2026-2-MSE306-001",
        college="材料学院",
        category="专业",
        nature="必修",
        campus="一校区",
        credits=3.0,
        total_hours=48.0,
        capacity=60,
        undergrad_seats=50,
        grad_seats=10,
        cultivation="本科",
        rooms=["智华楼102"],
        teachers=["张三"],
        slots_raw=slots_raw,
        task_type="专业任务",
        language="中文",
        college_code="020020",
        section_name="MSE306-001-材料表征",
        section_name_en="MSE306-001-Materials Characterization",
        enrolled=42,
        id="",
    )
    fields.update(overrides)
    return Course(**fields)  # type: ignore[arg-type]


# ── SectionSpan + spans property ────────────────────────────────


def test_spans_simple():
    """A Course with one Mon 3-4 meeting → one span."""
    course = _course([_slot(1, 3, 4, [1, 2, 3, 4, 5, 6, 7, 8])])
    spans = course.spans
    assert len(spans) == 1
    s = spans[0]
    assert s.day == 1
    assert s.day_name == "周一"
    assert s.period_start == 3
    assert s.period_end == 4
    assert s.weeks == (1, 2, 3, 4, 5, 6, 7, 8)
    assert s.weeks_label == "1-8 周"
    assert s.room == ""
    assert s.teacher == ""


def test_spans_multiple_meetings():
    """A Course with two meetings (Mon + Wed) → two spans."""
    course = _course([
        _slot(1, 3, 4, list(range(1, 17))),       # Mon 3-4, weeks 1-16
        _slot(3, 7, 8, [1, 3, 5, 7, 9, 11, 13, 15]),  # Wed 7-8, odd weeks
    ])
    assert len(course.spans) == 2
    assert course.spans[0].day == 1
    assert course.spans[1].day == 3
    assert course.spans[1].weeks_label == "1,3,5,7,9,11,13,15 周"


def test_spans_empty():
    """A Course with no slots → empty tuple."""
    course = _course([])
    assert course.spans == ()


def test_spans_with_room_and_teacher():
    course = _course([
        _slot(2, 5, 6, list(range(1, 17)), room="智华楼102", teacher="李四"),
    ])
    s = course.spans[0]
    assert s.room == "智华楼102"
    assert s.teacher == "李四"


# ── _format_weeks_label ────────────────────────────────────────────


def test_weeks_label():
    from sustech_survival.selectcourse.course import _format_weeks_label
    assert _format_weeks_label([1, 2, 3, 4, 5, 6, 7, 8]) == "1-8 周"
    assert _format_weeks_label([1, 8]) == "1,8 周"
    assert _format_weeks_label([]) == ""
    assert _format_weeks_label([1, 2, 4, 5, 6]) == "1-2,4-6 周"
    assert _format_weeks_label([5]) == "5 周"


# ── SectionTable + export_sections_table ─────────────────────────


def test_export_sections_table_markdown():
    course = _course([_slot(1, 3, 4, list(range(1, 17)), room="智华楼102", teacher="张三")])
    tbl = course.export_sections_table()
    md = tbl.to_markdown()
    assert "## MSE306 — 材料表征" in md
    assert "智华楼102" in md
    assert "张三" in md
    assert "1-16 周" in md
    assert "3-4节" in md


def test_export_sections_table_json():
    course = _course([_slot(2, 5, 6, list(range(1, 17)), room="图书馆", teacher="王五")])
    tbl = course.export_sections_table()
    j = json.loads(tbl.to_json())
    assert j["code"] == "MSE306"
    assert j["name"] == "材料表征"
    assert j["class_group"] == "001"
    assert j["credits"] == 3.0
    assert j["nature"] == "必修"
    assert len(j["spans"]) == 1
    sp = j["spans"][0]
    assert sp["day"] == 2
    assert sp["day_name"] == "周二"
    assert sp["room"] == "图书馆"
    assert sp["teacher"] == "王五"


# ── export_schedule_table (module-level) ─────────────────────────


def test_export_schedule_table_markdown():
    from sustech_survival.selectcourse.course import export_schedule_table
    courses = [
        _course([_slot(1, 3, 4, list(range(1, 17))), _slot(3, 7, 8, list(range(1, 17)))], code="MSE306", class_group="001"),
        _course([_slot(2, 1, 2, list(range(1, 17)), room="一教101")], code="HUM032", class_group="002", name="写作与交流"),
    ]
    md = export_schedule_table(courses)
    # Two sections, both rendered
    assert "MSE306" in md and "HUM032" in md
    assert md.count("---") >= 1   # separator between sections


def test_export_schedule_table_json():
    from sustech_survival.selectcourse.course import export_schedule_table
    courses = [_course([_slot(1, 3, 4, list(range(1, 17)))])]
    out = json.loads(export_schedule_table(courses, format="json"))
    assert isinstance(out, list)
    assert len(out) == 1
    assert out[0]["code"] == "MSE306"


def test_export_schedule_table_csv():
    from sustech_survival.selectcourse.course import export_schedule_table
    courses = [_course([_slot(1, 3, 4, list(range(1, 17)))])]
    csv = export_schedule_table(courses, format="csv")
    lines = csv.split("\n")
    assert lines[0].startswith("code,name,section,class_group")
    assert "MSE306" in lines[1]
    assert "周一" in lines[1]


# ── timetable.render_table ───────────────────────────────────────


def test_render_table_empty():
    from sustech_survival.tis.timetable import render_table
    out = render_table([])
    assert "Mon" in out
    assert "Sun" in out
    assert "Legend" in out
    assert "(empty)" in out


def test_render_table_one_class():
    from sustech_survival.tis.timetable import render_table
    schedule = [{
        "code": "MSE306",
        "section": "001",
        "room": "智华楼102",
        "teacher": "张三",
        "slots": [
            {"day": 1, "periods": [3, 4], "weeks": list(range(1, 17))},
            {"day": 3, "periods": [7, 8], "weeks": list(range(1, 17))},
        ],
    }]
    out = render_table(schedule)
    # Monday row contains MSE306/001 in periods 3-4
    mon_row = [l for l in out.splitlines() if l.startswith("| Mon")][0]
    assert "MSE306/001" in mon_row
    # Wed row contains MSE306/001 in periods 7-8
    wed_row = [l for l in out.splitlines() if l.startswith("| Wed")][0]
    assert "MSE306/001" in wed_row
    # Legend
    assert "MSE306/001" in out
    assert "智华楼102" in out
    assert "张三" in out


def test_render_table_periods_label():
    from sustech_survival.tis.timetable import render_table
    out = render_table([])
    assert "Periods:" in out
    assert "morning" in out.lower()
    assert "afternoon" in out.lower()