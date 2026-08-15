"""
Tests for sustech_survival.lib.booking.client — LibBookingClient.

These are MOCK tests — no live API calls. We construct a fake
`requests.Session` whose `.request()` returns canned JSON, and verify
the client:
  - dispatches to the right endpoint
  - passes the right params/method
  - unwraps the `data` field
  - raises `LibBookingError` on auth errors and tries to auto-relogin
  - propagates non-auth API errors with the server's message
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
import requests

from sustech_survival.lib.booking.client import (
    AUTH_ERROR_MESSAGES,
    DEFAULT_CLASS_KIND,
    LibBookingClient,
    LibBookingError,
    lib_booking,
)
from sustech_survival.lib.booking.schema import (
    CampusGroup,
    Reservation,
    RoomIdleCategory,
    UserInfo,
    build_reservation_payload,
)


# ── Mock session ────────────────────────────────────────────────────────────


class _MockResponse:
    """Minimal stand-in for requests.Response."""

    def __init__(self, *, status_code=200, json_data=None, text="", headers=None):
        self.status_code = status_code
        self._json = json_data or {}
        self.text = text or (str(json_data) if json_data is not None else "")
        self.headers = headers or {}

    def json(self):
        return self._json


def _make_session(responses: list) -> tuple:
    """Build a session + recorded-call list.

    Each call to `session.request(method, url, params=...)` pops the next
    response from `responses`. All calls (method, URL, params) are
    recorded in `calls` for assertion.
    """
    session = MagicMock(spec=requests.Session)
    calls = []
    iterator = iter(responses)

    def request(method, url, *, params=None, timeout=None, **kw):
        calls.append({"method": method, "url": url, "params": params, "timeout": timeout, **kw})
        try:
            return next(iterator)
        except StopIteration:
            raise AssertionError(
                f"Unexpected call: {method} {url} params={params}"
            )

    session.request.side_effect = request
    session.headers = {}
    session.cookies = MagicMock()
    return session, calls


def _ok(data=None) -> _MockResponse:
    return _MockResponse(status_code=200, json_data={"code": 0, "data": data})


def _err(message: str, code: int = 1) -> _MockResponse:
    return _MockResponse(status_code=200, json_data={"code": code, "message": message, "data": None})


# ── Construction & basic shape ──────────────────────────────────────────────


class TestConstruction:
    def test_construct_with_session(self):
        s = MagicMock(spec=requests.Session)
        c = LibBookingClient(s)
        assert c.s is s
        assert c._auth is None


# ── whoami ──────────────────────────────────────────────────────────────────


class TestWhoami:
    def test_returns_user_info(self):
        s, calls = _make_session([_ok({
            "accNo": 76727, "pid": "<sid>", "trueName": "<name>",
            "logonName": "<sid>", "className": "2024级本科",
            "deptName": "南方科技大学", "manager": 1, "ident": 257,
            "status": 1, "kind": 1,
        })])
        c = LibBookingClient(s)
        me = c.whoami()
        assert isinstance(me, UserInfo)
        assert me.true_name == "<name>"
        assert me.acc_no == 76727
        # Endpoint + method
        assert calls[0]["method"] == "GET"
        assert calls[0]["url"].endswith("/ic-web/auth/userInfo")

    def test_raises_on_api_error(self):
        s, _ = _make_session([_err("权限不足")])
        c = LibBookingClient(s)
        with pytest.raises(LibBookingError, match="权限不足"):
            c.whoami()


# ── home_summary ────────────────────────────────────────────────────────────


class TestHomeSummary:
    def test_returns_categories(self):
        s, calls = _make_session([_ok([
            {"name": "会议室", "idelQuantity": 2, "totalQuantity": 2},
            {"name": "讨论间 1-3", "idelQuantity": 7, "totalQuantity": 11},
        ])])
        c = LibBookingClient(s)
        cats = c.home_summary()
        assert len(cats) == 2
        assert isinstance(cats[0], RoomIdleCategory)
        assert cats[0].name == "会议室"
        assert cats[1].used_quantity == 4
        assert calls[0]["url"].endswith("/ic-web/home/page/room/idle")

    def test_handles_null_data(self):
        s, _ = _make_session([_ok(None)])
        c = LibBookingClient(s)
        cats = c.home_summary()
        assert cats == []


# ── labs ────────────────────────────────────────────────────────────────────


class TestLabs:
    def test_returns_lab_list(self):
        s, calls = _make_session([_ok([
            {"labId": 1, "labName": "琳恩一层(Lynn 1st floor)"},
            {"labId": 7, "labName": "会议室(Meeting Room)"},
        ])])
        c = LibBookingClient(s)
        labs = c.labs()
        assert len(labs) == 2
        assert labs[0].lab_id == 1
        # Check that kindIds="" is sent (the required param)
        assert calls[0]["params"] == {"classKind": 1, "kindIds": ""}

    def test_custom_class_kind(self):
        s, calls = _make_session([_ok([])])
        c = LibBookingClient(s)
        c.labs(class_kind=8)
        assert calls[0]["params"]["classKind"] == 8


# ── rooms ───────────────────────────────────────────────────────────────────


class TestRooms:
    def test_returns_campus_groups(self):
        s, calls = _make_session([_ok([{
            "campusId": 1,
            "campusName": "涵泳讨论间",
            "labInfos": [
                {"labId": 4, "labName": "涵泳一层", "roomInfos": [
                    {"devId": 13, "devName": "C105", "minResvTime": 10,
                     "openTimes": [{"openStartTime": "08:00", "openEndTime": "21:59", "openLimit": 1}],
                     "resvInfos": None},
                ]},
            ],
        }])])
        c = LibBookingClient(s)
        groups = c.rooms(kind_id=1, lab_id=4)
        assert len(groups) == 1
        assert isinstance(groups[0], CampusGroup)
        assert groups[0].labs[0].rooms[0].dev_id == 13
        assert calls[0]["params"] == {"classKind": 1, "kindId": 1, "labId": 4}


# ── reservation_count + my_reservations + resv_info ────────────────────────


class TestReservationRead:
    def test_count(self):
        s, calls = _make_session([_ok(3)])
        c = LibBookingClient(s)
        n = c.reservation_count()
        assert n == 3
        assert calls[0]["url"].endswith("/ic-web/reserve/count")

    def test_my_reservations_dict_rows(self):
        from datetime import date
        s, calls = _make_session([_ok({
            "code": 0, "message": "查询成功", "count": 2,
            "data": [
                {"resvId": 1, "uuid": "abc", "testName": "x",
                 "resvBeginTime": 1782885600000, "resvEndTime": 1782889200000,
                 "resvStatus": 1027, "classKind": 1, "resvKind": 16,
                 "resvDate": 20260701, "dayOfWeek": 2,
                 "resvDevInfoList": [{"devId": 13, "devName": "C105", "roomName": "C105", "labName": "L1", "kindName": "k1"}],
                 "resvMemberInfoList": [{"accNo": 76727, "trueName": "<name>", "logonName": "<sid>"}],
                 "memo": ""},
                {"resvId": 2, "uuid": "def", "testName": "y",
                 "resvBeginTime": 1782972000000, "resvEndTime": 1782975600000,
                 "resvStatus": 1027, "classKind": 1, "resvKind": 16,
                 "resvDate": 20260702, "dayOfWeek": 3,
                 "resvDevInfoList": [{"devId": 14, "devName": "C106", "roomName": "C106", "labName": "L1", "kindName": "k1"}],
                 "resvMemberInfoList": [],
                 "memo": ""},
            ],
        })])
        c = LibBookingClient(s)
        resvs = c.my_reservations(date(2026, 7, 1), date(2026, 7, 30))
        assert len(resvs) == 2
        assert all(isinstance(r, Reservation) for r in resvs)
        # dev_id comes from resvDevInfoList[0].devId (not top-level)
        assert resvs[0].dev_id == 13
        assert resvs[0].uuid == "abc"
        assert resvs[0].title == "x"
        assert resvs[0].resv_status == 1027
        assert resvs[0].resv_date == date(2026, 7, 1)
        assert resvs[0].day_of_week == 2
        assert resvs[0].begin_time == datetime(2026, 7, 1, 14, 0)  # unix ms
        assert resvs[0].end_time == datetime(2026, 7, 1, 15, 0)
        assert len(resvs[0].members) == 1
        assert resvs[0].members[0].acc_no == 76727
        assert resvs[0].members[0].true_name == "<name>"
        # The server uses `beginDate` (not `startDate`) — verified from SPA
        assert calls[0]["params"]["beginDate"] == "2026-07-01"
        assert calls[0]["params"]["endDate"] == "2026-07-30"
        # Endpoint is /reserve/resvInfo (not /borrow/reserve/own which returns empty)
        assert calls[0]["url"].endswith("/ic-web/reserve/resvInfo")
        # pageNum (not pageSize)
        assert calls[0]["params"]["pageNum"] == 20

    def test_my_reservations_list_data(self):
        from datetime import date
        s, _ = _make_session([_ok([
            {"resvId": 99, "uuid": "z", "testName": "x",
             "resvDevInfoList": [{"devId": 13, "devName": "C105"}]},
        ])])
        c = LibBookingClient(s)
        resvs = c.my_reservations(date(2026, 7, 1), date(2026, 7, 30))
        assert len(resvs) == 1
        assert resvs[0].resv_id == 99
        assert resvs[0].dev_id == 13

    def test_my_reservations_null_data(self):
        from datetime import date
        s, _ = _make_session([_ok(None)])
        c = LibBookingClient(s)
        resvs = c.my_reservations(date(2026, 7, 1), date(2026, 7, 30))
        assert resvs == []

    def test_my_reservations_need_status_filter(self):
        from datetime import date
        s, calls = _make_session([_ok([])])
        c = LibBookingClient(s)
        c.my_reservations(date(2026, 7, 1), date(2026, 7, 30), need_status=6)
        # needStatus=6 = 未开始 tab
        assert calls[0]["params"]["needStatus"] == 6

    def test_resv_info(self):
        # resv_info does a date-range lookup and filters by id, so we
        # mock the list response (rows in `data[]`)
        s, _ = _make_session([_ok({
            "code": 0, "message": "ok", "count": 1,
            "data": [{
                "resvId": 1, "uuid": "abc", "testName": "x",
                "resvBeginTime": 1782885600000, "resvEndTime": 1782889200000,
                "resvStatus": 1027,
                "resvDevInfoList": [{"devId": 13, "devName": "C105"}],
            }],
        })])
        c = LibBookingClient(s)
        r = c.resv_info(1)
        assert r is not None
        assert r.resv_id == 1
        assert r.title == "x"
        assert r.dev_id == 13
        assert r.uuid == "abc"
        assert r.begin_time == datetime(2026, 7, 1, 14, 0)

    def test_resv_info_not_found(self):
        # List returns empty, so resv_info returns None
        s, _ = _make_session([_ok({"code": 0, "data": [], "count": 0})])
        c = LibBookingClient(s)
        r = c.resv_info(99999)
        assert r is None


# ── Write: add_reservation ──────────────────────────────────────────────────


class TestAddReservation:
    def test_dry_run_returns_payload(self):
        # whoami + payload build — NO POST call expected.
        # We pass enforce_policy=False to skip the dev_name lookup
        # (which would otherwise call self.rooms() 10 times in the
        # best-effort name search). Policy enforcement is tested
        # separately in test_lib_booking_policy.py.
        s, calls = _make_session([
            _ok({"accNo": 76727, "pid": "1", "trueName": "x",
                 "logonName": "1", "className": "x", "deptName": "x",
                 "manager": 0, "ident": 0, "status": 1, "kind": 1}),
        ])
        c = LibBookingClient(s)
        result = c.add_reservation(
            dev_id=13,
            begin=datetime(2026, 7, 1, 14, 0),
            end=datetime(2026, 7, 1, 15, 0),
            title="my meeting",
            enforce_policy=False,
        )
        assert result["__dry_run__"] is True
        assert result["endpoint"] == "POST /reserve"
        assert result["payload"]["resvBeginTime"] == "2026-07-01 14:00:00"
        assert result["payload"]["testName"] == "my meeting"
        # No POST was made (only the whoami call)
        assert len(calls) == 1
        assert calls[0]["url"].endswith("/auth/userInfo")

    def test_commit_actually_posts(self):
        s, calls = _make_session([
            # whoami
            _ok({"accNo": 76727, "pid": "1", "trueName": "x",
                 "logonName": "1", "className": "x", "deptName": "x",
                 "manager": 0, "ident": 0, "status": 1, "kind": 1}),
            # POST /reserve
            _ok({"resvId": 99999, "status": 1}),
        ])
        c = LibBookingClient(s)
        result = c.add_reservation(
            dev_id=13,
            begin=datetime(2026, 7, 1, 14, 0),
            end=datetime(2026, 7, 1, 15, 0),
            title="my meeting",
            dry_run=False,
            enforce_policy=False,
        )
        assert result["resvId"] == 99999
        # 2 calls: whoami + POST
        assert len(calls) == 2
        assert calls[1]["method"] == "POST"
        assert calls[1]["url"].endswith("/ic-web/reserve")
        assert calls[1]["json"]["resvDev"] == [13]
        assert calls[1]["json"]["testName"] == "my meeting"

    def test_policy_violation_blocks_commit(self):
        # 6-month advance booking should be blocked by policy.
        # enforce_policy=True (default) — but with no dev_name lookup
        # we only get the time/duration check (no group-size check).
        # Mock the _dev_name lookup to return empty (room not found
        # in any lab) so the policy check fires only on the time.
        s, calls = _make_session([
            _ok({"accNo": 76727, "pid": "1", "trueName": "x",
                 "logonName": "1", "className": "x", "deptName": "x",
                 "manager": 0, "ident": 0, "status": 1, "kind": 1}),
            # _dev_name will call self.rooms() up to 10 times — queue
            # 10 empty responses (no rooms found, dev_name = None)
            _ok([]), _ok([]), _ok([]), _ok([]), _ok([]),
            _ok([]), _ok([]), _ok([]), _ok([]), _ok([]),
        ])
        c = LibBookingClient(s)
        with pytest.raises(LibBookingError, match="2 days"):
            c.add_reservation(
                dev_id=13,
                begin=datetime(2027, 1, 1, 14, 0),  # 6 months ahead
                end=datetime(2027, 1, 1, 15, 0),
                title="violates policy",
                dry_run=False,
            )
        # No POST should have been made
        assert not any(c["method"] == "POST" for c in calls)


# ── Write: cancel_reservation ──────────────────────────────────────────────


class TestCancelReservation:
    def test_dry_run(self):
        # With enforce_policy=True (default), dry-run does a resv_info
        # lookup. Pre-queue the response (empty = not found). The dry-run
        # should still succeed (with a placeholder uuid) because the
        # caller only wants to inspect the payload, not commit.
        s, calls = _make_session([_ok({})])
        c = LibBookingClient(s)
        result = c.cancel_reservation(12345)
        assert result["__dry_run__"] is True
        assert result["payload"] == {"uuid": "<resvId=12345>"}
        assert result["endpoint"] == "POST /reserve/delete"
        # Only the resv_info lookup (1 call) — no POST
        assert not any(c["method"] == "POST" for c in calls)

    def test_dry_run_no_policy(self):
        # enforce_policy=False skips the resv_info lookup
        s, calls = _make_session([])
        c = LibBookingClient(s)
        result = c.cancel_reservation(12345, enforce_policy=False)
        assert result["__dry_run__"] is True
        assert calls == []  # no API calls at all

    def test_commit(self):
        # with enforce_policy=True (default), cancel will try to look
        # up the reservation via resv_info. We queue that response.
        s, calls = _make_session([
            _ok({}),  # resvInfo — not found → raise (no commit)
            # If we get past the lookup, queue the actual delete
            _ok({"success": True}),
        ])
        c = LibBookingClient(s)
        with pytest.raises(LibBookingError, match="Cannot find reservation"):
            c.cancel_reservation(12345, dry_run=False)
        # No POST was made
        assert not any(c["method"] == "POST" for c in calls)

    def test_commit_with_uuid(self):
        # When uuid is provided directly, no resv_info lookup is needed
        s, calls = _make_session([_ok({"success": True})])
        c = LibBookingClient(s)
        result = c.cancel_reservation(uuid="abc-def", dry_run=False)
        assert result == {"success": True}
        # Only 1 call (the POST)
        assert len(calls) == 1
        post_call = calls[0]
        assert post_call["method"] == "POST"
        assert post_call["url"].endswith("/ic-web/reserve/delete")
        assert post_call["json"] == {"uuid": "abc-def"}

    def test_cancel_too_late_blocks_commit(self):
        # Reservation begins in 5 minutes — too late per policy 1.6
        from datetime import datetime as _dt
        from datetime import timedelta as _td
        begin = _dt.now() + _td(minutes=5)
        end = begin + _td(hours=1)
        s, calls = _make_session([
            # resv_info() calls my_reservations which returns rows in data[]
            _ok({"code": 0, "data": [{
                "resvId": 12345, "uuid": "abc",
                "testName": "x",
                "resvDevInfoList": [{"devId": 13, "devName": "C105"}],
                "resvBeginTime": int(begin.timestamp() * 1000),
                "resvEndTime":   int(end.timestamp() * 1000),
                "resvStatus": 1027,
                "memo": ""},
            ], "count": 1}),
        ])
        c = LibBookingClient(s)
        with pytest.raises(LibBookingError) as exc_info:
            c.cancel_reservation(12345, dry_run=False)
        # The error should be a LibBookingPolicyError
        assert "10 minutes" in str(exc_info.value) or "Cancellation" in str(exc_info.value)
        # No POST
        assert not any(call["method"] == "POST" for call in calls)

    def test_no_policy_skips_timing_check(self):
        # When uuid is unknown, dry-run still works (placeholder payload).
        # Commit requires either a real uuid OR a findable resv_id.
        # enforce_policy=False skips the timing check but not the lookup.
        s, _ = _make_session([])
        c = LibBookingClient(s)
        result = c.cancel_reservation(12345, dry_run=True, enforce_policy=False)
        assert result["__dry_run__"] is True

        # Without enforce_policy=False, dry-run with unknown resv_id
        # still does the resv_info lookup (to honor policy if found)
        s2, calls2 = _make_session([_ok({})])  # not found
        c2 = LibBookingClient(s2)
        result2 = c2.cancel_reservation(12345, dry_run=True)  # policy=True
        assert result2["__dry_run__"] is True
        assert len(calls2) == 1  # resv_info lookup happened


# ── Auto-relogin on auth error ─────────────────────────────────────────────


class TestAutoRelogin:
    def test_auth_error_triggers_relogin_then_retry(self):
        # The mock auth provides a fresh ic-cookie
        mock_auth = MagicMock()
        mock_auth.username = "u"
        mock_auth.password = "p"
        mock_auth.session_cache = {"ic-cookie": "new-cookie-value"}

        s, calls = _make_session([
            # 1st whoami call: returns auth error
            _err("用户未登录，请重新登录", code=300),
            # 2nd whoami call (after relogin): returns success
            _ok({"accNo": 1, "pid": "1", "trueName": "x",
                 "logonName": "1", "className": "x", "deptName": "x",
                 "manager": 0, "ident": 0, "status": 1, "kind": 1}),
        ])
        c = LibBookingClient(s, _auth=mock_auth)
        me = c.whoami()
        assert me.acc_no == 1
        # Relogin was triggered
        mock_auth.login_password.assert_called_once_with("u", "p")
        # 2 calls total: initial fail + retry after relogin
        assert len(calls) == 2

    def test_auth_error_without_auth_raises(self):
        s, _ = _make_session([_err("用户未登录", code=300)])
        c = LibBookingClient(s)  # no _auth
        with pytest.raises(LibBookingError, match="用户未登录"):
            c.whoami()

    def test_relogin_failure_propagates(self):
        mock_auth = MagicMock()
        mock_auth.username = "u"
        mock_auth.password = "p"
        mock_auth.login_password.side_effect = RuntimeError("auth failed")

        s, _ = _make_session([_err("用户未登录", code=300)])
        c = LibBookingClient(s, _auth=mock_auth)
        with pytest.raises(LibBookingError, match="Auto-relogin failed"):
            c.whoami()


# ── HTTP error + off-campus ─────────────────────────────────────────────────


class TestHttpErrors:
    def test_non_200_raises(self):
        s, _ = _make_session([_MockResponse(status_code=500, text="oops")])
        c = LibBookingClient(s)
        with pytest.raises(LibBookingError, match="500"):
            c.whoami()

    def test_off_campus_raises(self):
        s, _ = _make_session([_MockResponse(
            status_code=403,
            text="Access forbidden, please contact administrator.",
        )])
        c = LibBookingClient(s)
        with pytest.raises(LibBookingError, match="campus network"):
            c.whoami()

    def test_request_exception_wrapped(self):
        s = MagicMock(spec=requests.Session)
        s.headers = {}
        s.cookies = MagicMock()
        s.request.side_effect = requests.ConnectionError("nope")
        c = LibBookingClient(s)
        with pytest.raises(LibBookingError, match="HTTP GET"):
            c.whoami()


# ── Non-auth API error message propagated ──────────────────────────────────


class TestApiErrorMessages:
    def test_specific_message_preserved(self):
        s, _ = _make_session([_err("预约日期不能为空", code=1)])
        c = LibBookingClient(s)
        with pytest.raises(LibBookingError, match="预约日期不能为空"):
            c.whoami()
