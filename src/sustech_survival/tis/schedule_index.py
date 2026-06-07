"""
sustech_survival.tis.schedule_index — lazy, cached index over the TIS personal schedule.

Builds on top of `sustech_survival.tis.schedule` (raw xszykb API) to answer
"when was/will X class happen" questions in O(1) after one semester-wide fetch.

Quick reference:
    sched = CourseSchedule(semester_label="2026 Spring")
    sched.find("物化")                        # substring match → list[CourseEntry]
    last_occurrence("物化", as_of=date(...))   # most recent past date
    next_occurrence("物化", as_of=date(...))   # next future date
    dates_in_week("物化", week=15)            # all dates in a given week
    dates_in_semester("物化")                  # every date this semester

For LaTeX experiment reports:
    experiment_dates("物化", week=15, as_of=date(2026, 6, 7))
    # → {"course": ..., "experiment_date": ..., "submission_date": ..., "week": ...}
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


# ─────────────────────────────────────────────────────────────────────────
# Raw TIS API access (module-level lazy import to avoid circular deps)
# ─────────────────────────────────────────────────────────────────────────

def semester_schedule(xn: Optional[str] = None, xq: Optional[str] = None):
    """Re-export of TIS semester_schedule() for monkeypatching in tests."""
    from sustech_survival.tis import schedule as _api
    return _api.semester_schedule(xn, xq)


def current_semester() -> dict:
    from sustech_survival.tis import schedule as _api
    return _api.current_semester()


# ─────────────────────────────────────────────────────────────────────────
# CourseEntry — one parsed row of the semester schedule
# ─────────────────────────────────────────────────────────────────────────

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

        Required raw fields: KEY (xq{N}_jc{M}), ZC (week bitmap), KCWZSM or SKSJ
        """
        # Course name: prefer KCWZSM, fall back to SKSJ's first line
        name = (raw.get("KCWZSM")
                or raw.get("SKSJ", "").split("\n")[0]
                or "")

        # Day/period: KEY is "xq2_jc3" = day 2 (Tue), period 3
        key = raw.get("KEY", "")
        m = re.match(r"xq(\d+)_jc(\d+)", key)
        weekday = int(m.group(1)) if m else 0
        period_start = int(m.group(2)) if m else 0
        period_end = int(raw.get("JSJC") or period_start)

        # Weeks: ZC is a 36-char bitmap of 0/1, position i (0-indexed) = week i+1
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


# ─────────────────────────────────────────────────────────────────────────
# CourseSchedule — lazy, per-process index over one semester
# ─────────────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────────
# Shortcut functions
# ─────────────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────────
# experiment_dates — high-level helper for LaTeX experiment reports
# ─────────────────────────────────────────────────────────────────────────

def experiment_dates(
    course_name: str,
    *,
    week: Optional[int] = None,
    as_of: Optional[date] = None,
    schedule: Optional[CourseSchedule] = None,
) -> dict:
    """Return experiment date + submission date for a course.

    Designed for filling in LaTeX experiment report headers like:
        实验日期: 2026-05-28
        报告日期: 2026-06-07

    Args:
        course_name: substring or exact match (e.g. "物化", "有机", "物理化学实验")
        week: target academic week. If None, uses the most recent past week
              before as_of. If specified but no class meets in that week,
              returns the closest actual class date with a warning.
        as_of: reference date (default: today, China TZ). Submission date = as_of.
        schedule: pre-loaded CourseSchedule (default: lazy-load current semester)

    Returns:
        dict with keys:
          course            — matched full course name (or None if not found)
          course_query      — the original query
          experiment_date   — date the experiment class met (or None)
          submission_date   — when the report is being submitted (= as_of)
          week              — academic week of experiment_date
          weekday           — English day name (Monday, Tuesday, ...)
          weekday_zh        — Chinese day name (星期一, ...)
          warning           — None or a human-readable note (e.g. "W12 has no
                              gorganic class; using closest: W13")
          all_dates         — sorted list of all dates this course met this semester
          all_weeks         — sorted list of all weeks this course runs
    """
    sched = _resolve_schedule(schedule)
    ref = as_of or now_().date()
    matches = sched.find(course_name)
    all_dates = dates_in_semester(course_name, schedule=sched)
    all_weeks = sorted({w for e in matches for w in e.weeks})

    if not matches:
        return {
            "course": None,
            "course_query": course_name,
            "experiment_date": None,
            "submission_date": ref,
            "week": None,
            "weekday": None,
            "weekday_zh": None,
            "warning": f"Course not found: {course_name!r}. "
                       f"Known: {sched.courses[:5]}...",
            "all_dates": [],
            "all_weeks": [],
        }

    canonical_name = matches[0].name
    warning = None

    if week is None:
        # Default: most recent past date
        past = [d for d in all_dates if d <= ref]
        if past:
            exp_date = max(past)
            actual_week = _date_to_week(exp_date, sched.semester_start)
        else:
            exp_date = min(all_dates) if all_dates else None
            actual_week = _date_to_week(exp_date, sched.semester_start) if exp_date else None
            if exp_date:
                warning = (f"No past occurrence before {ref.isoformat()}; "
                           f"using earliest: week {actual_week}")
    else:
        # Specific week requested
        in_week = dates_in_week(course_name, week=week, schedule=sched)
        if in_week:
            exp_date = in_week[0]
            actual_week = week
        else:
            # No class in requested week — find closest
            if week in all_weeks:
                # (shouldn't happen if dates_in_week is correct, but safety net)
                exp_date = _week_to_date_for_course(week, matches, sched.semester_start)
                actual_week = week
            else:
                # Find the closest week with a class
                past_weeks = [w for w in all_weeks if w <= week]
                future_weeks = [w for w in all_weeks if w > week]
                if past_weeks:
                    nearest = max(past_weeks)
                    direction = "most recent past"
                elif future_weeks:
                    nearest = min(future_weeks)
                    direction = "next future"
                else:
                    return {
                        "course": canonical_name,
                        "course_query": course_name,
                        "experiment_date": None,
                        "submission_date": ref,
                        "week": None,
                        "weekday": None,
                        "weekday_zh": None,
                        "warning": f"W{week} has no class and no other weeks available",
                        "all_dates": all_dates,
                        "all_weeks": all_weeks,
                    }
                exp_date = _week_to_date_for_course(nearest, matches, sched.semester_start)
                actual_week = nearest
                warning = (f"W{week} has no {course_name!r} class; "
                           f"using {direction}: W{actual_week}")

    weekday_en = exp_date.strftime("%A") if exp_date else None
    weekday_cn = _WEEKDAY_ZH[exp_date.weekday()] if exp_date else None

    return {
        "course": canonical_name,
        "course_query": course_name,
        "experiment_date": exp_date,
        "submission_date": ref,
        "week": actual_week,
        "weekday": weekday_en,
        "weekday_zh": weekday_cn,
        "warning": warning,
        "all_dates": all_dates,
        "all_weeks": all_weeks,
    }


# ─────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────

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
    "last_occurrence",
    "next_occurrence",
    "dates_in_week",
    "dates_in_semester",
    "experiment_dates",
]


# ─────────────────────────────────────────────────────────────────────────
# Quick demo
# ─────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    sched = CourseSchedule(semester_label="2026 Spring")
    print(f"Semester start: {sched.semester_start}")
    print(f"Courses: {sched.courses}")
    print()

    for name in ["有机", "物化"]:
        print(f"--- {name} ---")
        info = experiment_dates(name, as_of=date(2026, 6, 7))
        print(f"  course:          {info['course']}")
        print(f"  experiment_date: {info['experiment_date']}")
        print(f"  submission_date: {info['submission_date']}")
        print(f"  week:            {info['week']}")
        print(f"  weekday:         {info['weekday']} ({info['weekday_zh']})")
        print(f"  all_dates:       {info['all_dates']}")
        print(f"  all_weeks:       {info['all_weeks']}")
        if info["warning"]:
            print(f"  WARNING:         {info['warning']}")
        print()

        # Specific week queries
        for w in [12, 13, 14, 15]:
            info_w = experiment_dates(name, week=w, as_of=date(2026, 6, 7))
            print(f"  W{w}: exp_date={info_w['experiment_date']} week={info_w['week']}"
                  + (f"  ⚠ {info_w['warning']}" if info_w["warning"] else ""))
        print()
