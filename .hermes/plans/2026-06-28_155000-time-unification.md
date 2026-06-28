# Time Representation Unification Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Unify time representation across sustech_survival. Single source of truth for period times, week expansion, weekday conventions. Replace string-based time descriptors in booking schema with typed dataclasses.

**Architecture:** One new shared module `classroom/_time.py` becomes the canonical home for PERIOD_TIMES, `expand_weeks()`, and the new typed descriptors (`PeriodRange`, `ClockRange`, `Weekday`, `Weeks`). `classroom/schema.py` and `classroom/live.py` import from `_time.py` instead of defining their own copies. `tis/classroom/booking_schema.py` replaces its raw string fields (`week_pattern: str`) with the typed equivalents (`Weekday`, `Weeks`).

**Tech Stack:** Python 3.10+, dataclasses, `sustech_survival` package.

---

## Task 1: Create `classroom/_time.py` — canonical time module

**Objective:** Create one module with all shared time types and constants. No duplicated logic anywhere.

**Files:**
- Create: `src/sustech_survival/classroom/_time.py`

**Step 1: Write the module**

```python
"""
sustech_survival.classroom._time — Canonical time types and constants.

Single source of truth for:
  - PERIOD_TIMES (the SUSTech 12-period schedule)
  - Week expansion (string → List[int])
  - Weekday (Mon=1 ... Sun=7)
  - Typed time descriptors (PeriodRange, ClockRange, Weeks)

Every other module that works with times should import from here.
No other module in the package defines its own PERIOD_TIMES or
expand_weeks().
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple, overload

# ── Period times (12 periods, 45-min blocks with 10-min breaks) ───────────

PERIOD_TIMES: List[Tuple[int, int, int, int]] = [
    (0, 0, 0, 0),       # 0 placeholder
    (8, 0, 8, 45),      # 1
    (8, 55, 9, 40),     # 2
    (10, 0, 10, 45),    # 3
    (10, 55, 11, 40),   # 4
    (14, 0, 14, 45),    # 5
    (14, 55, 15, 40),   # 6
    (16, 0, 16, 45),    # 7
    (16, 55, 17, 40),   # 8
    (19, 0, 19, 45),    # 9
    (19, 55, 20, 40),   # 10
    (20, 50, 21, 35),   # 11
    (21, 45, 22, 30),   # 12
]

PERIOD_TIME_STR: List[str] = [
    "",
    "08:00-08:45", "08:55-09:40", "10:00-10:45", "10:55-11:40",
    "14:00-14:45", "14:55-15:40", "16:00-16:45", "16:55-17:40",
    "19:00-19:45", "19:55-20:40", "20:50-21:35", "21:45-22:30",
]


def period_hms(p: int) -> Tuple[int, int, int, int]:
    """Return (start_h, start_m, end_h, end_m) for period p (1-12)."""
    if not (1 <= p <= 12):
        return (0, 0, 0, 0)
    return PERIOD_TIMES[p]


def period_str(p: int) -> str:
    """Return '08:00-08:45' for period p (1-12)."""
    return PERIOD_TIME_STR[p] if 1 <= p <= 12 else ""


# ── Week expansion ─────────────────────────────────────────────────────────

def expand_weeks(weeks_str: str) -> List[int]:
    """Expand '1-15' / '3,7,9,13' / '1-9,11-15' → sorted unique week ints."""
    out: List[int] = []
    for chunk in weeks_str.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            try:
                a, b = chunk.split("-", 1)
                a, b = int(a), int(b)
                if a <= b:
                    out.extend(range(a, b + 1))
                else:
                    out.extend(range(b, a + 1))
            except (ValueError, TypeError):
                continue
        else:
            try:
                out.append(int(chunk))
            except (ValueError, TypeError):
                continue
    return sorted(set(out))


def compact_weeks(weeks: List[int]) -> str:
    """Inverse of expand_weeks: [1,2,3,5,6,7] → '1-3,5-7'."""
    if not weeks:
        return ""
    weeks = sorted(set(weeks))
    ranges: List[str] = []
    start = weeks[0]
    end = weeks[0]
    for w in weeks[1:]:
        if w == end + 1:
            end = w
        else:
            ranges.append(f"{start}-{end}" if start != end else str(start))
            start = end = w
    ranges.append(f"{start}-{end}" if start != end else str(start))
    return ",".join(ranges)


# ── Day / weekday constants ────────────────────────────────────────────────

DAY_CHARS = "一二三四五六日"
DAY_NAMES_ZH = ["", "周一", "周二", "周三", "周四", "周五", "周六", "周日"]
DAY_NAMES_EN = ["", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

NUM_DAYS = 7
DAY_MON = 1
DAY_TUE = 2
DAY_WED = 3
DAY_THU = 4
DAY_FRI = 5
DAY_SAT = 6
DAY_SUN = 7


@dataclass(frozen=True)
class Weekday:
    """Monday=1 ... Sunday=7. Constructable from int or Chinese char."""
    n: int

    def __post_init__(self) -> None:
        if not (1 <= self.n <= 7):
            raise ValueError(f"Weekday must be 1-7, got {self.n}")

    @classmethod
    def from_str(cls, s: str) -> "Weekday":
        """Accept '一'/'二'/.../'日' or 'Mon'/'Tue'/... or '周一'."""
        for i, ch in enumerate(DAY_CHARS, 1):
            if ch in s:
                return cls(i)
        for i, name in enumerate(DAY_NAMES_EN[1:], 1):
            if name.lower() in s.lower():
                return cls(i)
        for i, name in enumerate(DAY_NAMES_ZH[1:], 1):
            if name in s:
                return cls(i)
        raise ValueError(f"Cannot parse weekday from {s!r}")

    @property
    def zh(self) -> str: return DAY_CHARS[self.n - 1]

    @property
    def zh_full(self) -> str: return DAY_NAMES_ZH[self.n]

    @property
    def en(self) -> str: return DAY_NAMES_EN[self.n]

    def __int__(self) -> int: return self.n

    def __str__(self) -> str: return self.zh_full

    def __repr__(self) -> str: return f"Weekday({self.n})"


def day_char_to_int(c: str) -> int:
    """'一' → 1, '二' → 2, ..., '日' → 7. Returns 0 on unknown."""
    try:
        return DAY_CHARS.index(c) + 1
    except ValueError:
        return 0


# ── Time descriptors (what the user actually describes) ────────────────────

@dataclass(frozen=True)
class PeriodRange:
    """A time described by TIS period numbers (节次). Periods 1-12."""
    start: int      # 1-12
    end: int        # 1-12

    def __post_init__(self) -> None:
        if not (1 <= self.start <= self.end <= 12):
            raise ValueError(
                f"PeriodRange requires 1 <= start <= end <= 12, "
                f"got {self.start}-{self.end}"
            )

    @property
    def span(self) -> int:
        return self.end - self.start + 1

    @property
    def period_list(self) -> List[int]:
        return list(range(self.start, self.end + 1))

    @property
    def clock_str(self) -> str:
        """Return '08:00-09:40' (combined start→end range)."""
        sh, sm, _, _ = period_hms(self.start)
        _, _, eh, em = period_hms(self.end)
        return f"{sh:02d}:{sm:02d}-{eh:02d}:{em:02d}"

    def __str__(self) -> str:
        if self.start == self.end:
            return f"第{self.start}节"
        return f"第{self.start}-{self.end}节"


@dataclass(frozen=True)
class ClockRange:
    """A time described by clock hours. '14:00'-'16:00'."""
    start: str      # "HH:MM"
    end: str        # "HH:MM"

    @property
    def start_minutes(self) -> int:
        h, m = self.start.split(":")
        return int(h) * 60 + int(m)

    @property
    def end_minutes(self) -> int:
        h, m = self.end.split(":")
        return int(h) * 60 + int(m)

    def to_period_range(self) -> PeriodRange:
        """Convert to nearest PeriodRange that covers this clock range."""
        sm = self.start_minutes
        em = self.end_minutes
        p_start = 0
        p_end = 0
        for p in range(1, 13):
            sh, smin, eh, emin = period_hms(p)
            ps = sh * 60 + smin
            pe = eh * 60 + emin
            if ps <= sm <= pe:
                p_start = p
            if ps <= em <= pe:
                p_end = p
        if p_start and p_end:
            return PeriodRange(p_start, p_end)
        raise ValueError(
            f"ClockRange {self.start}-{self.end} does not map to any "
            f"TIS period (must fall within class hours 08:00-22:30)"
        )

    def __str__(self) -> str:
        return f"{self.start}-{self.end}"


# ── Schedule descriptors (time + recurrence) ──────────────────────────────

@dataclass(frozen=True)
class Weeks:
    """A set of week numbers. Constructable from string or list."""
    numbers: List[int] = field(default_factory=list)

    def __post_init__(self) -> None:
        object.__setattr__(self, "numbers", sorted(set(self.numbers)))

    @classmethod
    def from_str(cls, s: str) -> "Weeks":
        return cls(expand_weeks(s))

    @classmethod
    def from_range(cls, first: int, last: int) -> "Weeks":
        return cls(list(range(first, last + 1)))

    @property
    def pattern(self) -> str:
        """TIS-compatible compact string: '5-8' or '1,3,5,7'."""
        return compact_weeks(self.numbers)

    @property
    def first(self) -> Optional[int]:
        return self.numbers[0] if self.numbers else None

    @property
    def last(self) -> Optional[int]:
        return self.numbers[-1] if self.numbers else None

    @property
    def count(self) -> int:
        return len(self.numbers)

    def __contains__(self, w: int) -> bool:
        return w in self.numbers

    def __iter__(self):
        return iter(self.numbers)

    def __len__(self) -> int:
        return len(self.numbers)

    def __str__(self) -> str:
        return self.pattern or "(empty)"


TimeSpec = PeriodRange | ClockRange


@dataclass(frozen=True)
class WeeklyTime:
    """A repeating weekly time: 'Tuesday period 3-4 weeks 5-8'."""
    weekday: Weekday     # Mon=1 ... Sun=7
    time: TimeSpec       # PeriodRange or ClockRange
    weeks: Optional[Weeks] = None    # None = all weeks of current semester

    def period_range(self) -> PeriodRange:
        if isinstance(self.time, PeriodRange):
            return self.time
        return self.time.to_period_range()


@dataclass(frozen=True)
class SpecificTime:
    """A one-off time: '2026-05-10, 14:00-16:00'."""
    date: str            # "YYYY-MM-DD"
    time: TimeSpec       # PeriodRange or ClockRange

    def period_range(self) -> PeriodRange:
        if isinstance(self.time, PeriodRange):
            return self.time
        return self.time.to_period_range()


Schedule = WeeklyTime | SpecificTime | List[WeeklyTime | SpecificTime]
```

**Step 2: Write test for `_time.py`**

Create `src/test/test_classroom_time.py` with tests for:
- `expand_weeks()` / `compact_weeks()` round-trip
- `Weekday` from int and from Chinese char
- `PeriodRange` validation (rejects 0, rejects start>end, rejects >12)
- `ClockRange.to_period_range()` for known cases (14:00-16:00 → periods 5-7)
- `Weeks` construction from string and list
- `WeeklyTime` / `SpecificTime` construction
- `period_hms()` / `period_str()` helpers

**Step 3: Run tests to verify baseline**

`pytest src/test/test_classroom_time.py -v` — expected: all pass

---

## Task 2: Migrate `classroom/schema.py` to import from `_time.py`

**Objective:** Remove local copies of PERIOD_TIMES, DAY_CHARS, DAY_NAMES_ZH, DAY_NAMES_EN, expand_weeks, day_char_to_int from schema.py. Import from _time.py instead. BACKWARD COMPATIBLE — public names still exported.

**Files:**
- Modify: `src/sustech_survival/classroom/schema.py`

**Step 1: Replace local definitions with imports**

```python
# Remove lines 32-50 (DAY_CHARS through day_char_to_int, PERIOD_TIMES)
# Remove lines 76-107 (expand_weeks)
# Add at top:
from ._time import (
    DAY_CHARS, DAY_NAMES_ZH, DAY_NAMES_EN, PERIOD_TIME_STR as PERIOD_TIMES,
    expand_weeks, day_char_to_int, Weekday, PeriodRange, ClockRange,
)
```

**Step 2: Verify PERIOD_TIMES compatibility**

Previously `PERIOD_TIMES` was `List[str]` in schema.py. Export as `PERIOD_TIMES = PERIOD_TIME_STR`. Any code doing `PERIOD_TIMES[p]` gets the same string. Any code doing `PERIOD_TIMES[p].split("-")` also works.

**Step 3: Run schema + classroom tests**

`pytest src/test/test_classroom_schema.py src/test/test_classroom_live.py -v` — expected: all pass

---

## Task 3: Migrate `classroom/live.py` to import from `_time.py`

**Objective:** Remove local copy of PERIOD_TIMES (tuple format, lines 330-345) and `_expand_week_pattern()` (lines 208-240). Import from `_time.py`. BACKWARD COMPATIBLE.

**Files:**
- Modify: `src/sustech_survival/classroom/live.py`

**Step 1: Replace**

Remove `_expand_week_pattern()` function. Replace all uses with `expand_weeks()`.

Remove local `PERIOD_TIMES` (tuple list). Import `PERIOD_TIMES` from `._time`.

**Step 2: Verify `current_period()` still works**

`current_period()` iterates `PERIOD_TIMES[p]` — same tuple format, same logic. No behavior change.

**Step 3: Run live tests**

`pytest src/test/test_classroom_live.py -v` — expected: all pass

---

## Task 4: Update `tis/classroom/booking_schema.py` — typed time descriptors

**Objective:** Replace `BorrowTimeSlot`'s raw `weekday: int` and `week_pattern: str` with `Weekday` and `Weeks`. Replace `BorrowApplication.weeks: str` with `Weeks`. Keep `from_api()` backward compatible (accept raw API shapes, convert internally).

**Files:**
- Modify: `src/sustech_survival/tis/classroom/booking_schema.py`

**Changes:**
- `BorrowTimeSlot`:
  ```python
  # OLD
  weekday: int = 0
  week_pattern: str = ""
  
  # NEW
  weekday: Weekday = Weekday(1)  # or int 1-7 (keep backward compat)
  week_pattern: Weeks = Weeks([])
  ```
  Actually, keep `weekday` as `int` for backward compat (TIS API gives raw ints). Add `Weekday` only in the new user-facing API (book function), not in the schema that mirrors the TIS backend.

- `BorrowApplication`:
  ```python
  # OLD
  weeks: str = ""
  
  # NEW
  weeks: str = ""  # stays — mirrors TIS backend
  ```

Wait — the user said "not a fan of strings." But `BorrowTimeSlot.week_pattern` is a raw TIS field. The fix should be: keep the `from_api()` parser as-is (accepts raw strings), but add computed properties or methods that return `Weeks` / `PeriodRange` objects.

Proposed change:
- `BorrowTimeSlot.week_pattern` stays `str` (API mirror)
- Add `BorrowTimeSlot.expanded_weeks: List[int]` property that calls `expand_weeks()`
- Add `BorrowTimeSlot.period_range: PeriodRange` property
- `BorrowApplication.weeks` stays `str` (API mirror)

This way the raw fields still round-trip correctly with `to_api()`/`from_api()`, but consumers get typed access.

**Step 1: Add computed properties**

```python
from sustech_survival.classroom._time import expand_weeks, Weekday, PeriodRange

@dataclass
class BorrowTimeSlot:
    # ... existing fields unchanged ...
    
    @property
    def expanded_weeks(self) -> List[int]:
        return expand_weeks(self.week_pattern) if self.week_pattern else []
    
    @property
    def period_range(self) -> PeriodRange:
        return PeriodRange(self.period_start, self.period_end)
    
    @property
    def weekday_obj(self) -> Weekday:
        return Weekday(self.weekday) if 1 <= self.weekday <= 7 else Weekday(1)
```

**Step 2: Run schema tests**

`pytest src/test/test_tis_booking_schema.py -v` — expected: all pass

---

## Task 5: Clean up `classroom/live.py` redundant exports

**Objective:** Remove the duplicated `PERIOD_TIMES` constant from `live.py`. Update `classroom/__init__.py` to use the new canonical location.

**Files:**
- Modify: `src/sustech_survival/classroom/live.py` (lines 330-345)
- Modify: `src/sustech_survival/classroom/__init__.py`

**Step 1:** Delete `PERIOD_TIMES` tuple definition from live.py lines 330-345.

**Step 2:** In `live.py`, replace the import at top to use `from ._time import PERIOD_TIMES`.

**Step 3:** In `classroom/__init__.py`, verify `PERIOD_TIMES` is still accessible via the existing re-export chain. (Currently `classroom.__init__` doesn't re-export PERIOD_TIMES — consumers import it directly from `classroom.live` or `classroom.schema`. After this change, both should import from `._time`.)

---

## Task 6: Full test suite verification

**Objective:** Confirm zero regressions.

**Step 1:** Run full test suite
```bash
cd ~/.openclaw/code/sustech_survival && python3 -m pytest src/test/ -v -m "not live"
```

Expected: all pass. If any fail, fix before continuing.

---

## Task 7: Documentation update

**Objective:** Update skill docs and module docstrings to reflect the new time module.

**Step 1:** Update `sustech-dev/SKILL.md` — add reference to `_time.py` as canonical time source.

**Step 2:** Update `tis/SKILL.md` — show new `WeeklyTime` usage in the venue borrowing example.

**Step 3:** Update `classroom/SKILL.md` — document `_time.py` as the canonical time module.

---

## Risk Assessment

| Risk | Mitigation |
|---|---|
| `PERIOD_TIMES` type change breaks consumers | `schema.py` exports string version as `PERIOD_TIMES = PERIOD_TIME_STR`; `live.py` imports tuple version. Both backward compatible. |
| `expand_weeks` removed from schema.py breaks imports | `schema.py` re-exports from `_time.py`. Any code that did `from classroom.schema import expand_weeks` still works. |
| `_expand_week_pattern` removed from live.py breaks internal callers | `live.py` switches to `expand_weeks` from `_time.py`. Same logic, verified by identical test outcomes. |
| `exams.py` has its own 50-min PERIOD_TIMES | DO NOT touch `exams.py` in this refactor. The exam schedule may legitimately use a different period structure. Add a comment noting the divergence. |
