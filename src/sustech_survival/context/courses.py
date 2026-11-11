"""Per-course session dates — "when is course X's next / last session?".

Answers the report-writing question the schedule snapshot can't: a SPECIFIC
course's upcoming / most recent meeting date + academic week (the context
snapshot only names whichever class is next overall). The academic week comes
from TIS (``current_week``), never from the user.

Read-only: queries the personal TIS timetable. No writes, no BB.

Sources: :func:`sustech_survival.tis.schedule.semester_schedule` — the same
personal timetable the context module uses for its class reminders.

TIS timetable row fields::

    SKSJ / SKSJ_EN   course name on the first line (Chinese / EN block)
    KEY              "xq{day}_jc{period}" e.g. "xq3_jc1" = Wed 1st slot
    KSJC / JSJC      first / last period numbers of the session
    ZC               36-char week bitmap — char w-1 == '1' ⇒ runs in week w

Parallel rows (several groups of the same course, e.g. 4 lab groups) collapse
into one session per (date, periods).
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Optional

from sustech_survival.context import CHINA_TZ

_WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _now() -> datetime:
    from sustech_survival.context import OVERRIDE_TIME, now_

    return now_()


def _anchor_monday(zc_now: int, today: date) -> date:
    """Monday of academic week 1.

    Prefers the academic calendar — authoritative, and week 1 always starts on
    a Monday even when teaching begins mid-week. Falls back to deriving it from
    TIS's current week + today, which only holds while ``today`` really is
    inside week ``zc_now`` (a stale week number or an injected clock date
    shifts every session date otherwise).
    """
    try:
        from sustech_survival.context import calendar_term
        sem = calendar_term(today)
        if sem is not None:
            return sem.date_of(1, 0)
    except Exception:
        pass
    monday_now = today - timedelta(days=today.weekday())
    return monday_now - timedelta(weeks=zc_now - 1)


def _row_name(row: dict) -> str:
    raw = (row.get("SKSJ") or "").split("\n")[0]
    if not raw.strip():
        raw = (row.get("SKSJ_EN") or "").split("\n")[0]
    return raw.strip()


def session_rows(rows: list, anchor: date) -> list:
    """Expand timetable rows into dated sessions (deduplicated, sorted).

    Each returned item: {"course", "date", "week", "periods": (ks, js)}.
    """
    out = []
    for row in rows:
        key = row.get("KEY") or ""
        m = re.fullmatch(r"xq(\d+)_jc(\d+)", key)
        if not m:
            continue
        day = int(m.group(1))
        ks = int(row.get("KSJC") or 0)
        js = int(row.get("JSJC") or 0)
        zc = row.get("ZC") or ""
        # TIS ZC bitmap: char at index i == '1' means the course meets in
        # week i (index 0 is a leading pad — courses that meet in week 1
        # carry '0' there, e.g. '01111...' = weeks 1,2,3,4...). Verified
        # against a live term: a Monday class of week 1 exists while
        # zc[0] == '0', so an i+1 mapping would shift every session one
        # week late (even weeks instead of odd).
        for w in (i for i, ch in enumerate(zc) if ch == "1" and i >= 1):
            d = anchor + timedelta(weeks=w - 1, days=day - 1)
            out.append({"course": _row_name(row), "date": d, "week": w,
                        "periods": (ks, js)})
    seen = set()
    uniq = []
    for s in out:
        k = (s["course"], s["date"], s["periods"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(s)
    return sorted(uniq, key=lambda s: (s["date"], s["periods"][0] or 99))


def match_courses(sessions: list, query: str) -> list:
    """Fuzzy course-name match (substring, both directions, case-folded)."""
    q = query.strip().lower()
    names = sorted({s["course"] for s in sessions})
    if not q:
        return []
    return [n for n in names if q in n.lower() or n.lower() in q]


def _load(course_query: str, now: Optional[datetime] = None) -> dict:
    """Fetch the semester timetable and resolve the course.

    ``now`` is the injectable clock (defaults to the real one) — it must reach
    the week anchor too, or an injected date filters session dates built from a
    different week's grid.

    Returns {"course": <matched full name>, "sessions": [...], "zc_now": n}.
    Raises ValueError with the available course list when nothing matches, or
    when the query is ambiguous.
    """
    from sustech_survival.tis.schedule import current_week, semester_schedule

    zc_now = int(current_week())
    today = (now or _now()).date()
    anchor = _anchor_monday(zc_now, today)
    sessions = session_rows(semester_schedule(), anchor)
    hits = match_courses(sessions, course_query)
    if not hits:
        avail = ", ".join(sorted({s["course"] for s in sessions})) or "(no courses)"
        raise ValueError(f"no course matches {course_query!r} — your courses: {avail}")
    if len(hits) > 1:
        raise ValueError(
            f"course query {course_query!r} is ambiguous — matches: {', '.join(hits)}"
        )
    return {"course": hits[0], "sessions": sessions, "zc_now": zc_now}


def _session_end(s: dict) -> datetime:
    """When a session ends (CHINA_TZ): the end of its last period.

    Falls back to the end of its day when the period has no known time.
    """
    from sustech_survival.tis.exams import _PERIOD_TIMES

    d = s["date"]
    slot = _PERIOD_TIMES.get(s["periods"][1]) or _PERIOD_TIMES.get(s["periods"][0])
    if slot:
        hh, mm = (int(x) for x in slot.split("-")[1].split(":"))
        return datetime(d.year, d.month, d.day, hh, mm, tzinfo=CHINA_TZ)
    return datetime(d.year, d.month, d.day, tzinfo=CHINA_TZ) + timedelta(days=1)


def course_when(course_query: str, when: str,
                now: Optional[datetime] = None) -> dict:
    """Find the next / last session of a course.

    Args:
        course_query: fuzzy course name (Chinese or English substring).
        when: "next" (the first session that has not ended yet) or
            "last" (<= today).
        now: injectable "today" for tests.

    Returns:
        {"course", "when", "session": {...}|None, "zc_now",
         "reason": "...", "edge": first-or-last session for context}
    """
    data = _load(course_query, now)
    sessions = [s for s in data["sessions"] if s["course"] == data["course"]]
    current = now or _now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=CHINA_TZ)
    today = current.date()
    if when == "next":
        # A session earlier today that has already ended is not "next".
        upcoming = [s for s in sessions if _session_end(s) > current]
        pick = upcoming[0] if upcoming else None
        reason = "no more sessions this semester" if not pick else None
        edge = sessions[-1] if sessions else None  # last ever (for context)
    elif when == "last":
        past = [s for s in sessions if s["date"] <= today]
        pick = past[-1] if past else None
        reason = "no session yet this term" if not pick else None
        edge = sessions[0] if sessions else None  # first ever (for context)
    else:  # pragma: no cover - CLI restricts choices
        raise ValueError(f"when must be 'next' or 'last', got {when!r}")
    return {"course": data["course"], "when": when, "session": pick,
            "reason": reason, "zc_now": data["zc_now"], "edge": edge}


def _fmt_session(s: dict) -> str:
    d = s["date"]
    wd = _WEEKDAY_NAMES[d.weekday()]
    ks, js = s["periods"]
    periods = f"第{ks}-{js}节" if js > ks else f"第{ks}节" if ks else ""
    return f"{d.isoformat()} ({wd}) Week {s['week']}" + (f", {periods}" if periods else "")


def render(course_query: str, when: str,
           now: Optional[datetime] = None) -> dict:
    """Human + machine friendly result for the CLI.

    Returns a dict safe for JSON output and a ``text`` line for humans.
    """
    try:
        res = course_when(course_query, when, now=now)
    except ValueError as e:
        return {"ok": False, "error": str(e), "text": f"❌ {e}"}
    s = res["session"]
    if s:
        text = f"{res['course']} — {res['when']} session: {_fmt_session(s)}"
        out = {"ok": True, "course": res["course"], "when": res["when"],
               "date": s["date"].isoformat(), "week": s["week"],
               "periods": list(s["periods"]), "text": text}
    else:
        edge = res["edge"]
        hint = (_fmt_session(edge) if edge else "—")
        text = (f"{res['course']} — {res['reason']}"
                + (f"; {'next' if res['when']=='last' else 'last'}: {hint}"
                   if edge else ""))
        out = {"ok": True, "course": res["course"], "when": res["when"],
               "session": None, "reason": res["reason"],
               "edge_date": edge["date"].isoformat() if edge else None,
               "edge_week": edge["week"] if edge else None,
               "text": text}
    return out
