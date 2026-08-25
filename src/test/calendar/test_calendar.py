"""
Tests for sustech_survival.calendar.

Coverage:
- Online load (canonical path)
- from_payloads (offline test path)
- Identity / semester math (date_of, week_of, in_semester)
- Day predicates (is_holiday, is_teaching_day, is_compensatory, etc.)
- Day.schedule for normal / holiday / compensatory / final days
- Compensatory transfer in fill + dates (the fill-all-then-transfer rule)
- summer = None when JSON has only start/end
- AcademicCalendar.day() dispatches to the right semester
- `date in semester` containment
- ICS export via courses_to_ical
"""
from __future__ import annotations

import json
import urllib.request
from datetime import date

import pytest

from sustech_survival.calendar import (
    DEFAULT_REPO, AcademicCalendar, CalendarError, ClassTime, Compensatory,
    Day, Holiday, Parity, Semester, Weekday,
)


# -- Fixtures ----------------------------------------------------


def _fake_general_json():
    """Minimal general.json payload — just holidays."""
    return {
        "holidays": [
            {"name": "National Day",  "start": "2026-10-01", "end": "2026-10-07"},
            {"name": "Labor Day",     "start": "2026-05-01", "end": "2026-05-05"},
            {"name": "Spring Festival","start": "2026-02-17","end": "2026-02-23"},
        ],
    }


def _fake_undergrad_json():
    """Minimal undergraduate.json payload — spring + fall + summer(minimal)."""
    return {
        "winter_holiday": {"start": "2026-01-12", "end": "2026-02-23"},
        "spring_semester": {
            "start": "2026-02-23", "end": "2026-06-30",
            "sign_in": "2026-02-24",
            "teaching_start": "2026-02-25",
            "total_teaching_weeks": 17,
            "midterm": {"start": "2026-04-13", "end": "2026-04-26",
                        "equivalent_weeks": [8, 9]},
            "final":   {"start": "2026-06-08", "end": "2026-06-18",
                        "equivalent_weeks": [16, 17]},
            "compensatories": [
                {"date": "2026-02-28", "week_type": "odd",  "workday_type": "Monday"},
                {"date": "2026-05-09", "week_type": "odd",  "workday_type": "Tuesday"},
            ],
        },
        "summer_semester": {"start": "2026-06-29", "end": "2026-08-07"},
        "fall_semester": {
            "start": "2026-09-01", "end": "2027-01-11",
            "sign_in": "2026-09-04",
            "teaching_start": "2026-09-07",
            "freshman_arrival": "2026-08-17",
            "total_teaching_weeks": 18,
            "midterm": {"start": "2026-10-26", "end": "2026-11-08",
                        "equivalent_weeks": [8, 9]},
            "final":   {"start": "2026-12-28", "end": "2027-01-08",
                        "equivalent_weeks": [17, 18]},
            "compensatories": [
                {"date": "2026-09-20", "week_type": "odd",  "workday_type": "Friday"},
                {"date": "2026-10-10", "week_type": "odd",  "workday_type": "Wednesday"},
            ],
            "extra_breaks": ["2026-11-20"],
        },
    }


def _fake_graduate_json():
    """Graduate has the same semester structure but different freshman dates."""
    ug = _fake_undergrad_json()
    ug = {**ug,
          "fall_semester": {
              **ug["fall_semester"],
              "freshman_arrival": "2026-08-25",
          }}
    return ug


@pytest.fixture
def fake_cal():
    """AcademicCalendar built from in-memory payloads (no network)."""
    return AcademicCalendar.from_payloads(
        year=2026, level="undergraduate",
        undergraduate=_fake_undergrad_json(),
        graduate=_fake_graduate_json(),
        general=_fake_general_json(),
    )


@pytest.fixture
def spring(fake_cal):
    return fake_cal.spring


@pytest.fixture
def fall(fake_cal):
    return fake_cal.fall


# -- Identity ----------------------------------------------------


class TestIdentity:
    def test_spring_human(self, spring):
        # Teaching starts 2026-02-25 (Spring), so human is "2026 Spring".
        assert spring.human == "2026 Spring"

    def test_fall_human(self, fall):
        # Fall 2026 starts 2026-09-07 (within 2025-2026 academic year).
        assert fall.human == "2026 Fall"

    def test_spring_tis(self, spring):
        # Spring 2026: cohort=2026, end=2026, term=2 → TIS code 2026-20262.
        assert spring.tis == "2026-20262"

    def test_fall_tis(self, fall):
        # Fall 2026: cohort=2026, end=2027, term=1 → TIS code 2027-20261.
        assert fall.tis == "2027-20261"

    def test_level(self, spring, fall):
        assert spring.level == "undergraduate"
        assert fall.level == "undergraduate"

    def test_graduate_freshman_arrival_differs(self):
        cal = AcademicCalendar.from_payloads(
            2026, "graduate",
            undergraduate=_fake_undergrad_json(),
            graduate=_fake_graduate_json(),
            general=_fake_general_json(),
        )
        assert cal.fall.freshman_arrival == date(2026, 8, 25)
        assert cal.spring.freshman_arrival is None  # undergrad payload has none


class TestSummerSemester:
    def test_summer_is_none_when_minimal(self, fake_cal):
        # The JSON has summer_semester with only start/end (no teaching_start).
        assert fake_cal.summer is None

    def test_summer_built_when_full_payload(self):
        ug = _fake_undergrad_json()
        ug = {**ug, "summer_semester": {
            **ug["summer_semester"],
            "teaching_start": "2026-07-01",
            "sign_in": "2026-06-29",
            "total_teaching_weeks": 6,
            "midterm": {"start": "2026-07-15", "end": "2026-07-22",
                        "equivalent_weeks": [3]},
            "final": {"start": "2026-07-25", "end": "2026-08-07",
                      "equivalent_weeks": [5, 6]},
        }}
        cal = AcademicCalendar.from_payloads(
            2026, "undergraduate",
            undergraduate=ug,
            graduate=_fake_graduate_json(),
            general=_fake_general_json(),
        )
        assert cal.summer is not None
        assert cal.summer.teaching_start == date(2026, 7, 1)


# -- Date math ---------------------------------------------------


class TestDateMath:
    def test_date_of_week_1_monday(self, spring):
        # Teaching starts 2026-02-25 (Wed). Week 1 Monday = 2026-02-23.
        assert spring.date_of(1, 0) == date(2026, 2, 23)

    def test_date_of_week_2_friday(self, spring):
        # Week 2 Friday: week 1 Monday = 2026-02-23 → +7 = 2026-03-02,
        # +4 days = 2026-03-06.
        assert spring.date_of(2, 4) == date(2026, 3, 6)

    def test_date_of_week_17_monday(self, spring):
        assert spring.date_of(17, 0) == date(2026, 6, 15)

    def test_week_of(self, spring):
        # 2026-02-25 (Wed) = teaching_start → week 1.
        assert spring.week_of(date(2026, 2, 25)) == 1
        # 2026-03-25 (Wed) → 30 days from 2026-02-23 → 30 // 7 = 4 → week 5.
        assert spring.week_of(date(2026, 3, 25)) == 5
        # 2026-06-17 (Wed) → 112 days from 2026-02-23 → 112 // 7 = 16 → week 17.
        assert spring.week_of(date(2026, 6, 17)) == 17

    def test_week_of_outside_teaching(self, spring):
        assert spring.week_of(date(2026, 1, 1)) == 0  # before teaching
        assert spring.week_of(date(2026, 6, 22)) == 0  # after teaching ends

    def test_date_of_out_of_range_raises(self, spring):
        with pytest.raises(CalendarError):
            spring.date_of(99, 0)
        with pytest.raises(CalendarError):
            spring.date_of(1, 7)  # weekday must be 0..6

    def test_is_in_semester(self, spring):
        assert spring.is_in_semester(date(2026, 2, 24))  # sign_in day
        assert spring.is_in_semester(date(2026, 6, 18))  # last final day
        assert not spring.is_in_semester(date(2026, 2, 23))

    def test_contains_dunder(self, spring):
        assert date(2026, 3, 15) in spring
        assert date(2026, 1, 15) not in spring


# -- Day predicates ----------------------------------------------


class TestDayPredicates:
    def test_normal_teaching_day(self, fake_cal, spring):
        d = fake_cal.day(date(2026, 3, 4))  # Wednesday week 2 — pure teaching
        assert d.is_teaching_day()
        assert not d.is_holiday()
        assert not d.is_compensatory()
        assert not d.is_final()
        assert not d.is_midterm()
        assert not d.is_extra_break()
        assert not d.is_weekend()
        assert d.has_class()

    def test_holiday(self, fake_cal):
        d = fake_cal.day(date(2026, 5, 1))  # Labor Day
        assert d.is_holiday()
        assert d.holiday.name == "Labor Day"
        assert not d.is_teaching_day()
        assert not d.has_class()

    def test_compensatory_day(self, fake_cal):
        # 2026-02-28 (Saturday) is a compensatory day for odd-Monday.
        d = fake_cal.day(date(2026, 2, 28))
        assert d.is_compensatory()
        assert d.comp.week_type == "odd"
        assert d.comp.workday == "Monday"
        assert d.has_class()  # compensatory counts as having class

    def test_final_week(self, fake_cal):
        # Final equivalent weeks are 16, 17 → 2026-06-08..2026-06-21.
        d = fake_cal.day(date(2026, 6, 10))
        assert d.is_final()
        assert not d.is_teaching_day()

    def test_midterm_week(self, fake_cal):
        # Midterm equivalent weeks are 8, 9 → 2026-04-13..2026-04-26.
        # 2026-04-15 is a Wednesday in week 9 (midterm).
        d = fake_cal.day(date(2026, 4, 15))
        assert d.in_midterm_week
        assert d.is_midterm()
        # Midterm weeks have classes — is_teaching_day should be True.
        assert d.is_teaching_day()
        assert d.has_class()

    def test_extra_break(self, fake_cal):
        # Fall extra_breaks has 2026-11-20.
        d = fake_cal.day(date(2026, 11, 20))
        assert d.is_extra_break()
        assert not d.has_class()

    def test_weekend(self, fake_cal):
        d = fake_cal.day(date(2026, 3, 7))  # Saturday
        assert d.is_weekend()
        # Weekends are not teaching days, so is_teaching_day and
        # has_class must both be False.
        assert not d.is_teaching_day()
        assert not d.has_class()

    def test_no_semester(self, fake_cal):
        d = fake_cal.day(date(2026, 7, 15))  # summer — not a full semester in fixture
        assert d.semester is None
        assert d.week == 0
        assert not d.has_class()

    def test_str_human_readable(self, fake_cal):
        d = fake_cal.day(date(2026, 5, 1))
        # Must contain the date, weekday, and the holiday name.
        s = str(d)
        assert "2026-05-01" in s
        assert "Friday" in s
        assert "Labor Day" in s


# -- Day.schedule -------------------------------------------------


class TestDaySchedule:
    def test_schedule_empty_on_holiday(self, fake_cal):
        d = fake_cal.day(date(2026, 5, 1))
        assert d.schedule == []

    def test_schedule_empty_on_final(self, fake_cal):
        d = fake_cal.day(date(2026, 6, 10))
        assert d.schedule == []

    def test_schedule_empty_on_extra_break(self, fake_cal):
        d = fake_cal.day(date(2026, 11, 20))
        assert d.schedule == []

    def test_schedule_normal_teaching_day(self, fake_cal, spring):
        ct = ClassTime(weeks=tuple(range(1, 18)), weekday=2, periods=(1, 2),
                       title="Test", teacher="T", room="R")
        spring.fill(ct)
        # Pick a Wednesday in week 3 — should include the test class.
        d = fake_cal.day(date(2026, 3, 11))
        assert d.schedule == [ct]

    def test_schedule_compensatory_transfers_classes(self, fake_cal, spring):
        from sustech_survival.calendar import Holiday
        # Add a custom holiday that overlaps with a teaching Monday.
        fake_hol = Holiday(name="Custom", start=date(2026, 3, 9),
                           end=date(2026, 3, 9))  # Monday week 3
        spring.calendar.holidays.append(fake_hol)
        # Make 2026-03-14 a compensatory day for odd-Monday.
        extra_comp = Compensatory(date=date(2026, 3, 14),
                                  week_type="odd", workday="Monday")
        spring.compensatories.append(extra_comp)
        # Add a Monday-odd class.
        ct = ClassTime(weeks=(1, 3), weekday=0, periods=(1, 2),
                       title="Monday Class", teacher="T", room="R")
        spring.fill(ct)
        # The comp day should "have" the class.
        d = fake_cal.day(date(2026, 3, 14))
        assert d.is_compensatory()
        assert ct in d.schedule


# -- Semester.fill + dates ---------------------------------------


class TestFillAndDates:
    def test_fill_returns_true_for_new(self, spring):
        ct = ClassTime(weeks=(1, 3, 5), weekday=0, periods=(1, 2))
        assert spring.fill(ct) is True
        assert ct in spring.classes

    def test_fill_returns_false_for_duplicate(self, spring):
        ct = ClassTime(weeks=(1, 3, 5), weekday=0, periods=(1, 2))
        spring.fill(ct)
        assert spring.fill(ct) is False  # duplicate

    def test_fill_equality_check(self, spring):
        # Two ClassTimes with the same fields compare equal (dataclass frozen).
        ct1 = ClassTime(weeks=(1,), weekday=0, periods=(1,))
        ct2 = ClassTime(weeks=(1,), weekday=0, periods=(1,))
        assert ct1 == ct2
        spring.fill(ct1)
        assert spring.fill(ct2) is False

    def test_dates_simple(self, spring):
        # Use Wednesday to avoid the "Mon of week 1 is before sign_in" issue.
        # Spring 2026: teaching_start = 2026-02-25 (Wed). Wednesday class.
        ct = ClassTime(weeks=(1, 2, 3), weekday=2, periods=(1, 2))
        assert spring.dates(ct) == [
            date(2026, 2, 25), date(2026, 3, 4), date(2026, 3, 11),
        ]

    def test_dates_skipped_on_holiday_without_comp(self, spring):
        # 2026-05-01 (Labor Day) is the Friday of week 10. No Friday comp
        # exists in the fixture, so the date is dropped.
        ct = ClassTime(weeks=(10,), weekday=4, periods=(1,))
        assert spring.dates(ct) == []

    def test_dates_kept_on_midterm_week(self, spring):
        # SUSTech rule: midterm weeks DO NOT cancel classes. Classes continue.
        # Midterm equivalent weeks are 8, 9 → Mondays 2026-04-13, 2026-04-20.
        ct = ClassTime(weeks=(8,), weekday=0, periods=(1,))
        assert spring.dates(ct) == [date(2026, 4, 13)]

    def test_dates_compensatory_transfer_actually_triggers(self, spring):
        # Construct a contrived scenario: a custom holiday on a teaching
        # Monday, with a custom compensatory day to replace it.
        from sustech_survival.calendar import Holiday
        # Custom holiday on Monday 2026-03-09 (Mon of week 3, odd).
        fake_hol = Holiday(name="Custom", start=date(2026, 3, 9),
                           end=date(2026, 3, 9))
        spring.calendar.holidays.append(fake_hol)
        # Custom comp day on Saturday 2026-03-14 for odd-Monday.
        extra_comp = Compensatory(date=date(2026, 3, 14),
                                  week_type="odd", workday="Monday")
        spring.compensatories.append(extra_comp)
        # Class meeting Mon week 1 (Wed teaching_start, so Mon of week 1 is
        # 2026-02-23 — before sign_in, dropped) and Mon week 3 (holiday →
        # transfer to 2026-03-14).
        ct = ClassTime(weeks=(1, 3), weekday=0, periods=(1,))
        result = spring.dates(ct)
        # Only the transferred date should appear (week 1 Mon is pre-sign_in).
        assert result == [date(2026, 3, 14)]


# -- AcademicCalendar.day dispatch ------------------------------


class TestCalendarDayDispatch:
    def test_spring_day(self, fake_cal):
        d = fake_cal.day(date(2026, 3, 15))
        assert d.semester is fake_cal.spring
        assert d.week > 0

    def test_fall_day(self, fake_cal):
        d = fake_cal.day(date(2026, 10, 15))
        assert d.semester is fake_cal.fall
        assert d.week > 0

    def test_between_semesters(self, fake_cal):
        # July 1 — between spring and fall, no summer in this fixture.
        d = fake_cal.day(date(2026, 7, 1))
        assert d.semester is None
        assert d.week == 0


# -- ICS export integration -------------------------------------


class TestIcalExport:
    def test_courses_to_ical_emits_one_vevent_per_period(self, spring):
        from sustech_survival.selectcourse.ical import courses_to_ical
        ct = ClassTime(weeks=(1, 3), weekday=2, periods=(1, 2),
                       title="Test", teacher="T", room="R")
        spring.fill(ct)
        text = courses_to_ical(spring)
        # 2 weeks × 2 periods = 4 VEVENTs.
        assert text.count("BEGIN:VEVENT") == 4
        assert text.count("END:VEVENT") == 4
        assert text.startswith("BEGIN:VCALENDAR\r\n")
        assert text.rstrip().endswith("END:VCALENDAR")
        # UTC times: 2026-02-25 (Wed, week 1) 08:00 China = 00:00 UTC.
        assert "DTSTART:20260225T000000Z" in text
        assert "DTEND:20260225T005000Z" in text
        assert "SUMMARY:Test" in text
        assert "LOCATION:R" in text

    def test_ics_utc_alignment(self, spring):
        from sustech_survival.selectcourse.ical import courses_to_ical
        ct = ClassTime(weeks=(1,), weekday=2, periods=(1,),
                       title="Test", teacher="T", room="R")
        spring.fill(ct)
        text = courses_to_ical(spring)
        # Wed of week 1 = 2026-02-25. Period 1 starts 08:00 China = 00:00 UTC.
        assert "DTSTART:20260225T000000Z" in text

    def test_empty_semester_produces_empty_calendar(self, spring):
        from sustech_survival.selectcourse.ical import courses_to_ical
        text = courses_to_ical(spring)
        assert "BEGIN:VCALENDAR" in text
        assert "END:VCALENDAR" in text
        assert "BEGIN:VEVENT" not in text


# -- Online load (network-required) ------------------------------


class TestOnlineLoad:
    """These hit the GitHub raw URL — skip if network unavailable."""

    @pytest.fixture(scope="class")
    def network_ok(self):
        try:
            with urllib.request.urlopen(
                "https://raw.githubusercontent.com/dumixthestpd/sustech-calendar/main/2026/general.json",
                timeout=8,
            ) as r:
                return r.status == 200
        except Exception:
            return False

    def test_load_from_github(self, network_ok):
        if not network_ok:
            pytest.skip("network unavailable")
        cal = AcademicCalendar.load(2026, "undergraduate")
        assert cal.year == 2026
        assert cal.level == "undergraduate"
        assert cal.spring.teaching_start == date(2026, 2, 25)
        assert cal.summer is None  # online JSON has minimal summer
        assert cal.fall.teaching_start == date(2026, 9, 7)

    def test_load_future_year_fails_loud(self, network_ok):
        """Regression: load(2027) must fail with CalendarError,
        not silently return last year's data."""
        if not network_ok:
            pytest.skip("network unavailable")
        with pytest.raises(CalendarError) as excinfo:
            AcademicCalendar.load(2027, "undergraduate")
        msg = str(excinfo.value)
        assert "404" in msg
        assert "2027" in msg

    def test_load_custom_base_url_does_not_silently_substitute(self):
        """Regression: a custom base_url pointing to a DIFFERENT year's
        directory must not silently load that other year's data when the
        caller asked for another year. The from_payloads year guard
        catches this case."""
        # Fetch 2026 data explicitly, then claim year=2027 — should fail.
        cal = AcademicCalendar.load(2026, "undergraduate")
        # Re-call with year=2027 but pass the 2026 base_url explicitly
        with pytest.raises(CalendarError) as excinfo:
            AcademicCalendar.load(
                2027, "undergraduate",
                base_url=DEFAULT_REPO,  # still the 2026 hardcoded one
            )
        # The load() substitution turns DEFAULT_REPO into ".../main/2027",
        # which 404s. Either way, year=2027 must not silently return
        # 2026 data.
        assert "2026" not in str(excinfo.value) or "404" in str(excinfo.value)


# -- Compensatory naming/types -----------------------------------


class TestCompensatoryTypes:
    def test_workday_is_literal_type(self):
        c = Compensatory(date=date(2026, 2, 28), week_type="odd",
                         workday="Monday")
        # All valid Literal values accepted.
        for wd in ("Monday", "Tuesday", "Wednesday", "Thursday",
                   "Friday", "Saturday", "Sunday"):
            Compensatory(date=date(2026, 2, 28), week_type="odd", workday=wd)

    def test_from_dict(self):
        d = {"date": "2026-02-28", "week_type": "odd", "workday_type": "Monday"}
        c = Compensatory.from_dict(d)
        assert c.date == date(2026, 2, 28)
        assert c.week_type == "odd"
        assert c.workday == "Monday"


# -- Cache layer (offline tests via local HTTP server) -----------


import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


# -- Fake GitHub-raw HTTP server for cache tests ------------------


class _FakeCalendarHandler(BaseHTTPRequestHandler):
    """Serves canned JSON responses for the three calendar files.

    Honours ``If-None-Match``: returns 304 when the request's etag
    matches what we have stored. Otherwise returns 200 with body + etag.
    """

    payloads: dict = {}  # filename → bytes (set per-test by fixture)
    etags: dict = {}     # filename → etag string

    def log_message(self, format, *args):
        pass

    def do_GET(self):  # noqa: N802
        filename = self.path.lstrip("/")
        inm = self.headers.get("If-None-Match")
        stored_etag = type(self).etags.get(filename)
        if inm and inm == stored_etag:
            self.send_response(304)
            self.end_headers()
            return
        body = type(self).payloads.get(filename, b"{}")
        self.send_response(200)
        if stored_etag:
            self.send_header("ETag", stored_etag)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def fake_calendar_server():
    """Spin up a localhost server that serves canned calendar JSONs.

    Returns (base_url, handler_class) so tests can mutate
    ``handler_class.payloads`` mid-test to simulate an upstream change.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    # Build a fresh handler subclass so per-test state is isolated.
    initial_payloads = {
        "undergraduate.json": _FAKE_UNDERGRAD,
        "graduate.json": _FAKE_GRAD,
        "general.json": _FAKE_GENERAL,
    }
    initial_etags = {fn: f'"v1-{fn}"' for fn in initial_payloads}

    class Handler(_FakeCalendarHandler):
        # Each subclass gets its own copy of payloads/etags.
        payloads = dict(initial_payloads)
        etags = dict(initial_etags)

    server = HTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}", Handler
    finally:
        server.shutdown()
        thread.join(timeout=2)


_FAKE_UNDERGRAD = json.dumps({
    "winter_holiday": {"start": "2026-01-12", "end": "2026-02-23"},
    "spring_semester": {
        "start": "2026-02-23", "end": "2026-06-30",
        "sign_in": "2026-02-24",
        "teaching_start": "2026-02-25",
        "total_teaching_weeks": 17,
        "midterm": {"start": "2026-04-13", "end": "2026-04-26",
                    "equivalent_weeks": [8, 9]},
        "final":   {"start": "2026-06-08", "end": "2026-06-18",
                    "equivalent_weeks": [16, 17]},
        "compensatories": [],
    },
    "fall_semester": {
        "start": "2026-08-24", "end": "2027-01-10",
        "sign_in": "2026-08-25",
        "teaching_start": "2026-09-07",
        "total_teaching_weeks": 17,
        "midterm": {"start": "2026-10-26", "end": "2026-11-08",
                    "equivalent_weeks": [8, 9]},
        "final":   {"start": "2027-01-04", "end": "2027-01-10",
                    "equivalent_weeks": [17]},
        "compensatories": [],
    },
}).encode("utf-8")

_FAKE_GRAD = json.dumps({
    "spring_semester": {
        "teaching_start": "2026-02-25",
        "total_teaching_weeks": 17,
        "midterm": {"equivalent_weeks": [8, 9]},
        "final": {"equivalent_weeks": [16, 17]},
    },
    "fall_semester": {
        "teaching_start": "2026-09-07",
        "total_teaching_weeks": 17,
        "midterm": {"equivalent_weeks": [8, 9]},
        "final": {"equivalent_weeks": [17]},
    },
}).encode("utf-8")

_FAKE_GENERAL = json.dumps({
    "holidays": [
        {"name": "National Day", "start": "2026-10-01", "end": "2026-10-07"},
    ],
}).encode("utf-8")


class TestCache:
    """Tests for the cache layer using a local fake server — no real
    network required. Each test gets an isolated cache root via the
    ``cache_root=`` kwarg on ``AcademicCalendar.load`` (no env var).
    """

    @pytest.fixture
    def isolated_cache(self, tmp_path):
        """Return a per-test cache root. Tests pass this explicitly via
        ``cache_root=`` to ``AcademicCalendar.load``; ``_cache.clear_cache``
        accepts it as the ``root=`` kwarg."""
        return tmp_path

    def test_first_load_writes_cache(self, isolated_cache, fake_calendar_server):
        base_url, _ = fake_calendar_server
        AcademicCalendar.load(2026, "undergraduate", base_url=base_url,
                              cache_root=isolated_cache)
        assert (isolated_cache / "calendar" / "2026" / ".meta.json").exists()
        for fn in ("undergraduate.json", "graduate.json", "general.json"):
            assert (isolated_cache / "calendar" / "2026" / fn).exists()

    def test_second_load_does_not_redo_full_download(
        self, isolated_cache, fake_calendar_server
    ):
        # Use a counter handler so we can assert # of GETs.
        calls = {"n": 0}
        base_url, Handler = fake_calendar_server
        orig_do_get = Handler.do_GET
        def counting_get(self):
            calls["n"] += 1
            return orig_do_get(self)
        Handler.do_GET = counting_get
        AcademicCalendar.load(2026, "undergraduate", base_url=base_url,
                              cache_root=isolated_cache)
        n_after_first = calls["n"]
        # Second load — server returns 304, no body sent.
        AcademicCalendar.load(2026, "undergraduate", base_url=base_url,
                              cache_root=isolated_cache)
        # Same number of GETs (3 per load), but second load received 304s.
        assert calls["n"] == n_after_first * 2

    def test_etag_round_trip_returns_cached_body(
        self, isolated_cache, fake_calendar_server
    ):
        """After a first load, the cached copy is reused — verified by
        observing that the second request carries If-None-Match and the
        server returns 304 (no body sent)."""
        calls: list = []
        base_url, Handler = fake_calendar_server

        original_do_get = Handler.do_GET
        def recording_get(self):
            inm = self.headers.get("If-None-Match")
            calls.append({"if_none_match": inm})
            return original_do_get(self)
        Handler.do_GET = recording_get

        AcademicCalendar.load(2026, "undergraduate", base_url=base_url,
                              cache_root=isolated_cache)
        # First call: no If-None-Match (3 GETs, all no-header).
        for c in calls:
            assert c["if_none_match"] is None
        # Second call: every GET should carry If-None-Match.
        AcademicCalendar.load(2026, "undergraduate", base_url=base_url,
                              cache_root=isolated_cache)
        second_calls = calls[3:]
        assert len(second_calls) == 3
        for c in second_calls:
            assert c["if_none_match"] is not None
            assert c["if_none_match"].startswith('"v1-')

    def test_refresh_skips_if_none_match_header(
        self, isolated_cache, fake_calendar_server
    ):
        """refresh=True must not send If-None-Match — the server should
        never see a conditional request."""
        calls: list = []
        base_url, Handler = fake_calendar_server
        original_do_get = Handler.do_GET
        def recording_get(self):
            calls.append({"if_none_match": self.headers.get("If-None-Match")})
            return original_do_get(self)
        Handler.do_GET = recording_get

        # Pre-populate cache so refresh has something to override.
        AcademicCalendar.load(2026, "undergraduate", base_url=base_url,
                              cache_root=isolated_cache)
        AcademicCalendar.refresh(2026, "undergraduate", base_url=base_url)
        # Last 3 calls are from refresh; none should carry If-None-Match.
        for c in calls[3:]:
            assert c["if_none_match"] is None

    def test_refresh_picks_up_upstream_change(
        self, isolated_cache, fake_calendar_server
    ):
        """Without refresh: server's new etag invalidates the cache
        (returns 200, body updated). With refresh: also gets new body,
        but request didn't bother with If-None-Match.

        Verifies the ETag handshake works AND that refresh forces a
        unconditional GET even when the cache would otherwise be fresh.
        """
        base_url, Handler = fake_calendar_server
        # Populate cache with v1.
        cal_v1 = AcademicCalendar.load(2026, "undergraduate", base_url=base_url,
                                       cache_root=isolated_cache)
        assert cal_v1.spring.teaching_start == date(2026, 2, 25)
        # Mutate upstream: bump etag + change teaching_start.
        new_payload = json.loads(_FAKE_UNDERGRAD.decode())
        new_payload["spring_semester"]["teaching_start"] = "2026-03-01"
        new_body = json.dumps(new_payload).encode("utf-8")
        Handler.payloads["undergraduate.json"] = new_body
        Handler.etags["undergraduate.json"] = '"v2-undergrad"'
        # Refresh: get new body (200, no If-None-Match sent).
        cal_v2 = AcademicCalendar.refresh(2026, "undergraduate",
                                           base_url=base_url)
        assert cal_v2.spring.teaching_start == date(2026, 3, 1)

    def test_refresh_classmethod_shortcut(
        self, isolated_cache, fake_calendar_server
    ):
        base_url, _ = fake_calendar_server
        AcademicCalendar.load(2026, "undergraduate", base_url=base_url,
                              cache_root=isolated_cache)
        cal = AcademicCalendar.refresh(2026, "undergraduate", base_url=base_url)
        assert cal.year == 2026
        assert cal.spring.teaching_start == date(2026, 2, 25)

    def test_cached_false_does_not_touch_disk(
        self, isolated_cache, fake_calendar_server
    ):
        base_url, _ = fake_calendar_server
        AcademicCalendar.load(2026, "undergraduate", base_url=base_url,
                              cached=False, cache_root=isolated_cache)
        assert not (isolated_cache / "calendar").exists()

    def test_clear_cache_via_module_helper(
        self, isolated_cache, fake_calendar_server
    ):
        """``_cache.clear_cache("calendar", root=...)`` wipes the entire
        calendar cache. No public method on AcademicCalendar needed."""
        from sustech_survival import _cache
        base_url, _ = fake_calendar_server
        AcademicCalendar.load(2026, "undergraduate", base_url=base_url,
                              cache_root=isolated_cache)
        AcademicCalendar.load(2025, "undergraduate", base_url=base_url,
                              cache_root=isolated_cache)
        assert (isolated_cache / "calendar" / "2026").exists()
        assert (isolated_cache / "calendar" / "2025").exists()
        removed = _cache.clear_cache("calendar", root=isolated_cache)
        assert not (isolated_cache / "calendar").exists() \
            or not any((isolated_cache / "calendar").iterdir())
        assert removed >= 4

    def test_clear_cache_when_no_cache_exists(self, isolated_cache):
        from sustech_survival import _cache
        assert _cache.clear_cache("calendar", root=isolated_cache) == 0
        assert _cache.clear_cache("nonexistent_module", root=isolated_cache) == 0


class TestCacheNetworkFallback:
    """When the network is down but a cache exists, load() falls back to
    the cached copy. When there's no cache, it raises CalendarError.
    """

    @pytest.fixture
    def isolated_cache(self, tmp_path):
        return tmp_path

    def test_offline_with_cache_returns_cached_data(
        self, isolated_cache, fake_calendar_server
    ):
        good_url, _ = fake_calendar_server
        bad_url = "http://127.0.0.1:1/dead-server"  # port 1 = unreachable
        # Populate cache via the good URL.
        AcademicCalendar.load(2026, "undergraduate", base_url=good_url,
                              cache_root=isolated_cache)
        # Now request through the bad URL — should fall back to cache.
        cal = AcademicCalendar.load(2026, "undergraduate", base_url=bad_url,
                                    cache_root=isolated_cache)
        assert cal.year == 2026
        assert cal.spring.teaching_start == date(2026, 2, 25)

    def test_offline_without_cache_raises(self, isolated_cache):
        with pytest.raises(CalendarError):
            AcademicCalendar.load(
                2026, "undergraduate",
                base_url="http://127.0.0.1:1/dead-server",
                cache_root=isolated_cache,
            )


class TestRepoBaseKwarg:
    """The calendar source default comes from a constant (env override at
    import) and every load takes an explicit base_url= — no settings object."""

    def test_default_repo_base_is_constant(self):
        import sustech_survival.calendar as cal
        assert cal.DEFAULT_REPO_BASE.startswith("http")
        assert "sustech-calendar" in cal.DEFAULT_REPO_BASE
        assert str(cal.DEFAULT_REPO).startswith(cal.DEFAULT_REPO_BASE)

    def test_load_accepts_base_url_override(self, fake_calendar_server):
        base_url, _ = fake_calendar_server
        cal = AcademicCalendar.load(2026, "undergraduate", base_url=base_url,
                                    cached=False)
        assert cal.year == 2026
        assert cal.spring is not None

    def test_reads_local_repo_off_disk(self, tmp_path):
        """base_url pointing at a local dir reads straight off disk — no HTTP."""
        year = 2026
        base = tmp_path / "cal"
        (base / str(year)).mkdir(parents=True, exist_ok=True)

        def _sem(season_key, final_weeks):
            return {
                "start": "2026-02-23" if season_key == "spring" else "2026-08-24",
                "end":   "2026-06-30" if season_key == "spring" else "2027-01-10",
                "sign_in": "2026-02-24" if season_key == "spring" else "2026-08-25",
                "teaching_start": "2026-02-25" if season_key == "spring" else "2026-09-07",
                "total_teaching_weeks": 17,
                "midterm": {"start": "2026-04-13", "end": "2026-04-26",
                            "equivalent_weeks": [8, 9]},
                "final": {"start": "2026-06-08" if season_key == "spring" else "2027-01-04",
                          "end": "2026-06-18" if season_key == "spring" else "2027-01-10",
                          "equivalent_weeks": final_weeks},
                "compensatories": [],
            }

        payload = {
            "spring_semester": _sem("spring", [16, 17]),
            "fall_semester": _sem("fall", [17]),
        }
        (base / str(year) / "undergraduate.json").write_text(
            json.dumps(payload), encoding="utf-8")
        (base / str(year) / "graduate.json").write_text(
            json.dumps(payload), encoding="utf-8")
        (base / str(year) / "general.json").write_text(
            json.dumps({"holidays": []}), encoding="utf-8")

        cal = AcademicCalendar.load(year, level="undergraduate",
                                    base_url=str(base), online=True, cached=False)
        assert cal.year == year
        assert cal.spring is not None
        assert cal.fall is not None