"""
sustech_survival.selectcourse.ical — enrolled classes to iCalendar (.ics) export.

Pure transform. Takes a Semester whose ``classes`` list has been populated
via ``semester.fill(...)``, and returns a text/calendar string with one
VEVENT per (class, date, period).

Usage::

    from sustech_survival.calendar import AcademicCalendar, ClassTime
    from sustech_survival.selectcourse.ical import courses_to_ical

    cal = AcademicCalendar.load(2026, "undergraduate")
    sem = cal.spring
    sem.fill(ClassTime(weeks=(1, 3, 5, ..., 17), weekday=0,
                       periods=(1, 2), title="...", teacher="...", room="..."))
    ical_text = courses_to_ical(sem)

No Flask, no HTTP, no fetch — pure data in, string out.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional

from ..calendar import ClassTime, Semester


__all__ = ["courses_to_ical", "PERIOD_START_TIMES"]


# Default SUSTech 50-minute class period start times (morning block has a
# 20-minute break between periods 2 and 3, otherwise 10 min).
PERIOD_START_TIMES: dict[int, tuple[int, int]] = {
    1:  ( 8,  0),
    2:  ( 9,  0),
    3:  (10, 20),
    4:  (11, 20),
    5:  (13, 30),
    6:  (14, 30),
    7:  (15, 30),
    8:  (16, 30),
    9:  (18,  0),
    10: (19,  0),
    11: (20,  0),
    12: (21,  0),
}
PERIOD_DURATION_MIN = 50

CHINA_TZ = timezone(timedelta(hours=8))


def _period_start(d: date, period: int) -> datetime:
    h, m = PERIOD_START_TIMES.get(period, (8, 0))
    return datetime(d.year, d.month, d.day, h, m, tzinfo=CHINA_TZ)


def _fmt_dt(dt: datetime) -> str:
    """Format datetime for ICS in UTC, basic format."""
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _escape(text: str) -> str:
    """Escape RFC 5545 special chars in TEXT values."""
    return (text.replace("\\", "\\\\")
                .replace(";", r"\;")
                .replace(",", r"\,")
                .replace("\n", r"\n"))


def _week_num(d: date, semester: Semester) -> int:
    return ((d - semester.teaching_start).days // 7) + 1


def courses_to_ical(semester: Semester, *, cal_name: Optional[str] = None) -> str:
    """Build a complete VCALENDAR with one VEVENT per (class, date, period)."""
    name = cal_name or f"SUSTech {semester.human}"
    lines: list[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//sustech_survival//calendar//EN",
        f"X-WR-CALNAME:{_escape(name)}",
        "CALSCALE:GREGORIAN",
    ]
    for i, ct in enumerate(semester.classes):
        uid_seed = f"c{i}-{_escape(ct.title) or 'class'}"
        for d in semester.dates(ct):
            for p in ct.periods:
                start = _period_start(d, p)
                end = start + timedelta(minutes=PERIOD_DURATION_MIN)
                summary = ct.title or "Class"
                desc_parts: list[str] = []
                if ct.teacher:
                    desc_parts.append(f"Teacher: {ct.teacher}")
                desc_parts.append(f"Week {_week_num(d, semester)}")
                description = " | ".join(desc_parts)
                uid = f"{uid_seed}-{d.isoformat()}-p{p}@sustech_survival"
                lines.append("BEGIN:VEVENT")
                lines.append(f"UID:{uid}")
                lines.append(f"DTSTAMP:{_fmt_dt(datetime.now(timezone.utc))}")
                lines.append(f"DTSTART:{_fmt_dt(start)}")
                lines.append(f"DTEND:{_fmt_dt(end)}")
                lines.append(f"SUMMARY:{_escape(summary)}")
                if ct.room:
                    lines.append(f"LOCATION:{_escape(ct.room)}")
                lines.append(f"DESCRIPTION:{_escape(description)}")
                lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"