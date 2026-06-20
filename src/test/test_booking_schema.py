"""
test_booking_schema.py — Offline tests for booking schema dataclasses.

No network. Tests the `_time_only` / `_parse_dt` helpers and the `from_api()`
classmethod parsers against canned API responses.
"""
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from sustech_survival.booking.schema import (
    Room, Meeting, MyMeeting,
    _time_only, _parse_dt,
)


# ── Helper functions ────────────────────────────────────────────────────────

class TestTimeOnly:
    def test_extracts_from_iso_datetime(self):
        assert _time_only("1970-01-01T08:00:00") == "08:00:00"

    def test_passthrough_short_form(self):
        assert _time_only("08:00:00") == "08:00:00"

    def test_empty_returns_empty(self):
        assert _time_only("") == ""
        assert _time_only(None) == ""

    def test_no_match_returns_input(self):
        # If the regex doesn't match, return the input unchanged.
        assert _time_only("nonsense") == "nonsense"


class TestParseDt:
    def test_iso_with_seconds(self):
        assert _parse_dt("2026-06-20T14:00:00") == datetime(2026, 6, 20, 14, 0, 0)

    def test_iso_without_seconds(self):
        assert _parse_dt("2026-06-20T14:00") == datetime(2026, 6, 20, 14, 0)

    def test_space_separator(self):
        assert _parse_dt("2026-06-20 14:00:00") == datetime(2026, 6, 20, 14, 0, 0)

    def test_empty_returns_none(self):
        assert _parse_dt("") is None
        assert _parse_dt(None) is None

    def test_garbage_returns_none(self):
        assert _parse_dt("not a date") is None


# ── Room.from_api ───────────────────────────────────────────────────────────

class TestRoomFromApi:
    SHORT_CODE = {
        "MeetingRoomID": "ZC02",
        "MeetingRoomName": "致诚小会议室",
        "MeetingRoomType": "会议室",
        "CapacityNumber": 8,
        "MeetingRoomLocal": "湖畔公寓2栋1层102",
        "IsAvailable": True,
        "IsApproval": True,
        "NumberOfDaysAhead": 100,
        "CanBookStartTime": "1970-01-01T08:00:00",
        "CanBookEndTime": "1970-01-01T17:00:00",
        "Longitude": 114.00546,
        "Latitude": 22.605972,
        "DeptName": "学生工作部",
        "MeetingRoomEquipments": [{"EquipmentName": "电视机", "Quantity": 1}],
        "MeetingRoomManagers": [{"UserInfoModel": {"XM": "杨秋伊"}}],
        "RegisterDistance": 300,
    }

    UUID_ROOM = {
        "MeetingRoomID": "5a95c2e6-a36f-4578-830d-fc6965e04330",
        "MeetingRoomName": "湖畔三栋402",
        "MeetingRoomType": "自习室",
        "CapacityNumber": 20,
        "MeetingRoomLocal": "湖畔公寓3栋4层402",
        "IsAvailable": True,
        "IsApproval": False,
        "NumberOfDaysAhead": 100,
        "CanBookStartTime": "1970-01-01T08:00:00",
        "CanBookEndTime": "1970-01-01T22:00:00",
        "Longitude": 0,
        "Latitude": 0,
        "DeptName": "树仁书院",
        "MeetingRoomEquipments": [],
        "MeetingRoomManagers": [],
        "RegisterDistance": 0,
    }

    def test_short_code_id(self):
        r = Room.from_api(self.SHORT_CODE)
        assert r.id == "ZC02"
        assert r.name == "致诚小会议室"
        assert r.room_type == "会议室"
        assert r.capacity == 8
        assert r.location == "湖畔公寓2栋1层102"
        assert r.is_available is True
        assert r.needs_approval is True
        assert r.bookable_days_ahead == 100
        assert r.book_start == "08:00:00"
        assert r.book_end == "17:00:00"
        assert r.dept_name == "学生工作部"
        assert r.equipment == ["电视机"]
        assert r.managers == ["杨秋伊"]
        assert r.register_distance_m == 300

    def test_uuid_id(self):
        r = Room.from_api(self.UUID_ROOM)
        assert r.id == "5a95c2e6-a36f-4578-830d-fc6965e04330"
        assert r.capacity == 20
        assert r.needs_approval is False
        assert r.book_end == "22:00:00"

    def test_equipment_filters_empty_names(self):
        raw = {
            "MeetingRoomID": "X",
            "MeetingRoomEquipments": [
                {"EquipmentName": "A"},
                {"EquipmentName": ""},
                {"EquipmentName": None},
                {"EquipmentName": "B"},
            ],
            "MeetingRoomManagers": [],
        }
        r = Room.from_api(raw)
        assert r.equipment == ["A", "B"]

    def test_managers_filters_empty_names(self):
        raw = {
            "MeetingRoomID": "X",
            "MeetingRoomManagers": [
                {"UserInfoModel": {"XM": "Alice"}},
                {"UserInfoModel": {}},
                {"UserInfoModel": None},
                {"UserInfoModel": {"XM": "Bob"}},
            ],
        }
        r = Room.from_api(raw)
        assert r.managers == ["Alice", "Bob"]

    def test_handles_missing_fields(self):
        r = Room.from_api({})
        assert r.id == ""
        assert r.capacity == 0
        assert r.is_available is False
        assert r.book_start == ""
        assert r.book_end == ""
        assert r.equipment == []
        assert r.managers == []

    def test_bookable_hours_str(self):
        r = Room.from_api(self.SHORT_CODE)
        assert r.bookable_hours_str() == "08:00-17:00"

    def test_bookable_hours_str_empty(self):
        r = Room.from_api({})
        assert r.bookable_hours_str() == "n/a"


# ── Meeting.from_api ────────────────────────────────────────────────────────

class TestMeetingFromApi:
    RAW = {
        "MeetingID": "M-001",
        "MeetingRoomID": "ZC02",
        "MeetingName": "Team sync",
        "MeetingStart": "2026-06-20T14:00:00",
        "MeetingEnd": "2026-06-20T16:00:00",
        "UserName": "Alice",
        "UserID": "12413021",
        "Status": "已批准",
        "MeetingType": "学术",
        "NumberOfParticipants": 5,
        "MeetingDesc": "Weekly sync",
    }

    def test_basic(self):
        m = Meeting.from_api(self.RAW)
        assert m.id == "M-001"
        assert m.room_id == "ZC02"
        assert m.title == "Team sync"
        assert m.start_at == datetime(2026, 6, 20, 14, 0, 0)
        assert m.end_at == datetime(2026, 6, 20, 16, 0, 0)
        assert m.user_name == "Alice"
        assert m.user_id == "12413021"
        assert m.status == "已批准"
        assert m.participants == 5
        assert m.description == "Weekly sync"

    def test_handles_alternate_field_names(self):
        # Some endpoints use Title / Description instead of MeetingName / MeetingDesc.
        raw = {
            "ID": "X-001",
            "MeetingRoomID": "ZC02",
            "Title": "Alt name",
            "StartTime": "2026-06-20T14:00:00",
            "EndTime": "2026-06-20T16:00:00",
        }
        m = Meeting.from_api(raw)
        assert m.id == "X-001"
        assert m.title == "Alt name"
        assert m.start_at == datetime(2026, 6, 20, 14, 0, 0)


# ── MyMeeting.from_api ─────────────────────────────────────────────────────

class TestMyMeetingFromApi:
    RAW = {
        "MeetingID": "MM-100",
        "MeetingRoomID": "EQBK01",
        "MeetingRoomName": "宿舍11栋活动室101",
        "MeetingName": "Group study",
        "MeetingStart": "2026-06-21T19:00:00",
        "MeetingEnd": "2026-06-21T21:00:00",
        "Status": "待审批",
        "IsUnread": True,
    }

    def test_basic(self):
        m = MyMeeting.from_api(self.RAW)
        assert m.id == "MM-100"
        assert m.room_id == "EQBK01"
        assert m.room_name == "宿舍11栋活动室101"
        assert m.title == "Group study"
        assert m.start_at == datetime(2026, 6, 21, 19, 0, 0)
        assert m.unread is True

    def test_unread_defaults_false(self):
        raw = dict(self.RAW)
        raw.pop("IsUnread")
        m = MyMeeting.from_api(raw)
        assert m.unread is False
