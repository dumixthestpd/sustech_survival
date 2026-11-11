"""
sustech_survival.context — single source of truth for "what's happening right now".

.. note:: CONSEQUENCE-FREE. This module is strictly read-only — it queries
   TIS/BB/weather/AQI and never mutates any student state. It is the safe
   surface for an agent to gather context without risk (see
   ``sustech_survival.consequence`` for the write ops that DO carry risk).

The `Context` class with tiered exporters:

    terse   - date, time, week, weekday, class_now  (sync, ≤1ms)
    normal  - terse + next_deadline, next_eval      (≤2s)
    verbose - normal + weather, aqi, library_status (≤5s)

Usage:
    from sustech_survival import Context
    ctx = Context()
    print(ctx.to_str(level="terse"))   # instant, no I/O
    print(ctx.weather_cond)           # lazy fetch

For testing:
    Context(level="terse", dt=datetime(2026, 5, 29, 14, 30, tzinfo=CHINA_TZ))
    Context(level="normal", time=1717000000.0)
    # OR set module-level OVERRIDE_TIME = <unix_ts>
"""
from __future__ import annotations
from .. import _net

import json
import re
import time as _time_module
from datetime import date, datetime, timezone, timedelta
from enum import Enum
from typing import Optional, Union


# -- Shared constants ------------------------------------------------------

CHINA_TZ = timezone(timedelta(hours=8))
SUSTECH_LAT = 22.6029
SUSTECH_LON = 113.9283


# -- Academic calendar -----------------------------------------------------

ACADEMIC_CALENDARS = {
    "2026 Spring": {
        "semester_start": "2026-02-24",
        "spring_break": ("2026-04-04", "2026-04-12"),
        "semester_end": "2026-06-28",
        "summer_start": "2026-06-29",
    },
    "2025 Fall": {
        "semester_start": "2025-09-01",
        "spring_break": None,
        "semester_end": "2025-12-28",
        "summer_start": "2025-12-29",
    },
}


# -- China holidays --------------------------------------------------------

HOLIDAY_DATA = {
    2026: {
        "2026-01-01": "New Year's Day",
        "2026-01-28": "Spring Festival",
        "2026-01-29": "Spring Festival",
        "2026-01-30": "Spring Festival",
        "2026-01-31": "Spring Festival",
        "2026-02-01": "Spring Festival",
        "2026-02-02": "Spring Festival",
        "2026-02-03": "Spring Festival",
        "2026-04-04": "Qingming Festival",
        "2026-04-05": "Qingming Festival",
        "2026-04-06": "Qingming Festival",
        "2026-05-01": "Labor Day",
        "2026-05-02": "Labor Day",
        "2026-05-03": "Labor Day",
        "2026-05-04": "Labor Day",
        "2026-05-05": "Labor Day",
        "2026-06-22": "Dragon Boat Festival",
        "2026-06-23": "Dragon Boat Festival",
        "2026-06-24": "Dragon Boat Festival",
        "2026-09-25": "Mid-Autumn Festival",
        "2026-09-26": "Mid-Autumn Festival",
        "2026-09-27": "Mid-Autumn Festival",
        "2026-10-01": "National Day",
        "2026-10-02": "National Day",
        "2026-10-03": "National Day",
        "2026-10-04": "National Day",
        "2026-10-05": "National Day",
        "2026-10-06": "National Day",
        "2026-10-07": "National Day",
        "2026-10-08": "National Day",
        "2026-02-08": "adjust",
        "2026-02-28": "adjust",
        "2026-04-26": "adjust",
        "2026-09-26": "adjust",
    },
    2025: {
        "2025-01-01": "New Year's Day",
        "2025-01-28": "Spring Festival",
        "2025-01-29": "Spring Festival",
        "2025-01-30": "Spring Festival",
        "2025-01-31": "Spring Festival",
        "2025-02-01": "Spring Festival",
        "2025-02-02": "Spring Festival",
        "2025-02-03": "Spring Festival",
        "2025-02-04": "Spring Festival",
        "2025-04-04": "Qingming Festival",
        "2025-04-05": "Qingming Festival",
        "2025-04-06": "Qingming Festival",
        "2025-05-01": "Labor Day",
        "2025-05-02": "Labor Day",
        "2025-05-03": "Labor Day",
        "2025-05-04": "Labor Day",
        "2025-05-05": "Labor Day",
        "2025-06-02": "Dragon Boat Festival",
        "2025-09-15": "Mid-Autumn Festival",
        "2025-09-16": "Mid-Autumn Festival",
        "2025-09-17": "Mid-Autumn Festival",
        "2025-10-01": "National Day",
        "2025-10-02": "National Day",
        "2025-10-03": "National Day",
        "2025-10-04": "National Day",
        "2025-10-05": "National Day",
        "2025-10-06": "National Day",
        "2025-10-07": "National Day",
        "2025-10-08": "National Day",
    },
}


# -- Time override (for testing / predictions / tracebacks) ---------------

OVERRIDE_TIME: Union[float, None] = None
"""If set, all schedule-aware computations use this Unix timestamp instead of now."""


def now_() -> datetime:
    """Return datetime.now(CHINA_TZ), or overridden time if set."""
    if OVERRIDE_TIME is not None:
        return datetime.fromtimestamp(OVERRIDE_TIME, tz=CHINA_TZ)
    return datetime.now(CHINA_TZ)


# -- Levels ----------------------------------------------------------------

class Level(str, Enum):
    TERSE = "terse"
    NORMAL = "normal"
    VERBOSE = "verbose"


_LEVEL_ORDER = {Level.TERSE: 0, Level.NORMAL: 1, Level.VERBOSE: 2}


# -- Network helpers (module-level, shared) -------------------------------

def fetch_json(url: str, timeout: int = 10) -> Optional[dict]:
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "SUSTechContext/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def aqi_level(aqi: int) -> str:
    return "unavailable"


def aqi_icon(aqi: int) -> str:
    return "—"


def fetch_weather() -> Optional[dict]:
    """Fetch current weather from api.sustech.online (SUSTech CRA official API).

    API: https://api.sustech.online/weather
    Response: {"msg": "南科大天气：气温26.8℃，体感29.1℃，近两个小时内无降雨。",
               "update_time": "2026-05-29T23:20:49.795395+08:00", "code": 602}
    """
    try:
        import urllib.request

        url = "https://api.sustech.online/weather"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=_net.service_timeout("context")) as resp:
            data = json.load(resp)

        raw = data.get("msg", "")
        temp_match = re.search(r"气温([0-9.]+)℃", raw)
        feels_match = re.search(r"体感([0-9.]+)℃", raw)

        return {
            "temp_c": round(float(temp_match.group(1))) if temp_match else None,
            "feels_like": round(float(feels_match.group(1))) if feels_match else None,
            "condition": raw,
        }
    except Exception:
        return None


def fetch_aqi() -> Optional[dict]:
    url = (
        f"https://air-quality-api.open-meteo.com/v1/air-quality"
        f"?latitude={SUSTECH_LAT}&longitude={SUSTECH_LON}"
        f"&current=us_aqi,pm2_5,pm10,ozone"
        f"&timezone=Asia/Shanghai"
    )
    data = fetch_json(url)
    if not data:
        return None
    cur = data["current"]
    aqi = cur["us_aqi"]
    return {
        "aqi": aqi,
        "aqi_level": aqi_level(aqi),
        "pm2_5": cur.get("pm2_5"),
        "pm10": cur.get("pm10"),
    }


def fetch_library_status() -> str:
    """Fetch real-time open/closed status from lib.sustech.edu.cn."""
    try:
        import urllib.request
        req = urllib.request.Request(
            "https://lib.sustech.edu.cn/",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=_net.service_timeout("library")) as resp:
            html = resp.read().decode("utf-8")

        rooms = re.findall(
            r'<span class="name">([^<]+)</span><span class="now">([^<]+)</span>',
            html,
        )
        if not rooms:
            return "Unknown"
        return ", ".join(f"{name}: {status}" for name, status in rooms)
    except Exception:
        return "Unknown"


# -- Schedule helpers (used by class_now) ---------------------------------

# Calendar/term/slot caches — one TIS fetch + one calendar load per process.
_CALENDAR_CACHE: dict = {}
_TERM_CACHE: dict = {}
_SLOT_CACHE: dict = {}


def _calendar_for(d: date):
    """The ``AcademicCalendar`` covering ``d``, or None when it can't be loaded.

    Tries the date's own year, then the academic-year start — a fall term that
    runs into January is filed under the previous calendar year, so January and
    February dates may legitimately belong to ``d.year - 1``.

    The previous year's calendar is only accepted for those Jan/Feb dates. A
    calendar answers for whatever date it is handed, so returning it
    unconditionally turned "the 2026 calendar could not be fetched" into a
    confident "no holiday here" for a 2026 date — and left the bundled
    ``HOLIDAY_DATA`` snapshot, the intended fallback, unused.
    """
    from sustech_survival.calendar import AcademicCalendar
    for year in (d.year, d.year - 1):
        if year not in _CALENDAR_CACHE:
            try:
                _CALENDAR_CACHE[year] = AcademicCalendar.load(year)
            except Exception:
                continue          # not cached — a transient failure may retry
        if year == d.year or d.month <= 2:
            return _CALENDAR_CACHE[year]
    return None


def calendar_term(d: date):
    """The academic-calendar Semester covering ``d``, with TIS classes filled in.

    The calendar owns date intelligence (holidays, 补课 transfer, week parity,
    final weeks). This is the single entry point the reminder uses, so class
    reporting can't drift from 校历. None when the calendar can't be loaded.
    """
    cal = _calendar_for(d)
    if cal is None:
        return None
    sem = cal.day(d).semester
    if sem is None:
        return None
    key = (getattr(sem, "xn", ""), getattr(sem, "xq", ""))
    if key not in _TERM_CACHE:
        _TERM_CACHE[key] = sem
        try:
            from sustech_survival.tis.schedule import class_times
            for ct in class_times(sem.xn, sem.xq):
                sem.fill(ct)
        except Exception:
            pass      # feed down: dates still work, classes come up empty
    return _TERM_CACHE[key]


def _period_minutes(ks: int, js: int, st: dict):
    """(start, end) minutes-of-day for periods ks..js, from the slot grid."""
    if ks not in st or js not in st:
        return None
    start, end = st[ks][0], st[js][1]
    try:
        return (int(start[:2]) * 60 + int(start[3:]),
                int(end[:2]) * 60 + int(end[3:]))
    except (ValueError, IndexError):
        return None


def _hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _detail(span: tuple, room: str = "", when: str = "") -> str:
    """'10:20-12:10 · 一教526' — date-prefixed when the class isn't today."""
    text = f"{_hhmm(span[0])}-{_hhmm(span[1])}"
    return " · ".join(bit for bit in (when, text, room) if bit)


def _slot_grid(d: date) -> dict:
    """50-minute slot grid (cached per ISO week)."""
    key = d.isocalendar()[:2]
    if key not in _SLOT_CACHE:
        try:
            from sustech_survival.tis.schedule import current_week
            week = current_week()
        except Exception:
            week = 1
        try:
            _SLOT_CACHE[key] = slot_times(week)
        except Exception:
            _SLOT_CACHE[key] = {}
    return _SLOT_CACHE[key]


def _next_class(now: datetime, sem, st: dict, horizon_days: int = 21) -> dict:
    """First class at or after ``now``, scanning the calendar day by day.

    Because it asks the calendar per day, holidays, extra breaks, final weeks
    and empty weekends are skipped and 补课 days are honoured.
    """
    today = now.date()
    total_min = now.hour * 60 + now.minute
    for offset in range(horizon_days + 1):
        d = today + timedelta(days=offset)
        day = sem.day(d)
        if not day.has_class():
            continue
        for ct in sorted(day.schedule, key=lambda c: min(c.periods or (99,))):
            if not ct.periods:
                continue
            span = _period_minutes(min(ct.periods), max(ct.periods), st)
            if span is None or (offset == 0 and total_min > span[1]):
                continue          # no grid for it, or already over today
            when = "" if offset == 0 else d.strftime("%a %Y-%m-%d")
            return {"next": ct.title, "next_detail": _detail(span, ct.room, when)}
    return {}


def slot_times(zc: int) -> dict:
    """Fetch actual 50-min slot start/end times from queryKbjg.

    Returns {slot_num: (kssj, jssj)} e.g. {1: ('08:00', '08:50'), 3: ('10:20', '11:10')}.
    Returns {} if auth fails (caller handles gracefully).

    Auth is NOT silently swallowed — if refresh fails this raises AuthorizerError
    so the caller (Context.class_now) surfaces it to the agent.
    """
    from sustech_survival.sso import TISAuth
    from sustech_survival.sso.authorizer import AuthorizerError
    from sustech_survival.semester import Semester
    try:
        auth = TISAuth()
        if not auth.refresh():
            raise AuthorizerError("TIS auth refresh failed — check credentials.txt")
        session = auth.session
        sem = Semester.current()
        resp = session.post(
            'https://tis.sustech.edu.cn/component/queryKbjg',
            data={'xn': sem.xn, 'xq': sem.xq, 'zc': str(zc)},
            timeout=_net.service_timeout("tis"),
        )
        content = resp.json().get('content', [])
        return {int(e['xj']): (e['kssj'], e['jssj']) for e in content}
    except AuthorizerError:
        raise
    except Exception:
        return {}


def entry_time_range(entry: dict, slot_times_: dict) -> Optional[tuple]:
    """Return (start_min, end_min) for an entry based on KSJC/JSJC."""
    ks = int(entry.get('KSJC', 0) or 0)
    js = int(entry.get('JSJC', 0) or 0)
    if ks <= 0 or js <= 0:
        return None
    if ks not in slot_times_ or js not in slot_times_:
        return None
    kssj, jssj = slot_times_[ks][0], slot_times_[js][1]
    h, m = int(kssj[:2]), int(kssj[3:])
    start_min = h * 60 + m
    h, m = int(jssj[:2]), int(jssj[3:])
    end_min = h * 60 + m
    return (start_min, end_min)


def entry_name(entry: dict) -> str:
    return (entry.get('SKSJ', '').split('\n')[0]
            or entry.get('SKSJ_EN', '').split('\n')[0]
            or '')


def get_schedule_reminder(ts: float) -> dict:
    """Compute the class reminder for Unix timestamp ``ts``.

    Calendar-aware: holiday / 补课 / break / final-week status comes from the
    academic calendar, so a Sunday running Friday's makeup schedule reports
    Friday's classes and a weekday holiday reports none. Falls back to the
    weekday-grid heuristic only when the calendar can't be loaded.

    Returns dict:
      {'now': str}                            — class happening right now
      {'next': str, 'next_detail': str}       — next class (today or later)
      {}                                      — no class within 3 weeks
    """
    try:
        now = datetime.fromtimestamp(ts, tz=CHINA_TZ)
        sem = calendar_term(now.date())
        if sem is None or not getattr(sem, "classes", None):
            # No calendar / no class feed — the old weekday-grid heuristic.
            return _legacy_reminder(ts)

        st = _slot_grid(now.date())
        total_min = now.hour * 60 + now.minute
        today = sem.day(now.date())

        if today.has_class() and today.schedule:
            meetings = sorted(today.schedule,
                              key=lambda c: min(c.periods or (99,)))
            for ct in meetings:
                span = _period_minutes(min(ct.periods), max(ct.periods), st)
                if span and span[0] <= total_min <= span[1]:
                    return {"now": ct.title}
            for ct in meetings:
                span = _period_minutes(min(ct.periods), max(ct.periods), st)
                if span and total_min < span[0]:
                    return {"next": ct.title,
                            "next_detail": _detail(span, ct.room)}
        return _next_class(now, sem, st)
    except Exception:
        try:
            return _legacy_reminder(ts)
        except Exception:
            return {}


def _legacy_reminder(ts: float) -> dict:
    """Weekday-grid fallback: today's rows by weekday number, no calendar."""
    try:
        from sustech_survival.tis.schedule import week_schedule, current_week

        now = datetime.fromtimestamp(ts, tz=CHINA_TZ)
        wd = now.weekday()        # 0=Mon
        h, m = now.hour, now.minute
        total_min = h * 60 + m
        is_night = h >= 19 or h < 6

        zc = current_week()
        week = week_schedule(zc)
        st = slot_times(zc)

        today_entries = []
        for entry in week:
            key = entry.get('KEY', '')
            if not key.startswith('xq') or '_jc' not in key:
                continue
            parts = key.split('_')
            if len(parts) != 2:
                continue
            try:
                day = int(parts[0][2:])
            except (ValueError, IndexError):
                continue
            if day != wd + 1:
                continue
            tr = entry_time_range(entry, st)
            today_entries.append((tr, entry))

        today_entries.sort(key=lambda x: (x[0][0] if x[0] else 99999))

        for tr, entry in today_entries:
            if tr is None:
                continue
            start_min, end_min = tr
            if start_min <= total_min <= end_min:
                return {"now": entry_name(entry)}

        if is_night:
            try:
                tomorrow_wd = (wd + 1) % 7
                morning = []
                for entry in week_schedule(zc):
                    key = entry.get('KEY', '')
                    if not key.startswith('xq') or '_jc' not in key:
                        continue
                    parts = key.split('_')
                    try:
                        day = int(parts[0][2:])
                    except ValueError:
                        continue
                    if day != tomorrow_wd + 1:
                        continue
                    ks = int(entry.get('KSJC', 0) or 0)
                    if ks in (1, 2):
                        morning.append((ks, entry_name(entry)))
                if morning:
                    morning.sort()
                    periods_str = " / ".join(f"第{ks}节" for ks, _ in morning)
                    names = " / ".join(name for _, name in morning)
                    return {"tomorrow_morning": f"{names} ({periods_str})"}
            except Exception:
                pass

        for tr, entry in today_entries:
            if tr is None:
                continue
            start_min, end_min = tr
            if total_min < start_min:
                ks = int(entry.get('KSJC', 0) or 0)
                js = int(entry.get('JSJC', 0) or 0)
                kssj = st.get(ks, ('??', '??'))[0] if ks else '??'
                jssj = st.get(js, ('??', '??'))[1] if js else '??'
                detail = f"{kssj}-{jssj}" if kssj != '??' else f"第{ks}-{js}节"
                return {"next": entry_name(entry), "next_detail": detail}

        return {}
    except Exception:
        return {}


# -- BB deadline / TIS eval fetchers ---------------------------------------

def fetch_next_deadline() -> Optional[dict]:
    """Get nearest BB assignment with due date. Returns {name, due, days_left}.

    On auth failure returns {"error": "auth", "hint": "sustech sso check"} so agents
    know exactly what to do without guessing.
    """
    from sustech_survival.bb.ddl import upcoming_deadlines
    from sustech_survival.exceptions import SessionExpired
    from sustech_survival.sso import BBAuth
    try:
        deadlines = upcoming_deadlines(days=30)
        if deadlines:
            d = deadlines[0]
            return {"name": d["name"], "due": d["due"], "days_left": d["days_left"]}
        return None
    except SessionExpired as e:
        return {"error": "auth", "message": str(e), "hint": "sustech sso check"}
    except Exception as e:
        return {"error": "unavailable", "message": str(e), "source": "bb"}


def _clock_time(text: str) -> Optional[tuple]:
    """``"09:00"`` -> ``(9, 0)``; None when it is not an HH:MM time."""
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", text or "")
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return None
    return int(m.group(1)), int(m.group(2))


def _slot_times(slot: str) -> tuple:
    """``"09:00-11:00"`` -> ``((9, 0), (11, 0))``; either side None if unreadable."""
    start, _, end = (slot or "").partition("-")
    return _clock_time(start), _clock_time(end)


def _exam_window(exam: dict) -> Optional[tuple]:
    """(start, end) datetimes of a TIS exam in CHINA_TZ, or None without a date.

    Times come from KSJTSJ (``"09:00-11:00"``) and fall back to the KSJC/JSJC
    period times. An unknown start is the start of the day and an unknown end
    the end of the day, so an exam is never dropped before its day is over.
    """
    from sustech_survival.tis.exams import _PERIOD_TIMES

    try:
        day = date.fromisoformat((exam.get("KSRQ") or "")[:10])
    except ValueError:
        return None
    start, end = _slot_times(exam.get("KSJTSJ") or "")
    try:
        if start is None:
            start = _slot_times(_PERIOD_TIMES.get(int(exam.get("KSJC")), ""))[0]
        if end is None:
            end = _slot_times(_PERIOD_TIMES.get(int(exam.get("JSJC")), ""))[1]
    except (TypeError, ValueError):
        pass
    begin = datetime(day.year, day.month, day.day, *(start or (0, 0)), tzinfo=CHINA_TZ)
    if end is None:
        finish = datetime(day.year, day.month, day.day, tzinfo=CHINA_TZ) + timedelta(days=1)
    else:
        finish = datetime(day.year, day.month, day.day, *end, tzinfo=CHINA_TZ)
    return begin, finish


def fetch_next_exam(now: Optional[datetime] = None) -> Optional[dict]:
    """Get the nearest TIS exam that has not ended yet.

    Returns {name, code, date, time, building, room}. Exams are ordered by
    date and start time (KSJTSJ, else the KSJC period); one that has already
    ended — an earlier day, or earlier today — is skipped. Exams whose date
    can't be read are kept, after the dated ones.

    On auth failure returns {"error": "auth", "hint": "sustech sso check"} so agents
    know exactly what to do without guessing. Matches fetch_next_deadline / fetch_next_eval
    shape for Context integration.

    Args:
        now: injectable current time for tests (defaults to ``now_()``).
    """
    from sustech_survival.sso import TISAuth
    from sustech_survival.tis.exams import fetch_exams
    auth = TISAuth()
    ok, msg = auth.ensure()
    if not ok:
        return {"error": "auth", "message": msg, "hint": "sustech sso check"}

    try:
        exams = fetch_exams(auth)
    except Exception:
        return None

    if not exams:
        return None

    now = now or now_()
    if now.tzinfo is None:
        now = now.replace(tzinfo=CHINA_TZ)
    dated, undated = [], []
    for exam in exams:
        window = _exam_window(exam)
        if window is None:
            undated.append(exam)
        elif window[1] > now:
            dated.append((window[0], exam))
    # Stable sort: exams at the same start keep the order TIS returned them in.
    dated.sort(key=lambda item: item[0])
    exams = [exam for _, exam in dated] + undated
    if not exams:
        return None

    nearest = exams[0]
    return {
        "name": nearest.get("KCMC", ""),
        "code": nearest.get("KCDM", ""),
        "date": nearest.get("KSRQ", ""),
        "weekday": nearest.get("XQJMC", ""),
        "time_slot": nearest.get("KSJTSJ", ""),
        "periods": f"第{nearest.get('KSJC', '?')}-{nearest.get('JSJC', '?')}节",
        "building": nearest.get("JXLMC", ""),
        "room": nearest.get("JXCDMC", ""),
        "campus": nearest.get("XIAOQUBMC", "") or "一期校区",
        "exam_type": nearest.get("KSSJDMC", "考试"),
    }


def fetch_next_eval() -> Optional[dict]:
    """Get nearest unsubmitted TIS evaluation. Returns {name, course, days_left}.

    Shows both untouched (lsjgzt=0) and saved-draft (lsjgzt=3) evals.
    """
    try:
        from sustech_survival.tis.eval import TISAuthEval
        from sustech_survival.semester import Semester, Season

        # Use the LIVE current semester — never a hardcoded past term.
        sem = Semester.current()
        auth = TISAuthEval()
        evals = auth.evaluations(xnxq=sem.tis, status="all")
        if not evals:
            return None

        # Per-course jzsj is always null; use the task window end. Derive it
        # from the current semester's season so it never goes stale.
        now = datetime.now()
        # Fall ends in January of the end year; Spring/Summer end ~July/August.
        if sem.season is Season.FALL:
            deadline = datetime(sem.end_year, 1, 31, 23, 59)
        else:
            deadline = datetime(sem.end_year, 8, 15, 23, 59)
        days_from_now = (deadline.date() - now.date()).days

        needs_attention = []
        for ev in evals:
            lsjgzt = ev.get("lsjgzt", "0")
            if lsjgzt in ("0", "3"):
                needs_attention.append(ev)

        if not needs_attention:
            return None

        ev = sorted(needs_attention, key=lambda x: x.get("course_name", ""))[0]
        course_name = ev.get("course_name", "") or ev.get("course", "")
        eval_name = ev.get("evaluationName", "") or ev.get("name", "") or "教学评价"
        lsjgzt = ev.get("lsjgzt", "0")
        status_flag = " [已保存]" if lsjgzt == "3" else ""

        return {
            "name": eval_name + status_flag,
            "course": course_name,
            "days_left": days_from_now,
        }
    except Exception:
        return None


# -- Academic-info helpers -------------------------------------------------

def get_academic_info(dt: datetime) -> tuple:
    """Returns (week_str, phase_str, label).

    Uses the live ``AcademicCalendar`` (from the sustech-calendar repo) so the
    semester dates are never stale. Falls back to the bundled
    ``ACADEMIC_CALENDARS`` snapshot only when the calendar can't be loaded
    (e.g. fully offline).
    """
    today = dt.date()
    cal = _calendar_for(today)
    if cal is not None:
        day = cal.day(today)
        sem = day.semester
    else:
        day = None
        sem = None

    if day is not None and day.week > 0:
        # In an active semester — classify the day via its phase predicates.
        if day.is_holiday():
            name = day.holiday.name if day.holiday else "Holiday"
            return str(day.week), name, f"Week {day.week} — {name} (holiday)"
        if day.is_final():
            return str(day.week), "Final exams", f"Week {day.week} — Final exams"
        if day.is_midterm():
            return str(day.week), "Midterm", f"Week {day.week} — Midterm"
        if day.week == 0:
            return "—", "Unknown", "[Unknown semester]"
        phase = sem.human if sem is not None else "semester"
        return str(day.week), phase, f"Week {day.week} of {phase}"
    if day is not None:
        # Between or outside semesters. Pick a season label based on the
        # calendar month, not just Jul/Aug — "Winter Vacation" in September
        # was misleading (it's still summer in the northern hemisphere).
        m = today.month
        if m in (7, 8):
            label = "Summer Vacation"
        elif m in (1, 2):
            label = "Winter Vacation"
        elif m == 9 and today.day < 15:
            # Early September before Fall semester usually starts.
            label = "Summer Vacation"
        else:
            label = "Between semesters"
        return "—", label, f"[{label}]"

    # Fallback: bundled snapshot (offline).
    for name, cal in ACADEMIC_CALENDARS.items():
        start = datetime.strptime(cal["semester_start"], "%Y-%m-%d").date()
        end = datetime.strptime(cal["semester_end"], "%Y-%m-%d").date()
        if start <= today <= end:
            spring_start_str, spring_end_str = cal["spring_break"] or ("", "")
            spring_start = (datetime.strptime(spring_start_str, "%Y-%m-%d").date()
                            if spring_start_str else None)
            spring_end = (datetime.strptime(spring_end_str, "%Y-%m-%d").date()
                          if spring_end_str else None)
            if spring_start and spring_end and spring_start <= today <= spring_end:
                return "—", "Spring Break", "[Spring Break]"
            days_since_start = (today - start).days
            week = days_since_start // 7 + 1
            return str(week), f"{name} semester", f"Week {week} of {name}"

    for name, cal in ACADEMIC_CALENDARS.items():
        summer = datetime.strptime(cal["summer_start"], "%Y-%m-%d").date()
        if today >= summer:
            # Same season fix as the live-calendar branch above: pick the
            # season by month, not by guessing from the calendar year.
            m = today.month
            if m in (7, 8):
                vac = "Summer Vacation"
            elif m in (1, 2):
                vac = "Winter Vacation"
            else:
                vac = "Between semesters"
            return "—", vac, f"[{vac}]"
    return "—", "Unknown", "[Unknown semester]"


def is_holiday(dt: datetime) -> str:
    """Holiday name for ``dt``, or '' — calendar-backed.

    Reads the academic calendar (the same source ``get_academic_info`` uses), so
    names match 校历. A 补课 (makeup-class) day is NOT a holiday. The bundled
    ``HOLIDAY_DATA`` snapshot is a last-resort fallback for when the calendar
    can't be loaded — it is stale (it marks 2026-09-26/27 and 2026-10-08 as
    holidays, none of which are).
    """
    cal = _calendar_for(dt.date())
    if cal is not None:
        day = cal.day(dt.date())
        if day.is_holiday():
            return day.holiday.name if day.holiday else "Holiday"
        return ""
    year = dt.year
    holidays = HOLIDAY_DATA.get(year, {})
    holidays.update(HOLIDAY_DATA.get(year - 1, {}))

    date_str = dt.strftime("%Y-%m-%d")
    if date_str in holidays:
        val = holidays[date_str]
        return "" if val == "adjust" else val

    if dt.weekday() >= 5:
        return holidays.get(f"adjust:{date_str}", "")
    return ""


# -------------------------------------------------------------------------
# Context — single class with tiered exporters
# -------------------------------------------------------------------------

class Context:
    """A student's daily context. str(ctx) returns a formatted string.

    Levels:
      terse   - date, time, week, weekday, class_now  (sync, ≤1ms)
      normal  - terse + next_deadline, next_eval      (≤2s)
      verbose - normal + weather, aqi, library_status (≤5s)
    """

    def __init__(self, *, level: Union[str, Level] = Level.NORMAL,
                 dt: Optional[datetime] = None, time: Optional[float] = None):
        """Initialize Context.

        Args:
            level: terse | normal | verbose (default: normal)
            dt:    Override datetime (for testing / predictions).
            time:  Unix timestamp float (for testing / predictions).
        """
        if isinstance(level, str):
            try:
                self.level = Level(level)
            except ValueError:
                valid = [l.value for l in Level]
                raise ValueError(f"Unknown level: {level!r}. Valid: {valid}")
        else:
            self.level = level

        if dt is not None:
            self.dt = dt
        elif time is not None:
            self.dt = datetime.fromtimestamp(time, tz=CHINA_TZ)
        else:
            self.dt = now_()

    # -- Sync properties (always populated) -------------------------------

    @property
    def date(self) -> str:
        """YYYY-MM-DD"""
        return self.dt.strftime("%Y-%m-%d")

    @property
    def time_24h(self) -> str:
        """HH:MM in 24h"""
        return self.dt.strftime("%H:%M")

    @property
    def day(self) -> str:
        """Day name, e.g. 'Thursday'"""
        return self.dt.strftime("%A")

    @property
    def weekday(self) -> str:
        """Alias for day — name e.g. 'Thursday'."""
        return self.day

    @property
    def week(self) -> str:
        """Academic week number, e.g. '14' or '—'"""
        return get_academic_info(self.dt)[0]

    @property
    def phase(self) -> str:
        """Academic phase, e.g. '2026 Spring semester' or 'Summer Vacation'"""
        return get_academic_info(self.dt)[1]

    @property
    def label(self) -> str:
        """Full academic label, e.g. 'Week 14 of 2026 Spring'"""
        return get_academic_info(self.dt)[2]

    @property
    def holiday(self) -> str:
        """Holiday name or ''"""
        return is_holiday(self.dt)

    @property
    def makeup(self) -> str:
        """Makeup-class day descriptor — 'Friday schedule' — or ''.

        Empty on every ordinary day, including holidays.
        """
        sem = calendar_term(self.dt.date())
        if sem is None:
            return ""
        day = sem.day(self.dt.date())
        if not day.is_compensatory() or day.comp is None:
            return ""
        return f"{day.comp.workday} schedule"

    @property
    def time(self) -> float:
        """Unix timestamp — uses OVERRIDE_TIME if set, else self.dt.timestamp()."""
        if OVERRIDE_TIME is not None:
            return OVERRIDE_TIME
        return self.dt.timestamp()

    @property
    def class_now(self) -> str:
        """Current class name or '' (sync — computes on first access, cached)."""
        cache_key = f"sr_{self.dt.strftime('%Y%m%d%H%M')}"
        if not hasattr(self, cache_key):
            try:
                reminder = get_schedule_reminder(self.time)
            except Exception:
                reminder = {}
            object.__setattr__(self, cache_key, reminder)
        return getattr(self, cache_key, {}).get("now") or ""

    # -- Lazy I/O properties (cached after first access) -----------------

    @property
    def weather(self) -> Optional[dict]:
        if not hasattr(self, "_weather_cache"):
            self._weather_cache = fetch_weather()
        return self._weather_cache

    @property
    def weather_cond(self) -> str:
        w = self.weather
        return w["condition"] if w else "unavailable"

    @property
    def weather_icon(self) -> str:
        w = self.weather
        return w.get("icon", "❓") if w else "❓"

    @property
    def temperature(self) -> Optional[float]:
        w = self.weather
        return w.get("temp_c") if w else None

    @property
    def feels_like(self) -> Optional[float]:
        w = self.weather
        return w.get("feels_like") if w else None

    @property
    def humidity(self) -> Optional[int]:
        w = self.weather
        return w.get("humidity") if w else None

    @property
    def wind_kmh(self) -> Optional[float]:
        w = self.weather
        return w.get("wind_kmh") if w else None

    @property
    def precipitation_mm(self) -> Optional[float]:
        w = self.weather
        return w.get("precipitation_mm") if w else None

    @property
    def aqi(self) -> Optional[dict]:
        if not hasattr(self, "_aqi_cache"):
            self._aqi_cache = fetch_aqi()
        return self._aqi_cache

    @property
    def aqi_value(self) -> Optional[int]:
        a = self.aqi
        return a["aqi"] if a else None

    @property
    def aqi_str_level(self) -> str:
        a = self.aqi
        return a["aqi_level"] if a else "unavailable"

    @property
    def pm25(self) -> Optional[float]:
        a = self.aqi
        return a.get("pm2_5") if a else None

    @property
    def pm10(self) -> Optional[float]:
        a = self.aqi
        return a.get("pm10") if a else None

    @property
    def library_status(self) -> str:
        if not hasattr(self, "_library_cache"):
            self._library_cache = fetch_library_status()
        return self._library_cache

    @property
    def next_deadline(self) -> Optional[dict]:
        if not hasattr(self, "_deadline_cache"):
            self._deadline_cache = fetch_next_deadline()
        return self._deadline_cache

    @property
    def next_eval(self) -> Optional[dict]:
        if not hasattr(self, "_eval_cache"):
            self._eval_cache = fetch_next_eval()
        return self._eval_cache

    @property
    def next_exam(self) -> Optional[dict]:
        if not hasattr(self, "_exam_cache"):
            self._exam_cache = fetch_next_exam(now=self.dt)
        return self._exam_cache

    # -- Tiered exporters ------------------------------------------------

    def to_str(self, *, level: Union[str, Level, None] = None) -> str:
        """Render the context at the given level (default: self.level)."""
        lvl = self._resolve_level(level)
        out = self._render_terse()
        if _LEVEL_ORDER[lvl] >= _LEVEL_ORDER[Level.NORMAL]:
            out += "\n" + self._render_normal()
        if _LEVEL_ORDER[lvl] >= _LEVEL_ORDER[Level.VERBOSE]:
            out += "\n" + self._render_verbose()
        return out

    def to_dict(self, *, level: Union[str, Level, None] = None) -> dict:
        """Return a dict of the fields at the given level."""
        lvl = self._resolve_level(level)
        out = {
            "date": self.date,
            "time": self.time_24h,
            "week": self.week,
            "weekday": self.day,
            "class_now": self.class_now,
        }
        if _LEVEL_ORDER[lvl] >= _LEVEL_ORDER[Level.NORMAL]:
            out["next_deadline"] = self.next_deadline
            out["next_eval"] = self.next_eval
            out["next_exam"] = self.next_exam
        if _LEVEL_ORDER[lvl] >= _LEVEL_ORDER[Level.VERBOSE]:
            out["weather_cond"] = self.weather_cond
            out["aqi"] = self.aqi_value
            out["library_status"] = self.library_status
        return out

    def __str__(self) -> str:
        return self.to_str()

    # -- Internal helpers ------------------------------------------------

    def _resolve_level(self, level: Union[str, Level, None]) -> Level:
        if level is None:
            return self.level
        if isinstance(level, str):
            try:
                return Level(level)
            except ValueError:
                valid = [l.value for l in Level]
                raise ValueError(f"Unknown level: {level!r}. Valid: {valid}")
        return level

    def _render_terse(self) -> str:
        parts = [
            f"Today is [{self.date}], [{self.day}]",
            f"According to SUSTech academic calendar, this is [{self.label}]",
            f"Current time is [{self.time_24h}]",
        ]

        if self.holiday:
            parts.append(f"Today is 🎉 [{self.holiday}]")
        if self.makeup:
            parts.append(f"Today is a 🔁 makeup-class day — [{self.makeup}]")

        try:
            cache_key = f"sr_{self.dt.strftime('%Y%m%d%H%M')}"
            now_val = getattr(self, cache_key, None)
            if now_val is None:
                try:
                    now_val = get_schedule_reminder(self.time)
                    object.__setattr__(self, cache_key, now_val)
                except Exception:
                    now_val = {}
            reminder = now_val.get("now")
            if reminder:
                parts.append(f"📍 Now: [{reminder}]")
            elif now_val.get("next"):
                parts.append(f"📅 Next: [{now_val['next']}] — {now_val['next_detail']}")
        except Exception:
            pass  # schedule unavailable — no CAS/网络, skip reminder block silently

        return "\n".join(parts)

    def _render_normal(self) -> str:
        parts = []

        nd = self.next_deadline
        if nd and "error" not in nd:
            days = nd["days_left"]
            if days == 0:
                due_str = "Due today"
            elif days == 1:
                due_str = "Due tomorrow"
            elif days < 0:
                due_str = f"Overdue by {-days} day{'s' if -days != 1 else ''}"
            else:
                due_str = f"Due in {days} days"
            parts.append(f"Next BB deadline: [{nd['name']}] — {due_str}")

        ne = self.next_eval
        if ne and "error" not in ne:
            days = ne["days_left"]
            if days <= 0:
                eval_str = "Eval overdue"
            elif days == 1:
                eval_str = "Eval due tomorrow"
            else:
                eval_str = f"Eval due in {days} days"
            parts.append(f"Next TIS eval: [{ne['course']} — {ne['name']}] — {eval_str}")

        nx = self.next_exam
        if nx and "error" not in nx:
            location = f"{nx['building']} {nx['room']}".strip() or nx.get("campus", "")
            parts.append(
                f"Next TIS exam: [{nx['name']} ({nx['code']})] — {nx['date']} "
                f"{nx['time_slot']} @ {location}"
            )

        return "\n".join(parts) if parts else "(no deadlines)"

    def _render_verbose(self) -> str:
        parts = []

        w = self.weather
        if w and w.get("condition"):
            parts.append(f"Weather at SUSTech: [{w['condition']}]")

        parts.append(f"Library: [{self.library_status}]")

        return "\n".join(parts)


__all__ = [
    "CHINA_TZ", "SUSTECH_LAT", "SUSTECH_LON",
    "ACADEMIC_CALENDARS", "HOLIDAY_DATA",
    "OVERRIDE_TIME",
    "Level", "Context",
    "now_",
    "fetch_json", "fetch_weather", "fetch_aqi", "fetch_library_status",
    "fetch_next_deadline", "fetch_next_eval", "fetch_next_exam",
    "slot_times", "entry_time_range", "entry_name", "get_schedule_reminder",
    "get_academic_info", "is_holiday",
    "aqi_level", "aqi_icon",
    "fetch_profile", "gen_usr_profile",
]

# -- User-profile helpers (context/profile.py) -----------------------------
from .profile import fetch_profile, gen_usr_profile  # noqa: E402


# -- Quick demo -----------------------------------------------------------

if __name__ == "__main__":
    print("=== terse ===")
    print(Context(level="terse").to_str(level="terse"))
    print("\n=== normal ===")
    print(Context(level="normal").to_str(level="normal"))
    print("\n=== verbose ===")
    print(Context(level="verbose").to_str(level="verbose"))
