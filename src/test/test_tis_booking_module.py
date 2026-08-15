"""
Tests for sustech_survival.tis.classroom.booking — VenueBorrowClient.

Minimal tests for the 3 operations that matter: check_permission,
query_venue_occupancy, and create_borrow_application. No list/get/update/
delete/submit — those were removed from the client as unnecessary for the
write-once TIS workflow.

Run: pytest src/test/test_tis_booking_module.py -v
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

sys.path.insert(0, str(Path(__file__).parent.parent))

from sustech_survival.semester import Semester
from sustech_survival.tis.classroom.booking import (
    BorrowError,
    EP_CREATE,
    EP_OCCUPANCY,
    EP_SHZTLIST,
    EP_YZKG,
    VenueBorrowClient,
    WORKFLOW_CDJY,
    _strip_envelope,
    venue_borrow,
)
from sustech_survival.tis.classroom.booking_schema import (
    BorrowApplication,
    BorrowDetail,
    BorrowTimeSlot,
)


# ── Helpers ────────────────────────────────────────────────────────────────


def make_response(
    payload=None,
    *,
    status_code: int = 200,
    raw_text: str = None,
    is_json: bool = True,
) -> MagicMock:
    r = MagicMock(spec=requests.Response)
    r.status_code = status_code
    if not is_json:
        r.text = raw_text if raw_text is not None else ""
        r.json.side_effect = ValueError("not JSON")
    elif payload is not None:
        r.json.return_value = payload
        r.text = json.dumps(payload, ensure_ascii=False)
    else:
        r.text = ""
        r.json.return_value = None
    return r


def make_session_mock() -> MagicMock:
    s = MagicMock(spec=requests.Session)
    s.headers = {}
    return s


def make_client(session=None) -> VenueBorrowClient:
    s = session or make_session_mock()
    return VenueBorrowClient(session=s)


# ── _strip_envelope ────────────────────────────────────────────────────────


class TestStripEnvelope:
    def test_spring_envelope(self):
        assert _strip_envelope({"code": 200, "content": {"id": "x"}}) == {"id": "x"}

    def test_no_envelope(self):
        assert _strip_envelope({"id": "x"}) == {"id": "x"}

    def test_none_content(self):
        assert _strip_envelope({"code": 200, "content": None}) is None

    def test_bare_dict(self):
        assert _strip_envelope({"foo": "bar"}) == {"foo": "bar"}

    def test_bare_list(self):
        assert _strip_envelope({"code": 200, "content": [{"a": 1}]}) == [{"a": 1}]

    def test_non_dict(self):
        assert _strip_envelope("hello") == "hello"

    def test_none(self):
        assert _strip_envelope(None) is None


# ── Permission check ──────────────────────────────────────────────────────


class TestCheckPermission:
    def test_allowed(self):
        c = make_client()
        c._sess.post.return_value = make_response(raw_text="1", is_json=False)
        result = c.check_permission(Semester("2025-20262"))
        assert result.allowed is True

    def test_denied(self):
        c = make_client()
        c._sess.post.return_value = make_response(raw_text="0", is_json=False)
        result = c.check_permission(Semester("2025-20262"))
        assert result.allowed is False

    def test_envelope_format(self):
        c = make_client()
        c._sess.post.return_value = make_response({"code": 200, "content": "1"})
        result = c.check_permission(Semester("2025-20262"))
        assert result.allowed is True

    def test_sends_correct_params(self):
        c = make_client()
        c._sess.post.return_value = make_response(raw_text="1", is_json=False)
        c.check_permission(Semester("2025-20262"))
        call = c._sess.post.call_args
        assert call.args[0] == EP_YZKG
        assert call.kwargs["data"] == {"xn": "2025-2026", "xq": "2"}


# ── Audit statuses ─────────────────────────────────────────────────────────


class TestListAuditStatuses:
    def test_parses_list(self):
        c = make_client()
        c._sess.post.return_value = make_response({
            "code": 200,
            "content": {"rows": [
                {"YWJDDM": "1", "YSHJDZTXSMC": "保存待审核"},
                {"YWJDDM": "2", "YSHJDZTXSMC": "审核通过"},
            ]},
        })
        statuses = c.list_audit_statuses()
        assert len(statuses) == 2
        assert statuses[0].name == "保存待审核"
        assert statuses[1].code == "2"

    def test_sends_workflow_code(self):
        c = make_client()
        c._sess.post.return_value = make_response({"code": 200, "content": {"rows": []}})
        c.list_audit_statuses()
        call = c._sess.post.call_args
        assert call.args[0] == EP_SHZTLIST
        assert call.kwargs["data"]["ywdm"] == WORKFLOW_CDJY


# ── Venue occupancy ─────────────────────────────────────────────────────────


class TestQueryVenueOccupancy:
    def test_basic(self):
        c = make_client()
        c._sess.post.return_value = make_response({
            "code": 200,
            "content": {"rows": [
                {"cddm": "YJ-123", "xqj": 2, "ksjc": 3, "jsjc": 4, "zcbds": "1-15"},
            ]},
        })
        slots = c.query_venue_occupancy(semester=Semester("2025-20262"))
        assert len(slots) == 1
        assert slots[0].room_code == "YJ-123"
        assert slots[0].weekday == 2

    def test_uses_json_body(self):
        c = make_client()
        c._sess.post.return_value = make_response({"code": 200, "content": {"rows": []}})
        c.query_venue_occupancy(semester=Semester("2025-20262"), room_codes=["YJ-123", "YJ-324"])
        call = c._sess.post.call_args
        assert call.kwargs["json"] == {
            "xn": "2025-2026", "xq": "2", "cddms": ["YJ-123", "YJ-324"],
        }
        assert "data" not in call.kwargs or not call.kwargs.get("data")

    def test_with_filters(self):
        c = make_client()
        c._sess.post.return_value = make_response({"code": 200, "content": {"rows": []}})
        c.query_venue_occupancy(
            semester=Semester("2025-20262"),
            room_codes=["YJ-123"], weeks=[5, 6, 7], weekday=2,
        )
        body = c._sess.post.call_args.kwargs["json"]
        assert body["cddms"] == ["YJ-123"]
        assert body["zcs"] == [5, 6, 7]
        assert body["xqj"] == 2

    def test_endpoint_url(self):
        c = make_client()
        c._sess.post.return_value = make_response({"code": 200, "content": {"rows": []}})
        c.query_venue_occupancy(semester=Semester("2025-20262"))
        assert c._sess.post.call_args.args[0] == EP_OCCUPANCY


# ── Create borrow application (the one real action) ────────────────────────


SAMPLE_FORM = BorrowApplication(
    id="",
    applicant_name="<name>",
    applicant_phone="13908478929",
    applicant_employee_id="<sid>",
    applicant_dept="材料科学与工程系",
    user_name="<name>",
    user_phone="13908478929",
    user_employee_id="<sid>",
    semester=Semester("2025-20262"),
    weeks="5-8",
    headcount=30,
    purpose="学术讲座",
    details=[
        BorrowDetail(
            seq=1, room_code="YJ-123", room_name="一教123", capacity=55,
            time_slots=[BorrowTimeSlot(weekday=2, period_start=3, period_end=4)],
        ),
    ],
)


class TestCreateBorrowApplication:
    def test_dry_run_does_not_post(self):
        c = make_client()
        result = c.create_borrow_application(SAMPLE_FORM, dry_run=True)
        c._sess.post.assert_not_called()
        assert result.applicant_name == "<name>"
        assert result.headcount == 30

    def test_dry_run_returns_reconstructed_form(self):
        c = make_client()
        result = c.create_borrow_application(SAMPLE_FORM, dry_run=True)
        assert result.applicant_name == "<name>"
        assert result.semester.xn == "2025-2026"
        assert result.details[0].room_code == "YJ-123"

    def test_real_post(self):
        c = make_client()
        c._sess.post.return_value = make_response({
            "code": 200,
            "content": {"id": "newapp", "jhdh": "JY-NEW", "shztmc": "保存待审核"},
        })
        result = c.create_borrow_application(SAMPLE_FORM, dry_run=False)
        call = c._sess.post.call_args
        assert call.kwargs["json"] is not None
        assert call.kwargs["json"]["sqr"] == "<name>"
        assert call.kwargs["json"]["xn"] == "2025-2026"
        assert call.args[0] == EP_CREATE
        assert result.id == "newapp"
        assert result.jhdh == "JY-NEW"

    def test_raises_on_error(self):
        c = make_client()
        c._sess.post.return_value = make_response({"code": 500, "msg": "validation failed"})
        with pytest.raises(BorrowError, match="validation"):
            c.create_borrow_application(SAMPLE_FORM, dry_run=False)


# ── Singleton ──────────────────────────────────────────────────────────────


class TestVenueBorrowSingleton:
    def test_returns_client(self):
        v = venue_borrow()
        assert isinstance(v, VenueBorrowClient)

    def test_singleton_identity(self):
        assert venue_borrow() is venue_borrow()

    def test_resets_with_clean_session(self):
        """A fresh test should get a clean singleton (pytest caches don't
        persist across test sessions)."""
        v = venue_borrow()
        assert v._sess is None  # no session created yet


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
