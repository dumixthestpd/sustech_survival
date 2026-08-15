"""
test_pms_schema.py — Offline schema parsing tests.

Uses fixture dicts that mimic the real PMS API responses. No network.
"""
import sys
from pathlib import Path

import pytest

# Make src/ importable
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from sustech_survival.pms.schema import (
    Station, ServerGroup, PrintJob, ScanJob, UsageRecord,
    PAPER_A4, PAPER_A3, PAPER_UNSPECIFIED,
    COLOR_BW, COLOR_COLOR,
    DUPLEX_SINGLE, DUPLEX_SHORT_EDGE, DUPLEX_LONG_EDGE,
    paper_name, paper_id,
)


# ── Paper name/id roundtrip ──────────────────────────────────────────────────

class TestPaperName:
    def test_known_codes(self):
        assert paper_name(9) == "A4"
        assert paper_name(8) == "A3"
        assert paper_name(-1) == ""
        assert paper_name(0) == ""
        assert paper_name(None) == ""

    def test_id_lookup(self):
        assert paper_id("A4") == PAPER_A4
        assert paper_id("A3") == PAPER_A3
        assert paper_id("不指定") == PAPER_UNSPECIFIED
        assert paper_id("") == PAPER_UNSPECIFIED
        assert paper_id("unspecified") == PAPER_UNSPECIFIED


# ── Station parsing ─────────────────────────────────────────────────────────

class TestStation:
    def _raw(self, **overrides):
        raw = {
            "dwDevSN": 1011,
            "dwFunction": 7,
            "dwCtrlType": 1,
            "dwProperty": 95,
            "dwStatus": 1,
            "dwKind": 0,
            "dwTrayPaper1": 9,
            "dwTrayPaper2": 9,
            "dwTrayPaper3": 0,
            "dwTrayPaper4": 0,
            "dwModel": 401,
            "dwSpeed": 0,
            "dwOpenTime": 0,
            "dwCloseTime": 1439,
            "dwChgTime": 1781234137,
            "dwUpdateTime": 1781266006,
            "szName": "慧园1栋二楼彩色(W1-2F CO)",
            "szIP": "172.30.5.11",
            "szPosition": "",
            "szTel": "",
            "szCardIP": "",
            "szMAC": "002246298f23",
            "szCampus": "",
            "szRoomName": "",
            "szDeptName": "",
            "szPrtDriver": "Gestetner MP C3004 PCL 6",
            "szStatInfo": "系统空闲",
            "szMemo": "",
        }
        raw.update(overrides)
        return raw

    def test_idle_station(self):
        s = Station.from_api(self._raw(dwStatus=1))
        assert s.is_idle
        assert s.state_text == "空闲"
        assert s.state_flag == 2
        assert s.papers == ["A4"]
        # dwProperty 95 = 64+16+8+4+2+1 → all caps on
        assert s.can_print
        assert s.can_copy
        assert s.can_scan
        assert s.can_color

    def test_busy_station(self):
        s = Station.from_api(self._raw(dwStatus=2))
        assert s.is_busy
        assert s.state_text == "忙碌"
        assert s.state_flag == 1

    def test_fault_station(self):
        s = Station.from_api(self._raw(dwStatus=0x20,
                                       szStatInfo="系统故障-卡纸"))
        assert s.is_fault
        assert s.state_text == "系统故障"   # text before "-"
        assert s.state_flag == 3

    def test_a3_paper(self):
        s = Station.from_api(self._raw(dwTrayPaper1=8))
        assert "A3" in s.papers

    def test_color_only_printer(self):
        # property 8 = color only (no print/copy/scan)
        s = Station.from_api(self._raw(dwProperty=8))
        assert not s.can_print
        assert not s.can_copy
        assert not s.can_scan
        assert s.can_color

    def test_server_group(self):
        s = Station.from_api(self._raw(dwDevSN=1050))
        assert s.server_group == 1  # 1050 // 1000

    def test_markdown_output(self):
        s = Station.from_api(self._raw())
        md = s.to_markdown()
        assert "慧园1栋二楼彩色" in md
        assert "空闲" in md
        assert "A4" in md
        assert "打印" in md
        assert "1011" in md


# ── ServerGroup ─────────────────────────────────────────────────────────────

class TestServerGroup:
    def test_parse(self):
        g = ServerGroup.from_api({"dwSN": 1, "szName": "OPMServer"})
        assert g.dw_sn == 1
        assert g.sz_name == "OPMServer"


# ── PrintJob parsing ────────────────────────────────────────────────────────

class TestPrintJob:
    def _raw(self, **overrides):
        raw = {
            "dwJobId": 1001,
            "szJobName": "homework.pdf",
            "dwCreateDate": 20260611,
            "dwCreateTime": 174039,
            "dwCopies": 2,
            "szAttribe": "single,A4",
            "szPaperDetail": '[{"dwPaperID":9,"dwBWPages":3,"dwColorPages":0}]',
        }
        raw.update(overrides)
        return raw

    def test_basic(self):
        j = PrintJob.from_api(self._raw())
        assert j.dw_job_id == 1001
        assert j.file_name == "homework.pdf"
        assert j.paper == "A4"
        assert j.dw_total_pages == 3
        assert j.dw_copies == 2
        assert j.duplex_label == "单面"
        assert not j.is_color
        assert not j.is_duplex
        assert j.datetime_str == "2026.06.11 17:40:39"

    def test_color_duplex_long(self):
        j = PrintJob.from_api(self._raw(szAttribe="color,vdup,A4"))
        assert j.is_color
        assert j.is_duplex
        assert j.duplex_label == "双面长边"

    def test_duplex_short(self):
        j = PrintJob.from_api(self._raw(szAttribe="hdup,A4"))
        assert j.is_duplex
        assert j.duplex_label == "双面短边"

    def test_color_pages_count(self):
        # Color pages counted separately
        j = PrintJob.from_api(self._raw(
            szAttribe="color,A4",
            szPaperDetail='[{"dwPaperID":9,"dwBWPages":1,"dwColorPages":2}]',
        ))
        assert j.dw_total_pages == 3

    def test_a3_paper(self):
        j = PrintJob.from_api(self._raw(
            szAttribe="single,A3",
            szPaperDetail='[{"dwPaperID":8,"dwBWPages":5,"dwColorPages":0}]',
        ))
        assert j.paper == "A3"

    def test_paper_detail_already_list(self):
        j = PrintJob.from_api(self._raw(
            szPaperDetail=[{"dwPaperID": 9, "dwBWPages": 1, "dwColorPages": 0}]
        ))
        assert j.paper == "A4"

    def test_markdown(self):
        j = PrintJob.from_api(self._raw())
        md = j.to_markdown()
        assert "homework.pdf" in md
        assert "A4" in md
        assert "1001" in md
        assert "黑白" in md


# ── ScanJob parsing ─────────────────────────────────────────────────────────

class TestScanJob:
    def test_basic(self):
        s = ScanJob.from_api({
            "dwJobId": 2001,
            "szDisplayName": "scan_001.pdf",
            "dwFileSize": 12345,
            "dwSubmitDate": 20260611,
            "dwSubmitTime": 174039,
        })
        assert s.dw_job_id == 2001
        assert s.file_name == "scan_001.pdf"
        assert s.file_size_kb == pytest.approx(12.06, rel=0.01)
        assert s.datetime_str == "2026.06.11 17:40:39"


# ── UsageRecord parsing ─────────────────────────────────────────────────────

class TestUsageRecord:
    def test_basic(self):
        r = UsageRecord.from_api({
            "dwSID": 3106522,
            "dwDate": 20260611,
            "dwTime": 174039,
            "dwPages": 3,
            "dwUnitFee": 10,
            "dwUsedCardMoney": 0,
            "dwUsedFreeMoney": 30,
            "dwUsedMoney": 0,
            "dwPaperID": 9,
            "dwType": 131073,
            "dwProperty": 0,
            "dwSettleType": 0,
            "szLogonName": "<sid>",
            "szCardNO": "EED73C02",
            "szTrueName": "<name>",
            "szMemo": "",
        })
        assert r.dw_sid == 3106522
        assert r.dw_date == 20260611
        assert r.dw_time == 174039
        assert r.dw_pages == 3
        assert r.paper == "A4"
        assert r.money_total == pytest.approx(0.30, rel=0.01)
        assert r.sz_true_name == "<name>"
        assert r.dw_mfp_sn == 0  # field not in this record
        assert r.datetime_str == "2026.06.11 17:40:39"
        assert r.settle_label == "自助收费"

    def test_manual_settle(self):
        r = UsageRecord.from_api({"dwSettleType": 4})
        assert r.settle_label == "手工收费"

    def test_money_components(self):
        r = UsageRecord.from_api({
            "dwUsedCardMoney": 50, "dwUsedFreeMoney": 30, "dwUsedMoney": 20,
        })
        # 50 + 30 + 20 = 100 cents = 1.00 yuan
        assert r.money_total == pytest.approx(1.00)

    def test_a3_paper(self):
        r = UsageRecord.from_api({"dwPaperID": 8})
        assert r.paper == "A3"