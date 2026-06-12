"""
sustech_survival.pms — Live client for the SUSTech 联创 PMS cloud print system.

ONE client class, FIVE record types, ZERO local data.

Public API:
    from sustech_survival.pms import pms, PMSClient, Station, PrintJob, ScanJob, UsageRecord, ...

Singleton:
    pms() — returns a PMSClient. Logs in automatically via PMSAuth on first call.

Schema (all live-parsed via `from_api()` classmethods):
    Station      — printer/copier/scanner on campus
    ServerGroup  — dropdown group on the print-points page
    PrintJob     — uploaded-but-not-yet-printed document
    ScanJob      — scanned document
    UsageRecord  — one line in the usage-records table

Constants (re-exported from schema):
    PAPER_A4, PAPER_A3, PAPER_UNSPECIFIED
    COLOR_BW, COLOR_COLOR
    DUPLEX_SINGLE, DUPLEX_SHORT_EDGE, DUPLEX_LONG_EDGE
    REPORT_TYPE_PRINT, REPORT_TYPE_SCAN, REPORT_TYPE_COPY

Auth: handled by `sustech_survival.sso.authlib.pms.PMSAuth`. The singleton
auto-auths on first call.
"""
from __future__ import annotations

from .pms import (
    PMSClient, PMSError, PrintUploadResult,
    pms,
    _coerce_color, _coerce_paper, _coerce_duplex,
)
from .schema import (
    Station, ServerGroup, PrintJob, ScanJob, UsageRecord,
    PAPER_UNSPECIFIED, PAPER_A4, PAPER_A3,
    COLOR_BW, COLOR_COLOR,
    DUPLEX_SINGLE, DUPLEX_SHORT_EDGE, DUPLEX_LONG_EDGE,
    REPORT_TYPE_PRINT, REPORT_TYPE_SCAN, REPORT_TYPE_COPY,
    paper_name, paper_id,
)


__all__ = [
    # Client
    "PMSClient", "PMSError", "PrintUploadResult", "pms",
    # Schema
    "Station", "ServerGroup", "PrintJob", "ScanJob", "UsageRecord",
    # Constants
    "PAPER_UNSPECIFIED", "PAPER_A4", "PAPER_A3",
    "COLOR_BW", "COLOR_COLOR",
    "DUPLEX_SINGLE", "DUPLEX_SHORT_EDGE", "DUPLEX_LONG_EDGE",
    "REPORT_TYPE_PRINT", "REPORT_TYPE_SCAN", "REPORT_TYPE_COPY",
    "paper_name", "paper_id",
]