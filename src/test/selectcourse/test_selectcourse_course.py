"""
test_selectcourse_schema.py — Offline tests for selectcourse schema.

No network. Tests Course.from_api() parser against canned TIS API rows.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from sustech_survival.selectcourse.course import Course


class TestCourseFromApi:
    FULL = {
        "kcdm": "BIO101",
        "kcmc": "生命科学概论",
        "kcmc_en": "Life Science Introduction-001class-Chinese",
        "rwmc_en": "Life Science Introduction-001class-Chinese",
        "kxh": "001",
        "rwh": "2025-2026-2-BIO101-001",
        "kkyxmc": "生命科学学院",
        "kclbmc": "大类基础",
        "kcxzmc": "必修",
        "xiaoqumc": "一期校区",
        "xf": "2.0",
        "zxs": "32.0",
        "zrl": "120",
        "bksrl": "100",
        "yjsrl": "20",
        "pylx": "1",
        "pylx_label": "1",  # raw code; if present, takes precedence over the pylx→label lookup
        "kcxx": (
            '<p>教师: <a href="javascript:void(0);">张三</a> '
            '<a href="javascript:void(0);">李四</a></p>'
            '<span class="ivu-tag-text"><p>1-15周,星期一第3-4节 一教324</p></span>'
            '<span class="ivu-tag-text"><p>1-15周,星期二第3-4节 一教324</p></span>'
        ),
    }

    def test_basic_fields(self):
        c = Course.from_api(self.FULL)
        assert c.code == "BIO101"
        assert c.name == "生命科学概论"
        assert c.name_en == "Life Science Introduction-001class-Chinese"
        assert c.class_group == "001"
        assert c.rwh == "2025-2026-2-BIO101-001"
        assert c.college == "生命科学学院"
        assert c.category == "大类基础"
        assert c.nature == "必修"
        assert c.campus == "一期校区"
        assert c.credits == 2.0
        assert c.total_hours == 32.0

    def test_capacity(self):
        c = Course.from_api(self.FULL)
        assert c.capacity == 120
        assert c.undergrad_seats == 100
        assert c.grad_seats == 20

    def test_cultivation_is_string(self):
        c = Course.from_api(self.FULL)
        # pylx is the int code (1=本科, 2=研究生) — we keep it raw.
        assert c.cultivation == "1"

    def test_teachers_parsed_from_kcxx(self):
        c = Course.from_api(self.FULL)
        assert "张三" in c.teachers
        assert "李四" in c.teachers

    def test_rooms_deduped_from_slots(self):
        c = Course.from_api(self.FULL)
        assert c.rooms == ["一教324"]

    def test_slots_parsed(self):
        c = Course.from_api(self.FULL)
        assert len(c.slots_raw) == 2
        assert c.slots_raw[0]["day"] == 1
        assert c.slots_raw[1]["day"] == 2

    def test_has_schedule_true_with_slots(self):
        c = Course.from_api(self.FULL)
        assert c.has_schedule is True

    def test_has_schedule_false_without_kcxx(self):
        c = Course.from_api({"kcdm": "X", "kcmc": "Y"})
        assert c.has_schedule is False

    def test_schedule_str(self):
        c = Course.from_api(self.FULL)
        # Should mention 周一, 周二, 一教324
        s = c.schedule_str
        assert "周一" in s
        assert "周二" in s
        assert "一教324" in s

    def test_schedule_str_empty_when_no_slots(self):
        c = Course.from_api({"kcdm": "X", "kcmc": "Y"})
        assert c.schedule_str == "(no schedule)"

    def test_handles_missing_optional_fields(self):
        c = Course.from_api({"kcdm": "X", "kcmc": "Y"})
        assert c.code == "X"
        assert c.name == "Y"
        assert c.credits == 0
        assert c.capacity is None
        assert c.undergrad_seats is None
        assert c.grad_seats is None
        assert c.teachers == []
        assert c.rooms == []

    def test_credit_zero_when_empty_string(self):
        c = Course.from_api({"kcdm": "X", "kcmc": "Y", "xf": ""})
        assert c.credits == 0

    def test_invalid_capacity_string_returns_none(self):
        c = Course.from_api({"kcdm": "X", "kcmc": "Y", "zrl": "abc"})
        assert c.capacity is None

    def test_current_personal_selection_count_fields(self):
        c = Course.from_api({
            "kcdm": "CS217", "kcmc": "数据结构与算法分析（H）",
            "zrl": "60", "bksrl": "60", "yxzrs": "58",
        })
        assert c.capacity == 60
        assert c.enrolled == 58

    def test_undergraduate_selection_count_fallback(self):
        c = Course.from_api({
            "kcdm": "CS207", "kcmc": "数字逻辑",
            "zrl": "120", "bksrl": "120", "bksyxrs": "117",
        })
        assert c.enrolled == 117

    def test_selection_count_capacity_fallback(self):
        c = Course.from_api({
            "kcdm": "HUM032", "kcmc": "写作与交流",
            "zrl": "35", "yxzrlrs": "34",
        })
        assert c.enrolled == 34
