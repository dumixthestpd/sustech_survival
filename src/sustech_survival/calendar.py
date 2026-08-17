"""
sustech_survival.calendar — academic calendar with date intelligence.

Loads the SUSTech校历 (academic calendar) JSON and answers date↔position
questions:

  * Which teaching week is a given date in?
  * Which calendar date does (week, weekday) fall on?
  * Given a class meeting pattern, what are the actual meeting dates?
  * What day-type is a given date (holiday / break / final / makeup-class)?

The source of truth is JSON files in the GitHub-hosted
``sustech-calendar`` repo, fetched at runtime from ``raw.githubusercontent.com``.
Pass ``online=False`` to read from a local checkout when iterating on the JSON.

Levels (undergraduate vs graduate) are a parameter — the two groups have
different freshman-arrival dates; otherwise the semester schedule is identical.

The legacy TIS-code ``Semester`` class in ``sustech_survival.semester`` is
imported privately for the TIS-code translation API ("2025-20262" etc).
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Literal, Optional

from . import _cache
from .semester import Season, Semester as _TisSemester

__all__ = [
    "Season",
    "Weekday",
    "Parity",
    "Compensatory",
    "Holiday",
    "ClassTime",
    "Day",
    "Semester",
    "AcademicCalendar",
    "CalendarError",
    "DEFAULT_REPO",
]


# -- Type aliases ------------------------------------------------

Weekday = Literal[
    "Monday", "Tuesday", "Wednesday", "Thursday",
    "Friday", "Saturday", "Sunday",
]
Parity = Literal["odd", "even"]


WEEKDAY_INDEX: dict[Weekday, int] = {
    "Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3,
    "Friday": 4, "Saturday": 5, "Sunday": 6,
}
INDEX_WEEKDAY: tuple[Weekday, ...] = (
    "Monday", "Tuesday", "Wednesday", "Thursday",
    "Friday", "Saturday", "Sunday",
)


# -- Constants ---------------------------------------------------

# The academic-calendar source is override-able via the SUSTECH_CALENDAR_REPO
# env var (or per-call base_url= kwarg), so a user can point it at a local /
# private more-detailed calendar. The default is the GitHub-hosted
# sustech-calendar repo. Base excludes the trailing <year>.
DEFAULT_REPO_BASE = os.environ.get(
    "SUSTECH_CALENDAR_REPO",
    "https://raw.githubusercontent.com/dumixthestpd/sustech-calendar/main",
)
# Base URL with the year segment, kept for backward-compat (year substitution
# in load() uses DEFAULT_REPO_BASE; DEFAULT_REPO remains the 2026 default).
DEFAULT_REPO = f"{DEFAULT_REPO_BASE}/2026"
_LOCAL_REPO = os.environ.get("SUSTECH_CALENDAR_LOCAL_REPO")


class CalendarError(Exception):
    """Raised on any failure to load or parse the academic calendar."""


# -- Records ------------------------------------------------------


@dataclass(frozen=True)
class Compensatory:
    """One makeup-class day — a weekend or holiday designated as a teaching
    day to replace a class that was flushed by a holiday.

    Attributes:
        date:      the actual calendar date of the makeup
        week_type: which week parity the makeup class belongs to ("odd" or "even")
        workday:   which weekday the original (flushed) class met on
    """
    date: date
    week_type: Parity
    workday: Weekday

    @classmethod
    def from_dict(cls, d: dict) -> "Compensatory":
        return cls(
            date=date.fromisoformat(d["date"]),
            week_type=d["week_type"],
            workday=d["workday_type"],
        )


@dataclass(frozen=True)
class Holiday:
    """A national statutory holiday (date range)."""
    name: str
    start: date
    end: date

    @classmethod
    def from_dict(cls, d: dict) -> "Holiday":
        return cls(
            name=d["name"],
            start=date.fromisoformat(d["start"]),
            end=date.fromisoformat(d["end"]),
        )


@dataclass(frozen=True)
class ClassTime:
    """An enrolled class — its meeting pattern plus identifying metadata.

    Used both as the pattern source (weeks / weekday / periods) and as the
    identity carried into events (title / teacher / room).
    """
    weeks: tuple[int, ...]
    weekday: int                          # 0=Mon..6=Sun
    periods: tuple[int, ...]
    title: str = ""
    teacher: str = ""
    room: str = ""

    def matches_date(self, d: date, semester: "Semester") -> bool:
        """True if the class time pattern includes the given date."""
        if d.weekday() != self.weekday:
            return False
        week = semester.week_of(d)
        if week == 0:
            return False
        return week in self.weeks


# -- Day ----------------------------------------------------------


class Day:
    """Info about a single calendar day. No enum kind — just bool methods."""

    __slots__ = (
        "date", "week", "weekday", "semester",
        "holiday", "comp", "in_final_week", "in_midterm_week",
    )

    def __init__(
        self,
        *,
        date: date,
        week: int,
        weekday: Weekday,
        semester: Optional["Semester"],
        holiday: Optional[Holiday] = None,
        comp: Optional[Compensatory] = None,
        in_final_week: bool = False,
        in_midterm_week: bool = False,
    ):
        self.date = date
        self.week = week
        self.weekday = weekday
        self.semester = semester
        self.holiday = holiday
        self.comp = comp
        self.in_final_week = in_final_week
        self.in_midterm_week = in_midterm_week

    # -- Day-type predicates --------------------------------------

    def is_holiday(self) -> bool:
        return self.holiday is not None

    def is_compensatory(self) -> bool:
        return self.comp is not None

    def is_extra_break(self) -> bool:
        if self.semester is None:
            return False
        return self.date in self.semester.extra_breaks

    def is_final(self) -> bool:
        return self.in_final_week

    def is_midterm(self) -> bool:
        """True if this teaching day falls in a midterm-equivalent week."""
        return self.in_midterm_week and not self.is_holiday() \
               and not self.is_compensatory() and not self.is_final() \
               and not self.is_extra_break()

    def is_weekend(self) -> bool:
        return self.date.weekday() >= 5

    def is_teaching_day(self) -> bool:
        """True if regular classes meet (no holiday / final / break / weekend)."""
        if self.semester is None:
            return False
        if self.is_holiday() or self.is_compensatory():
            return False
        if self.is_final() or self.is_extra_break():
            return False
        if self.is_weekend():
            return False
        return True

    def has_class(self) -> bool:
        """True if classes meet today — either a regular teaching day or a
        compensatory day (transferred classes run)."""
        return self.is_teaching_day() or self.is_compensatory()

    # -- Schedule for this day ------------------------------------

    @property
    def schedule(self) -> list[ClassTime]:
        """Classes meeting on this day.

        On a compensatory day: returns the transferred classes (those whose
        pattern matched the nearest flushed holiday).
        On a holiday / final / break: returns [].
        On a regular teaching day: returns the classes whose pattern matches.
        """
        if self.semester is None:
            return []
        if self.is_holiday() or self.is_final() or self.is_extra_break():
            return []
        if self.is_compensatory() and self.comp is not None:
            nearest = self.semester._holiday_for(self.comp)
            if nearest is None:
                return []
            return [
                c for c in self.semester.classes
                if c.matches_date(nearest, self.semester)
            ]
        return [
            c for c in self.semester.classes
            if c.matches_date(self.date, self.semester)
        ]

    # -- Human-readable ------------------------------------------

    def __str__(self) -> str:
        parts = [self.date.isoformat(), self.weekday]
        if self.week > 0:
            parts.append(f"Week {self.week}")
        if self.semester is not None:
            parts.append(self.semester.human)
        notes: list[str] = []
        if self.is_holiday() and self.holiday is not None:
            notes.append(f"({self.holiday.name})")
        if self.is_compensatory():
            notes.append("(makeup-class day)")
        if self.is_extra_break():
            notes.append("(school break)")
        if self.is_final():
            notes.append("(finals)")
        if self.is_midterm():
            notes.append("(midterm)")
        if notes:
            parts.append(" ".join(notes))
        return " — ".join(parts)

    def __repr__(self) -> str:
        return f"Day({self!s})"


# -- Semester ----------------------------------------------------


class Semester:
    """A SUSTech academic semester — date intelligence + enrolled classes.

    Wraps the legacy TIS-code ``Semester`` for the code-translation API
    (``tis``, ``tis_human``, ``human``, ``xn``, ``xq``) and adds the
    date↔position layer plus enrolled-class management.
    """

    __slots__ = (
        "_tis", "level",
        "teaching_start", "teaching_end", "sign_in", "freshman_arrival",
        "total_teaching_weeks",
        "midterm_start", "midterm_end", "midterm_weeks",
        "final_start", "final_end", "final_weeks",
        "compensatories", "extra_breaks",
        "classes", "_calendar",
    )

    def __init__(
        self,
        *,
        tis: _TisSemester,
        level: str,
        teaching_start: date,
        teaching_end: date,
        sign_in: date,
        freshman_arrival: Optional[date],
        total_teaching_weeks: int,
        midterm_start: date,
        midterm_end: date,
        midterm_weeks: list[int],
        final_start: date,
        final_end: date,
        final_weeks: list[int],
        compensatories: list[Compensatory],
        extra_breaks: list[date],
    ):
        object.__setattr__(self, "_tis", tis)
        object.__setattr__(self, "level", level)
        object.__setattr__(self, "teaching_start", teaching_start)
        object.__setattr__(self, "teaching_end", teaching_end)
        object.__setattr__(self, "sign_in", sign_in)
        object.__setattr__(self, "freshman_arrival", freshman_arrival)
        object.__setattr__(self, "total_teaching_weeks", total_teaching_weeks)
        object.__setattr__(self, "midterm_start", midterm_start)
        object.__setattr__(self, "midterm_end", midterm_end)
        object.__setattr__(self, "midterm_weeks", set(midterm_weeks))
        object.__setattr__(self, "final_start", final_start)
        object.__setattr__(self, "final_end", final_end)
        object.__setattr__(self, "final_weeks", set(final_weeks))
        object.__setattr__(self, "compensatories", compensatories)
        object.__setattr__(self, "extra_breaks", set(extra_breaks))
        object.__setattr__(self, "classes", [])
        object.__setattr__(self, "_calendar", None)

    # -- Identity -------------------------------------------------

    @property
    def season(self) -> Season:
        return self._tis.season

    @property
    def tis(self) -> str:
        return self._tis.tis

    @property
    def tis_human(self) -> str:
        return self._tis.tis_human

    @property
    def human(self) -> str:
        return self._tis.human

    @property
    def xn(self) -> str:
        return self._tis.xn

    @property
    def xq(self) -> str:
        return self._tis.xq

    @property
    def calendar(self) -> Optional["AcademicCalendar"]:
        return self._calendar

    @calendar.setter
    def calendar(self, value: "AcademicCalendar") -> None:
        object.__setattr__(self, "_calendar", value)

    # -- Date math -------------------------------------------------

    def date_of(self, week: int, weekday: int) -> date:
        """The calendar date for (week, weekday). weekday: 0=Mon..6=Sun.

        Anchored on the Monday on or before ``teaching_start`` — week 1
        always starts on a Monday, even if teaching actually begins
        mid-week (e.g. Wednesday).
        """
        max_week = self.total_teaching_weeks + (
            max(self.final_weeks) if self.final_weeks else 0
        )
        if not (1 <= week <= max_week):
            raise CalendarError(
                f"week {week} out of range for {self.human} (valid: 1..{max_week})"
            )
        if not (0 <= weekday <= 6):
            raise CalendarError(f"weekday must be 0..6, got {weekday}")
        teaching_monday = self.teaching_start - timedelta(
            days=self.teaching_start.weekday()
        )
        return teaching_monday + timedelta(days=7 * (week - 1) + weekday)

    def week_of(self, d: date) -> int:
        """1-indexed teaching week. 0 if outside the semester.

        Anchored on the Monday on or before ``teaching_start`` — week 1
        always starts on a Monday, even if teaching actually begins
        mid-week (e.g. Wednesday).
        """
        if not self.is_in_semester(d):
            return 0
        teaching_monday = self.teaching_start - timedelta(
            days=self.teaching_start.weekday()
        )
        return ((d - teaching_monday).days // 7) + 1

    def is_in_semester(self, d: date) -> bool:
        return self.sign_in <= d <= self.final_end

    def __contains__(self, d: date) -> bool:
        return self.is_in_semester(d)

    # -- Day lookup ------------------------------------------------

    def day(self, d: Optional[date] = None) -> Day:
        """Return Day for date (defaults to today, local date)."""
        if d is None:
            d = datetime.now().date()
        return self._build_day(d)

    def _build_day(self, d: date) -> Day:
        week = self.week_of(d)
        weekday = INDEX_WEEKDAY[d.weekday()]
        holiday = self._holiday_at(d)
        comp = self._compensatory_at(d)
        in_final = (week in self.final_weeks) if week > 0 else False
        in_midterm = (week in self.midterm_weeks) if week > 0 else False
        return Day(
            date=d, week=week, weekday=weekday, semester=self,
            holiday=holiday, comp=comp,
            in_final_week=in_final, in_midterm_week=in_midterm,
        )

    def _holiday_at(self, d: date) -> Optional[Holiday]:
        if self.calendar is None:
            return None
        for h in self.calendar.holidays:
            if h.start <= d <= h.end:
                return h
        return None

    def _compensatory_at(self, d: date) -> Optional[Compensatory]:
        for c in self.compensatories:
            if c.date == d:
                return c
        return None

    # -- Class management -----------------------------------------

    def fill(self, class_time: ClassTime) -> bool:
        """Register an enrolled class. Returns True on success.

        Returns False if the class is a duplicate (already in
        ``self.classes``) or if no meeting dates could be computed (e.g. all
        weeks outside the semester, or all dates flushed without a
        compensatory replacement).
        """
        if any(c == class_time for c in self.classes):
            return False
        dates = self._compute_dates(class_time)
        if not dates:
            return False
        self.classes.append(class_time)
        return True

    def dates(self, class_time: ClassTime) -> list[date]:
        """Actual meeting dates for an enrolled class.

        Algorithm: for each (week, weekday) in the pattern, compute the
        natural date. If it's a teaching day, include it. If it's a
        holiday/break/final, look up the compensatory day that replaces it
        and include that instead. If no compensatory exists, the occurrence
        is dropped. Compensatory dates themselves are not produced by this
        method — they are only produced as a transfer target.
        """
        return self._compute_dates(class_time)

    def _compute_dates(self, class_time: ClassTime) -> list[date]:
        """Compute the actual meeting dates for an enrolled class.

        Uses ``Day`` predicates directly (no enum/string classification):

        - Out-of-semester, weekend, and compensatory dates are skipped as
          natural sources — they're never the "where would this meeting fall"
          answer to the pattern.
        - Flushed dates (holiday / extra_break / final) are looked up for a
          compensatory replacement; if none exists, the occurrence is dropped.
        - Otherwise (midterm or teaching day) the natural date is included.
        """
        weekday = class_time.weekday
        weekday_name = INDEX_WEEKDAY[weekday]
        out: list[date] = []
        for week in class_time.weeks:
            try:
                d = self.date_of(week, weekday)
            except CalendarError:
                continue
            if not self.is_in_semester(d):
                continue
            if d.weekday() >= 5:
                continue  # weekend — not a teaching source
            if self._compensatory_at(d) is not None:
                continue  # compensatory is a transfer target, not a source
            day = self._build_day(d)
            if day.is_holiday() or day.is_final() or day.is_extra_break():
                parity: Parity = "odd" if week % 2 == 1 else "even"
                comp = self._comp_for_flushed(d, parity, weekday_name)
                if comp is not None:
                    out.append(comp.date)
            elif day.is_midterm() or day.is_teaching_day():
                out.append(d)
            # else: dropped (no predicate matched — defensive, shouldn't
            # happen for a well-formed semester + JSON)
        return sorted(set(out))

    # -- Compensatory lookups --------------------------------------

    def _holiday_for(self, comp: Compensatory) -> Optional[date]:
        """For a compensatory day, find the holiday date that flushed the
        same (week_type, workday). Returns the actual flushed date, not the
        holiday range. None if no holiday flushed this day-type."""
        if self.calendar is None:
            return None
        wi = WEEKDAY_INDEX[comp.workday]
        candidates: list[date] = []
        for h in self.calendar.holidays:
            n_days = (h.end - h.start).days + 1
            for offset in range(n_days):
                d = h.start + timedelta(days=offset)
                if d.weekday() != wi:
                    continue
                w = self.week_of(d)
                if w == 0:
                    continue
                if ("odd" if w % 2 == 1 else "even") != comp.week_type:
                    continue
                candidates.append(d)
        if not candidates:
            return None
        forward = sorted(d for d in candidates if d <= comp.date)
        backward = sorted(d for d in candidates if d > comp.date)
        return forward[-1] if forward else (backward[0] if backward else None)

    def _comp_for_flushed(
        self, flushed_date: date, parity: Parity, workday: Weekday,
    ) -> Optional[Compensatory]:
        """Inverse of _holiday_for: which compensatory day replaces this
        flushed date?"""
        candidates = [
            c for c in self.compensatories
            if c.week_type == parity
            and c.workday == workday
            and self._holiday_for(c) == flushed_date
        ]
        if not candidates:
            return None
        forward = sorted(
            (c for c in candidates if c.date >= flushed_date),
            key=lambda c: c.date,
        )
        return forward[0] if forward else max(candidates, key=lambda c: c.date)

    # -- Construction ---------------------------------------------

    @classmethod
    def from_payload(cls, payload: dict, level: str) -> "Semester":
        if "teaching_start" not in payload:
            raise CalendarError(f"payload missing 'teaching_start': {payload}")
        ts = date.fromisoformat(payload["teaching_start"])
        season = Season.SPRING if ts.month <= 7 else Season.FALL
        tis = _TisSemester(ts.year, season)
        sign_in = date.fromisoformat(payload["sign_in"])
        final_end = date.fromisoformat(payload["final"]["end"])
        teaching_end = _last_teaching_day(payload, ts, final_end)
        return cls(
            tis=tis,
            level=level,
            teaching_start=ts,
            teaching_end=teaching_end,
            sign_in=sign_in,
            freshman_arrival=(
                date.fromisoformat(payload["freshman_arrival"])
                if "freshman_arrival" in payload else None
            ),
            total_teaching_weeks=int(payload["total_teaching_weeks"]),
            midterm_start=date.fromisoformat(payload["midterm"]["start"]),
            midterm_end=date.fromisoformat(payload["midterm"]["end"]),
            midterm_weeks=list(payload["midterm"]["equivalent_weeks"]),
            final_start=date.fromisoformat(payload["final"]["start"]),
            final_end=final_end,
            final_weeks=list(payload["final"]["equivalent_weeks"]),
            compensatories=[
                Compensatory.from_dict(c)
                for c in payload.get("compensatories", [])
            ],
            extra_breaks=[
                date.fromisoformat(d) for d in payload.get("extra_breaks", [])
            ],
        )

    def __repr__(self) -> str:
        return f"Semester({self.human!r}, level={self.level!r})"


def _last_teaching_day(payload: dict, teaching_start: date, final_end: date) -> date:
    """Sunday of the last regular teaching week — the day before finals start.

    Anchored on the Monday on or before ``teaching_start``, so weeks are
    Monday-aligned (matching ``Semester.date_of``).
    """
    final_weeks = sorted(int(w) for w in payload["final"]["equivalent_weeks"])
    first_final_week = final_weeks[0]
    last_teaching_week = first_final_week - 1
    if last_teaching_week < 1:
        # Final starts in week 1 — no teaching days at all.
        return teaching_start - timedelta(days=1)
    teaching_monday = teaching_start - timedelta(days=teaching_start.weekday())
    last_day = teaching_monday + timedelta(days=7 * (last_teaching_week - 1) + 6)
    # Bound by final.end (final exams can't extend past teaching's start).
    return min(last_day, final_end - timedelta(days=1))


# -- AcademicCalendar ---------------------------------------------


class AcademicCalendar:
    """A year's calendar: spring + fall (+ summer if present) + national holidays.

    Levels:
      * "undergraduate" — uses undergraduate.json
      * "graduate"      — uses graduate.json

    Both levels share general.json (national holidays + compensatory workdays).
    """

    __slots__ = ("year", "level", "spring", "fall", "summer", "holidays")

    def __init__(
        self,
        *,
        year: int,
        level: str,
        spring: Semester,
        fall: Semester,
        summer: Optional[Semester],
        holidays: list[Holiday],
    ):
        if level not in ("undergraduate", "graduate"):
            raise CalendarError(
                f"level must be 'undergraduate' or 'graduate', got {level!r}"
            )
        object.__setattr__(self, "year", year)
        object.__setattr__(self, "level", level)
        object.__setattr__(self, "spring", spring)
        object.__setattr__(self, "fall", fall)
        object.__setattr__(self, "summer", summer)
        object.__setattr__(self, "holidays", holidays)
        spring.calendar = self
        fall.calendar = self
        if summer is not None:
            summer.calendar = self

    def day(self, d: Optional[date] = None) -> Day:
        """Day for a given date. If date is between semesters, returns a Day
        with semester=None (week=0)."""
        if d is None:
            d = datetime.now().date()
        if self.spring.is_in_semester(d):
            return self.spring._build_day(d)
        if self.fall.is_in_semester(d):
            return self.fall._build_day(d)
        if self.summer is not None and self.summer.is_in_semester(d):
            return self.summer._build_day(d)
        weekday = INDEX_WEEKDAY[d.weekday()]
        return Day(date=d, week=0, weekday=weekday, semester=None)

    @classmethod
    def load(
        cls,
        year: int,
        level: str = "undergraduate",
        *,
        online: bool = True,
        cached: bool = True,
        refresh: bool = False,
        base_url: str = DEFAULT_REPO,
        cache_root: Optional[Path] = None,
    ) -> "AcademicCalendar":
        """Load the academic calendar for the given year.

        ``level``: "undergraduate" or "graduate".
        ``online``:  True (default) reads from GitHub raw.
                     False reads from a local checkout of the calendar
                     repo — set ``$SUSTECH_CALENDAR_LOCAL_REPO`` to its
                     root path; useful when iterating on the JSON.
                     When ``online=False`` the cache is not consulted,
                     and ``$SUSTECH_CALENDAR_LOCAL_REPO`` must be set.
        ``cached``:  (only when ``online=True``) consult and update the
                     on-disk cache under the unified cache root
                     (``<cwd>/__sustech_cache__/calendar/{year}/`` —
                     override via ``SUSTECH_CACHE_DIR`` or ``cache_root=``).
                     Set ``cached=False`` for one-shot loads that should
                     never touch the disk (e.g. tests).
        ``refresh``: (only when ``online=True``) ignore any cached ETag and
                     always re-download, overwriting the cache. Use this
                     after upstream publishes a fix you want immediately,
                     or if your local cache has somehow drifted.
        ``base_url``: override the GitHub raw base URL (forks, mirrors).
        ``cache_root``: explicit cache root for the per-year JSON cache
            (default: the unified ``__sustech_cache__`` dir; pass a Path to
            isolate tests or point at a custom location).

        Cache behaviour in detail:
          * First load (no cache): downloads all three JSONs, saves them
            under ``{cache_root}/calendar/{year}/`` with a ``.meta.json``
            containing the server's ETag, fetched timestamp, source URL,
            and SHA-1.
          * Subsequent loads: sends ``If-None-Match`` per file. 304 means
            the cached copy is still fresh; 200 means the body is new and
            gets rewritten to disk.
          * Network failure with valid cache: falls back to the cached
            copy rather than raising — the whole point of caching is
            resilience.
        """
        from pathlib import Path as _Path
        if cache_root is not None:
            cache_root = _Path(cache_root)
        if level not in ("undergraduate", "graduate"):
            raise CalendarError(
                f"level must be 'undergraduate' or 'graduate', got {level!r}"
            )
        # Substitute year-specific URL when caller used DEFAULT_REPO —
        # otherwise load(2027) silently fetches DEFAULT_REPO's 2026.
        if base_url == DEFAULT_REPO:
            base_url = f"{DEFAULT_REPO_BASE}/{year}"

        # A local path base (the base_url= kwarg / SUSTECH_CALENDAR_REPO env
        # may point at a local mirror) is read straight off disk — no HTTP/ETag.
        _is_local = (not str(base_url).startswith(("http://", "https://")))
        if _is_local and online:
            _local_root = str(_Path(base_url) / str(year))
            ug = _read_json(f"{_local_root}/undergraduate.json")
            gr = _read_json(f"{_local_root}/graduate.json")
            ge = _read_json(f"{_local_root}/general.json")
        elif online:
            ug = _fetch_json_cached(year, "undergraduate.json", base_url,
                                    cached=cached, refresh=refresh,
                                    cache_root=cache_root)
            gr = _fetch_json_cached(year, "graduate.json", base_url,
                                    cached=cached, refresh=refresh,
                                    cache_root=cache_root)
            ge = _fetch_json_cached(year, "general.json", base_url,
                                    cached=cached, refresh=refresh,
                                    cache_root=cache_root)
        else:
            if not _LOCAL_REPO:
                raise CalendarError(
                    "online=False requires $SUSTECH_CALENDAR_LOCAL_REPO to be set "
                    "to the root of a local sustech-calendar checkout"
                )
            ug = _read_json(f"{_LOCAL_REPO}/{year}/undergraduate.json")
            gr = _read_json(f"{_LOCAL_REPO}/{year}/graduate.json")
            ge = _read_json(f"{_LOCAL_REPO}/{year}/general.json")
        sem_payload = ug if level == "undergraduate" else gr
        spring = Semester.from_payload(sem_payload["spring_semester"], level)
        fall = Semester.from_payload(sem_payload["fall_semester"], level)
        # Summer may be a minimal entry with only start/end (no teaching
        # structure). Treat as None unless it has teaching_start.
        summer_payload = sem_payload.get("summer_semester")
        if summer_payload and "teaching_start" in summer_payload:
            summer = Semester.from_payload(summer_payload, level)
        else:
            summer = None
        return cls(
            year=year, level=level,
            spring=spring, fall=fall, summer=summer,
            holidays=[Holiday.from_dict(h) for h in ge["holidays"]],
        )

    @classmethod
    def refresh(
        cls,
        year: int,
        level: str = "undergraduate",
        *,
        base_url: str = DEFAULT_REPO,
    ) -> "AcademicCalendar":
        """Force a fresh download and overwrite the cache.

        Equivalent to ``load(year, level, refresh=True)`` — convenient when
        you know upstream has changed and don't want to wait for the ETag
        round-trip.
        """
        return cls.load(year, level, online=True, cached=True,
                        refresh=True, base_url=base_url)

    @classmethod
    def from_payloads(
        cls,
        year: int,
        level: str,
        *,
        undergraduate: dict,
        graduate: dict,
        general: dict,
    ) -> "AcademicCalendar":
        """Construct from dicts in hand. Used by tests.

        Validates that the loaded payload's dates fall within the requested
        ``year`` — catches the bug where a custom ``base_url`` points to
        a different year's directory but the caller requested another year.
        """
        # Year guard — defense in depth against wrong-year substitution
        # (DEFAULT_REPO silent fallback, custom base_url drift, etc.).
        for h in general.get("holidays", []):
            for key in ("start", "end"):
                if key in h:
                    d_year = date.fromisoformat(h[key]).year
                    if d_year != year:
                        raise CalendarError(
                            f"holiday {h.get('name', '?')!r} {key}={h[key]} "
                            f"is in {d_year}, expected {year}"
                        )
        for comp_date in general.get("compensatory_workdays", []):
            d_year = date.fromisoformat(comp_date).year
            if d_year != year:
                raise CalendarError(
                    f"compensatory_workday {comp_date} is in {d_year}, "
                    f"expected {year}"
                )
        sem_payload = undergraduate if level == "undergraduate" else graduate
        spring = Semester.from_payload(sem_payload["spring_semester"], level)
        fall = Semester.from_payload(sem_payload["fall_semester"], level)
        summer_payload = sem_payload.get("summer_semester")
        if summer_payload and "teaching_start" in summer_payload:
            summer = Semester.from_payload(summer_payload, level)
        else:
            summer = None
        return cls(
            year=year, level=level,
            spring=spring, fall=fall, summer=summer,
            holidays=[Holiday.from_dict(h) for h in general["holidays"]],
        )

    def __repr__(self) -> str:
        return f"AcademicCalendar(year={self.year}, level={self.level!r})"


# -- Internal helpers ----------------------------------------------


# Cache schema for the per-year ``.meta.json`` sidecar.
_META_FILENAME = ".meta.json"


def _meta_path(year: int, cache_root: Optional[Path] = None) -> Path:
    """``<cache_root>/calendar/{year}/.meta.json``."""
    return _cache.cache_path("calendar", str(year), _META_FILENAME, root=cache_root)


def _payload_path(year: int, filename: str, cache_root: Optional[Path] = None) -> Path:
    """``<cache_root>/calendar/{year}/{filename}``."""
    return _cache.cache_path("calendar", str(year), filename, root=cache_root)


def _load_meta(year: int, cache_root: Optional[Path] = None) -> dict:
    """Read the per-year meta sidecar; empty dict if missing/corrupt."""
    return _cache.load_json(_meta_path(year, cache_root)) or {}


def _save_meta(year: int, meta: dict, cache_root: Optional[Path] = None) -> None:
    """Write the per-year meta sidecar atomically."""
    _cache.save_json(_meta_path(year, cache_root), meta)


def _fetch_json_cached(
    year: int,
    filename: str,
    base_url: str,
    *,
    cached: bool,
    refresh: bool,
    cache_root: Optional[Path] = None,
) -> dict:
    """Fetch one JSON, honouring the per-year cache and ETag.

    Logic:
      * ``cached=False`` → plain GET, no disk touch. (Used by tests.)
      * ``refresh=True`` → always GET, overwrite cache unconditionally.
      * Otherwise:
          - If the cached file exists, read its ETag from meta and
            send ``If-None-Match``. 304 → use cached body; 200 → save new
            body and update meta.
          - If no cache exists, GET, save body and meta.

    ``cache_root``: explicit cache root (default: the unified
    ``__sustech_cache__`` dir via :func:`sustech_survival._cache.tmp_root`).

    Network failures with a valid cached copy fall back to the cached
    body — that's the whole point of caching for resilience.
    """
    url = f"{base_url}/{filename}"
    target = _payload_path(year, filename, cache_root)

    if not cached:
        return _fetch_json(url)

    meta = _load_meta(year, cache_root)
    cached_etag = None if refresh else meta.get("files", {}).get(filename, {}).get("etag")

    try:
        body, new_etag, status = _cache.http_get_with_etag(url, cached_etag)
    except urllib.error.HTTPError as e:
        # 404 specifically means "the URL doesn't exist NOW". Don't fall
        # back to the cache for that — the cache may be poisoned from a
        # prior buggy call (e.g. the old hardcoded-2026 DEFAULT_REPO
        # silently wrote 2026 data under tmp/calendar/{year}/).
        if e.code == 404:
            raise CalendarError(f"{url}: HTTP {e.code}") from e
        raise CalendarError(f"{url}: HTTP {e.code} {e.reason}") from e
    except Exception as e:
        # Other (non-HTTP) network failure — fall back to cache if we have it.
        cached_body = _cache.load_json(target)
        if cached_body is not None:
            return cached_body
        raise CalendarError(f"failed to fetch {url}: {e}") from e

    if status == 304:
        # Server says our cached copy is fresh — body unchanged on disk.
        cached_body = _cache.load_json(target)
        if cached_body is None:
            # 304 but no body on disk — shouldn't happen, but re-download
            # to recover rather than blow up.
            body, new_etag, status = _cache.http_get_with_etag(url, None)
            return _decode_and_cache(year, filename, body, new_etag, url,
                                     cache_root=cache_root)
        # Refresh the fetched_at timestamp so we can see when we last
        # successfully validated.
        meta.setdefault("files", {}).setdefault(filename, {})["fetched_at"] = (
            datetime.now(timezone.utc).isoformat()
        )
        _save_meta(year, meta, cache_root)
        return cached_body

    # status == 200 (or anything else that returned a body) — cache it.
    return _decode_and_cache(year, filename, body, new_etag, url,
                             cache_root=cache_root)


def _decode_and_cache(
    year: int,
    filename: str,
    body: bytes | None,
    etag: str | None,
    source_url: str,
    *,
    cache_root: Optional[Path] = None,
) -> dict:
    """Decode a response body, persist to cache + meta, return parsed dict."""
    if body is None:
        raise CalendarError(f"no body from {source_url}")
    try:
        data = json.loads(body)
    except json.JSONDecodeError as e:
        raise CalendarError(f"invalid JSON from {source_url}: {e}") from e
    target = _payload_path(year, filename, cache_root)
    _cache.save_json(target, data)
    meta = _load_meta(year, cache_root)
    meta.setdefault("year", year)
    meta.setdefault("source_url", source_url.rsplit("/", 1)[0])
    meta.setdefault("files", {})[filename] = {
        "etag": etag,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "sha1": _cache.sha1_bytes(body),
        "size": len(body),
    }
    _save_meta(year, meta, cache_root)
    return data


def _fetch_json(url: str) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            data = resp.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise CalendarError(f"{url}: HTTP {e.code}") from e
        raise CalendarError(f"{url}: HTTP {e.code} {e.reason}") from e
    except Exception as e:
        raise CalendarError(f"failed to fetch {url}: {e}") from e
    try:
        return json.loads(data)
    except json.JSONDecodeError as e:
        raise CalendarError(f"invalid JSON from {url}: {e}") from e


def _read_json(path: str) -> dict:
    import os
    if not os.path.exists(path):
        raise CalendarError(f"calendar file not found: {path}")
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise CalendarError(f"failed to read {path}: {e}") from e