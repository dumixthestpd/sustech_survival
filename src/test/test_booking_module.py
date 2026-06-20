"""
test_booking_module.py — Module surface, helper, and import tests.

No network. Tests imports, constants, coercion helpers, and the singleton
factory structure.
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from sustech_survival.booking import (
    BookingClient, BookingError,
    booking,
    Room, Meeting, MyMeeting,
)
from sustech_survival.booking.booking import (
    OFF_CAMPUS_BODY, OFF_CAMPUS_HINT,
    BOOKING_BASE, BOOKING_API,
    AUTH_ERROR_MESSAGES,
    _looks_off_campus, _looks_auth_error,
)


# ── Module surface ──────────────────────────────────────────────────────────

class TestModuleExports:
    def test_all_classes_importable(self):
        for cls in [BookingClient, BookingError, Room, Meeting, MyMeeting]:
            assert cls is not None

    def test_singleton_factory_exists(self):
        assert callable(booking)


# ── Constants ───────────────────────────────────────────────────────────────

class TestConstants:
    def test_base_url(self):
        assert BOOKING_BASE == "https://booking.sustech.edu.cn"

    def test_api_url(self):
        assert BOOKING_API == "https://booking.sustech.edu.cn/api/SystemApi"

    def test_off_campus_body(self):
        assert OFF_CAMPUS_BODY == "Access forbidden, please contact administrator."

    def test_off_campus_hint_mentions_wifi(self):
        # Critical user-facing string — if you change it, the user can't recover.
        assert "Wi-Fi" in OFF_CAMPUS_HINT
        assert "campus" in OFF_CAMPUS_HINT.lower()

    def test_auth_error_messages_includes_known_tokens(self):
        assert "Authorization is NULL" in AUTH_ERROR_MESSAGES


# ── Coercion helpers ───────────────────────────────────────────────────────

class TestLooksOffCampus:
    def test_true_on_403_with_body(self):
        from requests import Response
        r = Response()
        r.status_code = 403
        r._content = OFF_CAMPUS_BODY.encode("utf-8")
        assert _looks_off_campus(r) is True

    def test_false_on_200(self):
        from requests import Response
        r = Response()
        r.status_code = 200
        r._content = b"<html>ok</html>"
        assert _looks_off_campus(r) is False

    def test_false_on_403_without_body(self):
        from requests import Response
        r = Response()
        r.status_code = 403
        r._content = b"some other 403 body"
        assert _looks_off_campus(r) is False


class TestLooksAuthError:
    def test_true_on_known_message(self):
        assert _looks_auth_error({"IsSuccess": False, "Message": "Authorization is NULL"}) is True

    def test_false_on_success(self):
        assert _looks_auth_error({"IsSuccess": True, "Message": "ok"}) is False

    def test_false_on_unrelated_error(self):
        assert _looks_auth_error({"IsSuccess": False, "Message": "参数错误"}) is False

    def test_false_on_no_message(self):
        assert _looks_auth_error({"IsSuccess": False}) is False


# ── add_meeting input validation ────────────────────────────────────────────

class TestAddMeetingValidation:
    """Validation happens BEFORE any HTTP call — verify with a stub client."""

    def _stub_client(self):
        # No HTTP — just exercise the input checks.
        import requests
        sess = requests.Session()
        return BookingClient(sess)

    def test_rejects_end_before_start(self):
        c = self._stub_client()
        with pytest.raises(BookingError, match="must be after start"):
            c.add_meeting(
                room_id="X",
                start=datetime(2026, 6, 20, 16, 0),
                end=datetime(2026, 6, 20, 14, 0),
                title="x",
            )

    def test_rejects_overlong_duration(self):
        c = self._stub_client()
        with pytest.raises(BookingError, match="8 hours"):
            c.add_meeting(
                room_id="X",
                start=datetime(2026, 6, 20, 8, 0),
                end=datetime(2026, 6, 20, 18, 0),  # 10 hours
                title="x",
            )

    def test_rejects_empty_title(self):
        c = self._stub_client()
        with pytest.raises(BookingError, match="Title is required"):
            c.add_meeting(
                room_id="X",
                start=datetime(2026, 6, 20, 14, 0),
                end=datetime(2026, 6, 20, 16, 0),
                title="   ",
            )
