"""
test_selectcourse_write.py — Offline tests for selectcourse WRITE-side.

No network. Mocks `requests.Session.post` to verify:
  1. `dry_run=True` never touches the network
  2. `dry_run=False` posts to the right URL with the right payload
  3. `EnrollmentError` is raised on jg != '1'
  4. The full queryform payload contains all the keys TIS expects
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from sustech_survival.selectcourse import (
    SelectCourseClient,
    EnrollmentError,
    TIS_ADD_XUANKE_URL, TIS_TUIKE_URL,
    TIS_ADD_GOUWUCHE_URL, TIS_DEL_GOUWUCHE_URL,
    XKTJZ_CART_TO_ENROLLED, XKTJZ_TASK_TO_CART,
)


class TestBuildQueryform:
    def test_keys_present(self):
        sc = SelectCourseClient(xn="2025-2026", xq="2")
        qf = sc._build_queryform(rwh="TEST-RWH")
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

    def test_rwh_goes_into_p_id(self):
        sc = SelectCourseClient(xn="2025-2026", xq="2")
        qf = sc._build_queryform(rwh="2025-2026-2-BIO101-001")
        assert qf["p_id"] == "2025-2026-2-BIO101-001"
        assert qf["p_xn"] == "2025-2026"
        assert qf["p_xq"] == "2"

    def test_xktjz_values(self):
        sc = SelectCourseClient(xn="2025-2026", xq="2")
        qf_cart = sc._build_queryform(xktjz=XKTJZ_CART_TO_ENROLLED)
        assert qf_cart["p_xktjz"] == "gwctjzyx"
        qf_task = sc._build_queryform(xktjz=XKTJZ_TASK_TO_CART)
        assert qf_task["p_xktjz"] == "rwtjzgwc"

    def test_ignore_flags(self):
        sc = SelectCourseClient()
        assert sc._build_queryform()["p_sfhlctkc"] == "0"
        assert sc._build_queryform(ignore_conflicts=True)["p_sfhlctkc"] == "1"
        assert sc._build_queryform()["p_sfhllrlkc"] == "0"
        assert sc._build_queryform(ignore_zero_capacity=True)["p_sfhllrlkc"] == "1"

    def test_ids_array_default(self):
        sc = SelectCourseClient()
        qf = sc._build_queryform()
        assert qf["p_ids"] == []
        qf2 = sc._build_queryform(ids=["a", "b"])
        assert qf2["p_ids"] == ["a", "b"]


class TestDryRun:
    """`dry_run=True` (default) MUST NOT touch the network."""

    def test_add_course_dry_run_returns_payload(self):
        sc = SelectCourseClient()
        res = sc.add_course("TEST-RWH", dry_run=True)
        assert res["dry_run"] is True
        assert res["endpoint"] == TIS_ADD_XUANKE_URL
        assert res["would_post"]["p_id"] == "TEST-RWH"
        assert res["would_post"]["p_xktjz"] == XKTJZ_CART_TO_ENROLLED
        assert res["jg"] is None
        # No real network call
        assert "session" not in res

    def test_drop_course_dry_run(self):
        sc = SelectCourseClient()
        res = sc.drop_course("TEST-RWH", dry_run=True)
        assert res["dry_run"] is True
        assert res["endpoint"] == TIS_TUIKE_URL
        assert res["would_post"]["p_id"] == "TEST-RWH"

    def test_add_to_cart_dry_run(self):
        sc = SelectCourseClient()
        res = sc.add_to_cart("TEST-RWH", dry_run=True)
        assert res["dry_run"] is True
        assert res["endpoint"] == TIS_ADD_GOUWUCHE_URL
        assert res["would_post"]["p_xktjz"] == XKTJZ_TASK_TO_CART

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

    @patch("sustech_survival.selectcourse.selectcourse.requests.Session.post")
    @patch("sustech_survival.selectcourse.selectcourse._tis_login")
    def test_dry_run_never_calls_post(self, mock_login, mock_post):
        """Ensure dry_run=True does NOT trigger any HTTP work."""
        sc = SelectCourseClient()
        sc.add_course("TEST-RWH", dry_run=True)
        sc.drop_course("TEST-RWH", dry_run=True)
        mock_login.assert_not_called()
        mock_post.assert_not_called()


class TestRealCall:
    """`dry_run=False` MUST hit the network and parse the response."""

    def _make_session(self, response_json):
        """Build a fake requests.Session that returns `response_json` on POST."""
        sess = MagicMock()
        resp = MagicMock()
        resp.status_code = 200
        resp.content = b'{"jg":"1","message":"ok"}' if response_json is None else None
        if response_json is not None:
            import json as _json
            resp.content = _json.dumps(response_json).encode()
        resp.json.return_value = response_json if response_json is not None else {"jg": "1", "message": "ok"}
        resp.raise_for_status = MagicMock()
        sess.post.return_value = resp
        return sess

    @patch("sustech_survival.selectcourse.selectcourse._tis_session")
    def test_add_course_real_call_success(self, mock_login):
        mock_login.return_value = self._make_session({"jg": "1", "message": "选课成功"})
        sc = SelectCourseClient()
        res = sc.add_course("TEST-RWH", dry_run=False)
        assert res["jg"] == "1"
        # Verify the URL hit
        call_url = mock_login.return_value.post.call_args[0][0]
        assert call_url == TIS_ADD_XUANKE_URL

    @patch("sustech_survival.selectcourse.selectcourse._tis_session")
    def test_add_course_real_call_failure_raises(self, mock_login):
        mock_login.return_value = self._make_session({"jg": "0", "message": "已选满"})
        sc = SelectCourseClient()
        with pytest.raises(EnrollmentError) as exc_info:
            sc.add_course("TEST-RWH", dry_run=False)
        assert exc_info.value.jg == "0"
        assert "已选满" in exc_info.value.message
        assert exc_info.value.endpoint == TIS_ADD_XUANKE_URL
        assert exc_info.value.rwh == "TEST-RWH"

    @patch("sustech_survival.selectcourse.selectcourse._tis_session")
    def test_drop_course_real_call_success(self, mock_login):
        mock_login.return_value = self._make_session({"jg": "1", "message": "退课成功"})
        sc = SelectCourseClient()
        res = sc.drop_course("TEST-RWH", dry_run=False)
        assert res["jg"] == "1"
        call_url = mock_login.return_value.post.call_args[0][0]
        assert call_url == TIS_TUIKE_URL

    @patch("sustech_survival.selectcourse.selectcourse._tis_session")
    def test_add_to_cart_real_call(self, mock_login):
        mock_login.return_value = self._make_session({"jg": "1", "message": "已加入购物车"})
        sc = SelectCourseClient()
        res = sc.add_to_cart("TEST-RWH", dry_run=False)
        assert res["jg"] == "1"
        call_url = mock_login.return_value.post.call_args[0][0]
        assert call_url == TIS_ADD_GOUWUCHE_URL
        # The form should be the second positional arg
        call_kwargs = mock_login.return_value.post.call_args
        payload = call_kwargs.kwargs.get("data") or call_kwargs[1].get("data")
        assert payload["p_xktjz"] == XKTJZ_TASK_TO_CART

    @patch("sustech_survival.selectcourse.selectcourse._tis_session")
    def test_jg_minus_one_means_not_allowed(self, mock_login):
        """jg='-1' is a special TIS code meaning 'not allowed to select'."""
        mock_login.return_value = self._make_session({"jg": "-1", "message": "您不在选课阶段"})
        sc = SelectCourseClient()
        with pytest.raises(EnrollmentError) as exc_info:
            sc.add_course("TEST-RWH", dry_run=False)
        assert exc_info.value.jg == "-1"


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


class TestPublicExports:
    def test_constants_exported(self):
        from sustech_survival import selectcourse as sc_mod
        assert sc_mod.TIS_ADD_XUANKE_URL.endswith("/Xsxk/addXuanke")
        assert sc_mod.TIS_TUIKE_URL.endswith("/Xsxk/tuike")
        assert sc_mod.XKTJZ_CART_TO_ENROLLED == "gwctjzyx"
        assert sc_mod.XKTJZ_TASK_TO_CART == "rwtjzgwc"