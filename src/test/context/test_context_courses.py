"""Tests for sustech_survival.context.courses — per-course next/last sessions.

Pure date-math tests: the TIS timetable and current week are patched, so no
network/auth is involved. The anchor invariant tested throughout: TIS week 1
of 2026 Fall starts Monday 2026-09-07 (week 1 was live on Tue 2026-09-08).

Ground truth baked into these fixtures (verified live):
  - TIS ZC bitmap char at index i means week i; index 0 is a pad, so
    '0111...' = weeks 1,2,3... — NOT weeks 2,3,4...
  - 材料学综合实验I meets Wednesdays (xq3) periods 1-8 every week 1-16.
  - 材料科学与工程高等实验I meets Mondays (xq1) periods 5-8 on ODD weeks
    1,3,...,15 (the Monday of week 1 was a real class).
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest

from sustech_survival.context import CHINA_TZ
from sustech_survival.context.courses import (
    course_when,
    match_courses,
    render,
    session_rows,
)

NOW = datetime(2026, 9, 8, 12, 0, tzinfo=CHINA_TZ)  # Tue, TIS week 1


def _zc(weeks: list, total: int = 36) -> str:
    """Build a TIS ZC bitmap (index i = week i, index 0 is pad)."""
    chars = ["0"] * total
    for w in weeks:
        chars[w] = "1"
    return "".join(chars)


def _row(name: str, key: str, ks: int, js: int, weeks: list) -> dict:
    return {"SKSJ": f"{name}\n[teacher]", "SKSJ_EN": name, "KEY": key,
            "KSJC": str(ks), "JSJC": str(js), "ZC": _zc(weeks)}


ROWS = [
    _row("材料学综合实验I", "xq3_jc1", 1, 8, list(range(1, 17))),
    _row("材料学综合实验I", "xq3_jc2", 1, 8, list(range(1, 17))),  # group rows
    _row("材料科学与工程高等实验I", "xq1_jc3", 5, 8, list(range(1, 16, 2))),
    _row("材料科学与工程高等实验I", "xq1_jc4", 5, 8, list(range(1, 16, 2))),
]


def _run(query: str, when: str, now=NOW):
    with patch("sustech_survival.tis.schedule.semester_schedule",
               return_value=ROWS), \
         patch("sustech_survival.tis.schedule.current_week", return_value=1):
        return course_when(query, when, now=now)


def test_session_rows_dedupe_and_sort():
    with patch("sustech_survival.tis.schedule.semester_schedule",
               return_value=ROWS):
        import sustech_survival.context.courses as cc
        anchor = cc._anchor_monday(1, NOW.date())
        sessions = session_rows(ROWS, anchor)
    comp = [s for s in sessions if s["course"] == "材料学综合实验I"]
    assert len(comp) == 16  # weeks 1..16, group rows collapsed
    assert comp[0]["date"].isoformat() == "2026-09-09"  # Wed of week 1
    assert comp[0]["week"] == 1
    assert comp[0]["periods"] == (1, 8)
    adv = [s for s in sessions if s["course"] == "材料科学与工程高等实验I"]
    assert [s["week"] for s in adv] == [1, 3, 5, 7, 9, 11, 13, 15]  # ODD weeks
    assert adv[0]["date"].isoformat() == "2026-09-07"  # the real Monday class


def test_fuzzy_match_substring_both_directions():
    with patch("sustech_survival.tis.schedule.semester_schedule",
               return_value=ROWS):
        import sustech_survival.context.courses as cc
        anchor = cc._anchor_monday(1, NOW.date())
        sessions = session_rows(ROWS, anchor)
    assert match_courses(sessions, "材料学综合") == ["材料学综合实验I"]
    assert match_courses(sessions, "高等实验") == ["材料科学与工程高等实验I"]


def test_next_weekly_lab():
    res = _run("材料学综合实验I", "next")
    s = res["session"]
    assert res["course"] == "材料学综合实验I"
    assert s["date"].isoformat() == "2026-09-09"  # Wed of week 1 (tomorrow)
    assert s["week"] == 1
    assert s["periods"] == (1, 8)


def test_next_skips_a_session_that_ended_earlier_today():
    # Wed 2026-09-09 (week 1) the lab runs periods 1-8, which end at 16:45.
    evening = datetime(2026, 9, 9, 18, 0, tzinfo=CHINA_TZ)
    s = _run("材料学综合实验I", "next", now=evening)["session"]
    assert s["date"].isoformat() == "2026-09-16"  # Wed of week 2
    assert s["week"] == 2


def test_next_keeps_todays_session_until_it_ends():
    for hour in (7, 12):  # before it starts, and while it is running
        now = datetime(2026, 9, 9, hour, 0, tzinfo=CHINA_TZ)
        s = _run("材料学综合实验I", "next", now=now)["session"]
        assert s["date"].isoformat() == "2026-09-09"
        assert s["week"] == 1


def test_last_before_term_classes_start():
    res = _run("材料学综合实验I", "last")
    assert res["session"] is None
    assert res["reason"] == "no session yet this term"
    assert res["edge"]["date"].isoformat() == "2026-09-09"  # first session hint


def test_next_odd_week_course_midterm():
    mid = datetime(2026, 9, 29, 12, 0, tzinfo=CHINA_TZ)  # Tue, week 4
    res = _run("材料科学与工程高等实验I", "next", now=mid)
    s = res["session"]
    assert s["date"].isoformat() == "2026-10-05"  # Mon of week 5 (odd)
    assert s["week"] == 5


def test_last_odd_week_course_midterm():
    mid = datetime(2026, 9, 29, 12, 0, tzinfo=CHINA_TZ)  # Tue, week 4
    res = _run("材料科学与工程高等实验I", "last", now=mid)
    s = res["session"]
    assert s["date"].isoformat() == "2026-09-21"  # Mon of week 3 (odd)
    assert s["week"] == 3
    assert s["periods"] == (5, 8)


def test_last_odd_week_course_week1_monday():
    # The user just had the week-1 Monday class (2026-09-07).
    monday_after = datetime(2026, 9, 7, 20, 0, tzinfo=CHINA_TZ)  # Mon wk1 eve
    res = _run("材料科学与工程高等实验I", "last", now=monday_after)
    s = res["session"]
    assert s["date"].isoformat() == "2026-09-07"
    assert s["week"] == 1


def test_ambiguous_query_raises():
    with pytest.raises(ValueError, match="ambiguous"):
        _run("实验", "next")  # matches both lab courses


def test_unknown_query_lists_available():
    with pytest.raises(ValueError, match="your courses:"):
        _run("量子力学", "next")


def test_render_ok_and_error_shapes():
    with patch("sustech_survival.tis.schedule.semester_schedule",
               return_value=ROWS), \
         patch("sustech_survival.tis.schedule.current_week", return_value=1):
        ok = render("材料学综合实验I", "next", now=NOW)
        assert ok["ok"] is True
        assert "2026-09-09" in ok["text"]
        bad = render("量子力学", "next", now=NOW)
        assert bad["ok"] is False
        assert "❌" in bad["text"]
