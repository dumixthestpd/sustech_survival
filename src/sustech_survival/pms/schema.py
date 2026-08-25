"""
sustech_survival.pms.schema — Dataclasses for PMS records.

Mirrors the JSON returned by `pms.sustech.edu.cn/api/client/*` endpoints.
All parsers are classmethods — never expose loose `parse_*` functions.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import List, Optional


# -- Constants ----------------------------------------------------------------

# Paper size codes used across the API (dwPaperId)
PAPER_UNSPECIFIED = -1
PAPER_A4 = 9
PAPER_A3 = 8

# Color codes (dwColor)
COLOR_BW = 1
COLOR_COLOR = 2

# Duplex codes (dwDuplex)
DUPLEX_SINGLE = 1
DUPLEX_SHORT_EDGE = 2
DUPLEX_LONG_EDGE = 3

# dwProperty bitmask for printer capabilities (printDev.js, backGong)
PROPERTY_PRINT = 1
PROPERTY_COPY = 2
PROPERTY_SCAN = 4
PROPERTY_COLOR = 8

# Status interpretation helpers
STATUS_IDLE = 1            # dwStatus & 1
STATUS_BUSY = 2            # dwStatus & 2
STATUS_FAULT_FLAGS = (0x20, 0x200, 0x400, 0x800, 0x1000, 0x2000, 0x10000)

# dwType for usage records (Report/DetailPage)
REPORT_TYPE_PRINT = 1
REPORT_TYPE_SCAN = 2
REPORT_TYPE_COPY = 3


def paper_name(code: Optional[int]) -> str:
    return {PAPER_A3: "A3", PAPER_A4: "A4"}.get(code or 0, "")


def paper_id(name: str) -> int:
    return {"A3": PAPER_A3, "A4": PAPER_A4, "不指定": PAPER_UNSPECIFIED,
            "unspecified": PAPER_UNSPECIFIED, "": PAPER_UNSPECIFIED}.get(
                name.strip(), PAPER_UNSPECIFIED)


# -- Station (打印点) ---------------------------------------------------------

@dataclass
class Station:
    """A physical printer/copier/scanner station on campus."""
    dw_dev_sn: int           # device serial number
    sz_name: str             # "慧园1栋二楼彩色(W1-2F CO)"
    sz_stat_info: str        # raw status text from server
    dw_status: int           # bitmask — see STATUS_* helpers
    dw_tray_paper_1: int     # -1 = unspecified; 9 = A4; 8 = A3
    dw_tray_paper_2: int
    dw_tray_paper_3: int
    dw_tray_paper_4: int
    dw_property: int         # bitmask — PROPERTY_PRINT | PROPERTY_COLOR | ...

    # Derived
    is_idle: bool = False
    is_busy: bool = False
    is_fault: bool = False
    state_text: str = ""
    state_flag: int = 0      # 2=idle, 1=busy, 3=fault/unavailable
    papers: List[str] = field(default_factory=list)        # ["A4", "A3"]
    can_print: bool = False
    can_copy: bool = False
    can_scan: bool = False
    can_color: bool = False

    @classmethod
    def from_api(cls, raw: dict) -> "Station":
        st = cls(
            dw_dev_sn=raw.get("dwDevSN", 0),
            sz_name=raw.get("szName", ""),
            sz_stat_info=raw.get("szStatInfo", ""),
            dw_status=raw.get("dwStatus", 0),
            dw_tray_paper_1=raw.get("dwTrayPaper1", -1),
            dw_tray_paper_2=raw.get("dwTrayPaper2", -1),
            dw_tray_paper_3=raw.get("dwTrayPaper3", -1),
            dw_tray_paper_4=raw.get("dwTrayPaper4", -1),
            dw_property=raw.get("dwProperty", 0),
        )
        st._derive()
        return st

    def _derive(self) -> None:
        s = self.dw_status
        self.is_idle = bool(s & STATUS_IDLE)
        self.is_busy = bool(s & STATUS_BUSY)
        self.is_fault = bool(s & 0x20) or bool(s & 0x200) or bool(s & 0x400) \
                        or bool(s & 0x800) or bool(s & 0x1000) \
                        or bool(s & 0x2000) or bool(s & 0x10000) or s == 0

        # State text (mirrors printDev.js backState)
        if s == 0:
            self.state_text = "未开放"
            self.state_flag = 3
        elif s & STATUS_IDLE:
            self.state_text = "空闲"
            self.state_flag = 2
        elif s & STATUS_BUSY:
            self.state_text = "忙碌"
            self.state_flag = 1
        elif s & 0x20 or s & 0x200 or s & 0x400 or s & 0x800 or s & 0x1000 \
                or s & 0x2000 or s & 0x10000:
            info = self.sz_stat_info or ""
            # Take text before first "-"
            short = info.split("-", 1)[0] if "-" in info else info
            self.state_text = short or "不可用"
            self.state_flag = 3
        else:
            self.state_text = "不可用"
            self.state_flag = 3

        # Papers
        seen = []
        for code in [self.dw_tray_paper_1, self.dw_tray_paper_2,
                     self.dw_tray_paper_3, self.dw_tray_paper_4]:
            name = paper_name(code)
            if name and name not in seen:
                seen.append(name)
        self.papers = seen

        # Capabilities
        self.can_print = bool(self.dw_property & PROPERTY_PRINT)
        self.can_copy = bool(self.dw_property & PROPERTY_COPY)
        self.can_scan = bool(self.dw_property & PROPERTY_SCAN)
        self.can_color = bool(self.dw_property & PROPERTY_COLOR)

    @property
    def server_group(self) -> int:
        """Server bucket (used by the dropdown filter)."""
        return self.dw_dev_sn // 1000

    @property
    def functions_text(self) -> str:
        parts = []
        if self.can_print:
            parts.append("打印")
        if self.can_copy:
            parts.append("复印")
        if self.can_scan:
            parts.append("扫描")
        if self.can_color:
            parts.append("支持彩色")
        return "，".join(parts)

    def to_markdown(self) -> str:
        lines = [
            f"### {self.sz_name}",
            f"- **状态**: {self.state_text}",
            f"- **纸型**: {', '.join(self.papers) or '—'}",
            f"- **功能**: {self.functions_text or '—'}",
            f"- **设备号**: {self.dw_dev_sn}",
        ]
        return "\n".join(lines)


@dataclass
class ServerGroup:
    """A filter group from the dropdown on the print-points page."""
    dw_sn: int
    sz_name: str

    @classmethod
    def from_api(cls, raw: dict) -> "ServerGroup":
        return cls(
            dw_sn=raw.get("dwSN", 0),
            sz_name=raw.get("szName", ""),
        )


# -- Print job (打印文档) -----------------------------------------------------

@dataclass
class PrintJob:
    """A document uploaded to PMS but not yet printed."""
    dw_job_id: int            # PMS internal job ID (the real key)
    sz_job_name: str = ""     # original uploaded filename
    dw_create_date: int = 0   # YYYYMMDD
    dw_create_time: int = 0   # HHMMSS
    dw_copies: int = 1
    sz_attribe: str = ""      # comma-sep flags: "color", "single", "vdup", "hdup"
    sz_paper_detail: List[dict] = field(default_factory=list)  # raw per-paper-info

    # Derived
    file_name: str = ""
    paper: str = ""           # "A4"/"A3" (from first paper detail)
    dw_total_pages: int = 0   # total across all paper sizes
    is_color: bool = False
    is_duplex: bool = False
    duplex_label: str = ""    # 单面 / 双面短边 / 双面长边
    date_str: str = ""
    time_str: str = ""

    @classmethod
    def from_api(cls, raw: dict) -> "PrintJob":
        # szPaperDetail is a JSON-encoded string in the API response
        paper_detail_raw = raw.get("szPaperDetail") or "[]"
        if isinstance(paper_detail_raw, str):
            try:
                paper_detail = json.loads(paper_detail_raw)
            except Exception:
                paper_detail = []
        else:
            paper_detail = paper_detail_raw

        attribe = raw.get("szAttribe", "")
        # Duplex: parse attribe flags
        if "single" in attribe:
            duplex_label = "单面"
            duplex_code = DUPLEX_SINGLE
        elif "vdup" in attribe:
            duplex_label = "双面长边"
            duplex_code = DUPLEX_LONG_EDGE
        elif "hdup" in attribe:
            duplex_label = "双面短边"
            duplex_code = DUPLEX_SHORT_EDGE
        else:
            duplex_label = "单面"
            duplex_code = DUPLEX_SINGLE

        # Paper info from first detail
        paper = ""
        total = 0
        if paper_detail:
            first = paper_detail[0]
            pid = first.get("dwPaperID", -1)
            paper = paper_name(pid)
            total = (first.get("dwBWPages", 0) or 0) + (first.get("dwColorPages", 0) or 0)

        date_str = ""
        cd = raw.get("dwCreateDate", 0)
        if cd:
            date_str = f"{cd:08d}"
            if len(date_str) == 8:
                date_str = f"{date_str[:4]}.{date_str[4:6]}.{date_str[6:]}"
        time_str = ""
        ct = raw.get("dwCreateTime", 0)
        if ct:
            t = f"{int(ct):06d}"
            time_str = f"{t[:2]}:{t[2:4]}:{t[4:]}"

        j = cls(
            dw_job_id=raw.get("dwJobId", 0),
            sz_job_name=raw.get("szJobName", ""),
            dw_create_date=cd,
            dw_create_time=ct,
            dw_copies=raw.get("dwCopies", 1),
            sz_attribe=attribe,
            sz_paper_detail=paper_detail,
            file_name=raw.get("szJobName", ""),
            paper=paper,
            dw_total_pages=total,
            is_color="color" in attribe,
            is_duplex=duplex_code != DUPLEX_SINGLE,
            duplex_label=duplex_label,
            date_str=date_str,
            time_str=time_str,
        )
        return j

    @property
    def datetime_str(self) -> str:
        if self.date_str and self.time_str:
            return f"{self.date_str} {self.time_str}"
        return self.date_str or self.time_str

    def to_markdown(self) -> str:
        return (
            f"### {self.file_name}\n"
            f"- **ID**: {self.dw_job_id}\n"
            f"- **上传时间**: {self.datetime_str or '—'}\n"
            f"- **页数**: {self.dw_total_pages}\n"
            f"- **纸型**: {self.paper or '不指定'}\n"
            f"- **份数**: {self.dw_copies}\n"
            f"- **颜色**: {'彩色' if self.is_color else '黑白'}\n"
            f"- **单双面**: {self.duplex_label}\n"
            f"- **属性**: `{self.sz_attribe}`\n"
        )


# -- Scan job (扫描文档) ------------------------------------------------------

@dataclass
class ScanJob:
    """A scanned document."""
    dw_job_id: int
    sz_display_name: str = ""
    dw_file_size: int = 0
    dw_submit_date: int = 0
    dw_submit_time: int = 0

    # Derived
    file_name: str = ""
    date_str: str = ""
    time_str: str = ""

    @classmethod
    def from_api(cls, raw: dict) -> "ScanJob":
        date_str = ""
        sd = raw.get("dwSubmitDate", 0)
        if sd:
            ds = f"{sd:08d}"
            if len(ds) == 8:
                date_str = f"{ds[:4]}.{ds[4:6]}.{ds[6:]}"
        time_str = ""
        st = raw.get("dwSubmitTime", 0)
        if st:
            t = f"{int(st):06d}"
            time_str = f"{t[:2]}:{t[2:4]}:{t[4:]}"

        return cls(
            dw_job_id=raw.get("dwJobId", 0),
            sz_display_name=raw.get("szDisplayName", ""),
            dw_file_size=raw.get("dwFileSize", 0),
            dw_submit_date=sd,
            dw_submit_time=st,
            file_name=raw.get("szDisplayName", ""),
            date_str=date_str,
            time_str=time_str,
        )

    @property
    def file_size_kb(self) -> float:
        return self.dw_file_size / 1024.0

    @property
    def datetime_str(self) -> str:
        if self.date_str and self.time_str:
            return f"{self.date_str} {self.time_str}"
        return self.date_str or self.time_str

    def to_markdown(self) -> str:
        return (
            f"### {self.file_name}\n"
            f"- **ID**: {self.dw_job_id}\n"
            f"- **大小**: {self.file_size_kb:.1f} KB\n"
            f"- **时间**: {self.datetime_str or '—'}\n"
        )


# -- Usage record (使用记录) --------------------------------------------------

@dataclass
class UsageRecord:
    """A line in the usage-records table (打印/扫描/复印)."""
    dw_sid: int = 0           # record ID
    dw_date: int = 0          # YYYYMMDD
    dw_time: int = 0          # HHMMSS
    dw_pages: int = 0         # total pages (printed/scanned/copied)
    dw_paper_id: int = -1     # 9=A4, 8=A3
    dw_unit_fee: int = 0      # per-page fee in cents
    dw_used_card_money: int = 0     # in cents
    dw_used_free_money: int = 0     # in cents (subsidy)
    dw_used_money: int = 0          # in cents
    dw_settle_type: int = 0         # 4=manual, else=self-service
    dw_mfp_sn: int = 0              # device serial
    dw_type: int = 0                # service type bits
    dw_property: int = 0
    sz_logon_name: str = ""
    sz_card_no: str = ""
    sz_true_name: str = ""
    sz_memo: str = ""

    # Derived
    date_str: str = ""
    time_str: str = ""
    paper: str = ""
    money_total: float = 0.0

    @classmethod
    def from_api(cls, raw: dict) -> "UsageRecord":
        r = cls(
            dw_sid=raw.get("dwSID", 0),
            dw_date=raw.get("dwDate", 0),
            dw_time=raw.get("dwTime", 0),
            dw_pages=raw.get("dwPages", 0),
            dw_paper_id=raw.get("dwPaperID") or raw.get("dwPaperId") or -1,
            dw_unit_fee=raw.get("dwUnitFee", 0),
            dw_used_card_money=raw.get("dwUsedCardMoney", 0),
            dw_used_free_money=raw.get("dwUsedFreeMoney", 0),
            dw_used_money=raw.get("dwUsedMoney", 0),
            dw_settle_type=raw.get("dwSettleType", 0),
            dw_mfp_sn=raw.get("dwMFPSN", 0),
            dw_type=raw.get("dwType", 0),
            dw_property=raw.get("dwProperty", 0),
            sz_logon_name=raw.get("szLogonName", ""),
            sz_card_no=raw.get("szCardNO", ""),
            sz_true_name=raw.get("szTrueName", ""),
            sz_memo=raw.get("szMemo", ""),
        )
        r.date_str = f"{r.dw_date:08d}" if r.dw_date else ""
        if r.date_str:
            r.date_str = f"{r.date_str[:4]}.{r.date_str[4:6]}.{r.date_str[6:]}"
        if r.dw_time:
            t = f"{int(r.dw_time):06d}"
            r.time_str = f"{t[:2]}:{t[2:4]}:{t[4:]}"
        r.paper = paper_name(r.dw_paper_id)
        r.money_total = (r.dw_used_card_money + r.dw_used_free_money + r.dw_used_money) / 100.0
        return r

    @property
    def datetime_str(self) -> str:
        if self.date_str and self.time_str:
            return f"{self.date_str} {self.time_str}"
        return self.date_str or self.time_str

    @property
    def settle_label(self) -> str:
        return "手工收费" if (self.dw_settle_type & 0xFF) == 4 else "自助收费"

    def to_markdown(self) -> str:
        return (
            f"- **{self.datetime_str}** — {self.paper or '?'}; "
            f"{self.dw_pages}页 — ¥{self.money_total:.2f} "
            f"({self.settle_label}, dev={self.dw_mfp_sn})"
        )