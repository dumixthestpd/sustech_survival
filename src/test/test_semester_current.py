"""
Dedicated tests for sustech_survival.semester.Semester.current() and
Season.from_months / from_int / from_term_num — the live-term resolver.

Fully offline and deterministic via the injectable ``_today`` parameter.
"""
from __future__ import annotations

from datetime import date

import pytest

from sustech_survival.semester import Semester, Season


# ── Semester.current() with an injected date ───────────────────────────────

@pytest.mark.parametrize("y,mo,d,exp_tis,xn,xq,season", [
    # Fall: end year = calendar year, cohort = +1
    (2026, 9, 1,  "2026-20271", "2026-2027", "1", Season.FALL),
    (2026, 12, 25, "2026-20271", "2026-2027", "1", Season.FALL),
    (2026, 11, 3, "2026-20271", "2026-2027", "1", Season.FALL),
    # Spring: belongs to academic year that began last autumn
    (2026, 3, 15, "2025-20262", "2025-2026", "2", Season.SPRING),
    (2026, 6, 30, "2025-20262", "2025-2026", "2", Season.SPRING),
    # Summer: same academic-year bucket as spring
    (2026, 7, 10, "2025-20263", "2025-2026", "3", Season.SUMMER),
    (2026, 8, 20, "2025-20263", "2025-2026", "3", Season.SUMMER),
])
def test_current_maps_date_to_term(y, mo, d, exp_tis, xn, xq, season):
    sem = Semester.current(date(y, mo, d))
    assert sem.tis == exp_tis
    assert sem.xn == xn
    assert sem.xq == xq
    assert sem.season is season


def test_current_defaults_to_today():
    # Must not raise and must return a valid Semester (parseable TIS code).
    sem = Semester.current()
    assert sem.tis.count("-") == 1
    assert len(sem.tis.replace("-", "")) == 9
    assert sem.tis.isascii()


# ── Season conversions ─────────────────────────────────────────────────────

def test_season_from_int():
    assert Season.from_int(1) is Season.FALL
    assert Season.from_int(2) is Season.SPRING
    assert Season.from_int(3) is Season.SUMMER


def test_season_from_term_num_alias():
    assert Season.from_term_num(1) is Season.FALL
    assert Season.from_term_num(2) is Season.SPRING
    assert Season.from_term_num(3) is Season.SUMMER


def test_season_from_months():
    assert Season.from_months(9) is Season.FALL
    assert Season.from_months(12) is Season.FALL
    assert Season.from_months(3) is Season.SPRING
    assert Season.from_months(6) is Season.SPRING
    assert Season.from_months(7) is Season.SUMMER
    assert Season.from_months(8) is Season.SUMMER


def test_term_num_roundtrip():
    for s in [Season.FALL, Season.SPRING, Season.SUMMER]:
        assert Season.from_term_num(s.term_num) is s


# ── TIS-code construction ──────────────────────────────────────────────────

def test_code_scheme():
    # Fall 2026 => end 2026, cohort 2027, term 1
    assert Semester._code(2026, 2027, Season.FALL) == "2026-20271"
    assert Semester._code(2025, 2026, Season.SPRING) == "2025-20262"
    assert Semester._code(2025, 2026, Season.SUMMER) == "2025-20263"


def test_semester_string_parsing():
    s = Semester("2025-20262")
    assert s.xn == "2025-2026"
    assert s.xq == "2"
    assert s.season is Season.SPRING
    assert s.cohort_year == 2026
    assert s.end_year == 2025
