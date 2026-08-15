"""
Tests for sustech_survival.lib.booking.schema — parsing + helpers.

These are OFFLINE tests — no live API calls, no Playwright, no real
credentials. They use synthetic JSON that mirrors the real API shape
(verified 2026-06-29) to ensure the dataclass parsers handle the data
correctly.

References:
    sustech-dev/references/lib-booking-ic-2026-06-29.md — full API map
    sustech-survival/references/sso-... — auth helper contract
"""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from sustech_survival.lib.booking.schema import (
    CampusGroup,
    Lab,
    LabWithRooms,
    OpenTime,
    Reservation,
    Room,
    RoomIdleCategory,
    UserInfo,
    build_reservation_payload,
    format_ic_dt,
    _parse_dt,
)


# ── Time helpers ─────────────────────────────────────────────────────────────


class TestParseDt:
    def test_iso_with_t_and_seconds(self):
        dt = _parse_dt("2026-07-01T14:30:00")
        assert dt == datetime(2026, 7, 1, 14, 30)

    def test_iso_with_space(self):
        dt = _parse_dt("2026-07-01 14:30:00")
        assert dt == datetime(2026, 7, 1, 14, 30)

    def test_ic_native_format(self):
        dt = _parse_dt("2026/07/01 14:30:00")
        assert dt == datetime(2026, 7, 1, 14, 30)

    def test_no_seconds(self):
        dt = _parse_dt("2026-07-01 14:30")
        assert dt == datetime(2026, 7, 1, 14, 30)

    def test_with_milliseconds(self):
        dt = _parse_dt("2026-07-01T14:30:00.000")
        assert dt == datetime(2026, 7, 1, 14, 30)

    def test_none_returns_none(self):
        assert _parse_dt(None) is None

    def test_empty_returns_none(self):
        assert _parse_dt("") is None

    def test_garbage_returns_none(self):
        assert _parse_dt("not a date") is None


class TestFormatIcDt:
    def test_basic(self):
        assert format_ic_dt(datetime(2026, 7, 1, 14, 30)) == "2026-07-01 14:30:00"

    def test_pads_zero(self):
        # Single-digit month/day/hour/minute
        assert format_ic_dt(datetime(2026, 3, 9, 8, 5)) == "2026-03-09 08:05:00"

    def test_seconds_always_zero(self):
        # We strip seconds regardless of input
        assert format_ic_dt(datetime(2026, 7, 1, 14, 30, 45)) == "2026-07-01 14:30:00"

    def test_round_trip(self):
        original = datetime(2026, 7, 1, 14, 30)
        formatted = format_ic_dt(original)
        parsed = _parse_dt(formatted)
        assert parsed == original


# ── Lab ──────────────────────────────────────────────────────────────────────


class TestLab:
    def test_from_api(self):
        raw = {"labId": 4, "labName": "涵泳一层(Learning Nexus 1st floor)"}
        lab = Lab.from_api(raw)
        assert lab.lab_id == 4
        assert lab.lab_name == "涵泳一层(Learning Nexus 1st floor)"

    def test_from_api_missing_optional(self):
        # No labName — defaults to empty string
        lab = Lab.from_api({"labId": 1})
        assert lab.lab_id == 1
        assert lab.lab_name == ""


# ── OpenTime + Room ──────────────────────────────────────────────────────────


class TestOpenTime:
    def test_from_api(self):
        raw = {"openStartTime": "08:00", "openEndTime": "21:59", "openLimit": 1}
        ot = OpenTime.from_api(raw)
        assert ot.open_start_time == "08:00"
        assert ot.open_end_time == "21:59"
        assert ot.open_limit == 1

    def test_from_api_missing_openLimit(self):
        raw = {"openStartTime": "08:00", "openEndTime": "21:59"}
        ot = OpenTime.from_api(raw)
        assert ot.open_limit == 0


class TestRoom:
    def test_from_api_with_resv_infos_null(self):
        # Real example from the 2026-06-29 probe
        raw = {
            "devId": 13,
            "devName": "C105（1-3人）",
            "minResvTime": 10,
            "openTimes": [
                {"openStartTime": "08:00", "openEndTime": "21:59", "openLimit": 1}
            ],
            "resvInfos": None,
        }
        r = Room.from_api(raw)
        assert r.dev_id == 13
        assert r.dev_name == "C105（1-3人）"
        assert r.min_resv_time == 10
        assert len(r.open_times) == 1
        assert r.open_times[0].open_start_time == "08:00"
        assert r.resv_infos is None

    def test_from_api_with_resv_infos_populated(self):
        # resvInfos shape not yet verified — but it should round-trip
        raw = {
            "devId": 14,
            "devName": "C106（1-3人）",
            "minResvTime": 10,
            "openTimes": [{"openStartTime": "08:00", "openEndTime": "21:59", "openLimit": 1}],
            "resvInfos": {"someKey": "someValue"},  # shape TBD
        }
        r = Room.from_api(raw)
        assert r.resv_infos == {"someKey": "someValue"}

    def test_from_api_multiple_open_times(self):
        raw = {
            "devId": 99,
            "devName": "morning+afternoon room",
            "minResvTime": 10,
            "openTimes": [
                {"openStartTime": "08:00", "openEndTime": "12:00", "openLimit": 1},
                {"openStartTime": "14:00", "openEndTime": "21:59", "openLimit": 2},
            ],
            "resvInfos": None,
        }
        r = Room.from_api(raw)
        assert len(r.open_times) == 2
        assert r.open_times[1].open_start_time == "14:00"

    def test_from_api_empty_open_times(self):
        raw = {"devId": 1, "devName": "x", "minResvTime": 0, "openTimes": []}
        r = Room.from_api(raw)
        assert r.open_times == []


# ── LabWithRooms + CampusGroup ───────────────────────────────────────────────


class TestLabWithRooms:
    def test_from_api(self):
        raw = {
            "labId": 4,
            "labName": "涵泳一层(Learning Nexus 1st floor)",
            "roomInfos": [
                {"devId": 13, "devName": "C105", "minResvTime": 10,
                 "openTimes": [], "resvInfos": None},
                {"devId": 14, "devName": "C106", "minResvTime": 10,
                 "openTimes": [], "resvInfos": None},
            ],
        }
        l = LabWithRooms.from_api(raw)
        assert l.lab_id == 4
        assert len(l.rooms) == 2
        assert l.rooms[0].dev_id == 13

    def test_from_api_no_rooms(self):
        l = LabWithRooms.from_api({"labId": 1, "labName": "empty", "roomInfos": []})
        assert l.rooms == []


class TestCampusGroup:
    def test_from_api_nested(self):
        # Real nested structure from 2026-06-29 probe
        raw = {
            "campusId": 1,
            "campusName": "涵泳讨论间(Learning Nexus Group Study Rooms)",
            "labInfos": [
                {
                    "labId": 4,
                    "labName": "涵泳一层",
                    "roomInfos": [
                        {"devId": 13, "devName": "C105", "minResvTime": 10,
                         "openTimes": [], "resvInfos": None},
                    ],
                },
                {
                    "labId": 5,
                    "labName": "涵泳二层",
                    "roomInfos": [
                        {"devId": 15, "devName": "C201", "minResvTime": 10,
                         "openTimes": [], "resvInfos": None},
                    ],
                },
            ],
        }
        g = CampusGroup.from_api(raw)
        assert g.campus_id == 1
        assert len(g.labs) == 2
        assert g.labs[0].rooms[0].dev_id == 13
        assert g.labs[1].rooms[0].dev_id == 15

    def test_from_api_empty(self):
        g = CampusGroup.from_api({"campusId": 0, "campusName": ""})
        assert g.labs == []


# ── RoomIdleCategory ────────────────────────────────────────────────────────


class TestRoomIdleCategory:
    def test_from_api(self):
        raw = {
            "name": "会议室",
            "idelQuantity": 2,
            "totalQuantity": 2,
        }
        c = RoomIdleCategory.from_api(raw)
        assert c.name == "会议室"
        assert c.idle_quantity == 2
        assert c.total_quantity == 2
        assert c.used_quantity == 0

    def test_used_quantity(self):
        c = RoomIdleCategory(
            name="讨论间 1-3", idle_quantity=7, total_quantity=11,
        )
        assert c.used_quantity == 4

    def test_from_api_bilingual_name(self):
        raw = {
            "name": "讨论间  Reserve Group Study Room (3-7 persons)",
            "idelQuantity": 13,
            "totalQuantity": 13,
        }
        c = RoomIdleCategory.from_api(raw)
        assert "Reserve Group Study Room" in c.name
        assert "3-7" in c.name


# ── Reservation ─────────────────────────────────────────────────────────────


class TestReservation:
    def test_from_api(self):
        # Verified wire shape (2026-06-30 Playwright probe of /#/ic/userinfo)
        raw = {
            "uuid": "abc123",
            "resvId": 12345,
            "resvDate": 20260701,
            "resvBeginTime": 1782885600000,   # unix ms — 2026-07-01 14:00 UTC+8
            "resvEndTime":   1782889200000,   # 2026-07-01 15:00 UTC+8
            "resvStatus": 1027,
            "classKind": 1,
            "resvKind": 16,
            "dayOfWeek": 2,
            "testName": "my meeting",
            "memo": "",
            "latestCheckInTime": 1782886500000,
            "resvDevInfoList": [{
                "devId": 13, "devName": "C105", "roomName": "C105",
                "labName": "涵泳一层", "kindName": "讨论间",
            }],
            "resvMemberInfoList": [
                {"accNo": 76727, "trueName": "<name>", "logonName": "<sid>",
                 "ident": 257, "kind": 65}
            ],
        }
        r = Reservation.from_api(raw)
        assert r.resv_id == 12345
        assert r.uuid == "abc123"
        assert r.dev_id == 13
        assert r.title == "my meeting"
        assert r.begin_time == datetime(2026, 7, 1, 14, 0)
        assert r.end_time == datetime(2026, 7, 1, 15, 0)
        assert r.resv_date == date(2026, 7, 1)
        assert r.resv_status == 1027
        assert r.class_kind == 1
        assert r.resv_kind == 16
        assert r.day_of_week == 2
        assert r.lab_name == "涵泳一层"
        assert r.dev_name == "C105"
        assert r.room_name == "C105"
        assert r.kind_name == "讨论间"
        assert len(r.members) == 1
        assert r.members[0].acc_no == 76727
        assert r.members[0].true_name == "<name>"
        assert r.display_name.startswith("#12345")

    def test_from_api_iso_t_separator(self):
        r = Reservation.from_api({
            "resvId": 1,
            "resvDevInfoList": [{"devId": 1}],
            "resvBeginTime": "2026-07-01T14:00:00",
            "resvEndTime":   "2026-07-01T15:00:00",
        })
        assert r.begin_time == datetime(2026, 7, 1, 14, 0)
        assert r.end_time == datetime(2026, 7, 1, 15, 0)

    def test_from_api_minimal(self):
        r = Reservation.from_api({"resvId": 999, "resvDevInfoList": [{"devId": 1}]})
        assert r.resv_id == 999
        assert r.begin_time is None
        assert r.end_time is None
        assert r.title == ""


# ── UserInfo ────────────────────────────────────────────────────────────────


class TestUserInfo:
    def test_from_api_real_shape(self):
        # Real 2026-06-29 probe response (redacted)
        raw = {
            "uuid": "8c253ced-...",
            "accNo": 76727,
            "pid": "<sid>",
            "logonName": "<sid>",
            "trueName": "<name>",
            "kind": 1,
            "ident": 257,
            "status": 1,
            "localstatus": 1,
            "classId": 369,
            "className": "2024级本科",
            "deptId": 2,
            "deptName": "南方科技大学",
            "manager": 1,
            "token": "29ee...",
        }
        u = UserInfo.from_api(raw)
        assert u.acc_no == 76727
        assert u.pid == "<sid>"
        assert u.true_name == "<name>"
        assert u.class_name == "2024级本科"
        assert u.dept_name == "南方科技大学"
        assert u.manager == 1

    def test_str_repr(self):
        u = UserInfo.from_api({"accNo": 76727, "pid": "<sid>", "trueName": "<name>"})
        s = str(u)
        assert "<name>" in s
        assert "76727" in s
        assert "<sid>" in s


# ── build_reservation_payload ──────────────────────────────────────────────


class TestBuildReservationPayload:
    def test_basic_self_reservation(self):
        payload = build_reservation_payload(
            acc_no=76727,
            dev_id=13,
            begin=datetime(2026, 7, 1, 14, 0),
            end=datetime(2026, 7, 1, 15, 0),
            title="my meeting",
        )
        assert payload["sysKind"] == 1
        assert payload["appAccNo"] == 76727
        assert payload["memberKind"] == 1
        assert payload["resvMember"] == [76727]
        assert payload["resvBeginTime"] == "2026-07-01 14:00:00"
        assert payload["resvEndTime"]   == "2026-07-01 15:00:00"
        assert payload["testName"] == "my meeting"
        assert payload["resvProperty"] == 0
        assert payload["resvDev"] == [13]
        assert payload["memo"] == ""

    def test_group_reservation(self):
        payload = build_reservation_payload(
            acc_no=76727,
            dev_id=13,
            begin=datetime(2026, 7, 1, 14, 0),
            end=datetime(2026, 7, 1, 15, 0),
            title="team sync",
            member_kind=2,
            resv_member=[76727, 76728, 76729],
            memo="weekly",
        )
        assert payload["memberKind"] == 2
        assert payload["resvMember"] == [76727, 76728, 76729]
        assert payload["memo"] == "weekly"

    def test_different_class_kind(self):
        # e.g. classKind=8 for seats
        payload = build_reservation_payload(
            acc_no=76727,
            dev_id=1,
            begin=datetime(2026, 7, 1, 14, 0),
            end=datetime(2026, 7, 1, 15, 0),
            title="x",
            class_kind=8,
        )
        assert payload["sysKind"] == 8

    def test_payload_keys_match_wire_shape(self):
        """Guard against accidental field name drift. If the server
        starts requiring a new key, this test will fail and force
        a deliberate update."""
        payload = build_reservation_payload(
            acc_no=1, dev_id=1,
            begin=datetime(2026, 7, 1, 0, 0),
            end=datetime(2026, 7, 1, 1, 0),
            title="x",
        )
        expected = {
            "sysKind", "appAccNo", "memberKind", "resvMember",
            "resvBeginTime", "resvEndTime", "testName",
            "resvProperty", "resvDev", "memo",
        }
        assert set(payload.keys()) == expected

    def test_resv_dev_is_list(self):
        """Wire shape requires resvDev to be an ARRAY, not a single int."""
        payload = build_reservation_payload(
            acc_no=1, dev_id=13,
            begin=datetime(2026, 7, 1, 14, 0),
            end=datetime(2026, 7, 1, 15, 0),
            title="x",
        )
        assert isinstance(payload["resvDev"], list)
        assert payload["resvDev"] == [13]

    def test_resv_member_is_list(self):
        payload = build_reservation_payload(
            acc_no=1, dev_id=13,
            begin=datetime(2026, 7, 1, 14, 0),
            end=datetime(2026, 7, 1, 15, 0),
            title="x",
        )
        assert isinstance(payload["resvMember"], list)
