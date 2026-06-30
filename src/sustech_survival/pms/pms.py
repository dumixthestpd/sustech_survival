"""
sustech_survival.pms — Live client for the SUSTech 联创 PMS cloud print system.

ONE class. ALL operations. ZERO local data (every call hits the live site).

Architecture mirrors `sustech_survival.faculty.FacultyClient`:

    PMSClient                  ← one client, all the methods
        .list_stations(...)        ← GET /client/Station/GetList
        .list_server_groups(...)   ← GET /client/Station/GetSrvList
        .list_print_jobs()         ← GET /client/PrintJob/Get
        .delete_print_job(id)      ← POST /client/PrintJob/Del
        .list_scan_jobs()          ← GET /client/Scan/Get
        .delete_scan_job(id)       ← POST /client/Scan/Del
        .history(...)              ← POST /client/Report/DetailPage
        .upload_print(file, ...)   ← POST /client/CloudPrint/Upload (multipart)

Schema classes (`Station`, `ServerGroup`, `PrintJob`, `ScanJob`, `UsageRecord`)
all live in `schema.py` with classmethod `from_api()` parsers.

Authentication is handled separately by `sustech_survival.sso.authlib.pms.PMSAuth`.
This class is auth-agnostic — pass it any `requests.Session` that has the
OSESSIONID cookie set.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, date
from pathlib import Path
from typing import List, Optional, Union

import requests

from .schema import (
    Station, ServerGroup, PrintJob, ScanJob, UsageRecord,
    PAPER_UNSPECIFIED, PAPER_A4, PAPER_A3,
    COLOR_BW, COLOR_COLOR,
    DUPLEX_SINGLE, DUPLEX_SHORT_EDGE, DUPLEX_LONG_EDGE,
    REPORT_TYPE_PRINT, REPORT_TYPE_SCAN, REPORT_TYPE_COPY,
    paper_name,
)


PMS_BASE = "https://pms.sustech.edu.cn"
PMS_API = f"{PMS_BASE}/api"

# PMS sits behind the SUSTech campus firewall. Off-campus (VPN or otherwise)
# requests get a 403 with a plain-text body before any auth runs.
# Detect it so callers/agents get an actionable error instead of a JSON
# decode crash. Shared with booking and (future) other submodules —
# canonical helpers live in ``sustech_survival.sso._offcampus``.
from sustech_survival.sso._offcampus import (
    OFF_CAMPUS_BODY,
    looks_off_campus as _looks_off_campus,
    off_campus_hint,
)

OFF_CAMPUS_HINT = off_campus_hint("PMS")


class PMSClient:
    """One client object for the SUSTech 联创 PMS cloud print system.

    Encapsulates session + all API operations. Construct with a session that
    has OSESSIONID set (use `PMSAuth` to obtain one). All operations are
    live HTTP calls — no local cache.
    """

    BASE_URL = PMS_BASE
    API_BASE = PMS_API

    # ── Construction ────────────────────────────────────────────────────────

    def __init__(self, session: requests.Session):
        self.session = session

    # ── Station queries (打印点) ─────────────────────────────────────────────

    def list_server_groups(self) -> List[ServerGroup]:
        """GET /client/Station/GetSrvList — the dropdown options on the page.

        Each group is a logical bucket (e.g. "OPMServer"); stations are
        filtered by `dwDevSN // 1000 == group.dwSN`.
        """
        r = self.session.get(f"{self.API_BASE}/client/Station/GetSrvList", timeout=10)
        data = self._unwrap(r)
        return [ServerGroup.from_api(g) for g in (data or [])]

    def list_stations(self, group_sn: Optional[int] = None) -> List[Station]:
        """GET /client/Station/GetList — all printers/copiers/scanners.

        If `group_sn` is given, filter to that server group (matches the
        dropdown filter on the page).
        """
        r = self.session.get(
            f"{self.API_BASE}/client/Station/GetList",
            params={"timestamp": "0"},
            timeout=15,
        )
        data = self._unwrap(r) or []
        stations = [Station.from_api(s) for s in data]
        if group_sn is not None:
            stations = [s for s in stations if s.server_group == group_sn]
        return stations

    # ── Print jobs (打印文档) ────────────────────────────────────────────────

    def list_print_jobs(self) -> List[PrintJob]:
        """GET /client/PrintJob/Get — documents uploaded but not yet printed."""
        r = self.session.get(
            f"{self.API_BASE}/client/PrintJob/Get",
            params={"timestamp": "0"},
            timeout=15,
        )
        data = self._unwrap(r) or []
        return [PrintJob.from_api(j) for j in data]

    def delete_print_job(self, job_id: int) -> bool:
        """POST /client/PrintJob/Del — delete an uploaded print job.

        The server expects `{dwJobId, dwOldJobId}` (both same value).
        """
        r = self.session.post(
            f"{self.API_BASE}/client/PrintJob/Del",
            data=json.dumps({"dwJobId": int(job_id), "dwOldJobId": int(job_id)}),
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        if _looks_off_campus(r):
            raise PMSError(OFF_CAMPUS_HINT)
        out = r.json()
        return out.get("code") == 0

    # ── Scan jobs (扫描文档) ────────────────────────────────────────────────

    def list_scan_jobs(self) -> List[ScanJob]:
        """GET /client/Scan/Get — scanned documents."""
        r = self.session.get(
            f"{self.API_BASE}/client/Scan/Get",
            params={"timestamp": "0"},
            timeout=15,
        )
        data = self._unwrap(r) or []
        return [ScanJob.from_api(j) for j in data]

    def delete_scan_job(self, job_id: int) -> bool:
        """POST /client/Scan/Del — delete a scan. Server expects `{dwJobId}`."""
        r = self.session.post(
            f"{self.API_BASE}/client/Scan/Del",
            data=json.dumps({"dwJobId": int(job_id)}),
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        if _looks_off_campus(r):
            raise PMSError(OFF_CAMPUS_HINT)
        out = r.json()
        return out.get("code") == 0

    # ── Usage records (使用记录) ────────────────────────────────────────────

    def history(
        self,
        *,
        begin: Optional[Union[date, str]] = None,
        end: Optional[Union[date, str]] = None,
        type: int = REPORT_TYPE_PRINT,
        page: int = 1,
        page_size: int = 5,
    ) -> tuple[List[UsageRecord], int]:
        """POST /client/Report/DetailPage — paginated usage records.

        Args:
            begin: start date (date object or "YYYY-MM-DD"/"YYYYMMDD" string).
                   Default: ~3 years ago (matches the page default).
            end:   end date. Default: today.
            type:  REPORT_TYPE_PRINT (1), REPORT_TYPE_SCAN (2), REPORT_TYPE_COPY (3).
            page:  1-indexed page number.
            page_size: rows per page (5 matches the page; max ~50).

        Returns:
            (records, total_pages).
        """
        begin_str = self._fmt_date(begin, default_days_back=365 * 3)
        end_str = self._fmt_date(end, default_days_back=0)

        body = {
            "dwBeginDate": begin_str,
            "dwEndDate": end_str,
            "dwType": int(type),
            "dwPageNo": int(page),
            "dwRowCount": int(page_size),
        }
        r = self.session.post(
            f"{self.API_BASE}/client/Report/DetailPage",
            data=json.dumps(body),
            headers={"Content-Type": "application/json"},
            timeout=15,
        )
        if _looks_off_campus(r):
            raise PMSError(OFF_CAMPUS_HINT)
        out = r.json()
        if out.get("code") != 0:
            raise PMSError(out.get("message", "Report/DetailPage failed"))
        records = [UsageRecord.from_api(x) for x in (out.get("result") or [])]
        total_pages = int(out.get("dwTotalPage") or 1)
        return records, total_pages

    # ── Cloud print upload (云打印) ─────────────────────────────────────────

    def upload_print(
        self,
        file_path: Union[str, Path],
        *,
        color: Union[int, str] = COLOR_BW,
        paper: Union[int, str] = PAPER_UNSPECIFIED,
        duplex: Union[int, str] = DUPLEX_SINGLE,
        page_from: int = 0,        # 0 = all pages (matches the form default)
        page_to: int = 0,          # ignored when page_from == 0
        copies: int = 1,
        dry_run: bool = False,
    ) -> "PrintUploadResult":
        """Upload a file to PMS for printing at any campus station.

        Args:
            file_path: local file to upload (PDF/doc/image).
            color:     COLOR_BW (1) / "bw" / "黑白"
                       COLOR_COLOR (2) / "color" / "彩色"
            paper:     PAPER_A4 (9) / "A4"
                       PAPER_A3 (8) / "A3"
                       PAPER_UNSPECIFIED (-1) / "不指定" / "" / "unspecified"
            duplex:    DUPLEX_SINGLE (1) / "single" / "单面"
                       DUPLEX_SHORT_EDGE (2) / "short" / "双面短边"
                       DUPLEX_LONG_EDGE (3) / "long" / "双面长边"
            page_from: 0 = all pages; otherwise the start page (1-indexed).
            page_to:   end page (1-indexed); ignored when page_from == 0.
            copies:    number of copies, 1+.
            dry_run:   if True, return the prepared form data without uploading.

        Returns:
            PrintUploadResult with `ok`, `message`, `code`, and the resolved
            numeric fields. When `dry_run=True`, `uploaded=False`.

        Cost note: uploading does NOT spend money — money is only deducted
        when the file is actually picked up at a physical printer. But it does
        create a record on your print queue that you may want to delete.
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(file_path)

        color_code = _coerce_color(color)
        paper_code = _coerce_paper(paper)
        duplex_code = _coerce_duplex(duplex)

        # The form submits dwFrom=0 for "all pages" and ignores dwTo.
        # For partial ranges, dwFrom=1 and dwTo=<end page>.
        if page_from == 0:
            dw_from, dw_to = 0, 0
        else:
            dw_from = max(1, int(page_from))
            dw_to = max(dw_from, int(page_to) if page_to else dw_from)

        copies = max(1, int(copies))

        result = PrintUploadResult(
            file_path=str(file_path),
            file_name=file_path.name,
            color=color_code,
            paper=paper_code,
            duplex=duplex_code,
            page_from=dw_from,
            page_to=dw_to,
            copies=copies,
            uploaded=False,
            ok=False,
            message="",
            code=None,
        )

        if dry_run:
            result.message = "DRY-RUN: prepared upload, did not POST"
            return result

        with open(file_path, "rb") as f:
            files = {"szPath": (file_path.name, f)}
            data = {
                "dwColor": str(color_code),
                "dwPaperId": str(paper_code),
                "dwDuplex": str(duplex_code),
                "dwFrom": str(dw_from),
                "dwTo": str(dw_to),
                "dwCopies": str(copies),
                "BackURL": "result.html",
            }
            r = self.session.post(
                f"{self.API_BASE}/client/CloudPrint/Upload",
                files=files,
                data=data,
                timeout=120,
            )

        # On success the response is a JSON body with code/message. On failure
        # the server may respond 413 (too big) or 200 with an error code.
        if r.status_code == 413:
            result.message = "File too large (HTTP 413)"
            return result
        try:
            out = r.json()
        except Exception:
            result.message = f"Non-JSON response: HTTP {r.status_code}"
            return result

        result.code = out.get("code")
        result.ok = (out.get("code") == 0)
        result.uploaded = result.ok
        result.message = out.get("message", "")
        return result

    # ── Helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def _unwrap(r: requests.Response):
        """Unwrap the standard {code, message, result} envelope.

        Detects PMS's off-campus 403 and raises a `PMSError` with an
        actionable hint instead of crashing on the non-JSON body.
        """
        if _looks_off_campus(r):
            raise PMSError(OFF_CAMPUS_HINT)
        try:
            out = r.json()
        except Exception:
            raise PMSError(
                f"Non-JSON response: HTTP {r.status_code} "
                f"(body: {(r.text or '')[:120]!r})"
            )
        if out.get("code") != 0:
            raise PMSError(out.get("message", f"code={out.get('code')}"))
        return out.get("result")

    @staticmethod
    def _fmt_date(d, *, default_days_back: int = 0) -> str:
        """Return YYYYMMDD string for a date / str / None input."""
        if d is None:
            today = date.today()
            from datetime import timedelta
            d = today - timedelta(days=default_days_back)
        if isinstance(d, str):
            s = d.replace("-", "").replace(".", "")
            if len(s) == 8 and s.isdigit():
                return s
            raise ValueError(f"Date string must be YYYY-MM-DD or YYYYMMDD: {d!r}")
        if isinstance(d, datetime):
            return d.strftime("%Y%m%d")
        if isinstance(d, date):
            return d.strftime("%Y%m%d")
        raise TypeError(f"Unsupported date type: {type(d)}")


# ── Result dataclass for upload_print ────────────────────────────────────────

@dataclass
class PrintUploadResult:
    file_path: str
    file_name: str
    color: int
    paper: int
    duplex: int
    page_from: int
    page_to: int
    copies: int
    uploaded: bool
    ok: bool
    message: str
    code: Optional[int]

    def to_markdown(self) -> str:
        if self.code is None and self.message.startswith("DRY-RUN"):
            flag = "🟡 DRY-RUN (no upload)"
        elif self.uploaded:
            flag = "✅ uploaded"
        else:
            flag = "❌ failed"
        return (
            f"### {self.file_name} — {flag}\n"
            f"- **Code**: {self.code}\n"
            f"- **Message**: {self.message or '—'}\n"
            f"- **Color**: {'黑白' if self.color == COLOR_BW else '彩色'}\n"
            f"- **Paper**: {paper_name(self.paper) or '不指定'}\n"
            f"- **Duplex**: {['', '单面', '双面短边', '双面长边'][self.duplex] if 1 <= self.duplex <= 3 else '—'}\n"
            f"- **Pages**: {'全部' if self.page_from == 0 else f'{self.page_from}-{self.page_to}'}\n"
            f"- **Copies**: {self.copies}\n"
        )


class PMSError(Exception):
    """Raised when PMS returns an error."""


# ── Coercion helpers ─────────────────────────────────────────────────────────

def _coerce_color(v) -> int:
    if isinstance(v, int):
        if v in (COLOR_BW, COLOR_COLOR):
            return v
        raise ValueError(f"Unknown color code: {v!r}")
    s = str(v).strip().lower()
    if s in ("bw", "black", "b&w", "黑白", "1"):
        return COLOR_BW
    if s in ("color", "彩色", "colour", "2"):
        return COLOR_COLOR
    raise ValueError(f"Unknown color: {v!r}")


def _coerce_paper(v) -> int:
    if isinstance(v, int):
        if v in (PAPER_A4, PAPER_A3, PAPER_UNSPECIFIED):
            return v
        raise ValueError(f"Unknown paper code: {v!r}")
    s = str(v).strip().upper()
    if s in ("A4", "9"):
        return PAPER_A4
    if s in ("A3", "8"):
        return PAPER_A3
    if s in ("", "不指定", "UNSPECIFIED", "NONE", "-1"):
        return PAPER_UNSPECIFIED
    raise ValueError(f"Unknown paper: {v!r}")


def _coerce_duplex(v) -> int:
    if isinstance(v, int):
        if v in (DUPLEX_SINGLE, DUPLEX_SHORT_EDGE, DUPLEX_LONG_EDGE):
            return v
        raise ValueError(f"Unknown duplex code: {v!r}")
    s = str(v).strip().lower()
    if s in ("single", "单面", "1"):
        return DUPLEX_SINGLE
    if s in ("short", "双面短边", "2"):
        return DUPLEX_SHORT_EDGE
    if s in ("long", "双面长边", "3"):
        return DUPLEX_LONG_EDGE
    raise ValueError(f"Unknown duplex: {v!r}")


# ── Module-level singleton (uses PMSAuth) ────────────────────────────────────

# The default singleton is built from the PMSAuth singleton. Users wanting
# a custom session should construct `PMSClient(session)` directly.
def _build_default_client() -> PMSClient:
    from sustech_survival.sso.authlib.pms import PMSAuth
    auth = PMSAuth()
    auth.ensure()  # login if needed
    return PMSClient(session=auth.session)


# Lazy singleton — only built on first attribute access, so importing this
# module never triggers a network call.
_pms_client: Optional[PMSClient] = None


def pms() -> PMSClient:
    """Module-level singleton PMSClient. Logs in on first call."""
    global _pms_client
    if _pms_client is None:
        _pms_client = _build_default_client()
    return _pms_client


# Re-export schema classes and constants at package level for convenience.
from .schema import (  # noqa: E402  (re-export)
    Station, ServerGroup, PrintJob, ScanJob, UsageRecord,
    PAPER_UNSPECIFIED, PAPER_A4, PAPER_A3,
    COLOR_BW, COLOR_COLOR,
    DUPLEX_SINGLE, DUPLEX_SHORT_EDGE, DUPLEX_LONG_EDGE,
    REPORT_TYPE_PRINT, REPORT_TYPE_SCAN, REPORT_TYPE_COPY,
)