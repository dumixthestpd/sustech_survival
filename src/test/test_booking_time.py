"""
Tests for classroom._booking_time — BookingTime, ClockTime, period conversion.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from sustech_survival.classroom._booking_time import (
    BookingTime,
    ClockTime,
    _clock_to_period,
)


class TestClockTime:
    def test_from_str(self):
        ct = ClockTime.from_str("14:00")
        assert ct.hours == 14
        assert ct.minutes == 0
        assert str(ct) == "14:00"

    def test_total_minutes(self):
        assert ClockTime(14, 30).total_minutes == 14 * 60 + 30

    def test_raises_on_invalid(self):
        with pytest.raises(ValueError):
            ClockTime(25, 0)
        with pytest.raises(ValueError):
            ClockTime(14, 60)
        with pytest.raises(ValueError):
            ClockTime(-1, 0)


class TestClockToPeriod:
    def test_period_1(self):
        assert _clock_to_period(ClockTime(8, 0)) == 1
        assert _clock_to_period(ClockTime(8, 30)) == 1

    def test_period_5_afternoon(self):
        assert _clock_to_period(ClockTime(14, 0)) == 5
        assert _clock_to_period(ClockTime(14, 30)) == 5

    def test_period_9_evening(self):
        assert _clock_to_period(ClockTime(19, 0)) == 9

    def test_period_boundaries(self):
        assert _clock_to_period(ClockTime(10, 0)) == 3
        assert _clock_to_period(ClockTime(10, 45)) == 3
        # 10:50 is between periods (3 ends 10:45, 4 starts 10:55)
        with pytest.raises(ValueError):
            _clock_to_period(ClockTime(10, 50))


class TestBookingTime:
    def test_basic(self):
        bt = BookingTime(weekday=2, period_start=3, period_end=4)
        assert bt.weekday == 2
        assert bt.period_start == 3
        assert bt.period_end == 4
        assert bt.weeks is None

    def test_with_weeks(self):
        bt = BookingTime(weekday=2, period_start=3, period_end=4, weeks=[5, 6, 7, 8])
        assert bt.week_str == "5-8"

    def test_from_clock(self):
        bt = BookingTime.from_clock(weekday=2, clock_start="14:00", clock_end="16:00")
        # 14:00 = period 5, 16:00 = period 7
        assert bt.period_start == 5
        assert bt.period_end == 7

    def test_from_clock_with_weeks(self):
        bt = BookingTime.from_clock(
            weekday=2, clock_start="14:00", clock_end="16:00", weeks=[5, 6, 7, 8]
        )
        assert bt.weeks == [5, 6, 7, 8]
        assert bt.week_str == "5-8"

    def test_period_range(self):
        bt = BookingTime(weekday=1, period_start=5, period_end=7)
        assert list(bt.period_range) == [5, 6, 7]

    def test_raises_invalid_weekday(self):
        with pytest.raises(ValueError):
            BookingTime(weekday=0, period_start=3, period_end=4)
        with pytest.raises(ValueError):
            BookingTime(weekday=8, period_start=3, period_end=4)

    def test_raises_invalid_period_range(self):
        with pytest.raises(ValueError):
            BookingTime(weekday=1, period_start=0, period_end=4)
        with pytest.raises(ValueError):
            BookingTime(weekday=1, period_start=5, period_end=3)
        with pytest.raises(ValueError):
            BookingTime(weekday=1, period_start=1, period_end=13)

    def test_str_single_period(self):
        bt = BookingTime(weekday=2, period_start=3, period_end=3)
        assert "第3节" in str(bt)

    def test_str_range(self):
        bt = BookingTime(weekday=2, period_start=3, period_end=4)
        assert "第3-4节" in str(bt)

    def test_week_str_discontinuous(self):
        bt = BookingTime(weekday=1, period_start=1, period_end=2,
                         weeks=[1, 3, 5, 7])
        assert bt.week_str == "1,3,5,7"

    def test_week_str_single(self):
        bt = BookingTime(weekday=1, period_start=1, period_end=2, weeks=[7])
        assert bt.week_str == "7"

    def test_week_str_empty(self):
        bt = BookingTime(weekday=1, period_start=1, period_end=2)
        assert bt.week_str == ""


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
