"""
sustech_survival.semester — Canonical semester type for the entire package.
"""
from __future__ import annotations

from enum import Enum


class Season(Enum):
    """SUSTech academic season."""
    FALL   = "fall"
    SPRING = "spring"
    SUMMER = "summer"

    @classmethod
    def from_int(cls, n: int) -> "Season":
        """Season(1) → FALL, Season(2) → SPRING, Season(3) → SUMMER."""
        return {1: cls.FALL, 2: cls.SPRING, 3: cls.SUMMER}[n]

    @classmethod
    def from_months(cls, month: int) -> "Season":
        """Map a calendar month to the academic season that spans it.

        SUSTech terms: Fall = Sep..Jan, Spring = Feb..Jul (starts mid-Feb),
        Summer = Jul..Aug. January/February straddle the boundary; we treat
        Jan+Feb as Spring (the Spring term that owns most of them), late
        Jul+Aug as Summer, and Sep..Dec as Fall.
        """
        if month in (9, 10, 11, 12):
            return cls.FALL
        if month in (1, 2, 3, 4, 5, 6):
            return cls.SPRING
        return cls.SUMMER  # 7, 8

    @property
    def chinese(self) -> str:
        return {"fall": "秋季", "spring": "春季", "summer": "夏季"}[self.value]

    @property
    def term_num(self) -> int:
        """Term number used in TIS code: 1=Fall, 2=Spring, 3=Summer."""
        return {"fall": 1, "spring": 2, "summer": 3}[self.value]

    @classmethod
    def from_term_num(cls, n: int) -> "Season":
        """Alias of :meth:`from_int` — 1→FALL, 2→SPRING, 3→SUMMER."""
        return {1: cls.FALL, 2: cls.SPRING, 3: cls.SUMMER}[n]


class Semester:
    """
    Represents a SUSTech academic semester.

    TIS code structure (9 chars when dashes removed):
      [end_year 4digits][cohort_year 4digits][term 1digit]

      end_year    = calendar year the semester ENDS in
      cohort_year = the academic year label (Fall cohort = enrollment year)
      term        = 1(Fall), 2(Spring), 3(Summer)

    Examples:
      '2025-20262' → end=2025, cohort=2026, term=2 → Spring 2026  (Feb–Jul 2026)
      '2025-20261' → end=2025, cohort=2026, term=1 → Fall 2026    (Sep 2026–Jan 2027)
      '2025-20263' → end=2025, cohort=2026, term=3 → Summer 2026  (Jul–Aug 2026)

    Representations:
      tis       = '2025-20262'    (compact, for API calls)
      tis_human = '2025-2026-2'   (hyphenated)
      human     = '2026 Spring'   (English display, cohort year)
      xnxqmc    = '2025春季'      (Chinese display, the number is end_year)
    """
    __slots__ = ("cohort_year", "end_year", "season")

    def __init__(self, value: str | int, season: Season | None = None):
        """
        Construct from a TIS semester code string, or from (cohort_year, season).

        String value — parse as TIS code (compact or hyphenated):
            Semester("2025-20262")           → Spring 2026  (term 2)
            Semester("2025-20261")           → Fall 2026    (term 1)
            Semester("2025-20263")           → Summer 2026  (term 3)

        Integer value — cohort year, requires explicit season:
            Semester(2026, Season.SPRING)     → Spring 2026
            Semester(2026, Season.FALL)       → Fall 2026
        """
        if isinstance(value, str) and season is not None and isinstance(season, str):
            # Semester("2025-2026", "2") — xn + xq string pair
            self.end_year    = int(value[:4])
            self.cohort_year = int(value[5:9])
            self.season      = Season.from_int(int(season))
        elif isinstance(value, str):
            # "2025-20262" (9 digits, optional dashes) → end=2025, cohort=2026, term=2
            clean = value.replace("-", "")
            if len(clean) != 9 or not clean.isdigit():
                raise ValueError(f"Invalid TIS code: {value!r}")
            self.end_year    = int(clean[:4])
            self.cohort_year = int(clean[4:8])
            self.season      = Season.from_int(int(clean[8]))
        else:
            if season is None:
                raise TypeError(
                    f"Semester({value}) requires an explicit season. "
                    "Use Semester(year, Season.FALL) or Semester('2025-20262')"
                )
            self.cohort_year = int(value)
            self.season      = season
            self.end_year    = self.cohort_year + 1 if season is Season.FALL else self.cohort_year

    @classmethod
    def current(cls, _today=None) -> "Semester":
        """Build the academic semester active on a given date (default: today).

        Lets callers stop hardcoding a semester — ``Semester.current()`` returns
        the term that is live right now (SUSTech calendar), so commands query the
        correct term no matter when they run. ``_today`` is injectable for tests.

        Returns a ``Semester`` whose TIS code matches the live term:
            Fall   (starts Sep of year Y)  → code "Y-(Y+1)1"   e.g. "2026-20271"
            Spring (starts Feb of year Y)  → code "(Y-1)-Y2"   e.g. "2025-20262"
            Summer (starts Jul of year Y)  → code "(Y-1)-Y3"
        """
        from datetime import date as _date

        today = _today if _today is not None else _date.today()
        season = Season.from_months(today.month)
        if season is Season.FALL:
            # Fall of calendar year Y: end year = Y, cohort/label year = Y+1
            end = today.year
            cohort = today.year + 1
        else:  # SPRING / SUMMER belong to the academic year that began last autumn
            end = today.year - 1
            cohort = today.year
        return cls(Semester._code(end, cohort, season))

    @staticmethod
    def _code(end: int, cohort: int, season: "Season") -> str:
        """Build a 9-char TIS code from end/cohort/season."""
        return f"{end}-{cohort}{season.term_num}"

    @property
    def xn(self) -> str:
        """学年 — academic year like '2025-2026'."""
        return f"{self.end_year}-{self.cohort_year}"

    @property
    def xq(self) -> str:
        """学期 — '1' (Fall) / '2' (Spring) / '3' (Summer)."""
        return str(self.season.term_num)

    @property
    def tis(self) -> str:
        """TIS compact code for API calls, e.g. '2025-20262'."""
        return f"{self.end_year}-{self.cohort_year}{self.season.term_num}"

    @property
    def tis_human(self) -> str:
        """TIS hyphenated code for display, e.g. '2025-2026-2'."""
        return f"{self.end_year}-{self.cohort_year}-{self.season.term_num}"

    @property
    def human(self) -> str:
        """English display name, e.g. '2026 Spring' (cohort year)."""
        return f"{self.cohort_year} {self.season.name.capitalize()}"

    @property
    def xnxq(self) -> str:
        """TIS hyphenated code (API field name), e.g. '2025-2026-2'."""
        return self.tis_human

    @property
    def xnxqmc(self) -> str:
        """Chinese display name from TIS, e.g. '2025春季'."""
        return f"{self.end_year}{self.season.chinese}"

    def __repr__(self) -> str:
        return f"Semester({self.human}, tis={self.tis!r})"

    def __str__(self) -> str:
        return self.human

    def __eq__(self, other) -> bool:
        if not isinstance(other, Semester):
            return NotImplemented
        return self.tis == other.tis

    def __hash__(self) -> int:
        return hash(self.tis)


# -----------------------------------------------------------------------
# Question type enum
# -----------------------------------------------------------------------

