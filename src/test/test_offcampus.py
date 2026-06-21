"""Tests for the shared SUSTech off-campus firewall detection helper.

Reference: ``sustech_survival.sso._offcampus``. Both pms.pms and
booking.booking re-export these symbols for back-compat — this test file
verifies the canonical implementation directly.
"""
from __future__ import annotations

from requests import Response

from sustech_survival.sso._offcampus import (
    OFF_CAMPUS_BODY,
    looks_off_campus,
    off_campus_hint,
)


# ── Constants ────────────────────────────────────────────────────────────────


def test_off_campus_body_matches_server_string():
    """The literal string the SUSTech firewall returns.

    If this changes, every submodule breaks. Do not edit without a
    coordinated rollout — see sustech-firewall-off-campus-403.md.
    """
    assert OFF_CAMPUS_BODY == "Access forbidden, please contact administrator."


# ── looks_off_campus ─────────────────────────────────────────────────────────


def _resp(status: int, body: str = "") -> Response:
    """Build a minimal Response with the given status + body."""
    r = Response()
    r.status_code = status
    r._content = body.encode("utf-8")
    return r


def test_detects_off_campus_403():
    r = _resp(403, OFF_CAMPUS_BODY)
    assert looks_off_campus(r) is True


def test_ignores_403_with_different_body():
    """Auth-failure 403s have a JSON body, not the plain-text marker."""
    r = _resp(403, '{"error": "unauthorized"}')
    assert looks_off_campus(r) is False


def test_ignores_200_with_off_campus_body():
    """Defensive: matching body alone must not trigger."""
    r = _resp(200, OFF_CAMPUS_BODY)
    assert looks_off_campus(r) is False


def test_ignores_500_with_off_campus_body():
    """Defensive: status code is part of the match."""
    r = _resp(500, OFF_CAMPUS_BODY)
    assert looks_off_campus(r) is False


def test_handles_empty_text_attribute():
    """Some Response objects have empty/None text — must not crash."""
    r = Response()
    r.status_code = 403
    # no _content set, .text will be empty string
    assert looks_off_campus(r) is False


# ── off_campus_hint ──────────────────────────────────────────────────────────


def test_hint_mentions_module_name():
    msg = off_campus_hint("Faculty")
    assert msg.startswith("Faculty ")


def test_hint_mentions_sustech_and_campus():
    """User-facing recovery instructions — both keywords required."""
    msg = off_campus_hint("Booking")
    assert "SUSTech" in msg
    assert "campus" in msg.lower()
    assert "Wi-Fi" in msg


def test_hint_mentions_offending_status():
    msg = off_campus_hint("PMS")
    assert "403" in msg
    assert OFF_CAMPUS_BODY in msg


def test_hint_distinct_per_module():
    """Per-module hints should differ so users know which subsystem failed."""
    pms = off_campus_hint("PMS")
    booking = off_campus_hint("Booking")
    assert pms != booking
    assert pms.startswith("PMS ")
    assert booking.startswith("Booking ")