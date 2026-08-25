"""
test_pms_module.py — Module import and coercion-helper tests.

No network. Tests imports + the value-coercion helpers in pms.py.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from sustech_survival.pms import (
    PMSClient, PMSError, PrintUploadResult, pms,
    Station, ServerGroup, PrintJob, ScanJob, UsageRecord,
    PAPER_A4, PAPER_A3, PAPER_UNSPECIFIED,
    COLOR_BW, COLOR_COLOR,
    DUPLEX_SINGLE, DUPLEX_SHORT_EDGE, DUPLEX_LONG_EDGE,
    REPORT_TYPE_PRINT, REPORT_TYPE_SCAN, REPORT_TYPE_COPY,
)
from sustech_survival.pms.pms import (
    _coerce_color, _coerce_paper, _coerce_duplex,
    _looks_off_campus, OFF_CAMPUS_BODY, OFF_CAMPUS_HINT,
    PMSClient as _PMSClient,
)


# -- Module surface ----------------------------------------------------------

class TestModuleExports:
    def test_all_classes_importable(self):
        for cls in [PMSClient, PMSError, PrintUploadResult,
                    Station, ServerGroup, PrintJob, ScanJob, UsageRecord]:
            assert cls is not None

    def test_all_constants(self):
        assert PAPER_A4 == 9
        assert PAPER_A3 == 8
        assert PAPER_UNSPECIFIED == -1
        assert COLOR_BW == 1
        assert COLOR_COLOR == 2
        assert DUPLEX_SINGLE == 1
        assert DUPLEX_SHORT_EDGE == 2
        assert DUPLEX_LONG_EDGE == 3
        assert REPORT_TYPE_PRINT == 1
        assert REPORT_TYPE_SCAN == 2
        assert REPORT_TYPE_COPY == 3


# -- Coercion helpers --------------------------------------------------------

class TestCoerceColor:
    def test_int_passthrough(self):
        assert _coerce_color(1) == COLOR_BW
        assert _coerce_color(2) == COLOR_COLOR

    def test_string_aliases(self):
        assert _coerce_color("bw") == COLOR_BW
        assert _coerce_color("black") == COLOR_BW
        assert _coerce_color("黑白") == COLOR_BW
        assert _coerce_color("color") == COLOR_COLOR
        assert _coerce_color("彩色") == COLOR_COLOR
        assert _coerce_color("colour") == COLOR_COLOR

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            _coerce_color("rainbow")
        with pytest.raises(ValueError):
            _coerce_color(99)


class TestCoercePaper:
    def test_int_passthrough(self):
        assert _coerce_paper(9) == PAPER_A4
        assert _coerce_paper(8) == PAPER_A3
        assert _coerce_paper(-1) == PAPER_UNSPECIFIED

    def test_string_aliases(self):
        assert _coerce_paper("A4") == PAPER_A4
        assert _coerce_paper("a4") == PAPER_A4
        assert _coerce_paper("A3") == PAPER_A3
        assert _coerce_paper("不指定") == PAPER_UNSPECIFIED
        assert _coerce_paper("") == PAPER_UNSPECIFIED
        assert _coerce_paper("unspecified") == PAPER_UNSPECIFIED
        assert _coerce_paper("none") == PAPER_UNSPECIFIED

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            _coerce_paper("A2")
        with pytest.raises(ValueError):
            _coerce_paper(99)


class TestCoerceDuplex:
    def test_int_passthrough(self):
        assert _coerce_duplex(1) == DUPLEX_SINGLE
        assert _coerce_duplex(2) == DUPLEX_SHORT_EDGE
        assert _coerce_duplex(3) == DUPLEX_LONG_EDGE

    def test_string_aliases(self):
        assert _coerce_duplex("single") == DUPLEX_SINGLE
        assert _coerce_duplex("单面") == DUPLEX_SINGLE
        assert _coerce_duplex("short") == DUPLEX_SHORT_EDGE
        assert _coerce_duplex("双面短边") == DUPLEX_SHORT_EDGE
        assert _coerce_duplex("long") == DUPLEX_LONG_EDGE
        assert _coerce_duplex("双面长边") == DUPLEX_LONG_EDGE

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            _coerce_duplex("duplex")
        with pytest.raises(ValueError):
            _coerce_duplex(99)


# -- PrintUploadResult -------------------------------------------------------

class TestPrintUploadResult:
    def test_dry_run_markdown(self):
        r = PrintUploadResult(
            file_path="/tmp/test.pdf", file_name="test.pdf",
            color=COLOR_BW, paper=PAPER_A4, duplex=DUPLEX_SINGLE,
            page_from=0, page_to=0, copies=1,
            uploaded=False, ok=False, code=None,
            message="DRY-RUN: prepared upload, did not POST",
        )
        md = r.to_markdown()
        assert "DRY-RUN" in md
        assert "test.pdf" in md
        assert "A4" in md
        assert "黑白" in md
        assert "全部" in md   # page_from == 0 means all

    def test_success_markdown(self):
        r = PrintUploadResult(
            file_path="/tmp/x.pdf", file_name="x.pdf",
            color=COLOR_COLOR, paper=PAPER_A3, duplex=DUPLEX_LONG_EDGE,
            page_from=1, page_to=5, copies=2,
            uploaded=True, ok=True, code=0, message="",
        )
        md = r.to_markdown()
        assert "uploaded" in md.lower()
        assert "彩色" in md
        assert "A3" in md
        assert "双面长边" in md
        assert "1-5" in md
        assert "2" in md

    def test_failed_markdown(self):
        r = PrintUploadResult(
            file_path="/tmp/x.pdf", file_name="x.pdf",
            color=COLOR_BW, paper=PAPER_UNSPECIFIED, duplex=DUPLEX_SINGLE,
            page_from=0, page_to=0, copies=1,
            uploaded=False, ok=False, code=413, message="File too large",
        )
        md = r.to_markdown()
        assert "failed" in md.lower()
        assert "File too large" in md


# -- PMSClient construction --------------------------------------------------

class TestPMSClient:
    def test_construct_with_session(self):
        import requests
        sess = requests.Session()
        c = PMSClient(session=sess)
        assert c.session is sess
        assert c.BASE_URL == "https://pms.sustech.edu.cn"
        assert c.API_BASE == "https://pms.sustech.edu.cn/api"


# -- Date formatting helper --------------------------------------------------

class TestFmtDate:
    def test_date_object(self):
        from datetime import date
        assert _PMSClient._fmt_date(date(2026, 6, 12)) == "20260612"

    def test_iso_string(self):
        assert _PMSClient._fmt_date("2026-06-12") == "20260612"

    def test_dashed_string(self):
        assert _PMSClient._fmt_date("20260612") == "20260612"

    def test_dotted_string(self):
        assert _PMSClient._fmt_date("2026.06.12") == "20260612"

    def test_default_none(self):
        # None defaults to today (default_days_back=0)
        from datetime import date
        result = _PMSClient._fmt_date(None, default_days_back=0)
        assert result == date.today().strftime("%Y%m%d")

    def test_invalid_string_raises(self):
        with pytest.raises(ValueError):
            _PMSClient._fmt_date("hello")

    def test_invalid_type_raises(self):
        with pytest.raises(TypeError):
            _PMSClient._fmt_date(12345)


# -- Off-campus (HTTP 403) detection -----------------------------------------

class TestOffCampus:
    """PMS sits behind SUSTech's campus firewall. Off-campus requests get a
    403 with body "Access forbidden, please contact administrator." and the
    module must surface that as an actionable error, not a JSON decode crash.
    """

    def _make_response(self, status_code: int, body: str):
        import requests
        r = requests.Response()
        r.status_code = status_code
        r._content = body.encode("utf-8")
        return r

    def test_body_constant_matches_server(self):
        assert OFF_CAMPUS_BODY == "Access forbidden, please contact administrator."

    def test_hint_mentions_campus_network(self):
        assert "SUSTech" in OFF_CAMPUS_HINT
        assert "campus network" in OFF_CAMPUS_HINT.lower() or "campus" in OFF_CAMPUS_HINT.lower()

    def test_detects_off_campus_403(self):
        r = self._make_response(403, "Access forbidden, please contact administrator.")
        assert _looks_off_campus(r) is True

    def test_ignores_403_with_different_body(self):
        # Some other 403 (auth, maintenance, etc.) — must not trigger hint.
        r = self._make_response(403, "Forbidden")
        assert _looks_off_campus(r) is False

    def test_ignores_200_with_offcampus_body(self):
        # Defensive: matching body but wrong status — must not trigger.
        r = self._make_response(200, "Access forbidden, please contact administrator.")
        assert _looks_off_campus(r) is False

    def test_ignores_500_with_offcampus_body(self):
        r = self._make_response(500, "Access forbidden, please contact administrator.")
        assert _looks_off_campus(r) is False

    def test_unwrap_raises_pmserror_with_hint_on_off_campus(self):
        r = self._make_response(403, "Access forbidden, please contact administrator.")
        with pytest.raises(PMSError) as exc:
            _PMSClient._unwrap(r)
        assert "NOT on the SUSTech campus network" in str(exc.value)

    def test_unwrap_falls_back_to_generic_on_other_non_json(self):
        # Non-JSON body that ISN'T the off-campus signal — generic hint.
        r = self._make_response(502, "<html>Bad Gateway</html>")
        with pytest.raises(PMSError) as exc:
            _PMSClient._unwrap(r)
        msg = str(exc.value)
        assert "Non-JSON response" in msg
        assert "NOT on the SUSTech" not in msg

    def test_unwrap_passes_through_valid_json(self):
        r = self._make_response(200, '{"code": 0, "message": "ok", "result": [1, 2]}')
        assert _PMSClient._unwrap(r) == [1, 2]

    def test_unwrap_raises_on_error_code(self):
        r = self._make_response(200, '{"code": 401, "message": "Not authenticated"}')
        with pytest.raises(PMSError) as exc:
            _PMSClient._unwrap(r)
        assert "Not authenticated" in str(exc.value)


# -- Off-campus wiring on history / delete_* ---------------------------------
# These methods call r.json() directly (not via _unwrap) — confirm the
# off-campus check is wired into each path independently.

class TestOffCampusWiring:
    def _make_response(self, status_code: int, body: str):
        import requests
        r = requests.Response()
        r.status_code = status_code
        r._content = body.encode("utf-8")
        return r

    def _fake_session(self, r):
        import requests
        sess = requests.Session()
        # Replace the methods we want to stub
        def fake_post(*a, **kw): return r
        def fake_get(*a, **kw): return r
        sess.post = fake_post
        sess.get = fake_get
        return sess

    def test_history_raises_offcampus(self):
        import requests
        r = self._make_response(403, "Access forbidden, please contact administrator.")
        c = _PMSClient(session=self._fake_session(r))
        with pytest.raises(PMSError) as exc:
            c.history(begin="20260601", end="20260614", type=1)
        assert "NOT on the SUSTech campus network" in str(exc.value)

    def test_delete_print_job_raises_offcampus(self):
        r = self._make_response(403, "Access forbidden, please contact administrator.")
        c = _PMSClient(session=self._fake_session(r))
        with pytest.raises(PMSError) as exc:
            c.delete_print_job(12345)
        assert "NOT on the SUSTech campus network" in str(exc.value)

    def test_delete_scan_job_raises_offcampus(self):
        r = self._make_response(403, "Access forbidden, please contact administrator.")
        c = _PMSClient(session=self._fake_session(r))
        with pytest.raises(PMSError) as exc:
            c.delete_scan_job(67890)
        assert "NOT on the SUSTech campus network" in str(exc.value)