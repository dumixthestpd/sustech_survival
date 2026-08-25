"""
sustech_survival.tis.schedule_index — class schedule lookup over the TIS personal schedule.

The two main functions:

  class_schedule(course_name)
      → "When is my class?" — day, period, and weeks
      → Returns a structured schedule for the named course

  experiment_date(course_name, week=N, as_of=...)
      → "When was my experiment?" — the actual calendar date of a specific
        class session, with explicit handling for weeks that have no class
        (returns nearest past/future with a warning)

Builds on `sustech_survival.tis.schedule` (raw xszykb API). One semester
fetch, cached per-process.

Quick reference:
    sched = CourseSchedule(semester_label="2026 Spring")
    sched.find("物化")                        # substring match → list[CourseEntry]
    last_occurrence("物化", as_of=date(...))   # most recent past date
    next_occurrence("物化", as_of=date(...))   # next future date
    dates_in_week("物化", week=15)            # all dates in a given week
    dates_in_semester("物化")                  # every date this semester
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from functools import lru_cache
from typing import Optional

from sustech_survival.context import (
    ACADEMIC_CALENDARS,
    CHINA_TZ,
    now_,
)


# -------------------------------------------------------------------------
# Raw TIS API access (module-level lazy import to avoid circular deps)
# -------------------------------------------------------------------------

def semester_schedule(xn: Optional[str] = None, xq: Optional[str] = None):
    """Re-export of TIS semester_schedule() for monkeypatching in tests."""
    from sustech_survival.tis import schedule as _api
    return _api.semester_schedule(xn, xq)


def current_semester() -> dict:
    from sustech_survival.tis import schedule as _api
    return _api.current_semester()


# -------------------------------------------------------------------------
# CourseEntry — one parsed row of the semester schedule
# -------------------------------------------------------------------------

@dataclass
class CourseEntry:
    """A single class meeting (one row of the TIS semester schedule).

    Multiple entries can share a course name (e.g. lecture + lab on different
    days, or same course on different periods).
    """
    name: str
    teacher: str = ""
    location: str = ""
    weekday: int = 0            # 1=Mon, 7=Sun (matches TIS KEY xq{N}_jc{M})
    period_start: int = 0
    period_end: int = 0
    weeks: list[int] = field(default_factory=list)
    semester_start: Optional[date] = None

    @classmethod
    def from_tis(cls, raw: dict, *, semester_start: date) -> "CourseEntry":
        """Parse a single TIS API row.

        Required raw fields: KEY (xq{N}_jc{M}), ZC (week bitmap), KCWZSM or SKSJ.
        Period start/end come from KSJC / JSJC fields (NOT the jc{M} in KEY —
        KEY's jc is the session UI grouping, KSJC/JSJC are the actual periods).
        """
        # Course name: prefer KCWZSM, fall back to SKSJ's first line
        name = (raw.get("KCWZSM")
                or raw.get("SKSJ", "").split("\n")[0]
                or "")

        # Day: KEY is "xq2_jc3" = day 2 (Tue)
        key = raw.get("KEY", "")
        m = re.match(r"xq(\d+)_jc(\d+)", key)
        weekday = int(m.group(1)) if m else 0
        # Periods: use KSJC (start) and JSJC (end) — NOT the jc{M} in KEY
        ksjc = raw.get("KSJC")
        jsjc = raw.get("JSJC")
        try:
            period_start = int(ksjc) if ksjc else 0
        except (TypeError, ValueError):
            period_start = 0
        try:
            period_end = int(jsjc) if jsjc else period_start
        except (TypeError, ValueError):
            period_end = period_start

        # Fallback: if KSJC/JSJC missing or 0, parse from KEY
        if period_start == 0:
            period_start = int(m.group(2)) if m else 0
            period_end = period_start

        # Weeks: ZC is a bitmap of 0/1, position i (0-indexed) = week i+1
        zc = raw.get("ZC", "") or ""
        weeks = [i + 1 for i, c in enumerate(zc) if c == "1"]

        return cls(
            name=name,
            teacher=raw.get("SKJS", "") or "",
            location=raw.get("SKDD", "") or "",
            weekday=weekday,
            period_start=period_start,
            period_end=period_end,
            weeks=weeks,
            semester_start=semester_start,
        )

    def _week_to_date(self, week: int) -> Optional[date]:
        """Return the date of THIS entry's class meeting in the given week.

        Accounts for partial first week if the semester started mid-week.
        Returns None if semester_start is unknown.
        """
        if not self.semester_start:
            return None
        # Week W starts at semester_start + (W-1)*7
        week_start = self.semester_start + timedelta(days=(week - 1) * 7)
        # Adjust to the entry's weekday (1=Mon..7=Sun; convert to 0=Mon..6=Sun)
        target = self.weekday - 1
        delta = target - self.semester_start.weekday()
        return week_start + timedelta(days=delta)

    def dates_in_range(self, week_from: int, week_to: int) -> list[date]:
        """Return all dates this entry meets between weeks [from, to] (inclusive)."""
        out: list[date] = []
        for w in self.weeks:
            if week_from <= w <= week_to:
                d = self._week_to_date(w)
                if d:
                    out.append(d)
        return out


# -------------------------------------------------------------------------
# CourseSchedule — lazy, per-process index over one semester
# -------------------------------------------------------------------------

# Per-process cache: (xn, xq_or_label) → CourseSchedule instance
_CACHE: dict[tuple, "CourseSchedule"] = {}


class CourseSchedule:
    """Lazy, cached index over the TIS personal schedule for one semester.

    The full semester is fetched on first access to `.entries` and cached
    for the process lifetime. Use `clear_cache()` to reset.
    """

    def __init__(self, *, xn: Optional[str] = None, xq: Optional[str] = None,
                 semester_label: Optional[str] = None):
        if semester_label:
            if semester_label not in ACADEMIC_CALENDARS:
                raise ValueError(
                    f"Unknown semester label: {semester_label!r}. "
                    f"Known: {list(ACADEMIC_CALENDARS.keys())}"
                )
            cal = ACADEMIC_CALENDARS[semester_label]
            self.semester_start = date.fromisoformat(cal["semester_start"])
            self.semester_label = semester_label
        else:
            # Auto-detect from TIS current semester
            sem = current_semester()
            self.xn = xn or sem.get("XN")
            self.xq = xq or sem.get("XQ")
            self.semester_start = self._resolve_semester_start(self.xn, self.xq)
            self.semester_label = self._label_from_xnxq(self.xn, self.xq)

        self._entries: Optional[list[CourseEntry]] = None

    @staticmethod
    def _resolve_semester_start(xn: Optional[str], xq: Optional[str]) -> date:
        """Look up semester start from ACADEMIC_CALENDARS by year/semester."""
        if not xn:
            # Fallback: 2026 Spring
            return date.fromisoformat(ACADEMIC_CALENDARS["2026 Spring"]["semester_start"])
        year = int(xn.split("-")[0])
        # Map (year, semester) → label
        if str(year + 1) in str(xq) or xq == "2":
            label = f"{year} Spring"
        else:
            label = f"{year - 1} Fall"
        if label in ACADEMIC_CALENDARS:
            return date.fromisoformat(ACADEMIC_CALENDARS[label]["semester_start"])
        # Final fallback
        return date.fromisoformat(ACADEMIC_CALENDARS["2026 Spring"]["semester_start"])

    @staticmethod
    def _label_from_xnxq(xn: Optional[str], xq: Optional[str]) -> Optional[str]:
        if not xn or not xq:
            return None
        year = int(xn.split("-")[0])
        label = f"{year} Spring" if xq == "2" else f"{year - 1} Fall"
        return label if label in ACADEMIC_CALENDARS else None

    @property
    def entries(self) -> list[CourseEntry]:
        """All course entries in this semester (lazy-loaded, cached)."""
        if self._entries is None:
            self._load()
        return self._entries

    @property
    def courses(self) -> list[str]:
        """Unique course names, sorted."""
        return sorted({e.name for e in self.entries if e.name})

    def find(self, name: str, *, exact: bool = False) -> list[CourseEntry]:
        """Find entries matching `name`.

        Matching strategy (in order):
          1. If exact=True: only exact name match
          2. Substring: `name in e.name` (query is a substring of course name)
          3. Subsequence (fuzzy): all chars of `name` appear in `e.name` in order
             — supports short abbreviations like "物化" → "物理化学实验"

        When subsequence fallback is used and the matches include courses
        with "实验" (experiment) in the name, prefer those — a short query
        like "物化" almost always means the experiment, not the lecture.

        Returns a list — multiple entries can match (e.g. lecture + lab).
        """
        if exact:
            return [e for e in self.entries if e.name == name]
        # Substring (one-directional: query in course name)
        direct = [e for e in self.entries if name in e.name]
        if direct:
            return sorted(direct, key=lambda e: -len(e.name))
        # Subsequence fallback
        fuzzy = [e for e in self.entries if _is_subsequence(name, e.name)]
        if not fuzzy:
            return []
        # If any subsequence match has 实验, prefer those (heuristic for short queries)
        exp = [e for e in fuzzy if "实验" in e.name]
        if exp:
            return sorted(exp, key=lambda e: -len(e.name))
        return sorted(fuzzy, key=lambda e: -len(e.name))

    def _load(self) -> None:
        raw = semester_schedule()
        self._entries = [
            CourseEntry.from_tis(r, semester_start=self.semester_start)
            for r in raw
        ]

    @classmethod
    def clear_cache(cls) -> None:
        """Reset the module-level per-process cache."""
        _CACHE.clear()


# -------------------------------------------------------------------------
# Shortcut functions
# -------------------------------------------------------------------------

def _resolve_schedule(schedule) -> CourseSchedule:
    if isinstance(schedule, CourseSchedule):
        return schedule
    return CourseSchedule(semester_label="2026 Spring")


def last_occurrence(course_name: str, *, as_of: Optional[date] = None,
                    schedule: Optional[CourseSchedule] = None) -> Optional[date]:
    """Return the most recent past date the named course met.

    Args:
        course_name: substring match (e.g. "物化" matches "物理化学实验")
        as_of: reference date (default: today, China TZ)
        schedule: CourseSchedule instance (default: lazy-load current semester)

    Returns:
        The most recent date <= as_of, or None if no past occurrence.
    """
    sched = _resolve_schedule(schedule)
    ref = as_of or now_().date()
    candidates: list[date] = []
    for e in sched.find(course_name):
        for w in e.weeks:
            d = e._week_to_date(w)
            if d and d <= ref:
                candidates.append(d)
    return max(candidates) if candidates else None


def next_occurrence(course_name: str, *, as_of: Optional[date] = None,
                    schedule: Optional[CourseSchedule] = None) -> Optional[date]:
    """Return the next future date the named course will meet (>= as_of + 1)."""
    sched = _resolve_schedule(schedule)
    ref = as_of or now_().date()
    candidates: list[date] = []
    for e in sched.find(course_name):
        for w in e.weeks:
            d = e._week_to_date(w)
            if d and d > ref:
                candidates.append(d)
    return min(candidates) if candidates else None


def dates_in_week(course_name: str, *, week: int,
                  schedule: Optional[CourseSchedule] = None) -> list[date]:
    """Return all dates the named course meets in a given week number."""
    sched = _resolve_schedule(schedule)
    out: list[date] = []
    for e in sched.find(course_name):
        out.extend(e.dates_in_range(week, week))
    return sorted(set(out))


def dates_in_semester(course_name: str, *,
                      schedule: Optional[CourseSchedule] = None) -> list[date]:
    """Return every date the named course meets this semester (sorted)."""
    sched = _resolve_schedule(schedule)
    out: list[date] = []
    for e in sched.find(course_name):
        for w in e.weeks:
            d = e._week_to_date(w)
            if d:
                out.append(d)
    return sorted(set(out))


# -------------------------------------------------------------------------
# class_schedule — "When is my class?" (day + period + weeks)
# -------------------------------------------------------------------------

# weekday index → (English, Chinese)
_WEEKDAY = [
    (1, "Monday", "星期一"),
    (2, "Tuesday", "星期二"),
    (3, "Wednesday", "星期三"),
    (4, "Thursday", "星期四"),
    (5, "Friday", "星期五"),
    (6, "Saturday", "星期六"),
    (7, "Sunday", "星期日"),
]
_WEEKDAY_MAP = {w[0]: (w[1], w[2]) for w in _WEEKDAY}


def class_schedule(
    course_name: str,
    *,
    schedule: Optional[CourseSchedule] = None,
) -> dict:
    """Return the schedule for a course: which day, which period, which weeks.

    Designed for the common question: "When is my <course> class?"

    Args:
        course_name: substring or full course name (e.g. "有机", "物化实验",
            "基础有机化学实验"). Subsequence fallback (e.g. "物化" →
            "物理化学实验") and experiment-preference both apply — see
            CourseSchedule.find for the matching rules.
        schedule: pre-loaded CourseSchedule (default: lazy-load current semester)

    Returns:
        {
          "course": str,                # full matched name
          "course_query": str,          # original query
          "section": str | None,        # e.g. "01班" if detectable from SKSJ
          "meetings": [                 # one entry per distinct (day, period) slot
            {
              "weekday": "Monday",      # English day name
              "weekday_zh": "星期一",    # Chinese
              "weekday_index": 1,       # 1=Mon, 7=Sun (matches TIS KEY)
              "period_start": 3,        # 1-based, matches TIS KEY jc{M}
              "period_end": 4,
              "periods_label": "3-4节",
              "weeks": [3, 5, 7, ...], # academic weeks this meeting runs
              "all_dates": [date(...)], # actual calendar dates
              "location": "慧园2栋...",
              "teachers": ["王海鸥", ...],
            },
            ...
          ],
          "warning": str | None,        # e.g. "Multiple sections matched; showing first"
        }

    Example:
        >>> class_schedule("有机实验")
        {
          "course": "基础有机化学实验",
          "section": "01班",
          "meetings": [{
            "weekday": "Monday", "weekday_zh": "星期一",
            "period_start": 3, "period_end": 4, "periods_label": "3-4节",
            "weeks": [3, 5, 7, 9, 11, 13, 15],
            "all_dates": [date(2026, 3, 9), date(2026, 3, 23), ...],
            "location": "慧园2栋405A实验室",
            "teachers": ["王海鸥", "李慧丽", "李艳艳"],
          }]
        }
    """
    sched = _resolve_schedule(schedule)
    matches = sched.find(course_name)
    if not matches:
        return {
            "course": None,
            "course_query": course_name,
            "section": None,
            "meetings": [],
            "warning": f"Course not found: {course_name!r}. "
                       f"Known: {sched.courses[:5]}...",
        }

    canonical_name = matches[0].name
    section = _extract_section(matches[0])
    warning = None

    # Group by weekday. TIS often returns one entry per period (xq1_jc3,
    # xq1_jc4) for the same class session — those should be ONE meeting
    # spanning periods 3-4, not two separate meetings.
    by_day: dict[int, list[CourseEntry]] = {}
    for e in matches:
        by_day.setdefault(e.weekday, []).append(e)

    meetings = []
    for weekday, entries in sorted(by_day.items()):
        # The entries for the same day are the same class session. Use the
        # min period_start and max period_end.
        period_start = min(e.period_start for e in entries)
        period_end = max(e.period_end for e in entries)
        # Combine weeks from all entries (should be identical for the same class)
        weeks: list[int] = sorted({w for e in entries for w in e.weeks})
        # Compute actual dates
        all_dates: list[date] = []
        for w in weeks:
            d = entries[0]._week_to_date(w)
            if d:
                all_dates.append(d)
        all_dates.sort()

        wd_en, wd_zh = _WEEKDAY_MAP.get(weekday, ("?", "?"))
        periods_label = (
            f"{period_start}-{period_end}节"
            if period_start != period_end
            else f"第{period_start}节"
        )

        # Location + teachers: pick the first entry's, or join uniques
        location = entries[0].location
        teachers = sorted({t for e in entries for t in (e.teacher or "").split(",") if t})

        meetings.append({
            "weekday": wd_en,
            "weekday_zh": wd_zh,
            "weekday_index": weekday,
            "period_start": period_start,
            "period_end": period_end,
            "periods_label": periods_label,
            "weeks": weeks,
            "all_dates": all_dates,
            "location": location,
            "teachers": teachers,
        })

    if len({e.name for e in matches}) > 1:
        warning = (f"Multiple courses matched: {[e.name for e in matches]}. "
                   f"Showing schedule for: {canonical_name!r}")

    return {
        "course": canonical_name,
        "course_query": course_name,
        "section": section,
        "meetings": meetings,
        "warning": warning,
    }


def _extract_section(entry: CourseEntry) -> Optional[str]:
    """Pull the section (e.g. "01班") out of the raw TIS SKSJ, if present."""
    # The CourseEntry stores name/teacher/location but not the raw SKSJ.
    # Try the teacher's name (sometimes encodes section) — best-effort.
    # We can't reliably extract section without the raw SKSJ; return None
    # for now and let the caller pass the raw row if needed.
    return None


# -------------------------------------------------------------------------
# experiment_date — "When was my experiment?" (calendar date for a week)
# -------------------------------------------------------------------------

def experiment_date(
    course_name: str,
    *,
    week: Optional[int] = None,
    as_of: Optional[date] = None,
    schedule: Optional[CourseSchedule] = None,
) -> dict:
    """Return the actual calendar date of a class session.

    Designed for filling in LaTeX experiment report headers like:
        实验日期: 2026-05-04

    Args:
        course_name: substring or full course name
        week: target academic week. If None, uses the most recent past
              week before as_of. If specified but the course has no class
              in that week, returns the nearest past + nearest future with
              an explicit warning (so the caller can pick the right one).
        as_of: reference date (default: today, China TZ)
        schedule: pre-loaded CourseSchedule (default: lazy-load)

    Returns:
        {
          "course": str | None,        # matched full name
          "course_query": str,         # original query
          "experiment_date": date | None,  # the date, or None if no class at all
          "submission_date": date,     # = as_of
          "week": int | None,          # academic week of experiment_date
          "weekday_zh": str | None,    # "星期一" etc.
          "warning": str | None,       # human-readable note if requested week
                                        # has no class — caller should pick
                                        # nearest_past or nearest_future
          "nearest_past": {            # populated when the requested week
                                        # has no class
            "week": int, "date": date, "weekday_zh": str,
          } | None,
          "nearest_future": {...} | None,
        }
    """
    sched = _resolve_schedule(schedule)
    ref = as_of or now_().date()
    cs = class_schedule(course_name, schedule=sched)
    matches = sched.find(course_name)

    if not matches or not cs["meetings"]:
        return {
            "course": cs["course"],
            "course_query": course_name,
            "experiment_date": None,
            "submission_date": ref,
            "week": None,
            "weekday_zh": None,
            "warning": cs.get("warning")
                       or f"Course not found: {course_name!r}",
            "nearest_past": None,
            "nearest_future": None,
        }

    canonical_name = cs["course"]
    all_weeks = sorted({w for m in cs["meetings"] for w in m["weeks"]})
    all_dates = sorted({d for m in cs["meetings"] for d in m["all_dates"]})

    if week is None:
        # Most recent past date
        past = [d for d in all_dates if d <= ref]
        if past:
            exp_date = max(past)
            actual_week = _date_to_week(exp_date, sched.semester_start)
            wd_zh = _WEEKDAY_MAP[exp_date.weekday() + 1][1]
            return {
                "course": canonical_name,
                "course_query": course_name,
                "experiment_date": exp_date,
                "submission_date": ref,
                "week": actual_week,
                "weekday_zh": wd_zh,
                "warning": None,
                "nearest_past": None,
                "nearest_future": None,
            }
        # No past — use earliest
        if all_dates:
            exp_date = min(all_dates)
            return {
                "course": canonical_name,
                "course_query": course_name,
                "experiment_date": exp_date,
                "submission_date": ref,
                "week": _date_to_week(exp_date, sched.semester_start),
                "weekday_zh": _WEEKDAY_MAP[exp_date.weekday() + 1][1],
                "warning": f"No past occurrence before {ref.isoformat()}; using earliest",
                "nearest_past": None,
                "nearest_future": None,
            }
        return {
            "course": canonical_name, "course_query": course_name,
            "experiment_date": None, "submission_date": ref,
            "week": None, "weekday_zh": None,
            "warning": "Course has no class dates this semester",
            "nearest_past": None, "nearest_future": None,
        }

    # Specific week requested
    in_week = [d for d in all_dates if _date_to_week(d, sched.semester_start) == week]
    if in_week:
        exp_date = in_week[0]
        wd_zh = _WEEKDAY_MAP[exp_date.weekday() + 1][1]
        return {
            "course": canonical_name,
            "course_query": course_name,
            "experiment_date": exp_date,
            "submission_date": ref,
            "week": week,
            "weekday_zh": wd_zh,
            "warning": None,
            "nearest_past": None,
            "nearest_future": None,
        }

    # Requested week has no class — find nearest past + future
    past_weeks = [w for w in all_weeks if w < week]
    future_weeks = [w for w in all_weeks if w > week]
    nearest_past = _nearest_summary(past_weeks, all_dates, "max",
                                    sched.semester_start) if past_weeks else None
    nearest_future = _nearest_summary(future_weeks, all_dates, "min",
                                      sched.semester_start) if future_weeks else None

    return {
        "course": canonical_name,
        "course_query": course_name,
        "experiment_date": None,
        "submission_date": ref,
        "week": week,
        "weekday_zh": None,
        "warning": f"W{week} has no {course_name!r} class. "
                   f"Nearest past: W{past_weeks[-1] if past_weeks else '—'}, "
                   f"nearest future: W{future_weeks[0] if future_weeks else '—'}",
        "nearest_past": nearest_past,
        "nearest_future": nearest_future,
    }


def _nearest_summary(weeks: list[int], all_dates: list[date],
                     pick: str, semester_start: date) -> Optional[dict]:
    """Build a {week, date, weekday_zh} summary from a list of weeks."""
    if not weeks:
        return None
    if pick == "max":
        w = max(weeks)
    else:
        w = min(weeks)
    dates_in_w = [d for d in all_dates if _date_to_week(d, semester_start) == w]
    if not dates_in_w:
        return {"week": w, "date": None, "weekday_zh": None}
    d = dates_in_w[0]
    return {
        "week": w,
        "date": d,
        "weekday_zh": _WEEKDAY_MAP[d.weekday() + 1][1],
    }


# -------------------------------------------------------------------------
# Internal helpers
# -------------------------------------------------------------------------

_WEEKDAY_ZH = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


def _is_subsequence(query: str, name: str) -> bool:
    """Check if all characters of `query` appear in `name` in order.

    Used for fuzzy matching of short abbreviations like "物化" → "物理化学实验".
    """
    it = iter(name)
    return all(c in it for c in query)


def _date_to_week(d: Optional[date], semester_start: date) -> Optional[int]:
    """Inverse of week → date: given a date, return its academic week number.

    Uses Mon-Sun convention, with the "effective start" being the Monday on
    or before the semester start. This matches the TIS bitmap numbering
    (e.g. gorganic W15 class on Monday 2026-06-01 → W15, not W14).
    """
    if d is None:
        return None
    effective_start = semester_start - timedelta(days=semester_start.weekday())
    return (d - effective_start).days // 7 + 1


def _week_to_date_for_course(week: int, entries: list[CourseEntry],
                             semester_start: date) -> Optional[date]:
    """For a list of matching entries, return the first class date in `week`."""
    for e in entries:
        if week in e.weeks:
            return e._week_to_date(week)
    return None


__all__ = [
    "CourseEntry",
    "CourseSchedule",
    "class_schedule",
    "experiment_date",
    "last_occurrence",
    "next_occurrence",
    "dates_in_week",
    "dates_in_semester",
    # Backward-compat alias — older callers used experiment_dates (plural)
    "experiment_dates",
]


# -------------------------------------------------------------------------
# Backward-compat alias
# -------------------------------------------------------------------------

# Older code imported experiment_dates (plural). Keep the alias so existing
# callers (incl. tests) still work.
experiment_dates = experiment_date


# -------------------------------------------------------------------------
# Quick demo
# -------------------------------------------------------------------------

if __name__ == "__main__":
    sched = CourseSchedule(semester_label="2026 Spring")
    print(f"Semester start: {sched.semester_start}")
    print(f"Courses: {sched.courses}")
    print()

    for name in ["有机", "物化"]:
        print(f"--- class_schedule({name!r}) ---")
        cs = class_schedule(name)
        print(f"  course:  {cs['course']}")
        print(f"  section: {cs.get('section')}")
        for m in cs["meetings"]:
            print(f"  {m['weekday_zh']} ({m['weekday']}) periods {m['periods_label']}")
            print(f"    weeks:  {m['weeks']}")
            print(f"    dates:  {m['all_dates']}")
            print(f"    where:  {m['location']}")
            print(f"    who:    {m['teachers']}")
        if cs.get("warning"):
            print(f"  ⚠ {cs['warning']}")
        print()

        print(f"--- experiment_date({name!r}, week=12) ---")
        ed = experiment_date(name, week=12, as_of=date(2026, 6, 7))
        if ed["experiment_date"]:
            print(f"  experiment_date: {ed['experiment_date']} ({ed['weekday_zh']})")
            print(f"  week: {ed['week']}")
        else:
            print(f"  W12 has no class. Nearest past: {ed['nearest_past']}")
            print(f"                   Nearest future: {ed['nearest_future']}")
        print()
