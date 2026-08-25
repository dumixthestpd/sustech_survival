"""
Tests for sustech_survival.lib.booking client policy enforcement.

These tests verify the module enforces the library's published policy
"南方科技大学图书馆讨论间使用办法" (verified 2026-06-29 from
sysInfo/help endpoint). They are OFFLINE — no live API calls.

Policy summary (per the verified document):
  - 1.2: max 2 days in advance
  - 1.2: max 2 hours per booking
  - 1.3: 3+ person rooms need 2+ co-applicants (resv_member >= 3 total)
  - 1.5: 15 min no-show penalty (server-enforced, not in client checks)
  - 1.6: cancellation must happen >= 10 minutes before start
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from sustech_survival.lib.booking.client import (
    LibBookingError,
    LibBookingPolicyError,
    PolicyWarning,
    _is_3plus_person_room,
    validate_against_policy,
    validate_cancellation_timing,
)


# -- _is_3plus_person_room ----------------------------------------------------


class TestIs3PlusPersonRoom:
    def test_1_to_3(self):
        assert _is_3plus_person_room("C105（1-3人）") is False

    def test_3_to_6(self):
        assert _is_3plus_person_room("C201（3-6人）") is True

    def test_3_to_7(self):
        assert _is_3plus_person_room("G101（3-7人）") is True

    def test_3_to_10(self):
        assert _is_3plus_person_room("G104（3-10人）") is True

    def test_no_capacity_marker(self):
        # No "（N-M人）" pattern — return None (unknown)
        assert _is_3plus_person_room("C201") is None

    def test_none(self):
        assert _is_3plus_person_room(None) is None

    def test_empty(self):
        assert _is_3plus_person_room("") is None


# -- validate_against_policy -------------------------------------------------


class TestValidateAgainstPolicy:
    """Per policy 1.2 + 1.3 + 1.6."""

    NOW = datetime(2026, 7, 1, 12, 0)  # reference time for all tests

    # -- 1.2: max 2 days in advance -------------------------------------

    def test_advance_within_2_days_ok(self):
        warnings = validate_against_policy(
            dev_id=13, begin=self.NOW + timedelta(hours=2),
            end=self.NOW + timedelta(hours=3),
            member_kind=1, resv_member=None,
            dev_name="C105（1-3人）", now=self.NOW,
        )
        # No policy violations
        assert all(w.severity != "error" for w in warnings)

    def test_advance_at_2_days_ok(self):
        warnings = validate_against_policy(
            dev_id=13, begin=self.NOW + timedelta(days=2),
            end=self.NOW + timedelta(days=2, hours=1),
            member_kind=1, resv_member=None,
            dev_name="C105（1-3人）", now=self.NOW,
        )
        # At exactly 2 days = OK
        assert all(w.severity != "error" for w in warnings)

    def test_advance_3_days_errors(self):
        warnings = validate_against_policy(
            dev_id=13, begin=self.NOW + timedelta(days=3),
            end=self.NOW + timedelta(days=3, hours=1),
            member_kind=1, resv_member=None,
            dev_name="C105（1-3人）", now=self.NOW,
        )
        errors = [w for w in warnings if w.severity == "error"]
        assert any("2 days" in w.message for w in errors)

    def test_advance_5_days_errors(self):
        warnings = validate_against_policy(
            dev_id=13, begin=self.NOW + timedelta(days=5),
            end=self.NOW + timedelta(days=5, hours=1),
            member_kind=1, resv_member=None,
            dev_name="C105（1-3人）", now=self.NOW,
        )
        errors = [w for w in warnings if w.severity == "error"]
        assert any("2 days" in w.message for w in errors)

    def test_advance_in_past_warns(self):
        warnings = validate_against_policy(
            dev_id=13, begin=self.NOW - timedelta(hours=1),
            end=self.NOW + timedelta(hours=1),
            member_kind=1, resv_member=None,
            dev_name="C105（1-3人）", now=self.NOW,
        )
        past_warnings = [w for w in warnings if "past" in w.message]
        assert past_warnings
        # Past is a warning, not an error (the error is the duration)
        assert all(w.severity != "error" for w in past_warnings)

    # -- 1.2: max 2 hours per booking -----------------------------------

    def test_duration_1h_ok(self):
        warnings = validate_against_policy(
            dev_id=13, begin=self.NOW + timedelta(hours=1),
            end=self.NOW + timedelta(hours=2),
            member_kind=1, resv_member=None,
            dev_name="C105（1-3人）", now=self.NOW,
        )
        # No duration errors
        assert not any("2 hours" in w.message for w in warnings)

    def test_duration_2h_ok(self):
        warnings = validate_against_policy(
            dev_id=13, begin=self.NOW + timedelta(hours=1),
            end=self.NOW + timedelta(hours=3),
            member_kind=1, resv_member=None,
            dev_name="C105（1-3人）", now=self.NOW,
        )
        # Exactly 2h = OK
        assert not any("2 hours" in w.message for w in warnings)

    def test_duration_3h_errors(self):
        warnings = validate_against_policy(
            dev_id=13, begin=self.NOW + timedelta(hours=1),
            end=self.NOW + timedelta(hours=4),
            member_kind=1, resv_member=None,
            dev_name="C105（1-3人）", now=self.NOW,
        )
        errors = [w for w in warnings if w.severity == "error"]
        assert any("2 hours" in w.message for w in errors)

    def test_duration_4h_errors(self):
        warnings = validate_against_policy(
            dev_id=13, begin=self.NOW + timedelta(hours=1),
            end=self.NOW + timedelta(hours=5),
            member_kind=1, resv_member=None,
            dev_name="C105（1-3人）", now=self.NOW,
        )
        errors = [w for w in warnings if w.severity == "error"]
        assert any("2 hours" in w.message for w in errors)

    def test_duration_zero_errors(self):
        warnings = validate_against_policy(
            dev_id=13, begin=self.NOW + timedelta(hours=1),
            end=self.NOW + timedelta(hours=1),  # 0 duration
            member_kind=1, resv_member=None,
            dev_name="C105（1-3人）", now=self.NOW,
        )
        errors = [w for w in warnings if w.severity == "error"]
        assert any("non-positive" in w.message for w in errors)

    def test_duration_negative_errors(self):
        warnings = validate_against_policy(
            dev_id=13, begin=self.NOW + timedelta(hours=2),
            end=self.NOW + timedelta(hours=1),  # negative
            member_kind=1, resv_member=None,
            dev_name="C105（1-3人）", now=self.NOW,
        )
        errors = [w for w in warnings if w.severity == "error"]
        assert any("non-positive" in w.message for w in errors)

    # -- 1.3: 3+ person rooms need 2+ co-applicants ----------------------

    def test_3plus_room_with_3_members_ok(self):
        # C201 is 3-6 person, booker + 2 co-applicants = 3 members
        warnings = validate_against_policy(
            dev_id=15, begin=self.NOW + timedelta(hours=1),
            end=self.NOW + timedelta(hours=2),
            member_kind=2, resv_member=[100001, 100002, 100003],
            dev_name="C201（3-6人）", now=self.NOW,
        )
        # No group errors
        assert not any("3+ person" in w.message for w in warnings)

    def test_3plus_room_with_2_members_errors(self):
        # Only booker + 1 co-applicant = 2 members < 3 required
        warnings = validate_against_policy(
            dev_id=15, begin=self.NOW + timedelta(hours=1),
            end=self.NOW + timedelta(hours=2),
            member_kind=2, resv_member=[100001, 100002],
            dev_name="C201（3-6人）", now=self.NOW,
        )
        errors = [w for w in warnings if w.severity == "error"]
        assert any("3+ person" in w.message for w in errors)

    def test_3plus_room_self_only_errors(self):
        # Only self = 1 member
        warnings = validate_against_policy(
            dev_id=15, begin=self.NOW + timedelta(hours=1),
            end=self.NOW + timedelta(hours=2),
            member_kind=1, resv_member=[100001],
            dev_name="C201（3-6人）", now=self.NOW,
        )
        errors = [w for w in warnings if w.severity == "error"]
        assert any("3+ person" in w.message for w in errors)

    def test_1to3_room_with_1_member_ok(self):
        warnings = validate_against_policy(
            dev_id=13, begin=self.NOW + timedelta(hours=1),
            end=self.NOW + timedelta(hours=2),
            member_kind=1, resv_member=[100001],
            dev_name="C105（1-3人）", now=self.NOW,
        )
        # No group errors
        assert not any("3+ person" in w.message for w in warnings)

    def test_1to3_room_with_group_warns(self):
        # Allowed but unnecessary — warn, don't error
        warnings = validate_against_policy(
            dev_id=13, begin=self.NOW + timedelta(hours=1),
            end=self.NOW + timedelta(hours=2),
            member_kind=2, resv_member=[100001, 100002, 100003],
            dev_name="C105（1-3人）", now=self.NOW,
        )
        # The warning is "group booking not required" (advisory)
        warnings_only = [w for w in warnings if w.severity == "warning"]
        assert any("not required" in w.message for w in warnings_only)

    def test_unknown_room_no_group_check(self):
        # dev_name=None — skip the group check
        warnings = validate_against_policy(
            dev_id=999, begin=self.NOW + timedelta(hours=1),
            end=self.NOW + timedelta(hours=2),
            member_kind=1, resv_member=None,
            dev_name=None, now=self.NOW,
        )
        # No group errors (we don't know the room capacity)
        assert not any("3+ person" in w.message for w in warnings)

    # -- 1.6: cancellation deadline (advisory at create time) -----------

    def test_cancellation_deadline_warning(self):
        # Begin is 5 minutes from now — too late to cancel
        warnings = validate_against_policy(
            dev_id=13, begin=self.NOW + timedelta(minutes=5),
            end=self.NOW + timedelta(hours=1, minutes=5),
            member_kind=1, resv_member=None,
            dev_name="C105（1-3人）", now=self.NOW,
        )
        warn_only = [w for w in warnings if w.severity == "warning"]
        assert any("10-minute cancellation deadline" in w.message for w in warn_only)


# -- validate_cancellation_timing -------------------------------------------


class TestValidateCancellationTiming:
    """Per policy 1.6: cancel >= 10 minutes before start."""

    NOW = datetime(2026, 7, 1, 12, 0)

    def test_cancel_30_min_before_ok(self):
        warnings = validate_cancellation_timing(
            begin=self.NOW + timedelta(minutes=30), now=self.NOW,
        )
        assert warnings == []

    def test_cancel_10_min_before_ok(self):
        warnings = validate_cancellation_timing(
            begin=self.NOW + timedelta(minutes=10), now=self.NOW,
        )
        # Exactly 10 min = boundary, not an error
        assert not any(w.severity == "error" for w in warnings)

    def test_cancel_5_min_before_errors(self):
        warnings = validate_cancellation_timing(
            begin=self.NOW + timedelta(minutes=5), now=self.NOW,
        )
        errors = [w for w in warnings if w.severity == "error"]
        assert any("10 minutes" in w.message for w in errors)
        assert any("5.0 minutes" in w.message for w in errors)

    def test_cancel_1_min_before_errors(self):
        warnings = validate_cancellation_timing(
            begin=self.NOW + timedelta(minutes=1), now=self.NOW,
        )
        errors = [w for w in warnings if w.severity == "error"]
        assert errors

    def test_cancel_after_start_warns(self):
        warnings = validate_cancellation_timing(
            begin=self.NOW - timedelta(minutes=5), now=self.NOW,
        )
        # Already started — should be a warning (use endReserve instead)
        warnings_only = [w for w in warnings if w.severity == "warning"]
        assert any("already started" in w.message for w in warnings_only)
        # Should not be an error (it's a warning)
        assert not any(w.severity == "error" for w in warnings)

    def test_cancel_exactly_now_errors(self):
        warnings = validate_cancellation_timing(
            begin=self.NOW, now=self.NOW,
        )
        # 0 minutes to start = within the 10-min no-cancel window
        errors = [w for w in warnings if w.severity == "error"]
        assert any("10 minutes" in w.message for w in errors)


# -- Integration: validate_against_policy returns a list of PolicyWarning ----


class TestPolicyWarningDataclass:
    def test_policy_warning_shape(self):
        w = PolicyWarning("error", "test message")
        assert w.severity == "error"
        assert w.message == "test message"

    def test_validate_returns_list_of_warnings(self):
        warnings = validate_against_policy(
            dev_id=13,
            begin=datetime(2026, 7, 1, 14, 0),
            end=datetime(2026, 7, 1, 14, 0),  # 0 duration
            member_kind=1, resv_member=None,
            dev_name="C105（1-3人）",
        )
        assert isinstance(warnings, list)
        assert all(isinstance(w, PolicyWarning) for w in warnings)
        # The 0-duration is the violation
        assert any(w.severity == "error" for w in warnings)


# -- Integration: LibBookingError vs LibBookingPolicyError ------------------


class TestPolicyErrorClasses:
    def test_policy_error_subclasses_runtime(self):
        # The policy error is both a RuntimeError (parent of LibBookingError)
        # and a LibBookingError — so existing error handlers catch it.
        e = LibBookingPolicyError("test")
        assert isinstance(e, RuntimeError)
        assert isinstance(e, LibBookingError)
        assert str(e) == "test"
