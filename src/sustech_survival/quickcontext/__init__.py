"""
QuickContext — a student's daily context summary.

QuickContext   — always-fast core fields (sync, no I/O on __str__):
                  date, day, time_24h, week, phase, label, holiday, class_now
DetailedContext(QuickContext) — adds slow fields fetched from external sources:
                  weather, aqi (from open-meteo), library_status (from lib.sustech.edu.cn),
                  next_deadline (Blackboard), next_eval (TIS)

String-callable: str(ctx) → formatted context string.
Properties:     all fields accessible as ctx.week, ctx.class_now, etc.

Usage:
    ctx = QuickContext()
    print(ctx)                  # core context string (no I/O)
    print(ctx.week)             # "14"
    print(ctx.class_now)         # "材料力学B" or ""

    dctx = DetailedContext()
    print(dctx.weather_cond)    # "Thunderstorm"
    print(dctx.library_status)  # "一丹: 开放中, 琳恩: 开放中, 涵泳: 开放中"
    print(dctx.next_deadline)   # {'name': ..., 'due': ..., 'days_left': ...}
"""
from __future__ import annotations

import json, re, time as _time_module
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Union

# ── Shared constants ─────────────────────────────────────────────────────────

CHINA_TZ = timezone(timedelta(hours=8))
SUSTECH_LAT = 22.6029
SUSTECH_LON = 113.9283

# ── Academic calendar ───────────────────────────────────────────────────────────

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

# ── China holidays ───────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────────────
# Module-level time override (for testing / predictions / tracebacks)
# ─────────────────────────────────────────────────────────────────────────────

_OVERRIDE_TIME: Union[float, None] = None
"""If set, all schedule-aware computations use this Unix timestamp instead of now."""


# ─────────────────────────────────────────────────────────────────────────────
# Helper utilities (module-level, shared)
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_json(url: str, timeout: int = 10) -> Optional[dict]:
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "QuickContext/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def _now() -> datetime:
    """Return datetime.now(CHINA_TZ), or overridden time if set."""
    if _OVERRIDE_TIME is not None:
        return datetime.fromtimestamp(_OVERRIDE_TIME, tz=CHINA_TZ)
    return datetime.now(CHINA_TZ)


def _weather_code_map(code: int) -> tuple[str, str]:
    maps = {
        0: ("Clear", "☀️"),
        1: ("Mostly Clear", "🌤️"),
        2: ("Partly Cloudy", "⛅"),
        3: ("Overcast", "☁️"),
        45: ("Foggy", "🌫️"),
        48: ("Icy Fog", "🌫️"),
        51: ("Light Drizzle", "🌧️"),
        53: ("Drizzle", "🌧️"),
        55: ("Heavy Drizzle", "🌧️"),
        61: ("Light Rain", "🌧️"),
        63: ("Rain", "🌧️"),
        65: ("Heavy Rain", "🌧️"),
        71: ("Light Snow", "🌨️"),
        73: ("Snow", "🌨️"),
        75: ("Heavy Snow", "🌨️"),
        80: ("Showers", "🌦️"),
        81: ("Rain Showers", "🌦️"),
        82: ("Heavy Showers", "🌦️"),
        95: ("Thunderstorm", "⛈️"),
        96: ("Thunderstorm", "⛈️"),
        99: ("Thunderstorm", "⛈️"),
    }
    return maps.get(code, (f"Code {code}", "🌡️"))


def _aqi_level(aqi: int) -> str:
    if aqi is None: return "Unknown"
    if aqi <= 50: return "Good"
    if aqi <= 100: return "Moderate"
    if aqi <= 150: return "Unhealthy for Sensitive"
    if aqi <= 200: return "Unhealthy"
    if aqi <= 300: return "Very Unhealthy"
    return "Hazardous"


def _aqi_icon(aqi: int) -> str:
    if aqi is None: return "❓"
    if aqi <= 50: return "🟢"
    if aqi <= 100: return "🟡"
    if aqi <= 150: return "🟠"
    if aqi <= 200: return "🔴"
    if aqi <= 300: return "🟣"
    return "⚫"


# ─────────────────────────────────────────────────────────────────────────────
# QuickContext — always-fast fields only
# ─────────────────────────────────────────────────────────────────────────────

class QuickContext:
    """
    A student's daily context. str(ctx) returns a formatted string.
    Individual fields accessible as properties.

    Always-fast (computed locally, no I/O on __str__):
      date, day, time_24h, week, phase, label, holiday, class_now
    """

    def __init__(self, dt: datetime = None, *, time: float = None):
        """Initialize QuickContext.

        Args:
            dt:  Override datetime. If omitted, derived from ``time``.
            time: Unix timestamp (float). Defaults to time.time().
                  Pass this for testing/predictions/tracebacks.
        """
        if dt is not None:
            self._dt = dt
        elif time is not None:
            self._dt = datetime.fromtimestamp(time, tz=CHINA_TZ)
        else:
            self._dt = datetime.now(CHINA_TZ)

    # ── computed properties ────────────────────────────────────────────────

    @property
    def date(self) -> str:
        """YYYY-MM-DD"""
        return self._dt.strftime("%Y-%m-%d")

    @property
    def day(self) -> str:
        """Day name, e.g. 'Thursday'"""
        return self._dt.strftime("%A")

    @property
    def time_24h(self) -> str:
        """HH:MM in 24h"""
        return self._dt.strftime("%H:%M")

    @property
    def week(self) -> str:
        """Academic week number, e.g. '14' or '—'"""
        return _get_academic_info(self._dt)[0]

    @property
    def phase(self) -> str:
        """Academic phase, e.g. '2026 Spring semester' or 'Summer Vacation'"""
        return _get_academic_info(self._dt)[1]

    @property
    def label(self) -> str:
        """Full academic label, e.g. 'Week 14 of 2026 Spring'"""
        return _get_academic_info(self._dt)[2]

    @property
    def holiday(self) -> str:
        """Holiday name or ''"""
        return _is_holiday(self._dt)

    @property
    def time(self) -> float:
        """Unix timestamp — uses _OVERRIDE_TIME if set, else self._dt.timestamp()."""
        if _OVERRIDE_TIME is not None:
            return _OVERRIDE_TIME
        return self._dt.timestamp()

    @property
    def class_now(self) -> str:
        """Current class name or '' (used as a fast accessor)."""
        return _get_schedule_reminder(self.time).get("now") or ""

    # ── string callable ───────────────────────────────────────────────────

    def __str__(self) -> str:
        parts = [
            f"Today is [{self.date}], [{self.day}]",
            f"According to SUSTech academic calendar, this is [{self.label}]",
            f"Current time is [{self.time_24h}]",
        ]

        if self.holiday:
            parts.append(f"Today is 🎉 [{self.holiday}]")

        reminder = _get_schedule_reminder(self.time)
        if reminder.get("now"):
            parts.append(f"📍 Now: [{reminder['now']}]")
        elif reminder.get("next"):
            parts.append(f"📅 Next: [{reminder['next']}] — {reminder['next_detail']}")
        elif reminder.get("tomorrow_morning"):
            parts.append(f"🌅 Tomorrow morning: [{reminder['tomorrow_morning']}]")

        return "\n".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# DetailedContext — adds slow external fields
# ─────────────────────────────────────────────────────────────────────────────

class DetailedContext(QuickContext):
    """
    Inherits all QuickContext fields plus slow external fields:
      weather, aqi (from open-meteo), library_status (from lib.sustech.edu.cn),
      next_deadline (Blackboard), next_eval (TIS)
    """

    def __init__(self, dt: datetime = None, *, time: float = None):
        super().__init__(dt, time=time)
        self._weather: Optional[dict] = None
        self._aqi: Optional[dict] = None
        self._deadline: Optional[dict] = None
        self._next_eval: Optional[dict] = None
        self._library: Optional[str] = None

    # ── weather lazily fetched ─────────────────────────────────────────────

    @property
    def weather_cond(self) -> str:
        if self._ensure_weather(): return self._weather["condition"]
        return "unavailable"

    @property
    def weather_icon(self) -> str:
        if self._ensure_weather(): return self._weather["icon"]
        return "❓"

    @property
    def temperature(self) -> Optional[float]:
        if self._ensure_weather(): return self._weather["temp_c"]
        return None

    @property
    def feels_like(self) -> Optional[float]:
        if self._ensure_weather(): return self._weather["feels_like"]
        return None

    @property
    def humidity(self) -> Optional[int]:
        if self._ensure_weather(): return self._weather["humidity"]
        return None

    @property
    def wind_kmh(self) -> Optional[float]:
        if self._ensure_weather(): return self._weather["wind_kmh"]
        return None

    @property
    def precipitation_mm(self) -> Optional[float]:
        if self._ensure_weather(): return self._weather["precipitation_mm"]
        return None

    # ── AQI lazily fetched ─────────────────────────────────────────────────

    @property
    def aqi(self) -> Optional[int]:
        if self._ensure_aqi(): return self._aqi["aqi"]
        return None

    @property
    def aqi_level(self) -> str:
        if self._ensure_aqi(): return self._aqi["aqi_level"]
        return "unavailable"

    @property
    def aqi_icon(self) -> str:
        if self._ensure_aqi(): return _aqi_icon(self._aqi["aqi"])
        return "❓"

    @property
    def pm25(self) -> Optional[float]:
        if self._ensure_aqi(): return self._aqi["pm2_5"]
        return None

    @property
    def pm10(self) -> Optional[float]:
        if self._ensure_aqi(): return self._aqi["pm10"]
        return None

    # ── deadline / eval / library ─────────────────────────────────────────

    @property
    def next_deadline(self) -> Optional[dict]:
        """{'name': str, 'due': str, 'days_left': int} or None"""
        if self._deadline is not None:
            return self._deadline
        self._deadline = _fetch_next_deadline()
        return self._deadline

    @property
    def next_eval(self) -> Optional[dict]:
        """{'name': str, 'course': str, 'days_left': int} or None"""
        if self._next_eval is not None:
            return self._next_eval
        self._next_eval = _fetch_next_eval()
        return self._next_eval

    @property
    def library_status(self) -> str:
        """'一丹: 开放中, 琳恩: 开放中, 涵泳: 开放中' or 'Unknown'"""
        if self._library is not None:
            return self._library
        self._library = _fetch_library_status()
        return self._library

    # ── internal lazy fetchers ─────────────────────────────────────────────

    def _ensure_weather(self) -> bool:
        if self._weather is not None:
            return True
        self._weather = _fetch_weather()
        return self._weather is not None

    def _ensure_aqi(self) -> bool:
        if self._aqi is not None:
            return True
        self._aqi = _fetch_aqi()
        return self._aqi is not None

    # ── string callable ───────────────────────────────────────────────────

    def __str__(self) -> str:
        base = QuickContext.__str__(self)
        lines = [base]

        self._ensure_weather()
        self._ensure_aqi()

        if self._weather:
            w = self._weather
            w_parts = [f"{w['condition']} {w['icon']}"]
            if w["temp_c"] is not None:
                w_parts.append(f"{w['temp_c']}°C")
                if w["feels_like"] is not None:
                    w_parts.append(f"(feels {w['feels_like']}°C)")
                if w["humidity"] is not None:
                    w_parts.append(f"💧{w['humidity']}%")
                if w["wind_kmh"] is not None:
                    w_parts.append(f"💨{w['wind_kmh']}km/h")
            lines.append(f"Weather at SUSTech (Shenzhen Nanshan): [{', '.join(w_parts)}]")

        if self._aqi:
            a = self._aqi
            if a["aqi"] is not None:
                lines.append(
                    f"Air quality: [{a['aqi']} ({a['aqi_level']}) {_aqi_icon(a['aqi'])}]"
                )

        ls = self.library_status
        lines.append(f"Library: [{ls}]")

        nd = self.next_deadline
        if nd:
            days = nd["days_left"]
            if days == 0:
                due_str = "Due today"
            elif days == 1:
                due_str = "Due tomorrow"
            elif days < 0:
                due_str = f"Overdue by {-days} day{'s' if -days != 1 else ''}"
            else:
                due_str = f"Due in {days} days"
            lines.append(f"Next BB deadline: [{nd['name']}] — {due_str}")

        ne = self.next_eval
        if ne:
            days = ne["days_left"]
            if days <= 0:
                eval_str = "Eval overdue"
            elif days == 1:
                eval_str = "Eval due tomorrow"
            else:
                eval_str = f"Eval due in {days} days"
            lines.append(f"Next TIS eval: [{ne['course']} — {ne['name']}] — {eval_str}")

        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Module-level helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_academic_info(dt: datetime):
    """Returns (week_str, phase_str, label)."""
    today = dt.date()

    for name, cal in ACADEMIC_CALENDARS.items():
        start = datetime.strptime(cal["semester_start"], "%Y-%m-%d").date()
        end = datetime.strptime(cal["semester_end"], "%Y-%m-%d").date()
        if start <= today <= end:
            spring_start_str, spring_end_str = cal["spring_break"] or ("", "")
            spring_start = datetime.strptime(spring_start_str, "%Y-%m-%d").date() if spring_start_str else None
            spring_end = datetime.strptime(spring_end_str, "%Y-%m-%d").date() if spring_end_str else None
            if spring_start and spring_end and spring_start <= today <= spring_end:
                return "—", "Spring Break", "[Spring Break]"
            days_since_start = (today - start).days
            week = days_since_start // 7 + 1
            return str(week), f"{name} semester", f"Week {week} of {name}"

    # Vacation detection
    for name, cal in ACADEMIC_CALENDARS.items():
        summer = datetime.strptime(cal["summer_start"], "%Y-%m-%d").date()
        if today >= summer:
            vac = "Summer Vacation" if "2026" in name else "Winter Vacation"
            return "—", vac, f"[{vac}]"
    return "—", "Unknown", "[Unknown semester]"


def _is_holiday(dt: datetime) -> str:
    """Check against known holiday data. Returns holiday name or ''."""
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


_SHENZHEN_LAT = 22.5431
_SHENZHEN_LON = 114.0579


def _fetch_weather() -> Optional[dict]:
    """Fetch current weather from Open-Meteo using explicit Shenzhen coords.

    Uses explicit lat/lon to avoid IP-based geolocation (Warp routes via HK).
    """
    try:
        import urllib.request, json

        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={_SHENZHEN_LAT}&longitude={_SHENZHEN_LON}"
            f"&current=temperature_2m,relative_humidity_2m,apparent_temperature,"
            f"wind_speed_10m,weather_code,precipitation"
            f"&wind_speed_unit=kmh"
            f"&timezone=Asia/Shanghai"
            f"&forecast_days=1"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.load(resp)

        cur = data["current"]
        code = cur["weather_code"]
        cond, _ = _weather_code_map(code)  # _ = icon, discarded

        return {
            "temp_c": cur["temperature_2m"],
            "feels_like": cur["apparent_temperature"],
            "humidity": int(cur["relative_humidity_2m"]),
            "wind_kmh": cur["wind_speed_10m"],
            "condition": cond,
            "precipitation_mm": cur.get("precipitation", 0),
        }
    except Exception:
        return None


def _fetch_aqi() -> Optional[dict]:
    url = (
        f"https://air-quality-api.open-meteo.com/v1/air-quality"
        f"?latitude={SUSTECH_LAT}&longitude={SUSTECH_LON}"
        f"&current=us_aqi,pm2_5,pm10,ozone"
        f"&timezone=Asia/Shanghai"
    )
    data = _fetch_json(url)
    if not data:
        return None
    cur = data["current"]
    aqi = cur["us_aqi"]
    return {
        "aqi": aqi,
        "aqi_level": _aqi_level(aqi),
        "pm2_5": cur.get("pm2_5"),
        "pm10": cur.get("pm10"),
    }


def _fetch_library_status() -> str:
    """Fetch real-time open/closed status from lib.sustech.edu.cn."""
    try:
        import urllib.request
        req = urllib.request.Request(
            "https://lib.sustech.edu.cn/",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8")

        # Parse <li><span class="name">一丹</span><span class="now">开放中</span></li>
        rooms = re.findall(
            r'<span class="name">([^<]+)</span><span class="now">([^<]+)</span>',
            html,
        )
        if not rooms:
            return "Unknown"
        return ", ".join(f"{name}: {status}" for name, status in rooms)
    except Exception:
        return "Unknown"


def _slot_times(zc: int) -> dict[int, tuple[str, str]]:
    """Fetch actual 50-min slot start/end times from queryKbjg.

    Returns {slot_num: (kssj, jssj)} e.g. {1: ('08:00', '08:50'), 3: ('10:20', '11:10')}.
    """
    try:
        from sustech_survival.tis.schedule import TISAuth
        auth = TISAuth()
        auth.refresh()
        session = auth.session
        resp = session.post(
            'https://tis.sustech.edu.cn/component/queryKbjg',
            data={'xn': '2025-2026', 'xq': '2', 'zc': str(zc)}
        )
        content = resp.json().get('content', [])
        return {int(e['xj']): (e['kssj'], e['jssj']) for e in content}
    except Exception:
        return {}


def _entry_time_range(entry: dict, slot_times: dict) -> tuple[int, int] | None:
    """Return (start_min, end_min) for an entry based on KSJC/JSJC.

    Returns None if KSJC/JSJC not in slot_times.
    """
    ks = int(entry.get('KSJC', 0) or 0)
    js = int(entry.get('JSJC', 0) or 0)
    if ks <= 0 or js <= 0:
        return None
    if ks not in slot_times or js not in slot_times:
        return None
    kssj, jssj = slot_times[ks][0], slot_times[js][1]
    h, m = int(kssj[:2]), int(kssj[3:])
    start_min = h * 60 + m
    h, m = int(jssj[:2]), int(jssj[3:])
    end_min = h * 60 + m
    return (start_min, end_min)


def _entry_name(entry: dict) -> str:
    return entry.get('SKSJ', '').split('\n')[0] or \
           entry.get('SKSJ_EN', '').split('\n')[0] or ''


def _get_schedule_reminder(ts: float) -> dict:
    """Compute today's schedule reminder for Unix timestamp ``ts``.

    Returns dict:
      {'now': str}           — class happening right now
      {'next': str, 'next_detail': str}  — next class today + detail
      {'tomorrow_morning': str} — tomorrow morning courses (slots 1-2, 08:00-09:50)
      {}                     — no classes today/tomorrow
    """
    try:
        from sustech_survival.tis.schedule import week_schedule, current_week

        now = datetime.fromtimestamp(ts, tz=CHINA_TZ)
        wd = now.weekday()        # 0=Mon
        h, m = now.hour, now.minute
        total_min = h * 60 + m
        is_night = h >= 19 or h < 6

        zc = current_week()
        week = week_schedule(zc)
        slot_times = _slot_times(zc)

        # Collect today's entries sorted by their start time
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
            tr = _entry_time_range(entry, slot_times)
            today_entries.append((tr, entry))

        # Sort by start time (None = at end)
        today_entries.sort(key=lambda x: (x[0][0] if x[0] else 99999))

        # 1. Check if a class is running right now
        for tr, entry in today_entries:
            if tr is None:
                continue
            start_min, end_min = tr
            if start_min <= total_min <= end_min:
                return {"now": _entry_name(entry)}

        # 2. Night time — show tomorrow morning courses (slots 1 and 2)
        if is_night:
            try:
                tomorrow_wd = (wd + 1) % 7
                morning = []
                for entry in week_schedule(tomorrow_zc if False else zc):
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
                    if ks in (1, 2):   # slot 1 or slot 2
                        morning.append((ks, _entry_name(entry)))
                if morning:
                    morning.sort()
                    periods_str = " / ".join(f"第{ks}节" for ks, _ in morning)
                    names = " / ".join(name for _, name in morning)
                    return {"tomorrow_morning": f"{names} ({periods_str})"}
            except Exception:
                pass

        # 3. No class now — find next class today
        for tr, entry in today_entries:
            if tr is None:
                continue
            start_min, end_min = tr
            if total_min < start_min:
                ks = int(entry.get('KSJC', 0) or 0)
                js = int(entry.get('JSJC', 0) or 0)
                kssj = slot_times.get(ks, ('??', '??'))[0] if ks else '??'
                jssj = slot_times.get(js, ('??', '??'))[1] if js else '??'
                detail = f"{kssj}-{jssj}" if kssj != '??' else f"第{ks}-{js}节"
                return {"next": _entry_name(entry), "next_detail": detail}

        return {}
    except Exception:
        return {}


def _fetch_next_deadline() -> Optional[dict]:
    """Get nearest BB assignment with due date. Returns {name, due, days_left}."""
    try:
        from sustech_survival.bb.ddl import upcoming_deadlines
        deadlines = upcoming_deadlines(days=30)
        if deadlines:
            d = deadlines[0]
            return {"name": d["name"], "due": d["due"], "days_left": d["days_left"]}
        return None
    except Exception:
        return None


def _fetch_next_eval() -> Optional[dict]:
    """Get nearest unsubmitted TIS evaluation. Returns {name, course, days_left}."""
    try:
        from sustech_survival.tis import TISAuth
        auth = TISAuth()
        cookies = auth.load()
        if not cookies:
            return None

        import requests
        sess = requests.Session()
        for k, v in cookies.items():
            if v:
                sess.cookies.set(k, v, domain=".tis.sustech.edu.cn", path="/")

        r = sess.get(
            "https://tis.sustech.edu.cn/student/api/teachingEvaluation/fetch?page=1&limit=20",
            timeout=10
        )
        if r.status_code != 200:
            return None
        data = r.json()
        now = _now()

        for item in data.get("data", []) or data.get("list", []):
            if item.get("status") == 0:  # unsubmitted
                due_str = item.get("deadline", "")
                if due_str:
                    try:
                        due_dt = datetime.strptime(due_str[:10], "%Y-%m-%d").replace(tzinfo=CHINA_TZ)
                        days = (due_dt.date() - now.date()).days
                    except Exception:
                        days = 99
                    return {
                        "name": item.get("evaluationName", "") or item.get("name", ""),
                        "course": item.get("courseName", "") or item.get("course", ""),
                        "days_left": days,
                    }
        return None
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Quick demo
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== QuickContext ===")
    ctx = QuickContext()
    print(str(ctx))

    print("\n=== DetailedContext ===")
    dctx = DetailedContext()
    print(str(dctx))