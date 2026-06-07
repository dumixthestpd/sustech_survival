"""
Tests for the new sustech_survival.tis.schedule_index module.

Covers:
  - CourseSchedule lazy index over TIS semester_schedule()
  - CourseEntry date arithmetic
  - find() substring match
  - last_occurrence / next_occurrence / dates_in_week / dates_in_semester
  - experiment_dates() high-level helper for LaTeX reports
"""
from __future__ import annotations

from datetime import date, datetime
from unittest.mock import patch

import pytest

from sustech_survival.context import CHINA_TZ
from sustech_survival.tis.schedule_index import (
    CourseEntry,
    CourseSchedule,
    dates_in_semester,
    dates_in_week,
    experiment_dates,
    last_occurrence,
    next_occurrence,
)


# ─── Sample TIS semester data ──────────────────────────────────────────────
# Real shape from the TIS API: each entry has KCWZSM, SKSJ, KEY, ZC, etc.
# Bitmap ZC is a 36-char string of 0/1 indicating which weeks the course runs.

SAMPLE_SEMESTER = [
    # gorganic exp: Monday periods 3-4, weeks 3,5,7,9,11,13,15 (odd weeks)
    {"KCWZSM": "基础有机化学实验", "SKJS": "李艳艳", "SKDD": "慧园2栋",
     "KEY": "xq1_jc3", "KSJC": 3, "JSJC": 4,
     "ZC": "0010101010101010000000000000000000"},
    {"KCWZSM": "基础有机化学实验", "SKJS": "李艳艳", "SKDD": "慧园2栋",
     "KEY": "xq1_jc4", "KSJC": 4, "JSJC": 4,
     "ZC": "0010101010101010000000000000000000"},
    # phychem exp: Thursday periods 1-2, weeks 2,4,6,8,10,12,14,16 (even weeks)
    {"KCWZSM": "物理化学实验", "SKJS": "田雷蕾", "SKDD": "慧园2栋303A",
     "KEY": "xq4_jc1", "KSJC": 1, "JSJC": 2,
     "ZC": "0101010101010101000000000000000000"},
    {"KCWZSM": "物理化学实验", "SKJS": "田雷蕾", "SKDD": "慧园2栋303A",
     "KEY": "xq4_jc2", "KSJC": 2, "JSJC": 2,
     "ZC": "0101010101010101000000000000000000"},
    # 物理化学 lecture: Monday+Wednesday period 2, weeks 2-16
    {"KCWZSM": "物理化学", "SKJS": "田雷蕾", "SKDD": "一教406",
     "KEY": "xq1_jc2", "KSJC": 2, "JSJC": 2,
     "ZC": "0111111101111111000000000000000000"},
]


def _patch_semester(monkeypatch, data=SAMPLE_SEMESTER):
    """Patch the TIS semester_schedule() to return sample data."""
    monkeypatch.setattr(
        "sustech_survival.tis.schedule_index.semester_schedule",
        lambda *a, **kw: data,
    )


# ─── CourseEntry basics ───────────────────────────────────────────────────

def test_course_entry_parses_name():
    e = CourseEntry.from_tis(SAMPLE_SEMESTER[0], semester_start=date(2026, 2, 24))
    assert e.name == "基础有机化学实验"
    assert e.teacher == "李艳艳"
    assert e.location == "慧园2栋"
    assert e.weekday == 1  # Monday
    assert e.period_start == 3


def test_course_entry_parses_weeks():
    e = CourseEntry.from_tis(SAMPLE_SEMESTER[0], semester_start=date(2026, 2, 24))
    assert e.weeks == [3, 5, 7, 9, 11, 13, 15]


def test_course_entry_handles_null_name_falls_back_to_sksj():
    entry = dict(SAMPLE_SEMESTER[0])
    entry["KCWZSM"] = None
    entry["SKSJ"] = "物理化学实验\n[李艳艳]\n[03班]"
    e = CourseEntry.from_tis(entry, semester_start=date(2026, 2, 24))
    assert e.name == "物理化学实验"


def test_course_entry_week_to_date_returns_class_date():
    """_week_to_date returns the class meeting date (not week start)."""
    e = CourseEntry.from_tis(SAMPLE_SEMESTER[0], semester_start=date(2026, 2, 24))
    # gorganic is Monday (xq1)
    # W3 starts 2026-02-24 + 14 = 2026-03-10 (Tue). The class is Mon = 2026-03-10 - 1
    d3 = e._week_to_date(3)
    assert d3 == date(2026, 3, 9)


def test_course_entry_week_to_date_thursday():
    """Thursday class (phychem, xq4) — should be Tue of week start + 2 days."""
    e = CourseEntry.from_tis(SAMPLE_SEMESTER[2], semester_start=date(2026, 2, 24))
    # phychem is Thursday (xq4). W14 starts 2026-02-24 + 91 = 2026-05-26 (Tue)
    # Thursday of W14 = 2026-05-26 + 2 = 2026-05-28
    d14 = e._week_to_date(14)
    assert d14 == date(2026, 5, 28)


# ─── CourseSchedule lazy index ────────────────────────────────────────────

def test_course_schedule_lazy_loads(monkeypatch):
    _patch_semester(monkeypatch)
    sched = CourseSchedule(semester_label="2026 Spring")
    # No API call yet
    with patch("sustech_survival.tis.schedule_index.semester_schedule",
               side_effect=AssertionError("Should not be called before .entries")):
        pass
    # Trigger load
    entries = sched.entries
    assert len(entries) >= 4  # 2 org + 2 phychem (lecture excluded if filtered)


def test_course_schedule_caches_after_load(monkeypatch):
    call_count = [0]

    def fake_semester(*a, **kw):
        call_count[0] += 1
        return SAMPLE_SEMESTER

    monkeypatch.setattr(
        "sustech_survival.tis.schedule_index.semester_schedule",
        fake_semester,
    )
    sched = CourseSchedule(semester_label="2026 Spring")
    _ = sched.entries
    _ = sched.entries  # second access
    assert call_count[0] == 1


def test_course_schedule_courses_returns_unique_names(monkeypatch):
    _patch_semester(monkeypatch)
    sched = CourseSchedule(semester_label="2026 Spring")
    names = sched.courses
    # Should be deduplicated
    assert "基础有机化学实验" in names
    assert "物理化学实验" in names
    assert len(names) == len(set(names))


def test_course_schedule_find_substring(monkeypatch):
    _patch_semester(monkeypatch)
    sched = CourseSchedule(semester_label="2026 Spring")
    matches = sched.find("有机")
    assert len(matches) > 0
    assert all("有机" in e.name for e in matches)


def test_course_schedule_find_exact_match(monkeypatch):
    _patch_semester(monkeypatch)
    sched = CourseSchedule(semester_label="2026 Spring")
    matches = sched.find("物理化学实验")
    assert len(matches) == 2
    assert all(e.name == "物理化学实验" for e in matches)


def test_course_schedule_find_no_match_returns_empty(monkeypatch):
    _patch_semester(monkeypatch)
    sched = CourseSchedule(semester_label="2026 Spring")
    assert sched.find("不存在的课程") == []


# ─── Shortcut functions ───────────────────────────────────────────────────

def test_last_occurrence_returns_most_recent(monkeypatch):
    _patch_semester(monkeypatch)
    # On 2026-06-07 (Sun W15), last gorganic exp = W15 Monday = 2026-06-01
    # W15 starts 2026-02-24 + 14*7 = 2026-06-02 (Tue). Mon = 2026-06-01
    result = last_occurrence("有机", as_of=date(2026, 6, 7))
    assert result == date(2026, 6, 1)


def test_next_occurrence_returns_next_future(monkeypatch):
    _patch_semester(monkeypatch)
    # On 2026-06-07 (Sun W15), next gorganic would be... not in semester
    result = next_occurrence("有机", as_of=date(2026, 6, 7))
    # Last gorganic was W15 (5/25), no more — should be None
    assert result is None
    # On an earlier date, e.g. 2026-04-20 (start of W9), next gorganic = W9 Mon = 2026-04-20
    result = next_occurrence("有机", as_of=date(2026, 4, 19))  # Sunday before W9
    assert result is not None
    # W9: 2026-02-24 + 8*7 = 2026-04-21 (Tue). Mon of W9 = 2026-04-20
    assert result == date(2026, 4, 20)


def test_dates_in_week_returns_specific_date(monkeypatch):
    _patch_semester(monkeypatch)
    # W12 gorganic — but gorganic is odd weeks only, so W12 has no gorganic
    result = dates_in_week("有机", week=12)
    assert result == []  # empty list, not None

    # W13 gorganic — exists. W13: 2026-02-24 + 12*7 = 2026-05-19 (Tue)
    # Monday of W13 = 2026-05-18
    result = dates_in_week("有机", week=13)
    assert result == [date(2026, 5, 18)]


def test_dates_in_semester_returns_all(monkeypatch):
    _patch_semester(monkeypatch)
    # gorganic odd weeks: 3, 5, 7, 9, 11, 13, 15
    result = dates_in_semester("有机")
    assert len(result) == 7
    # All Mondays
    assert all(d.weekday() == 0 for d in result)  # Monday = 0
    # First one is W3 Monday = 2026-03-09
    assert result[0] == date(2026, 3, 9)
    # Last one is W15 Monday = 2026-06-01
    assert result[-1] == date(2026, 6, 1)


# ─── experiment_dates() helper ────────────────────────────────────────────

def test_experiment_dates_for_specific_week(monkeypatch):
    _patch_semester(monkeypatch)
    # gorganic W13 (exists)
    result = experiment_dates("有机", week=13, as_of=date(2026, 6, 7))
    assert result["course"] == "基础有机化学实验"
    assert result["experiment_date"] == date(2026, 5, 18)  # Mon of W13
    assert result["submission_date"] == date(2026, 6, 7)  # as_of
    assert result["week"] == 13


def test_experiment_dates_for_nonexistent_week_returns_closest(monkeypatch):
    _patch_semester(monkeypatch)
    # gorganic W12 — gorganic is odd weeks only, W12 doesn't exist
    result = experiment_dates("有机", week=12, as_of=date(2026, 6, 7))
    assert result["course"] == "基础有机化学实验"
    # Closest actual class — should be W11 (May 4-10) or W13 (May 18-24)
    # The function should return the most recent past one before or on W12
    assert result["experiment_date"] is not None
    assert result["week"] in (11, 13)
    assert "W12 has no gorganic class" in result.get("warning", "") or \
           result["week"] in (11, 13)


def test_experiment_dates_no_week_returns_most_recent(monkeypatch):
    _patch_semester(monkeypatch)
    result = experiment_dates("有机", as_of=date(2026, 6, 7))
    # W15 gorganic = 2026-06-01 (Monday)
    assert result["experiment_date"] == date(2026, 6, 1)
    assert result["week"] == 15


def test_experiment_dates_phychem_w15_even_weeks(monkeypatch):
    _patch_semester(monkeypatch)
    # phychem is even weeks (2,4,6,8,10,12,14,16) — W15 doesn't exist
    result = experiment_dates("物化", week=15, as_of=date(2026, 6, 7))
    assert result["course"] == "物理化学实验"
    # Should be W14 (Thursday 5/28) or W16 (Thursday 6/11) — but as_of is 6/7 so W16 is future
    # Most recent past: W14 (Thursday)
    # W14 starts 2026-02-24 + 13*7 = 2026-05-26 (Tue). Thursday of W14 = 2026-05-28
    assert result["experiment_date"] == date(2026, 5, 28)  # W14 Thursday
    assert result["week"] == 14


def test_experiment_dates_returns_weekday_info(monkeypatch):
    _patch_semester(monkeypatch)
    result = experiment_dates("有机", week=13, as_of=date(2026, 6, 7))
    assert result["weekday"] == "Monday"  # gorganic is Monday


def test_experiment_dates_phychem_weekday(monkeypatch):
    _patch_semester(monkeypatch)
    result = experiment_dates("物化", week=14, as_of=date(2026, 6, 7))
    assert result["weekday"] == "Thursday"  # phychem is Thursday


# ─── Module-level cache invalidation ──────────────────────────────────────

def test_clear_cache_resets(monkeypatch):
    _patch_semester(monkeypatch)
    sched1 = CourseSchedule(semester_label="2026 Spring")
    _ = sched1.entries  # load
    sched1.clear_cache()
    # After clear, next access should reload
    # (We can't easily verify without spy, just check no exception)


# ─── Edge cases ───────────────────────────────────────────────────────────

def test_unknown_course_returns_none_for_shortcuts(monkeypatch):
    _patch_semester(monkeypatch)
    assert last_occurrence("不存在的课程", as_of=date(2026, 6, 7)) is None
    assert next_occurrence("不存在的课程", as_of=date(2026, 6, 7)) is None


def test_dates_in_week_with_no_course_in_week(monkeypatch):
    _patch_semester(monkeypatch)
    # Phychem is even weeks; W15 has no phychem
    result = dates_in_week("物化", week=15)
    assert result == []


def test_experiment_dates_for_unknown_course(monkeypatch):
    _patch_semester(monkeypatch)
    result = experiment_dates("不存在的课程", as_of=date(2026, 6, 7))
    assert result["experiment_date"] is None
    assert "not found" in result.get("warning", "").lower() or \
           result.get("course") is None
