"""
sustech_survival.classroom._booking_time — Typed time descriptors for booking.

Follows the existing ScheduleSlot convention: int weekday, int periods,
List[int] weeks. No strings. No WeeklyTime/SpecificTime proliferation.

Every time descriptor MUST be one of these types — no raw strings accepted.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Union

from sustech_survival.classroom.live import PERIOD_TIMES


# ── Simple descriptors ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ClockTime:
    """A point in time as HH:MM. '14:00' → (14, 0)."""
    hours: int
    minutes: int

    def __post_init__(self) -> None:
        if not (0 <= self.hours < 24 and 0 <= self.minutes < 60):
            raise ValueError(f"Invalid clock time: {self.hours:02d}:{self.minutes:02d}")

    @classmethod
    def from_str(cls, s: str) -> "ClockTime":
        h, m = s.strip().split(":")
        return cls(int(h), int(m))

    @property
    def total_minutes(self) -> int:
        return self.hours * 60 + self.minutes

    def __str__(self) -> str:
        return f"{self.hours:02d}:{self.minutes:02d}"


def _clock_to_period(tm: ClockTime) -> int:
    """Map a clock time to the nearest TIS period number (1-12)."""
    minutes = tm.total_minutes
    for p in range(1, 13):
        sh, sm, eh, em = PERIOD_TIMES[p]
        if sh * 60 + sm <= minutes <= eh * 60 + em:
            return p
    raise ValueError(
        f"Clock time {tm} does not fall within any TIS period "
        f"(class hours are 08:00-22:30)"
    )


# ── Booking time (user-facing) ───────────────────────────────────────────────


@dataclass(frozen=True)
class BookingTime:
    """A repeating weekly time slot for venue booking.

    Follows ScheduleSlot convention: int weekday (1=Mon), int periods,
    List[int] weeks. Accepts clock strings which auto-convert to periods.

    Construction::

        # Period-based (preferred — no conversion needed)
        BookingTime(weekday=2, period_start=3, period_end=4)

        # Clock-based (auto-converts to periods)
        BookingTime(weekday=2, clock_start="14:00", clock_end="16:00")

        # With specific weeks
        BookingTime(weekday=2, period_start=3, period_end=4,
                    weeks=[5, 6, 7, 8])

        # All weeks (default)
        BookingTime(weekday=2, period_start=3, period_end=4)
        # → weeks = None  (means "all weeks of current semester")
    """
    weekday: int                   # 1=Mon … 7=Sun
    period_start: int = field()    # 1-12
    period_end: int = field()      # 1-12 (inclusive)
    weeks: Optional[List[int]] = None   # None = all weeks

    def __post_init__(self) -> None:
        if not (1 <= self.weekday <= 7):
            raise ValueError(f"Weekday must be 1-7, got {self.weekday}")
        if not (1 <= self.period_start <= self.period_end <= 12):
            raise ValueError(
                f"Period range must be 1-12 with start <= end, "
                f"got {self.period_start}-{self.period_end}"
            )

    @classmethod
    def from_clock(
        cls,
        weekday: int,
        clock_start: str,
        clock_end: str,
        *,
        weeks: Optional[List[int]] = None,
    ) -> "BookingTime":
        """Construct from clock strings. '14:00', '16:00' → periods 5-7.

        Uses the SUSTech period schedule (45-min blocks from PERIOD_TIMES).
        """
        ps = _clock_to_period(ClockTime.from_str(clock_start))
        pe = _clock_to_period(ClockTime.from_str(clock_end))
        return cls(weekday=weekday, period_start=ps, period_end=pe, weeks=weeks)

    @property
    def period_range(self) -> range:
        return range(self.period_start, self.period_end + 1)

    @property
    def week_str(self) -> str:
        """Compact week pattern for TIS: '[5,6,7,8]' → '5-8'."""
        if not self.weeks:
            return ""
        weeks = sorted(set(self.weeks))
        if not weeks:
            return ""
        ranges: List[str] = []
        start = end = weeks[0]
        for w in weeks[1:]:
            if w == end + 1:
                end = w
            else:
                ranges.append(f"{start}-{end}" if start != end else str(start))
                start = end = w
        ranges.append(f"{start}-{end}" if start != end else str(start))
        return ",".join(ranges)

    def to_borrow_slots(self) -> List:
        """Convert to BorrowTimeSlot list for the TIS API.

        Returns a list (one slot per period) with the week pattern
        and period range expanded for the cdjyform.jtsjlist format.
        """
        from sustech_survival.tis.classroom.booking_schema import BorrowTimeSlot

        week_pattern = self.week_str if self.weeks else "1-17"
        return [
            BorrowTimeSlot(
                weekday=self.weekday,
                period_start=self.period_start,
                period_end=self.period_end,
                week_pattern=week_pattern,
            )
        ]

    def __str__(self) -> str:
        day_zh = ["", "周一", "周二", "周三", "周四", "周五", "周六", "周日"][self.weekday]
        p = f"第{self.period_start}-{self.period_end}节" if self.period_start != self.period_end else f"第{self.period_start}节"
        w = f" {self.week_str}周" if self.weeks else ""
        return f"{day_zh} {p}{w}"


# ── Schedule (the argument to book()) ────────────────────────────────────────


Schedule = Union[BookingTime, List[BookingTime]]
"""
A booking schedule — either a single slot or multiple.

::

    # Single slot
    book(schedule=BookingTime(weekday=2, period_start=3, period_end=4))

    # Multiple slots
    book(schedule=[
        BookingTime(weekday=2, period_start=3, period_end=4),
        BookingTime(weekday=4, period_start=5, period_end=6),
    ])
"""


__all__ = [
    "BookingTime",
    "ClockTime",
    "Schedule",
    "_clock_to_period",
]
