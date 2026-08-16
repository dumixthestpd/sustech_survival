"""
Dedicated tests for sustech_survival.api — the Flask-free JSON data contract.

Fully OFFLINE: no TIS network, no auth. We test the pure serializer and
semester-resolution helpers, plus the graceful error paths when a client
lookup or network call fails.
"""
from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest
from unittest.mock import patch, MagicMock

# Ensure src is importable
import sustech_survival
from sustech_survival import api as api_pkg
from sustech_survival.api import tis as api_tis
from sustech_survival.api import nces as api_nces
from sustech_survival.api import transit as api_transit


# ── resolve_semester ───────────────────────────────────────────────────────

def test_resolve_semester_defaults_to_live(monkeypatch):
    # Freeze Semester.current() to a known term via an injected date.
    import sustech_survival.api.tis as t
    monkeypatch.setattr("sustech_survival.api.tis._default_sem",
                        lambda: ("2025-2026", "2"))
    assert t.resolve_semester(None, None) == ("2025-2026", "2")


def test_resolve_semester_prefers_explicit():
    import sustech_survival.api.tis as t
    with patch.object(t, "_default_sem", return_value=("2025-2026", "2")):
        assert t.resolve_semester("2026-2027", "1") == ("2026-2027", "1")
        assert t.resolve_semester(None, "1") == ("2025-2026", "1")
        assert t.resolve_semester("2026-2027", None) == ("2026-2027", "2")


# ── serializer ─────────────────────────────────────────────────────────────

def _fake_course():
    return SimpleNamespace(
        code="MA212", name="数学分析", name_en="Analysis", section_name="A",
        section_name_en="A", class_group="1", rwh="20262012",
        college="数学系", category="数学", campus="主校区",
        credits=4, total_hours=64, capacity=80,
        undergrad_seats=70, grad_seats=10, cultivation="本科",
        enrolled=45, id="12345", rooms=["YJ-101"], teachers=["张老师"],
        schedule_str="周一3-4节", slots_raw=[], has_schedule=True,
        task_type="auto", language="中文", college_code="01",
    )


def test_course_to_dict_shape():
    c = _fake_course()
    d = api_tis._course_to_dict(c)
    assert d["code"] == "MA212"
    assert d["rwh"] == "20262012"
    assert d["name"] == "数学分析"
    assert d["credits"] == 4
    assert d["has_schedule"] is True
    # all expected keys present
    for key in ["code", "name", "name_en", "section_name", "rwh", "college",
                "category", "campus", "credits", "capacity", "enrolled",
                "rooms", "teachers", "schedule", "slots", "task_type",
                "language"]:
        assert key in d


# ── int helper ─────────────────────────────────────────────────────────────

def test_int_or_none():
    assert api_tis._int_or_none("5") == 5
    assert api_tis._int_or_none(5) == 5
    assert api_tis._int_or_none(None) is None
    assert api_tis._int_or_none("") is None
    assert api_tis._int_or_none(0) is None
    assert api_tis._int_or_none("abc") is None
    assert api_tis._int_or_none(None) is None


# ── graceful error paths (client / network failure) ───────────────────────

def test_info_returns_error_dict_if_client_raises():
    with patch.object(api_tis, "_client", side_effect=RuntimeError("net down")):
        out = api_tis.info()
    assert out["error"]
    assert out["count"] == 0


def test_courses_returns_error_dict_if_client_raises():
    with patch.object(api_tis, "_client", side_effect=RuntimeError("net down")):
        out = api_tis.courses()
    assert out["error"]
    assert out["courses"] == []


def test_course_detail_returns_error_if_client_raises():
    with patch.object(api_tis, "_client", side_effect=RuntimeError("net down")):
        out = api_tis.course_detail("12345")
    assert out["error"]


def test_course_detail_not_found():
    c = MagicMock()
    c.list_courses.return_value = [_fake_course()]
    with patch.object(api_tis, "_client", return_value=c):
        out = api_tis.course_detail("NOPE")
    assert out == {"error": "not found"}


def test_write_returns_error_dict_on_exception():
    c = MagicMock()
    c.add_course.side_effect = RuntimeError("boom")
    with patch.object(api_tis, "_client", return_value=c):
        out = api_tis.write("add", "20262012", dry_run=False)
    assert out["ok"] is False
    assert "boom" in out["error"]


def test_write_dry_run_forwards_dry_run_flag():
    c = MagicMock()
    c.add_course.return_value = {"ok": True, "dry_run": True}
    with patch.object(api_tis, "_client", return_value=c):
        api_tis.write("add", "20262012", dry_run=True)
    # dry_run must be forwarded as a keyword
    assert c.add_course.call_args.kwargs["dry_run"] is True


# ── each api submodule imports and exposes its core entrypoints ────────────

def test_api_submodules_export_entrypoints():
    assert callable(api_tis.info)
    assert callable(api_tis.courses)
    assert callable(api_tis.course_detail)
    assert callable(api_tis.write)
    assert callable(api_nces.code)
    assert callable(api_nces.teacher)
    assert callable(api_nces.course)
    assert callable(api_transit.live)
    assert callable(api_transit.facilities)


def test_api_package_exports_submodules():
    assert api_pkg.tis is api_tis
    assert api_pkg.nces is api_nces
    assert api_pkg.transit is api_transit
