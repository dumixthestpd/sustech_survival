"""
test_pms_module.py — Module import and coercion-helper tests.

No network. Tests imports + the value-coercion helpers in pms.py.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
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
    PMSClient as _PMSClient,
)


# ── Module surface ──────────────────────────────────────────────────────────

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


# ── Coercion helpers ────────────────────────────────────────────────────────

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


# ── PrintUploadResult ───────────────────────────────────────────────────────

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


# ── PMSClient construction ──────────────────────────────────────────────────

class TestPMSClient:
    def test_construct_with_session(self):
        import requests
        sess = requests.Session()
        c = PMSClient(session=sess)
        assert c.session is sess
        assert c.BASE_URL == "https://pms.sustech.edu.cn"
        assert c.API_BASE == "https://pms.sustech.edu.cn/api"


# ── Date formatting helper ──────────────────────────────────────────────────

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