"""
Tests for sustech_survival.tis.classroom.booking_schema — TIS 场地借用
schema dataclasses (BorrowApplication, BorrowDetail, BorrowTimeSlot, etc.).

All tests are pure offline — no live TIS server hit.

Run: pytest src/test/test_tis_booking_schema.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from sustech_survival.semester import Semester
from sustech_survival.tis.classroom.booking_schema import (
    AuditNode,
    AuditStatus,
    BorrowApplication,
    BorrowDetail,
    BorrowTimeSlot,
    PermissionResult,
    VenueOccupancySlot,
    STATUS_APPROVED,
    STATUS_REJECTED,
    STATUS_SAVED,
    STATUS_SUBMITTED,
    _fmt_dt,
    _parse_dt,
    _to_int,
)


# ── Helper tests ────────────────────────────────────────────────────────────


class TestParseDt:
    def test_iso_space(self):
        assert _parse_dt("2026-06-28 14:00:00") is not None

    def test_iso_t(self):
        assert _parse_dt("2026-06-28T14:00:00") is not None

    def test_date_only(self):
        assert _parse_dt("2026-06-28") is not None

    def test_iso_with_microseconds(self):
        assert _parse_dt("2026-06-28T14:00:00.123") is not None

    def test_iso_with_timezone(self):
        dt = _parse_dt("2026-06-26T08:15:18.000+00:00")
        assert dt is not None
        assert dt.year == 2026 and dt.month == 6 and dt.day == 26

    def test_iso_with_timezone_no_microseconds(self):
        dt = _parse_dt("2026-06-26T08:15:18+00:00")
        assert dt is not None
        assert dt.year == 2026

    def test_none(self):
        assert _parse_dt(None) is None

    def test_empty_string(self):
        assert _parse_dt("") is None

    def test_junk(self):
        assert _parse_dt("not a date") is None


class TestFmtDt:
    def test_roundtrip(self):
        from datetime import datetime
        dt = datetime(2026, 6, 28, 14, 0, 0)
        assert _fmt_dt(dt) == "2026-06-28 14:00:00"

    def test_none(self):
        assert _fmt_dt(None) == ""


class TestToInt:
    def test_int(self):
        assert _to_int(42) == 42

    def test_string_int(self):
        assert _to_int("42") == 42

    def test_none(self):
        assert _to_int(None) == 0

    def test_empty_string(self):
        assert _to_int("") == 0

    def test_custom_default(self):
        assert _to_int(None, default=99) == 99

    def test_junk(self):
        assert _to_int("not a number") == 0


# ── PermissionResult ───────────────────────────────────────────────────────


class TestPermissionResult:
    def test_allowed_string(self):
        p = PermissionResult.from_api("1")
        assert p.allowed is True
        assert p.raw == "1"

    def test_denied_string(self):
        p = PermissionResult.from_api("0")
        assert p.allowed is False
        assert p.raw == "0"

    def test_envelope_dict(self):
        p = PermissionResult.from_api({"code": 200, "content": "1"})
        assert p.allowed is True

    def test_none_input(self):
        p = PermissionResult.from_api(None)
        assert p.allowed is False
        assert p.raw == ""

    def test_other_string(self):
        p = PermissionResult.from_api("true")
        assert p.allowed is False


# ── AuditStatus ─────────────────────────────────────────────────────────────


class TestAuditStatus:
    def test_basic(self):
        raw = {"YWJDDM": "1", "YSHJDZTXSMC": "审核通过", "YSHJDZTXSMC_EN": "Approved"}
        s = AuditStatus.from_api(raw)
        assert s.code == "1"
        assert s.name == "审核通过"
        assert s.name_en == "Approved"
        assert s.occurred_at is None

    def test_missing_en(self):
        raw = {"YWJDDM": "2", "YSHJDZTXSMC": "驳回"}
        s = AuditStatus.from_api(raw)
        assert s.code == "2"
        assert s.name == "驳回"
        assert s.name_en == ""

    def test_alternate_keys(self):
        raw = {"code": "3", "name": "保存待审核"}
        s = AuditStatus.from_api(raw)
        assert s.code == "3"
        assert s.name == "保存待审核"

    def test_real_live_shape(self):
        raw = {"SJ": "2026-06-26T08:15:18.000+00:00", "YSHJDZTXSMC": "教工部审核通过"}
        s = AuditStatus.from_api(raw)
        assert s.name == "教工部审核通过"
        assert s.code == "教工部审核通过"
        assert s.occurred_at is not None
        assert s.occurred_at.year == 2026
        assert s.occurred_at.month == 6
        assert s.occurred_at.day == 26


# ── BorrowTimeSlot ─────────────────────────────────────────────────────────


class TestBorrowTimeSlot:
    def test_basic(self):
        raw = {
            "xh": 1,
            "xqj": 2,
            "ksjc": 3,
            "jsjc": 4,
            "zcbds": "1-15",
            "bz": "Week 1-15, Tuesday 3-4",
        }
        s = BorrowTimeSlot.from_api(raw)
        assert s.seq == 1
        assert s.weekday == 2
        assert s.period_start == 3
        assert s.period_end == 4
        assert s.week_pattern == "1-15"
        assert s.note.startswith("Week")

    def test_missing_fields(self):
        s = BorrowTimeSlot.from_api({})
        assert s.seq == 0
        assert s.weekday == 0
        assert s.period_start == 0
        assert s.period_end == 0
        assert s.week_pattern == ""

    def test_string_numbers(self):
        s = BorrowTimeSlot.from_api({"xqj": "5", "ksjc": "7", "jsjc": "8"})
        assert s.weekday == 5
        assert s.period_start == 7
        assert s.period_end == 8


# ── BorrowDetail ────────────────────────────────────────────────────────────


class TestBorrowDetail:
    def test_with_time_slots(self):
        raw = {
            "xuhhao": 1,
            "cddm": "YJ-123",
            "cdmc": "一教123",
            "zws": 55,
            "cdlocation": "一教 1层",
            "yongtu": "讲座",
            "jtsjlist": [
                {"xh": 1, "xqj": 2, "ksjc": 3, "jsjc": 4, "zcbds": "5-8"},
            ],
        }
        d = BorrowDetail.from_api(raw)
        assert d.seq == 1
        assert d.room_code == "YJ-123"
        assert d.room_name == "一教123"
        assert d.capacity == 55
        assert d.location == "一教 1层"
        assert d.purpose == "讲座"
        assert len(d.time_slots) == 1
        assert d.time_slots[0].weekday == 2

    def test_no_time_slots(self):
        d = BorrowDetail.from_api({"cddm": "YJ-324"})
        assert d.room_code == "YJ-324"
        assert d.time_slots == []

    def test_empty_input(self):
        d = BorrowDetail.from_api({})
        assert d.seq == 0
        assert d.room_code == ""


# ── AuditNode ───────────────────────────────────────────────────────────────


class TestAuditNode:
    def test_basic(self):
        raw = {
            "xh": 1,
            "shjs": "ROLE_FDY",
            "shjsxm": "辅导员",
            "shjsxm_en": "Counselor",
            "shzt": "审核通过",
            "shyj": "同意",
            "shr": "张三",
            "shsj": "2026-06-28 10:30:00",
        }
        n = AuditNode.from_api(raw)
        assert n.seq == 1
        assert n.role_code == "ROLE_FDY"
        assert n.role_name == "辅导员"
        assert n.role_name_en == "Counselor"
        assert n.status == "审核通过"
        assert n.opinion == "同意"
        assert n.auditor == "张三"
        assert n.audited_at is not None
        assert n.audited_at.year == 2026

    def test_no_audit_yet(self):
        n = AuditNode.from_api({"shjs": "ROLE_DEAN", "shjsxm": "院长"})
        assert n.role_name == "院长"
        assert n.auditor == ""
        assert n.audited_at is None

    def test_alternate_keys(self):
        n = AuditNode.from_api({"status": "pending"})
        assert n.status == "pending"


# ── VenueOccupancySlot ──────────────────────────────────────────────────────


class TestVenueOccupancySlot:
    def test_basic(self):
        raw = {
            "cddm": "YJ-123",
            "xqj": 2,
            "ksjc": 3,
            "jsjc": 4,
            "zcbds": "1-15",
            "label": "YJ-123 Tuesday 3-4 weeks 1-15",
        }
        s = VenueOccupancySlot.from_api(raw)
        assert s.room_code == "YJ-123"
        assert s.weekday == 2
        assert s.period_start == 3
        assert s.period_end == 4
        assert s.week_pattern == "1-15"

    def test_alt_keys(self):
        s = VenueOccupancySlot.from_api({"cddm": "X", "jc": 5})
        assert s.room_code == "X"
        assert s.period_start == 5
        assert s.period_end == 5

    def test_empty(self):
        s = VenueOccupancySlot.from_api({})
        assert s.room_code == ""
        assert s.weekday == 0


# ── BorrowApplication ───────────────────────────────────────────────────────


REAL_APPLICATION = {
    "id": "abc123",
    "jhdh": "JY20260628001",
    "shztmc": "保存待审核",
    "sqr": "段斯宸",
    "sqrdh": "13908478929",
    "sqrzgh": "12413021",
    "sqrdw": "材料科学与工程系",
    "sqrdwdh": "01",
    "syr": "段斯宸",
    "syrdh": "13908478929",
    "syrzgh": "12413021",
    "syrdwdm": "01",
    "xnxq": "2025-2026-2",
    "xn": "2025-2026",
    "xq": "2",
    "zc": "5-8",
    "qsjsz": "5,8",
    "xiaoqu": "1",
    "rs": 30,
    "jyyy": "学术讲座",
    "sfsjysxtly": "",
    "shjs": "",
    "shjsxm": "",
    "shyj": "",
    "shbj": "",
    "xnxw": None,
    "cdjymxlist": [
        {
            "xuhhao": 1,
            "cddm": "YJ-123",
            "cdmc": "一教123",
            "zws": 55,
            "cdlocation": "一教 1层",
            "yongtu": "讲座",
            "jtsjlist": [
                {"xh": 1, "xqj": 2, "ksjc": 3, "jsjc": 4, "zcbds": "5-8"},
            ],
        },
    ],
}


class TestBorrowApplication:
    def test_from_api_full(self):
        b = BorrowApplication.from_api(REAL_APPLICATION)
        assert b.id == "abc123"
        assert b.jhdh == "JY20260628001"
        assert b.status == "保存待审核"
        assert b.applicant_name == "段斯宸"
        assert b.applicant_phone == "13908478929"
        assert b.applicant_employee_id == "12413021"
        assert b.applicant_dept == "材料科学与工程系"
        assert b.semester == Semester("2025-2026-2")
        assert b.semester.xn == "2025-2026"
        assert b.semester.xq == "2"
        assert b.weeks == "5-8"
        assert b.start_end_weeks == "5,8"
        assert b.campus == "1"
        assert b.headcount == 30
        assert b.purpose == "学术讲座"
        assert len(b.details) == 1
        assert b.details[0].room_code == "YJ-123"
        assert b.details[0].time_slots[0].weekday == 2

    def test_status_predicates(self):
        b = BorrowApplication(status=STATUS_SAVED)
        assert b.is_saved is True
        assert b.is_submitted is False
        b = BorrowApplication(status=STATUS_SUBMITTED)
        assert b.is_submitted is True
        assert b.is_approved is False
        b = BorrowApplication(status=STATUS_APPROVED)
        assert b.is_approved is True
        b = BorrowApplication(status=STATUS_REJECTED)
        assert b.is_rejected is True

    def test_room_codes_property(self):
        b = BorrowApplication(
            details=[
                BorrowDetail(room_code="YJ-123"),
                BorrowDetail(room_code="YJ-324"),
                BorrowDetail(room_code="YJ-123"),
                BorrowDetail(room_code=""),
            ]
        )
        assert b.room_codes == ["YJ-123", "YJ-324"]

    def test_to_api_roundtrip(self):
        original = BorrowApplication.from_api(REAL_APPLICATION)
        dumped = original.to_api()
        assert dumped["sqr"] == "段斯宸"
        assert dumped["xn"] == "2025-2026"
        assert dumped["xq"] == "2"
        assert dumped["rs"] == 30
        assert dumped["jyyy"] == "学术讲座"
        assert len(dumped["cdjymxlist"]) == 1
        assert dumped["cdjymxlist"][0]["cddm"] == "YJ-123"
        assert dumped["cdjymxlist"][0]["jtsjlist"][0]["xqj"] == 2

    def test_to_api_skips_server_fields(self):
        b = BorrowApplication(
            id="abc123", jhdh="JY20260628001", status=STATUS_SAVED,
            audit_role_name="辅导员", audit_opinion="",
        )
        dumped = b.to_api()
        assert dumped["id"] == "abc123"
        assert dumped["jhdh"] == "JY20260628001"
        assert dumped["shjs"] == ""
        assert "status" not in dumped
        assert "shjsxm" not in dumped
        assert "shyj" not in dumped

    def test_from_api_empty(self):
        b = BorrowApplication.from_api({})
        assert b.id == ""
        assert b.status == ""
        assert b.details == []

    def test_from_api_string_numbers(self):
        raw = dict(REAL_APPLICATION, rs="50", xq="2")
        b = BorrowApplication.from_api(raw)
        assert b.headcount == 50
        assert b.semester.xq == "2"

    def test_from_api_missing_optional(self):
        b = BorrowApplication.from_api({"id": "x", "jhdh": "y"})
        assert b.id == "x"
        assert b.jhdh == "y"
        assert b.status == ""


# ── Integration: detail + slot + booking ────────────────────────────────────


class TestNestedIntegration:
    def test_construct_full_booking_from_scratch(self):
        app = BorrowApplication(
            applicant_name="段斯宸",
            applicant_phone="13908478929",
            applicant_employee_id="12413021",
            applicant_dept="材料科学与工程系",
            user_name="段斯宸",
            user_phone="13908478929",
            user_employee_id="12413021",
            semester=Semester("2025-2026-2"),
            weeks="5-8",
            campus="1",
            headcount=30,
            purpose="学术讲座",
            details=[
                BorrowDetail(
                    seq=1,
                    room_code="YJ-123",
                    room_name="一教123",
                    capacity=55,
                    location="一教 1层",
                    purpose="讲座",
                    time_slots=[
                        BorrowTimeSlot(
                            seq=1, weekday=2, period_start=3, period_end=4,
                            week_pattern="5-8",
                        ),
                    ],
                ),
            ],
        )

        dumped = app.to_api()
        reconstructed = BorrowApplication.from_api(dumped)

        assert reconstructed.applicant_name == "段斯宸"
        assert reconstructed.semester.xn == "2025-2026"
        assert reconstructed.weeks == "5-8"
        assert reconstructed.details[0].room_code == "YJ-123"
        assert reconstructed.details[0].time_slots[0].weekday == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
