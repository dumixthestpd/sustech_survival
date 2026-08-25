"""
test_selectcourse_write.py — Offline tests for selectcourse WRITE-side.

No network. Mocks `SelectCourseClient._auth.post` (and `_auth.ensure`)
to verify:
  1. `dry_run=True` never touches the network
  2. `dry_run=False` posts to the right URL with the right payload
  3. `EnrollmentError` is raised on jg != '1'
  4. The full queryform payload contains all the keys TIS expects

API notes (post-2026-08-08 refactor):
  - `build_queryform` is a free function in `selectcourse.queryform`,
    NOT a method on the client. It takes `sem=...` and `auth=...`
    kwargs plus the per-call options.
  - Authentication is via `client._auth` (a TISAuth instance), NOT
    the legacy `selectcourse.selectcourse._tis_login/_tis_session`
    functions (those were removed from selectcourse.py and live
    only as deprecated wrappers in `tis.classroom.classroom`).
  - `XKTJZ_TASK_TO_CART` is now a legacy alias pointing at the
    corrected value `"rwtjzyx"` (the HAR analysis showed
    addGouwuche/updXkxsByyx/tuike ALL use this, not the previously
    assumed `"rwtjzgwc"`).
  - The TIS write-key is `id_field` (32-char hex from queryKxrw),
    NOT the human-readable `rwh`. The catalog rwh is still the
    lookup key for the write method, but `p_id` on the wire is the
    hex id.
"""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from sustech_survival.selectcourse import (
    SelectCourseClient,
    EnrollmentError,
    TIS_ADD_XUANKE_URL, TIS_TUIKE_URL,
    TIS_ADD_GOUWUCHE_URL, TIS_DEL_GOUWUCHE_URL,
    XKTJZ_CART_TO_ENROLLED, XKTJZ_TASK_TO_ENROLLED,
)
from sustech_survival.selectcourse.queryform import build_queryform


# -- Test helpers -----------------------------------------------------------


def _stub_auth(sc, response_json=None):
    """Stub `sc._auth` so no real HTTP or auth happens.

    `build_queryform` calls `auth.post("/Xsxk/queryXkdqXnxq", ...)`
    to fetch the current active term. The write methods call
    `auth.post(endpoint, ...)`. Stubbing `auth.post` to always
    return the same canned response covers both — the tests that
    care about the response inspect only the write call's payload.
    """
    if response_json is None:
        response_json = {"jg": "1", "message": "ok"}
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = json.dumps(response_json).encode()
    mock_resp.json.return_value = response_json
    mock_resp.raise_for_status = MagicMock()
    sc._auth.ensure = MagicMock(return_value=(True, "stub"))
    sc._auth.post = MagicMock(return_value=mock_resp)
    return sc._auth.post


def _seed_catalog_id(sc, rwh="TEST-RWH", hex_id="TEST-HEX-ID"):
    """Pre-populate `sc._courses` so `_lookup_id(rwh)` returns hex_id.

    The catalog rows in production don't carry `id`; only personal-mode
    rows (queryKxrw) do. `add_course` walks `sc._courses` for the
    matching rwh and uses its `id` as `p_id` on the wire.
    """
    from sustech_survival.selectcourse.course import Course
    sc._courses = [
        Course(
            code="TEST", name="Test", name_en="Test",
            class_group="", rwh=rwh,
            college="", category="", nature="", campus="",
            credits=0, total_hours=0,
            capacity=None, undergrad_seats=None, grad_seats=None,
            cultivation="1",
            rooms=[], teachers=[], slots_raw=[],
            id=hex_id,
        )
    ]


# -- build_queryform shape (the old `_build_queryform` test) ----------------


class TestBuildQueryform:
    def test_keys_present(self):
        sc = SelectCourseClient(xn="2025-2026", xq="2")
        # build_queryform fetches dq via auth.post; stub it.
        _stub_auth(sc)
        qf = build_queryform(sem=sc._sem, auth=sc._auth, id_field="TEST-HEX")
        # Every key TIS expects (extracted from xsxk bundle queryform)
        required = [
            "p_pylx", "p_sfgldjr", "p_sfredis", "p_sfsyxkgwc", "p_xktjz",
            "p_chaxunxh", "p_gjz", "p_skjs", "p_xn", "p_xq", "p_xnxq",
            "p_dqxn", "p_dqxq", "p_dqxnxq", "p_xkfsdm", "p_xiaoqu",
            "p_kkyx", "p_kclb", "p_xkxs", "p_dyc", "p_kkxnxq",
            "p_id", "p_ids",
            "p_sfhlctkc", "p_sfhllrlkc",
            "p_kxsj_xqj", "p_kxsj_ksjc", "p_kxsj_jsjc",
            "p_kcdm_js", "p_kcdm_cxrw", "p_kcdm_cxrw_zckc", "p_kc_gjz",
            "p_xzcxtjz_nj", "p_xzcxtjz_yx", "p_xzcxtjz_zy",
            "p_xzcxtjz_zyfx", "p_xzcxtjz_bj",
            "p_sfxsgwckb", "p_skyy", "p_sfmxzj",
        ]
        for k in required:
            assert k in qf, f"missing key {k!r}"

    def test_id_field_goes_into_p_id(self):
        """The hex id_field becomes p_id (NOT the human-readable rwh)."""
        sc = SelectCourseClient(xn="2025-2026", xq="2")
        _stub_auth(sc)
        qf = build_queryform(sem=sc._sem, auth=sc._auth,
                             id_field="TEST-HEX-001")
        assert qf["p_id"] == "TEST-HEX-001"
        assert qf["p_xn"] == "2025-2026"
        assert qf["p_xq"] == "2"

    def test_xktjz_values(self):
        sc = SelectCourseClient(xn="2025-2026", xq="2")
        _stub_auth(sc)
        qf_cart = build_queryform(sem=sc._sem, auth=sc._auth,
                                  xktjz=XKTJZ_CART_TO_ENROLLED)
        assert qf_cart["p_xktjz"] == "gwctjzyx"
        qf_task = build_queryform(sem=sc._sem, auth=sc._auth,
                                  xktjz=XKTJZ_TASK_TO_ENROLLED)
        assert qf_task["p_xktjz"] == "rwtjzyx"

    def test_ignore_flags(self):
        sc = SelectCourseClient()
        _stub_auth(sc)
        assert build_queryform(sem=sc._sem, auth=sc._auth)["p_sfhlctkc"] == "0"
        assert build_queryform(sem=sc._sem, auth=sc._auth,
                               ignore_conflicts=True)["p_sfhlctkc"] == "1"
        assert build_queryform(sem=sc._sem, auth=sc._auth)["p_sfhllrlkc"] == "0"
        assert build_queryform(sem=sc._sem, auth=sc._auth,
                               ignore_zero_capacity=True)["p_sfhllrlkc"] == "1"

    def test_ids_array_default(self):
        sc = SelectCourseClient()
        _stub_auth(sc)
        qf = build_queryform(sem=sc._sem, auth=sc._auth)
        assert qf["p_ids"] == []
        qf2 = build_queryform(sem=sc._sem, auth=sc._auth, ids=["a", "b"])
        assert qf2["p_ids"] == ["a", "b"]


# -- Dry-run safety ---------------------------------------------------------


class TestDryRun:
    """`dry_run=True` (default) MUST NOT touch the network."""

    def test_add_course_dry_run_returns_payload(self):
        sc = SelectCourseClient()
        res = sc.add_course("TEST-RWH", dry_run=True)
        assert res["dry_run"] is True
        assert res["endpoint"] == TIS_ADD_XUANKE_URL
        assert res["would_post"]["p_id"] == ""  # lookup with no catalog → ""
        assert res["would_post"]["p_xktjz"] == XKTJZ_CART_TO_ENROLLED
        assert res["jg"] is None
        # No real network call
        assert "session" not in res

    def test_drop_course_dry_run(self):
        sc = SelectCourseClient()
        res = sc.drop_course("TEST-RWH", dry_run=True)
        assert res["dry_run"] is True
        assert res["endpoint"] == TIS_TUIKE_URL
        assert res["would_post"]["p_id"] == ""

    def test_add_to_cart_dry_run(self):
        sc = SelectCourseClient()
        res = sc.add_to_cart("TEST-RWH", dry_run=True)
        assert res["dry_run"] is True
        assert res["endpoint"] == TIS_ADD_GOUWUCHE_URL
        assert res["would_post"]["p_xktjz"] == XKTJZ_TASK_TO_ENROLLED

    def test_remove_from_cart_dry_run(self):
        sc = SelectCourseClient()
        res = sc.remove_from_cart("TEST-RWH", dry_run=True)
        assert res["dry_run"] is True
        assert res["endpoint"] == TIS_DEL_GOUWUCHE_URL

    def test_default_is_dry_run(self):
        """No-arg call must be dry-run."""
        sc = SelectCourseClient()
        res = sc.add_course("TEST-RWH")
        assert res["dry_run"] is True

    def test_dry_run_never_calls_post(self):
        """Ensure dry_run=True does NOT trigger any WRITE-side POST.

        NOTE: the payload is still built eagerly (which means the read-only
        ``/Xsxk/queryXkdqXnxq`` dq-fetch IS called — it caches the current
        TIS active term). What we GUARANTEE here is that NO write endpoint
        (``/Xsxk/addXuanke`` / ``/Xsxk/tuike`` / ``/Xsxk/addGouwuche`` /
        ``/Xsxk/delGouwuche``) is hit, and ``_auth.ensure()`` is never
        triggered (because the write path is the only thing that needs
        login).
        """
        sc = SelectCourseClient()
        mock_post = _stub_auth(sc)
        sc.add_course("TEST-RWH", dry_run=True)
        sc.drop_course("TEST-RWH", dry_run=True)
        sc.add_to_cart("TEST-RWH", dry_run=True)
        sc.remove_from_cart("TEST-RWH", dry_run=True)
        # No write-side POST: every URL hit should be the dq fetch.
        write_urls = {TIS_ADD_XUANKE_URL, TIS_TUIKE_URL,
                      TIS_ADD_GOUWUCHE_URL, TIS_DEL_GOUWUCHE_URL}
        for c in mock_post.call_args_list:
            called_url = c[0][0]
            assert called_url not in write_urls, (
                f"dry_run=True must not POST to write endpoint {called_url}"
            )
        # And we never needed a real login.
        sc._auth.ensure.assert_not_called()


# -- Real-call semantics ----------------------------------------------------


class TestRealCall:
    """`dry_run=False` MUST hit the network and parse the response."""

    def _setup_with_response(self, response_json):
        sc = SelectCourseClient()
        _seed_catalog_id(sc)  # so add_course finds the id for TEST-RWH
        mock_post = _stub_auth(sc, response_json)
        return sc, mock_post

    def test_add_course_real_call_success(self):
        sc, mock_post = self._setup_with_response({"jg": "1", "message": "选课成功"})
        res = sc.add_course("TEST-RWH", dry_run=False)
        assert res["jg"] == "1"
        # Verify the URL hit (last call_args is the actual write; first is the dq fetch)
        write_calls = [c for c in mock_post.call_args_list
                       if TIS_ADD_XUANKE_URL in str(c)]
        assert write_calls, f"no POST to {TIS_ADD_XUANKE_URL} in {mock_post.call_args_list}"
        call_url = write_calls[-1][0][0]
        assert call_url == TIS_ADD_XUANKE_URL

    def test_add_course_real_call_failure_raises(self):
        sc, _ = self._setup_with_response({"jg": "0", "message": "已选满"})
        with pytest.raises(EnrollmentError) as exc_info:
            sc.add_course("TEST-RWH", dry_run=False)
        assert exc_info.value.jg == "0"
        assert "已选满" in exc_info.value.message
        assert exc_info.value.endpoint == TIS_ADD_XUANKE_URL
        assert exc_info.value.rwh == "TEST-RWH"

    def test_drop_course_real_call_success(self):
        sc, mock_post = self._setup_with_response({"jg": "1", "message": "退课成功"})
        res = sc.drop_course("TEST-RWH", dry_run=False)
        assert res["jg"] == "1"
        write_calls = [c for c in mock_post.call_args_list
                       if TIS_TUIKE_URL in str(c)]
        assert write_calls, f"no POST to {TIS_TUIKE_URL} in {mock_post.call_args_list}"
        call_url = write_calls[-1][0][0]
        assert call_url == TIS_TUIKE_URL

    def test_add_to_cart_real_call(self):
        sc, mock_post = self._setup_with_response({"jg": "1", "message": "已加入购物车"})
        res = sc.add_to_cart("TEST-RWH", dry_run=False)
        assert res["jg"] == "1"
        write_calls = [c for c in mock_post.call_args_list
                       if TIS_ADD_GOUWUCHE_URL in str(c)]
        assert write_calls, f"no POST to {TIS_ADD_GOUWUCHE_URL} in {mock_post.call_args_list}"
        call_args = write_calls[-1]
        call_url = call_args[0][0]
        payload = call_args.kwargs.get("data") or call_args[1].get("data")
        assert call_url == TIS_ADD_GOUWUCHE_URL
        # addGouwuche uses p_xktjz=rwtjzyx (the "task → enrolled" code).
        # The legacy name "XKTJZ_TASK_TO_CART" is now an alias for this.
        assert payload["p_xktjz"] == XKTJZ_TASK_TO_ENROLLED

    def test_jg_minus_one_means_not_allowed(self):
        """jg='-1' is a special TIS code meaning 'not allowed to select'."""
        sc, _ = self._setup_with_response({"jg": "-1", "message": "您不在选课阶段"})
        with pytest.raises(EnrollmentError) as exc_info:
            sc.add_course("TEST-RWH", dry_run=False)
        assert exc_info.value.jg == "-1"


# -- Error class ------------------------------------------------------------


class TestEnrollmentError:
    def test_string_format(self):
        e = EnrollmentError("0", "已选满", endpoint=TIS_ADD_XUANKE_URL, rwh="TEST")
        s = str(e)
        assert "TEST" in s
        assert "已选满" in s
        assert "addXuanke" in s

    def test_attributes(self):
        e = EnrollmentError("-1", "no", endpoint=TIS_TUIKE_URL, rwh="R")
        assert e.jg == "-1"
        assert e.message == "no"
        assert e.endpoint == TIS_TUIKE_URL
        assert e.rwh == "R"


# -- Public API exports -----------------------------------------------------


class TestPublicExports:
    def test_constants_exported(self):
        from sustech_survival import selectcourse as sc_mod
        assert sc_mod.TIS_ADD_XUANKE_URL.endswith("/Xsxk/addXuanke")
        assert sc_mod.TIS_TUIKE_URL.endswith("/Xsxk/tuike")
        assert sc_mod.XKTJZ_CART_TO_ENROLLED == "gwctjzyx"
        # XKTJZ_TASK_TO_CART is a legacy alias for TASK_TO_ENROLLED —
        # the HAR analysis showed addGouwuche/updXkxsByyx/tuike ALL
        # use p_xktjz=rwtjzyx (NOT the previously-assumed rwtjzgwc).
        assert sc_mod.XKTJZ_TASK_TO_CART == "rwtjzyx"
        assert sc_mod.XKTJZ_TASK_TO_CART == sc_mod.XKTJZ_TASK_TO_ENROLLED