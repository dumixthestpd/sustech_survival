"""
Tests for sustech_survival._settings — the principled runtime settings.

Covers precedence (default < user config < env) and that the calendar
source + cache dir honour overrides. Offline.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from sustech_survival import _settings
import sustech_survival.calendar as calendar


# ── precedence ─────────────────────────────────────────────────────────────

def test_defaults():
    s = _settings.load(user_config={})
    assert s.calendar_repo_base.startswith("http")
    assert "sustech-calendar" in s.calendar_repo_base
    assert s.cache_dir  # non-empty


def test_env_overrides_default(monkeypatch):
    monkeypatch.setenv("SUSTECH_CALENDAR_REPO", "https://mirror.example.com/cal")
    s = _settings.load(user_config={})
    assert s.calendar_repo_base == "https://mirror.example.com/cal"


def test_config_overrides_env(monkeypatch):
    monkeypatch.setenv("SUSTECH_CALENDAR_REPO", "https://env.example.com/cal")
    s = _settings.load(user_config={"calendar": {"repo_base": "https://cfg.example.com/cal"}})
    assert s.calendar_repo_base == "https://cfg.example.com/cal"


def test_cache_dir_env(monkeypatch):
    monkeypatch.setenv("SUSTECH_CACHE_DIR", "~/sustech_cache")
    s = _settings.load(user_config={})
    assert "sustech_cache" in s.cache_dir


# ── calendar wiring ────────────────────────────────────────────────────────

def test_calendar_default_repo_base_comes_from_settings():
    # DEFAULT_REPO_BASE must reflect the settings default
    assert calendar.DEFAULT_REPO_BASE == _settings.calendar_repo_base
    assert str(calendar.DEFAULT_REPO).startswith(str(calendar.DEFAULT_REPO_BASE))


def test_calendar_reads_local_repo(tmp_path):
    """Pointing calendar.repo_base at a local dir reads off disk (no HTTP)."""
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
    (base / str(year) / "undergraduate.json").write_text(json.dumps(payload), encoding="utf-8")
    (base / str(year) / "graduate.json").write_text(json.dumps(payload), encoding="utf-8")
    (base / str(year) / "general.json").write_text(
        json.dumps({"holidays": []}), encoding="utf-8")

    # Force the calendar to use the local base (bypass settings module default)
    cal = calendar.AcademicCalendar.load(year, level="undergraduate",
                                         base_url=str(base), online=True, cached=False)
    assert cal.year == year
    assert cal.spring is not None
    assert cal.fall is not None


# ── cache wiring ───────────────────────────────────────────────────────────

def test_cache_root_override(monkeypatch, tmp_path):
    import sustech_survival._cache as cache
    override = tmp_path / "mycache"
    monkeypatch.setattr(_settings, "cache_dir", str(override))
    assert cache.tmp_root() == override
    # cache_path (the helper every consumer uses) must honour it too
    assert cache.cache_path("calendar") == override / "calendar"
    assert cache.cache_path("bb", "x.json") == override / "bb" / "x.json"


def test_cache_path_defaults_to_package_tmp():
    import sustech_survival._cache as cache
    p = cache.cache_path("sometest")
    # default root is <package>/tmp (unless overridden in this env)
    assert p.parent == cache.package_root() / "tmp" or str(p).endswith("tmp/sometest")


def test_clear_cache_honours_override(monkeypatch, tmp_path):
    import sustech_survival._cache as cache
    override = tmp_path / "mc"
    monkeypatch.setattr(_settings, "cache_dir", str(override))
    target = override / "sel" / "f.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{}", encoding="utf-8")
    n = cache.clear_cache("sel")
    assert n == 1
    assert not (override / "sel").exists()
