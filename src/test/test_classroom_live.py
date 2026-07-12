"""
Tests for sustech_survival.tis.classroom.live — TIS 场地课表 (per-room schedule).

These tests cover offline parsing + integration with the live client.
The integration tests use a mock session that returns canned API responses,
so they don't hit the live TIS server.

Run: pytest src/test/test_live.py -v
Mark as offline: parser tests are pure offline.
Mark the @pytest.mark.live tests for live-server runs only.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from sustech_survival.tis.classroom.live import (
    LiveOccupancyClient,
    RoomScheduleEntry,
    _first_full_week_start,
    _expand_week_pattern,
    current_period,
    current_semester,
    current_week,
    current_weekday_and_period,
    parse_key,
    parse_sksj,
)
from sustech_survival.tis.classroom.classroom import (
    BUILDING_ALIASES,
    ClassroomOccupancy,
    normalize_room_name,
)


# ── Parser tests (pure offline) ─────────────────────────────────────────────


class TestParseKey:
    def test_basic(self):
        assert parse_key("xq7_jc6") == (7, 6)

    def test_monday(self):
        assert parse_key("xq1_jc1") == (1, 1)

    def test_invalid(self):
        assert parse_key("") is None
        assert parse_key("invalid") is None
        assert parse_key("xq_jc") is None
        assert parse_key("xq7") is None

    def test_non_integer(self):
        assert parse_key("xqA_jc1") is None
        assert parse_key("xq1_jcX") is None


class TestParseSksjBorrowing:
    def test_single_week(self):
        text = "【借用】[17周]\n使用人:井水淼\n联系电话:18926762778"
        p = parse_sksj(text)
        assert p["type"] == "borrowing"
        assert p["weeks"] == [17]
        assert p["borrower"] == "井水淼"
        assert p["phone"] == "18926762778"
        assert p["course_name"] is None

    def test_week_range(self):
        text = "【借用】[1-9周]\n使用人:张三\n联系电话:13908478929"
        p = parse_sksj(text)
        assert p["weeks"] == [1, 2, 3, 4, 5, 6, 7, 8, 9]

    def test_discrete_weeks(self):
        text = "【借用】[1,3,5周]\n使用人:李四\n联系电话:13500000000"
        p = parse_sksj(text)
        assert p["weeks"] == [1, 3, 5]

    def test_empty(self):
        p = parse_sksj("")
        assert p["type"] == "unknown"
        assert p["weeks"] == []
        assert p["borrower"] is None


class TestParseSksjCourse:
    def test_undergrad(self):
        text = "【本】人体微生态结构与功能[刘星吟][人体微生态结构与功能-01班-双语][9周][9-10节]"
        p = parse_sksj(text)
        assert p["type"] == "undergrad"
        assert p["weeks"] == [9]
        assert p["course_name"] == "人体微生态结构与功能"
        assert p["borrower"] is None
        assert p["phone"] is None

    def test_grad(self):
        text = "【研】蛋白质工程[Peter Pimpl][蛋白质工程-01班-英文][1-15周][3-4节]"
        p = parse_sksj(text)
        assert p["type"] == "grad"
        assert p["weeks"] == list(range(1, 16))
        assert p["course_name"] == "蛋白质工程"

    def test_mixed(self):
        text = "【研本】生物芯片设计及应用[李毅][生物芯片设计及应用-01班-英文][6周][5-6节]"
        p = parse_sksj(text)
        assert p["type"] == "mixed"
        assert p["weeks"] == [6]


class TestExpandWeekPattern:
    def test_single(self):
        assert _expand_week_pattern("5") == [5]

    def test_range(self):
        assert _expand_week_pattern("1-15") == list(range(1, 16))

    def test_discrete(self):
        assert _expand_week_pattern("1,3,5") == [1, 3, 5]

    def test_mixed(self):
        assert _expand_week_pattern("1-9,11-15") == [1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 13, 14, 15]


# ── RoomScheduleEntry ───────────────────────────────────────────────────────


class TestRoomScheduleEntry:
    def test_from_api_borrowing(self):
        raw = {
            "KCDM": "jy",
            "SKSJ": "【借用】[17周]\n使用人:井水淼\n联系电话:18926762778",
            "SKSJ_EN": "招生活动",
            "XB": 19,
            "KEY": "xq7_jc6",
        }
        e = RoomScheduleEntry.from_api(raw, cddm="YJ-123")
        assert e is not None
        assert e.is_borrowing
        assert e.weekday == 7
        assert e.period_start == 6
        assert e.weeks == [17]
        assert e.borrower == "井水淼"
        assert e.phone == "18926762778"
        assert e.purpose == "招生活动"

    def test_from_api_course(self):
        raw = {
            "KCDM": "MA111",
            "SKSJ": "【本】高等代数 II[陆康][高等代数 II-01班-中文][14周][5-6节]",
            "XB": 10,
            "KEY": "xq6_jc3",
        }
        e = RoomScheduleEntry.from_api(raw, cddm="YJ-123")
        assert e is not None
        assert e.is_course
        assert e.course_code == "MA111"
        assert e.course_name == "高等代数 II"
        assert e.weeks == [14]

    def test_from_api_invalid_key(self):
        raw = {"KCDM": "x", "SKSJ": "x", "KEY": "invalid"}
        assert RoomScheduleEntry.from_api(raw, cddm="X") is None

    def test_active_on(self):
        e = RoomScheduleEntry(
            raw={}, cddm="X", weekday=3, period_start=5,
            weeks=[1, 2, 3, 5, 7], type="borrowing",
        )
        assert e.active_on(3, 3)
        assert e.active_on(5, 3)
        assert not e.active_on(4, 3)  # not in weeks
        assert not e.active_on(3, 4)  # wrong weekday

    def test_when_str_single_week(self):
        e = RoomScheduleEntry(
            raw={}, cddm="X", weekday=3, period_start=5,
            weeks=[5], type="borrowing",
        )
        assert e.when_str == "5周 周三 第5节"

    def test_when_str_range(self):
        e = RoomScheduleEntry(
            raw={}, cddm="X", weekday=7, period_start=6,
            weeks=list(range(1, 16)), type="course",
        )
        assert e.when_str == "1-15周 周日 第6节"


# ── Time helpers ────────────────────────────────────────────────────────────


class TestCurrentPeriod:
    def test_morning(self):
        assert current_period(8, 0) == 1
        assert current_period(8, 30) == 1
        assert current_period(9, 0) == 2

    def test_lunch_break(self):
        # Between 11:40 and 14:00 — no class period active
        assert current_period(12, 0) is None

    def test_afternoon(self):
        assert current_period(14, 30) == 5
        assert current_period(15, 0) == 6

    def test_evening(self):
        assert current_period(19, 30) == 9

    def test_night(self):
        assert current_period(23, 30) is None
        assert current_period(2, 0) is None


class TestCurrentWeekdayAndPeriod:
    def test_now(self):
        import datetime as dt
        when = dt.datetime(2026, 6, 28, 10, 30)  # Sunday 10:30 AM
        weekday, period = current_weekday_and_period(when)
        assert weekday == 7  # Sunday
        # 10:30 falls in period 3 (10:00-10:45)
        assert period == 3


# ── LiveOccupancyClient integration (mocked) ───────────────────────────────


class TestLiveOccupancyClientMocked:
    @pytest.fixture
    def mock_session(self):
        sess = MagicMock()
        # querycdkbList response
        cdkb_resp = MagicMock()
        cdkb_resp.json.return_value = [
            {"KCDM": "jy",
             "SKSJ": "【借用】[17周]\n使用人:井水淼\n联系电话:18926762778",
             "SKSJ_EN": "招生活动", "XB": 19, "KEY": "xq7_jc6"},
            {"KCDM": "MA111",
             "SKSJ": "【本】高等代数 II[陆康][14周][5-6节]",
             "XB": 10, "KEY": "xq6_jc3"},
        ]
        cdkb_resp.text = json.dumps(cdkb_resp.json.return_value)
        cdkb_resp.status_code = 200
        cdkb_resp.raise_for_status = lambda: None

        sess.post.return_value = cdkb_resp
        return sess

    def test_query_room_returns_entries(self, mock_session, tmp_path,
                                         monkeypatch):
        from sustech_survival import _cache
        monkeypatch.setattr(_cache, "TMP_ROOT", tmp_path, raising=False)
        client = LiveOccupancyClient()
        client._sess = mock_session
        entries = client.query_room("YJ-123", xn="2025-2026", xq="2",
                                     use_cache=False)
        assert len(entries) == 2
        assert entries[0].is_borrowing
        assert entries[1].is_course
        assert entries[0].borrower == "井水淼"
        assert entries[0].cddm == "YJ-123"

    def test_live_at_filters_by_weekday(self, mock_session, tmp_path,
                                         monkeypatch):
        from sustech_survival import _cache
        monkeypatch.setattr(_cache, "TMP_ROOT", tmp_path, raising=False)
        client = LiveOccupancyClient()
        client._sess = mock_session
        entries = client.query_room("YJ-123", xn="2025-2026", xq="2",
                                     use_cache=False)
        # Filter for week=17, weekday=7 (Sunday) — should match entry 0
        hits = [e for e in entries if e.active_on(17, 7)]
        assert len(hits) == 1
        assert hits[0].is_borrowing
        # Filter for week=14, weekday=6 (Saturday) — should match entry 1
        hits = [e for e in entries if e.active_on(14, 6)]
        assert len(hits) == 1
        assert hits[0].is_course
        # No match for week=14, weekday=7 (Sunday) — entry 1 is Saturday
        hits = [e for e in entries if e.active_on(14, 7)]
        assert len(hits) == 0

    def test_cache_persists(self, mock_session, tmp_path, monkeypatch):
        from sustech_survival import _cache
        monkeypatch.setattr(_cache, "TMP_ROOT", tmp_path, raising=False)
        client = LiveOccupancyClient()
        client._sess = mock_session
        # First call: hits mock_session
        client.query_room("YJ-123", xn="2025-2026", xq="2", use_cache=False)
        # Second call: should hit cache, not mock_session.post again
        client.query_room("YJ-123", xn="2025-2026", xq="2", use_cache=True)
        # mock_session.post called only once for cdkb (plus once for dq_xnxq)
        # but the second query_room uses cache
        # Actually first query also calls dq_xnxq because query_room calls _ensure_session
        # Wait, _ensure_session is mocked by _sess = mock_session, so post is only called
        # when query_room actually fires. query_room does NOT call dq_xnxq.
        # So post should be called once for cdkb
        cdkb_calls = sum(1 for call in mock_session.post.call_args_list
                          if 'cdkb' in str(call))
        assert cdkb_calls == 1


# ── Building name aliases (verified 2026-06-28) ─────────────────────────────


class TestNormalizeRoomName:
    """Prefix aliasing: 三教 / 智华 → 智华楼.

    Key cases:
      - Longest-prefix match wins (智华楼 vs 智华) to avoid '智华楼楼102'.
      - Self-aliasing canonical name keeps it as-is.
      - Non-aliased names pass through (一教, 二教, etc.).
    """

    def test_sanjiao_to_zhihua(self):
        assert normalize_room_name("三教102") == "智华楼102"

    def test_short_zhihua_to_zhihua(self):
        assert normalize_room_name("智华102") == "智华楼102"

    def test_canonical_unchanged(self):
        # The 智华楼→智华楼 self-alias + longest-prefix-first sort means
        # '智华楼102' stays as '智华楼102' (NOT '智华楼楼102').
        assert normalize_room_name("智华楼102") == "智华楼102"

    def test_no_double_up_on_canonical(self):
        """Regression for the original bug: '智华楼' was being matched as
        a prefix of itself, then '智华' was being matched inside, giving
        '智华楼楼'.
        """
        assert "楼楼" not in normalize_room_name("智华楼102")
        assert "楼楼" not in normalize_room_name("智华楼")
        assert "楼楼" not in normalize_room_name("智华楼A201")

    def test_non_aliased_unchanged(self):
        assert normalize_room_name("一教324") == "一教324"
        assert normalize_room_name("二教201") == "二教201"
        assert normalize_room_name("润杨体育馆") == "润杨体育馆"

    def test_alphanumeric_suffix_preserved(self):
        assert normalize_room_name("三教A201") == "智华楼A201"
        assert normalize_room_name("智华A201") == "智华楼A201"

    def test_whitespace_stripped(self):
        assert normalize_room_name("  三教102  ") == "智华楼102"

    def test_aliases_dict_includes_self_alias(self):
        """The canonical name must be a self-alias so longest-prefix-first
        iteration picks it before the shorter alias (e.g. 智华楼 before 智华).
        """
        assert "智华楼" in BUILDING_ALIASES
        assert BUILDING_ALIASES["智华楼"] == "智华楼"
        # And 三教 → 智华楼
        assert BUILDING_ALIASES["三教"] == "智华楼"
        assert BUILDING_ALIASES["智华"] == "智华楼"


@pytest.mark.skipif(
    not Path("/Users/dumix/.openclaw/workspace/skills/sustech_survival/classroom/cache/live/didian_2025-2026_2.json").exists(),
    reason="didian cache not present (run `classroom live` once to bootstrap)",
)
class TestRoomCodeForNameAliasing:
    """All three 三教 / 智华 / 智华楼 spellings must resolve to the same dm.

    Uses the on-disk didian cache, no network. Verifies the end-to-end
    aliasing→catalog-match path that `classroom live 三教102` walks through.
    """

    def setup_method(self):
        self.c = ClassroomOccupancy()

    def test_sanjiao_resolves_to_zh(self):
        """三教102 → ZH-102 (the live data source)."""
        assert self.c._room_code_for_name("三教102") == "ZH-102"

    def test_short_zhihua_resolves_to_zh(self):
        assert self.c._room_code_for_name("智华102") == "ZH-102"

    def test_canonical_resolves_to_zh(self):
        assert self.c._room_code_for_name("智华楼102") == "ZH-102"

    def test_all_three_spellings_return_same_dm(self):
        """The whole point — 三教 / 智华 / 智华楼 all give the same room code."""
        a = self.c._room_code_for_name("三教116")
        b = self.c._room_code_for_name("智华116")
        c = self.c._room_code_for_name("智华楼116")
        assert a is not None
        assert a == b == c

    def test_unrelated_buildings_unaffected(self):
        """一教324 is NOT aliased — must still work normally."""
        assert self.c._room_code_for_name("一教324") == "YJ-324"

    def test_nonexistent_room_returns_none(self):
        """Rooms that don't exist anywhere return None, not crash."""
        assert self.c._room_code_for_name("不存在999") is None


# ── Mark for live tests (skipped by default) ────────────────────────────────


class TestFirstFullWeekStart:
    """Round semester_start UP to the next Monday.

    TIS week 1 begins on the first FULL Mon-Sun week that follows the
    first class day. If classes start on a Tuesday (e.g. Tue Feb 24),
    TIS week 1 starts the NEXT Monday (Mar 2), not the preceding one.
    The days Tue-Sun between them are "week 0" / pre-class.
    """

    def test_tuesday_rounds_forward(self):
        import datetime as dt
        # Spring 2026: classes officially start Tue Feb 24, 2026
        # TIS week 1 = Mon Mar 2 - Sun Mar 8 (the first full Mon-Sun week
        # after the start date)
        assert _first_full_week_start(dt.date(2026, 2, 24)) == dt.date(2026, 3, 2)

    def test_monday_unchanged(self):
        import datetime as dt
        # Fall 2025: Sep 1, 2025 was a Monday → that's week 1 anchor
        assert _first_full_week_start(dt.date(2025, 9, 1)) == dt.date(2025, 9, 1)

    def test_friday_rounds_forward(self):
        import datetime as dt
        # Friday Aug 28 → next Monday Aug 31 (3 days later)
        assert _first_full_week_start(dt.date(2026, 8, 28)) == dt.date(2026, 8, 31)

    def test_sunday_rounds_forward_to_next_monday(self):
        import datetime as dt
        # Sunday Sep 6 → next Monday Sep 7
        assert _first_full_week_start(dt.date(2026, 9, 6)) == dt.date(2026, 9, 7)


class TestCurrentWeek:
    """The core inference: today → (xn, xq) → week number.

    Verified 2026-06-28 by YJ-123 borrowings distribution:
      - Today (Jun 28, Sunday) = week 17 of Spring 2026.
      - TIS week 1 starts Mon Mar 2 (the next Monday after Feb 24).
      - Borrowings span weeks 1-17 with no week 0.
    """

    ACAL = {
        "2026 Spring": {
            "semester_start": "2026-02-24",
            "spring_break": ("2026-04-04", "2026-04-12"),
            "semester_end": "2026-06-28",
            "summer_start": "2026-06-29",
        },
        "2025 Fall": {
            "semester_start": "2025-09-01",
            "spring_break": None,
            "semester_end": "2025-12-28",
            "summer_start": "2025-12-29",
        },
    }

    def test_today_spring_2026_is_week_17(self):
        """Today is 2026-06-28 (Sunday). With the round-UP rule,
        Spring 2026 (Feb 24 start) is in week 17.
        Anchor = Mon Mar 2; days = 118; 118//7 + 1 = 17.
        """
        import datetime as dt
        w = current_week("2025-2026", "2", today=dt.date(2026, 6, 28), acal=self.ACAL)
        assert w == 17

    def test_partial_first_week_counts_as_week_1(self):
        """Tue Feb 24 (first class day) is week 1, even though it's before
        the anchor Mon Mar 2. Same for the rest of the partial first week
        (Wed Feb 25 through Sun Mar 1).
        """
        import datetime as dt
        for d in [dt.date(2026, 2, 24), dt.date(2026, 2, 25), dt.date(2026, 2, 28),
                  dt.date(2026, 3, 1)]:
            w = current_week("2025-2026", "2", today=d, acal=self.ACAL)
            assert w == 1, f"{d} should be week 1, got {w}"

    def test_first_full_monday_is_week_1(self):
        """Mon Mar 2 (the first full Monday-Sunday week) is the start of week 1."""
        import datetime as dt
        w = current_week("2025-2026", "2", today=dt.date(2026, 3, 2), acal=self.ACAL)
        assert w == 1

    def test_spring_break_does_not_bump_week(self):
        """During Qingming break (Apr 4-12, 2026), `classroom now` should
        snap to the week containing the START of the break.

        Anchor = Mar 2. Apr 4 (Sat) days = 33; week = 33//7 + 1 = 5.
        So both Apr 4 and Apr 12 should return week 5.
        """
        import datetime as dt
        w_start = current_week("2025-2026", "2", today=dt.date(2026, 4, 4), acal=self.ACAL)
        w_end = current_week("2025-2026", "2", today=dt.date(2026, 4, 12), acal=self.ACAL)
        assert w_start == 5
        assert w_end == 5

    def test_outside_semester_returns_none(self):
        """Days before/after the semester window return None."""
        import datetime as dt
        # Before Spring 2026 (e.g. Feb 23, the day before classes start)
        assert current_week("2025-2026", "2", today=dt.date(2026, 2, 23), acal=self.ACAL) is None
        # After Spring 2026 (e.g. Jun 29, first day of summer)
        assert current_week("2025-2026", "2", today=dt.date(2026, 6, 29), acal=self.ACAL) is None

    def test_unknown_semester_returns_none(self):
        import datetime as dt
        # 2024-2025 xq=1 is Fall 2024, not in ACAL
        assert current_week("2024-2025", "1", today=dt.date(2024, 10, 1), acal=self.ACAL) is None

    def test_fall_semester_first_day(self):
        """Fall 2025 starts Mon Sep 1, 2025 — straightforward (anchor = start)."""
        import datetime as dt
        w = current_week("2025-2026", "1", today=dt.date(2025, 9, 1), acal=self.ACAL)
        assert w == 1
        w = current_week("2025-2026", "1", today=dt.date(2025, 9, 7), acal=self.ACAL)
        assert w == 1  # Still week 1 (Sep 1-7)
        w = current_week("2025-2026", "1", today=dt.date(2025, 9, 8), acal=self.ACAL)
        assert w == 2

    def test_week_midpoint(self):
        """Spot-check: 2026-04-15 (Wed, week 6 of Spring 2026).

        Anchor Mar 2. Apr 15 days = 44; 44 // 7 + 1 = 7. Wait —
        Mar has 31 days, so Mar 2 to Mar 31 = 29 days. Apr 1-15 = 15.
        Total = 29 + 15 = 44. 44 // 7 + 1 = 7.

        But Apr 4-12 is spring break, so Apr 15 (Wed) is AFTER the break
        and should be in week 7 (the week that starts Apr 13, Mon).
        """
        import datetime as dt
        w = current_week("2025-2026", "2", today=dt.date(2026, 4, 15), acal=self.ACAL)
        assert w == 7


@pytest.mark.live
class TestLiveOccupancyClientLive:
    """Live-server tests. Run with: pytest -m live src/test/test_live.py"""

    def test_query_room_live(self):
        """Hit the live TIS server. Requires valid CAS credentials."""
        client = LiveOccupancyClient()
        entries = client.query_room("YJ-123", xn="2025-2026", xq="2")
        # Should have at least 50 entries (real room with activity)
        assert len(entries) > 50
        # At least some borrowings
        assert sum(1 for e in entries if e.is_borrowing) > 0

    def test_current_semester_live(self):
        client = LiveOccupancyClient()
        sess = client._ensure_session()
        sem = current_semester(sess)
        # Current semester should be 2025-2026 xq=2 (Spring 2026) since
        # today is 2026-06-28
        assert sem.xn == "2025-2026"
        assert sem.xq == "2"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])