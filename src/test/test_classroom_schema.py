"""
test_classroom_schema.py — Offline tests for the classroom schema + parser.

No network. Tests the kcxx HTML parser, week expansion, and ScheduleSlot
helpers against canned strings.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from sustech_survival.classroom.schema import (
    Room, ScheduleSlot,
    parse_kcxx_slot, parse_kcxx,
    expand_weeks, day_char_to_int,
    DAY_NAMES_ZH, PERIOD_TIMES,
)


# ── expand_weeks ────────────────────────────────────────────────────────────

class TestExpandWeeks:
    def test_simple_range(self):
        assert expand_weeks("1-15") == list(range(1, 16))

    def test_single_week(self):
        assert expand_weeks("5") == [5]

    def test_discrete_weeks(self):
        assert expand_weeks("3,7,9,13") == [3, 7, 9, 13]

    def test_mixed_range_and_discrete(self):
        # 1-9,11-15 = weeks 1-9 + 11-15 (skip week 10, e.g. spring festival)
        result = expand_weeks("1-9,11-15")
        assert result == list(range(1, 10)) + list(range(11, 16))

    def test_empty(self):
        assert expand_weeks("") == []

    def test_dedupes(self):
        assert expand_weeks("3,3,5") == [3, 5]

    def test_reverse_range_falls_back(self):
        # "5-3" is malformed; should be tolerated.
        result = expand_weeks("5-3")
        assert result == [3, 4, 5]


# ── day_char_to_int ────────────────────────────────────────────────────────

class TestDayCharToInt:
    def test_monday(self):
        assert day_char_to_int("一") == 1

    def test_sunday(self):
        assert day_char_to_int("日") == 7

    def test_unknown_returns_zero(self):
        assert day_char_to_int("?") == 0


# ── parse_kcxx_slot ─────────────────────────────────────────────────────────

class TestParseKcxxSlot:
    def test_basic(self):
        slot = parse_kcxx_slot("1-15周,星期一第3-4节 一教324")
        assert slot is not None
        assert slot["weeks"] == list(range(1, 16))
        assert slot["day"] == 1
        assert slot["period_start"] == 3
        assert slot["period_end"] == 4
        assert slot["room"] == "一教324"

    def test_single_period(self):
        slot = parse_kcxx_slot("3,7,9,13周,星期日第1节 校外活动场所")
        assert slot is not None
        assert slot["weeks"] == [3, 7, 9, 13]
        assert slot["day"] == 7  # Sunday
        assert slot["period_start"] == 1
        assert slot["period_end"] == 1
        assert slot["room"] == "校外活动场所"

    def test_mixed_weeks_with_skip(self):
        slot = parse_kcxx_slot("1-9,11-15周,星期二第3-4节 一教326")
        assert slot is not None
        assert 10 not in slot["weeks"]
        assert 1 in slot["weeks"] and 15 in slot["weeks"]

    def test_lab_room(self):
        slot = parse_kcxx_slot("1-9,11-15周,星期三第1-4节 慧园2栋509")
        assert slot["room"] == "慧园2栋509"
        assert slot["period_start"] == 1
        assert slot["period_end"] == 4

    def test_non_schedule_returns_none(self):
        # Common kcxx noise: "选课要求:本课程只面向..."
        assert parse_kcxx_slot("选课要求:本课程只面向力学系研究生") is None
        assert parse_kcxx_slot("") is None
        assert parse_kcxx_slot("教师: 张三") is None


# ── parse_kcxx (multi-paragraph HTML) ──────────────────────────────────────

class TestParseKcxx:
    HTML = """
    <span class="ivu-tag-text"><p>1-15周,星期一第3-4节 一教324</p></span>
    <span class="ivu-tag-text"><p>1-15周,星期二第3-4节 一教325</p></span>
    <span class="ivu-tag-text"><p>1-15周,星期三第7-8节 一教326</p></span>
    """

    def test_extracts_three_slots(self):
        slots = parse_kcxx(self.HTML)
        assert len(slots) == 3

    def test_slot_rooms(self):
        slots = parse_kcxx(self.HTML)
        assert [s["room"] for s in slots] == ["一教324", "一教325", "一教326"]

    def test_slot_days(self):
        slots = parse_kcxx(self.HTML)
        assert [s["day"] for s in slots] == [1, 2, 3]

    def test_handles_html_entities(self):
        html = '<span class="ivu-tag-text"><p>1-15周,星期一第3-4节 一教&nbsp;324</p></span>'
        slots = parse_kcxx(html)
        assert len(slots) == 1
        assert "一教" in slots[0]["room"]

    def test_ignores_non_schedule_paragraphs(self):
        html = """
        <span class="ivu-tag-text"><p>1-15周,星期一第3-4节 一教324</p></span>
        <span class="ivu-tag-text"><p>选课要求:本课程只面向力学系研究生</p></span>
        """
        slots = parse_kcxx(html)
        assert len(slots) == 1
        assert slots[0]["room"] == "一教324"

    def test_empty_returns_empty(self):
        assert parse_kcxx("") == []
        assert parse_kcxx(None) == []


# ── ScheduleSlot ────────────────────────────────────────────────────────────

class TestScheduleSlot:
    def _make(self, **kw):
        defaults = dict(
            course_code="BIO101", course_name="生命科学概论",
            class_group="001", weeks=list(range(1, 16)),
            day=1, period_start=3, period_end=4, room="一教324",
        )
        defaults.update(kw)
        return ScheduleSlot(**defaults)

    def test_duration(self):
        s = self._make(period_start=3, period_end=4)
        assert s.duration == 2
        s = self._make(period_start=5, period_end=5)
        assert s.duration == 1

    def test_active_on_true(self):
        s = self._make(weeks=[1, 2, 3], day=2)
        assert s.active_on(week=2, day=2) is True
        assert s.active_on(week=1, day=2) is True

    def test_active_on_wrong_day(self):
        s = self._make(day=2)
        assert s.active_on(week=5, day=3) is False

    def test_active_on_wrong_week(self):
        s = self._make(weeks=[1, 2, 3])
        assert s.active_on(week=4, day=1) is False

    def test_overlaps_basic(self):
        s = self._make(period_start=3, period_end=4)
        # [3-4] vs [3-3] → overlap
        assert s.overlaps(3, 3) is True
        # [3-4] vs [4-5] → overlap at period 4
        assert s.overlaps(4, 5) is True
        # [3-4] vs [5-5] → no overlap
        assert s.overlaps(5, 5) is False
        # [3-4] vs [1-2] → no overlap
        assert s.overlaps(1, 2) is False

    def test_when_str_full_range(self):
        s = self._make(weeks=list(range(1, 16)), day=1, period_start=3, period_end=4)
        assert s.when_str == "1-15周 周一 第3-4节"

    def test_when_str_single_week(self):
        s = self._make(weeks=[5], day=2, period_start=7, period_end=7)
        assert s.when_str == "5周 周二 第7节"

    def test_when_str_discrete_weeks(self):
        s = self._make(weeks=[3, 7, 9, 13], day=7, period_start=1, period_end=4)
        assert s.when_str == "3,7,9,13周 周日 第1-4节"


# ── Room ────────────────────────────────────────────────────────────────────

class TestRoom:
    def test_short_name_basic(self):
        assert Room(name="一教324").short_name == "一教"
        assert Room(name="慧园2栋509").short_name == "慧园"
        assert Room(name="商学院101").short_name == "商学院"

    def test_short_name_no_digits(self):
        # If no digits, fall back to the whole name.
        assert Room(name="游泳馆").short_name == "游泳馆"


# ── ScheduleSlot.from_course_and_kcxx ──────────────────────────────────────

class TestScheduleSlotFromCourse:
    COURSE = {
        "kcdm": "BIO101",
        "kcmc": "生命科学概论",
        "kxh": "001",
        "kcxx": '<span class="ivu-tag-text"><p>1-15周,星期一第3-4节 一教324</p></span>'
                '<span class="ivu-tag-text"><p>1-15周,星期二第3-4节 一教324</p></span>',
        "jszws": "120",
    }

    def test_emits_one_slot_per_kcxx_paragraph(self):
        slots = ScheduleSlot.from_course_and_kcxx(self.COURSE)
        assert len(slots) == 2
        assert all(s.course_code == "BIO101" for s in slots)
        assert all(s.room == "一教324" for s in slots)
        assert [s.day for s in slots] == [1, 2]

    def test_no_kcxx_returns_empty(self):
        course = {"kcdm": "X", "kcmc": "Y", "kxh": "001", "kcxx": ""}
        assert ScheduleSlot.from_course_and_kcxx(course) == []

    def test_unparseable_kcxx_returns_empty(self):
        course = {"kcdm": "X", "kcmc": "Y", "kxh": "001",
                  "kcxx": "选课要求:本课程只面向..."}
        assert ScheduleSlot.from_course_and_kcxx(course) == []
