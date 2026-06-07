"""
Tests for the new sustech_survival.context module.

Covers:
  - Context() construction and level handling
  - Sync fields (date, time_24h, week, weekday, class_now)
  - Lazy I/O fields (weather_cond, aqi, library_status, next_deadline, next_eval)
  - to_str(level=...) tiered rendering
  - to_dict(level=...) tiered dict
  - __str__ defaults to instance level
  - OVERRIDE_TIME / dt injection for deterministic tests
  - Old quickcontext shim re-exports with DeprecationWarning
"""
from __future__ import annotations

import warnings
from datetime import datetime
from unittest.mock import patch

import pytest

from sustech_survival.context import (
    CHINA_TZ,
    ACADEMIC_CALENDARS,
    HOLIDAY_DATA,
    Context,
    Level,
    OVERRIDE_TIME,
    fetch_weather,
    fetch_aqi,
    fetch_library_status,
    fetch_next_deadline,
    fetch_next_eval,
    get_academic_info,
    is_holiday,
    now_,
)


# ─── Construction & level handling ─────────────────────────────────────────

def test_context_default_level_is_normal():
    ctx = Context()
    assert ctx.level == Level.NORMAL


def test_context_accepts_string_level():
    assert Context(level="terse").level == Level.TERSE
    assert Context(level="normal").level == Level.NORMAL
    assert Context(level="verbose").level == Level.VERBOSE


def test_context_accepts_enum_level():
    assert Context(level=Level.TERSE).level == Level.TERSE


def test_context_rejects_unknown_level():
    with pytest.raises(ValueError):
        Context(level="invalid")


# ─── Sync fields with fixed time ───────────────────────────────────────────

def test_sync_fields_with_fixed_dt():
    """A pinned dt should produce deterministic sync output."""
    fixed = datetime(2026, 5, 29, 14, 30, tzinfo=CHINA_TZ)
    ctx = Context(level="terse", dt=fixed)
    assert ctx.date == "2026-05-29"
    assert ctx.time_24h == "14:30"
    # May 29 2026 is a Friday in week 14 of 2026 Spring
    assert ctx.day == "Friday"
    # Week count is sync; 2026 Spring starts 2026-02-24
    # Feb 24 = week 1; Mar 2 = week 2; ... May 29 is week 14
    assert ctx.week == "14"


def test_sync_fields_with_unix_time():
    fixed = datetime(2026, 5, 29, 14, 30, tzinfo=CHINA_TZ).timestamp()
    ctx = Context(level="terse", time=fixed)
    assert ctx.date == "2026-05-29"
    assert ctx.time_24h == "14:30"


def test_holiday_field_returns_known_holiday():
    fixed = datetime(2026, 5, 1, 12, 0, tzinfo=CHINA_TZ)
    ctx = Context(level="terse", dt=fixed)
    assert "Labor Day" in ctx.holiday


def test_holiday_field_returns_empty_for_normal_day():
    fixed = datetime(2026, 5, 13, 12, 0, tzinfo=CHINA_TZ)  # a Wednesday
    ctx = Context(level="terse", dt=fixed)
    assert ctx.holiday == ""


# ─── Level-filtered dict ───────────────────────────────────────────────────

def test_to_dict_terse_excludes_io_fields():
    ctx = Context(level="terse", dt=datetime(2026, 5, 29, 14, 30, tzinfo=CHINA_TZ))
    _pre_cache_schedule_reminder(ctx)
    d = ctx.to_dict(level="terse")
    assert d["date"] == "2026-05-29"
    assert d["time"] == "14:30"
    assert d["week"] == "14"
    # Normal/verbose fields are NOT in terse dict
    for k in ("next_deadline", "next_eval", "weather_cond", "aqi", "library_status"):
        assert k not in d, f"terse dict should not include {k}"


def test_to_dict_normal_includes_deadlines_but_not_weather():
    ctx = Context(level="normal", dt=datetime(2026, 5, 29, 14, 30, tzinfo=CHINA_TZ))
    _pre_cache_schedule_reminder(ctx)
    with patch("sustech_survival.context.fetch_next_deadline", return_value=None), \
         patch("sustech_survival.context.fetch_next_eval", return_value=None):
        d = ctx.to_dict(level="normal")
    # Terse fields present
    assert "date" in d and "time" in d and "week" in d
    # Normal fields present (keys, values may be None)
    assert "next_deadline" in d
    assert "next_eval" in d
    # Verbose fields NOT in normal dict
    assert "weather_cond" not in d
    assert "aqi" not in d
    assert "library_status" not in d


def test_to_dict_verbose_includes_everything():
    ctx = Context(level="verbose", dt=datetime(2026, 5, 29, 14, 30, tzinfo=CHINA_TZ))
    _pre_cache_schedule_reminder(ctx)
    with patch("sustech_survival.context.fetch_weather", return_value=None), \
         patch("sustech_survival.context.fetch_aqi", return_value=None), \
         patch("sustech_survival.context.fetch_library_status", return_value="Unknown"), \
         patch("sustech_survival.context.fetch_next_deadline", return_value=None), \
         patch("sustech_survival.context.fetch_next_eval", return_value=None):
        d = ctx.to_dict(level="verbose")
    # Sync + normal + verbose
    for k in ("date", "time", "week", "weekday", "class_now",
              "next_deadline", "next_eval",
              "weather_cond", "aqi", "library_status"):
        assert k in d, f"verbose dict missing {k}"


# ─── Level-filtered to_str ─────────────────────────────────────────────────

def _pre_cache_schedule_reminder(ctx):
    """Pre-set the schedule reminder cache so to_str doesn't hit TIS auth."""
    # The cache key format is sr_{YYYYMMDDHHMM} — see class_now property
    object.__setattr__(ctx, f"sr_{ctx.dt.strftime('%Y%m%d%H%M')}", {})


def test_to_str_terse_does_no_io():
    """to_str(level='terse') must not trigger any I/O calls."""
    ctx = Context(level="terse", dt=datetime(2026, 5, 29, 14, 30, tzinfo=CHINA_TZ))
    _pre_cache_schedule_reminder(ctx)
    with patch("sustech_survival.context.fetch_weather") as mock_w, \
         patch("sustech_survival.context.fetch_aqi") as mock_a, \
         patch("sustech_survival.context.fetch_library_status") as mock_l, \
         patch("sustech_survival.context.fetch_next_deadline") as mock_d, \
         patch("sustech_survival.context.fetch_next_eval") as mock_e, \
         patch("sustech_survival.context.get_schedule_reminder") as mock_sr:
        s = ctx.to_str(level="terse")
        mock_w.assert_not_called()
        mock_a.assert_not_called()
        mock_l.assert_not_called()
        mock_d.assert_not_called()
        mock_e.assert_not_called()
        # Schedule reminder is also pre-cached, so this is a defense-in-depth check
        mock_sr.assert_not_called()
    assert "2026-05-29" in s
    assert "Friday" in s


def test_to_str_normal_triggers_deadline_io():
    """to_str(level='normal') should call deadline + eval fetchers."""
    ctx = Context(level="normal", dt=datetime(2026, 5, 29, 14, 30, tzinfo=CHINA_TZ))
    _pre_cache_schedule_reminder(ctx)
    with patch("sustech_survival.context.fetch_weather") as mock_w, \
         patch("sustech_survival.context.fetch_aqi") as mock_a, \
         patch("sustech_survival.context.fetch_library_status") as mock_l, \
         patch("sustech_survival.context.fetch_next_deadline", return_value=None) as mock_d, \
         patch("sustech_survival.context.fetch_next_eval", return_value=None) as mock_e, \
         patch("sustech_survival.context.get_schedule_reminder") as mock_sr:
        s = ctx.to_str(level="normal")
        mock_d.assert_called_once()
        mock_e.assert_called_once()
        mock_w.assert_not_called()
        mock_a.assert_not_called()
        mock_l.assert_not_called()
    assert "2026-05-29" in s


def test_to_str_verbose_triggers_all_io():
    """to_str(level='verbose') should call all I/O fetchers."""
    ctx = Context(level="verbose", dt=datetime(2026, 5, 29, 14, 30, tzinfo=CHINA_TZ))
    _pre_cache_schedule_reminder(ctx)
    with patch("sustech_survival.context.fetch_weather", return_value=None) as mock_w, \
         patch("sustech_survival.context.fetch_aqi", return_value=None) as mock_a, \
         patch("sustech_survival.context.fetch_library_status", return_value="Unknown") as mock_l, \
         patch("sustech_survival.context.fetch_next_deadline", return_value=None) as mock_d, \
         patch("sustech_survival.context.fetch_next_eval", return_value=None) as mock_e, \
         patch("sustech_survival.context.get_schedule_reminder") as mock_sr:
        s = ctx.to_str(level="verbose")
        mock_d.assert_called_once()
        mock_e.assert_called_once()
        # Library is always called in verbose
        mock_l.assert_called_once()
    assert "2026-05-29" in s


# ─── __str__ default behavior ──────────────────────────────────────────────

def test_dunder_str_uses_instance_level():
    """__str__ should render at the instance's level, not always terse."""
    ctx = Context(level="terse", dt=datetime(2026, 5, 29, 14, 30, tzinfo=CHINA_TZ))
    _pre_cache_schedule_reminder(ctx)
    with patch("sustech_survival.context.fetch_next_deadline") as mock_d, \
         patch("sustech_survival.context.fetch_next_eval") as mock_e, \
         patch("sustech_survival.context.get_schedule_reminder") as mock_sr:
        s = str(ctx)
        mock_d.assert_not_called()
        mock_e.assert_not_called()
    assert "2026-05-29" in s


def test_to_str_with_explicit_level_overrides_instance():
    """to_str(level='terse') should respect explicit level, not instance level."""
    ctx = Context(level="verbose", dt=datetime(2026, 5, 29, 14, 30, tzinfo=CHINA_TZ))
    _pre_cache_schedule_reminder(ctx)
    with patch("sustech_survival.context.fetch_weather") as mock_w, \
         patch("sustech_survival.context.fetch_aqi") as mock_a, \
         patch("sustech_survival.context.fetch_library_status") as mock_l, \
         patch("sustech_survival.context.fetch_next_deadline") as mock_d, \
         patch("sustech_survival.context.fetch_next_eval") as mock_e, \
         patch("sustech_survival.context.get_schedule_reminder") as mock_sr:
        s = ctx.to_str(level="terse")
        # Explicit terse should NOT trigger I/O
        mock_w.assert_not_called()
        mock_a.assert_not_called()
        mock_l.assert_not_called()
        mock_d.assert_not_called()
        mock_e.assert_not_called()


# ─── Lazy I/O properties ───────────────────────────────────────────────────

def test_lazy_io_properties_return_none_on_failure():
    """I/O properties should return None (or 'unavailable') when fetch fails."""
    ctx = Context(level="verbose", dt=datetime(2026, 5, 29, 14, 30, tzinfo=CHINA_TZ))
    with patch("sustech_survival.context.fetch_weather", return_value=None), \
         patch("sustech_survival.context.fetch_aqi", return_value=None), \
         patch("sustech_survival.context.fetch_library_status", return_value="Unknown"), \
         patch("sustech_survival.context.fetch_next_deadline", return_value=None), \
         patch("sustech_survival.context.fetch_next_eval", return_value=None):
        # Weather/AQI on failure
        assert ctx.weather_cond == "unavailable"
        assert ctx.aqi is None
        # Library returns "Unknown" on failure per existing behavior
        assert ctx.library_status == "Unknown"
        # Deadlines return None
        assert ctx.next_deadline is None
        assert ctx.next_eval is None


def test_lazy_io_cached_after_first_access():
    """Once fetched, I/O properties should be cached (not re-fetched)."""
    ctx = Context(level="verbose", dt=datetime(2026, 5, 29, 14, 30, tzinfo=CHINA_TZ))
    with patch("sustech_survival.context.fetch_weather", return_value={"condition": "Clear", "icon": "☀️", "temp_c": 25, "feels_like": 26, "humidity": 60, "wind_kmh": 5, "precipitation_mm": 0}) as mock_w:
        _ = ctx.weather_cond
        _ = ctx.weather_cond  # second access
        assert mock_w.call_count == 1


# ─── Module exports ────────────────────────────────────────────────────────

def test_china_tz_is_utc_plus_8():
    from datetime import timedelta
    assert CHINA_TZ.utcoffset(None) == timedelta(hours=8)


def test_academic_calendars_has_known_semesters():
    assert "2026 Spring" in ACADEMIC_CALENDARS
    assert "2025 Fall" in ACADEMIC_CALENDARS


def test_holiday_data_has_known_years():
    assert 2025 in HOLIDAY_DATA
    assert 2026 in HOLIDAY_DATA


# ─── Helper functions ──────────────────────────────────────────────────────

def test_get_academic_info_for_known_semester():
    fixed = datetime(2026, 5, 29, 14, 30, tzinfo=CHINA_TZ)
    week_str, phase_str, label = get_academic_info(fixed)
    assert week_str == "14"
    assert "2026 Spring" in phase_str
    assert "Week 14" in label


def test_get_academic_info_outside_semester():
    fixed = datetime(2026, 7, 15, 14, 30, tzinfo=CHINA_TZ)
    week_str, phase_str, label = get_academic_info(fixed)
    assert week_str == "—"
    assert "Vacation" in phase_str or "Vacation" in label


def test_is_holiday_known_date():
    fixed = datetime(2026, 5, 1, 12, 0, tzinfo=CHINA_TZ)
    assert "Labor Day" in is_holiday(fixed)


def test_is_holiday_normal_weekday():
    fixed = datetime(2026, 5, 13, 12, 0, tzinfo=CHINA_TZ)
    assert is_holiday(fixed) == ""


# ─── OVERRIDE_TIME ─────────────────────────────────────────────────────────

def test_override_time_changes_now():
    """When OVERRIDE_TIME is set, now_() returns that time."""
    fixed_ts = datetime(2026, 5, 29, 14, 30, tzinfo=CHINA_TZ).timestamp()
    try:
        from sustech_survival import context as ctx_mod
        ctx_mod.OVERRIDE_TIME = fixed_ts
        n = now_()
        assert n.date().isoformat() == "2026-05-29"
        assert n.hour == 14 and n.minute == 30
    finally:
        from sustech_survival import context as ctx_mod
        ctx_mod.OVERRIDE_TIME = None


# ─── Deprecation shim ──────────────────────────────────────────────────────

def test_quickcontext_shim_emits_warning_and_reexports():
    """The old quickcontext module should re-export Context with a DeprecationWarning."""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        from sustech_survival.quickcontext import Context as OldContext, Level as OldLevel
        assert OldContext is Context
        assert OldLevel is Level
        # At least one DeprecationWarning was emitted
        dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
        assert len(dep_warnings) >= 1
        assert "quickcontext" in str(dep_warnings[0].message)
        assert "context" in str(dep_warnings[0].message)


def test_quickcontext_shim_reexports_constants():
    """The shim should also re-export CHINA_TZ, ACADEMIC_CALENDARS, etc."""
    from sustech_survival import quickcontext as qc
    assert qc.CHINA_TZ is CHINA_TZ
    assert qc.ACADEMIC_CALENDARS is ACADEMIC_CALENDARS
    assert qc.HOLIDAY_DATA is HOLIDAY_DATA
