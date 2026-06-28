"""
sustech_survival.tis.classroom.booking — TIS 场地借用 (Venue Borrowing) client.

A minimal client: check permission, create applications, check occupancy.
No dynamic CRUD — TIS borrow applications are write-once, wait-for-approval.

Usage::

    from sustech_survival.tis.classroom.booking import (
        venue_borrow,                 # singleton getter
        VenueBorrowClient,            # the client class
        BorrowError,                  # raised on any failure
    )
    from sustech_survival.tis.classroom.booking_schema import (
        BorrowApplication, BorrowDetail, BorrowTimeSlot,
        AuditStatus, PermissionResult, VenueOccupancySlot,
    )

    c = venue_borrow()
    c.ensure_session()

    # Check permission
    perm = c.check_permission("2025-2026", "2")
    print(perm.allowed)

    # Query occupancy before booking
    slots = c.query_venue_occupancy(xn="2025-2026", xq="2", room_codes=["YJ-123"])

    # Create a borrowing application (dry-run by default)
    form = BorrowApplication(
        applicant_name="段斯宸", ...,
        details=[BorrowDetail(room_code="YJ-123", ...)],
    )
    saved = c.create_borrow_application(form, dry_run=True)   # no network call
    saved = c.create_borrow_application(form, dry_run=False)  # actually commits

Known response-shape quirks (probed 2026-06-28):
  - yzkg returns bare text "1" or "0" (not JSON)
  - queryzcbykssjjssj returns a week bitmask, not start/end dates
  - queryJrjtrq returns null — don't rely on it
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import requests

from sustech_survival.classroom.live import LiveOccupancyClient, TIS_BASE
from .booking_schema import (
    AuditStatus,
    BorrowApplication,
    BorrowDetail,
    BorrowTimeSlot,
    PermissionResult,
    VenueOccupancySlot,
)


# ── Endpoint paths ────────────────────────────────────────────────────────────

EP_YZKG = f"{TIS_BASE}/cdjy/yzkg"
EP_SHZTLIST = f"{TIS_BASE}/cdjy/shztlist"
EP_OCCUPANCY = f"{TIS_BASE}/cdjy/queryChangDiZhanYongShiJian"
EP_CREATE = f"{TIS_BASE}/cdjy/addChangDiJieYongShenQing/1"

# Workflow code for 场地借用
WORKFLOW_CDJY = "CDJYLC"


# ── Errors ───────────────────────────────────────────────────────────────────


class BorrowError(RuntimeError):
    """Any failure from the TIS 场地借用 API or its auth flow."""


# ── Internal helpers ─────────────────────────────────────────────────────────


def _looks_off_campus(r: requests.Response) -> bool:
    try:
        from sustech_survival.sso._offcampus import looks_off_campus
        return looks_off_campus(r)
    except ImportError:
        return False


def _strip_envelope(payload) -> Any:
    """TIS responses use the Spring envelope {code:200, content: ...}."""
    if isinstance(payload, dict) and "content" in payload:
        return payload.get("content")
    return payload


def _extract_rows(content) -> list:
    """Extract the rows list from a TIS response content dict/list."""
    if isinstance(content, list):
        return content
    if isinstance(content, dict):
        rows = content.get("rows")
        if isinstance(rows, list):
            return rows
    return []


# ── Client ────────────────────────────────────────────────────────────────────


class VenueBorrowClient:
    """Minimal client for the TIS 场地借用 module.

    Three operations: check permission, create a new application, and query
    venue occupancy. No dynamic list/get/update/delete/submit — those are
    unnecessary for the write-once, wait-for-approval flow.
    """

    def __init__(
        self,
        *,
        session: Optional[requests.Session] = None,
        live_client: Optional[LiveOccupancyClient] = None,
    ):
        self._live_client = live_client
        self._sess = session

    # ── Session management ────────────────────────────────────────────────

    def ensure_session(self) -> requests.Session:
        """Return a logged-in TIS session. Cached after first call."""
        if self._sess is None:
            if self._live_client is not None:
                sess = self._live_client._ensure_session()
            else:
                self._live_client = LiveOccupancyClient()
                sess = self._live_client._ensure_session()
            self._sess = sess
        else:
            sess = self._sess
        sess.headers.setdefault("X-Requested-With", "XMLHttpRequest")
        sess.headers.setdefault("RoleCode", "00")
        return sess

    # ── Internal: API call ────────────────────────────────────────────────

    def _post(
        self, url: str, *, data: Optional[dict] = None, json_body: Optional[dict] = None
    ) -> Any:
        sess = self.ensure_session()
        try:
            if json_body is not None:
                r = sess.post(url, json=json_body, timeout=30)
            else:
                r = sess.post(url, data=data or {}, timeout=30)
        except requests.RequestException as e:
            raise BorrowError(f"Network error calling {url}: {e}") from e

        if _looks_off_campus(r):
            raise BorrowError(
                f"{url}: appears off-campus (SUSTech firewall 403). "
                "Connect to campus Wi-Fi or VPN and retry."
            )

        if r.status_code != 200:
            raise BorrowError(f"{url}: HTTP {r.status_code}, body={r.text[:200]!r}")

        try:
            return r.json()
        except (ValueError, json.JSONDecodeError):
            return r.text

    # ── Permission check ──────────────────────────────────────────────────

    def check_permission(self, xn: str, xq: str) -> PermissionResult:
        """Check if the current user is allowed to borrow venues this semester."""
        raw = self._post(EP_YZKG, data={"xn": xn, "xq": xq})
        return PermissionResult.from_api(raw)

    # ── Audit statuses (workflow reference) ────────────────────────────────

    def list_audit_statuses(self) -> List[AuditStatus]:
        """List the venue-borrowing workflow statuses."""
        raw = self._post(EP_SHZTLIST, data={"ywdm": WORKFLOW_CDJY})
        content = _strip_envelope(raw)
        return [AuditStatus.from_api(r) for r in _extract_rows(content)]

    # ── Venue occupancy (read availability) ────────────────────────────────

    def query_venue_occupancy(
        self,
        *,
        xn: str,
        xq: str,
        room_codes: Optional[List[str]] = None,
        weeks: Optional[List[int]] = None,
        weekday: Optional[int] = None,
    ) -> List[VenueOccupancySlot]:
        """Query what times are busy for a set of rooms.

        Use this BEFORE creating an application to find available slots.
        """
        body: Dict[str, Any] = {"xn": xn, "xq": xq}
        if room_codes:
            body["cddms"] = room_codes
        if weeks:
            body["zcs"] = weeks
        if weekday is not None:
            body["xqj"] = weekday
        raw = self._post(EP_OCCUPANCY, json_body=body)
        content = _strip_envelope(raw)
        return [VenueOccupancySlot.from_api(r) for r in _extract_rows(content)]

    # ── Create application (the one real action) ──────────────────────────

    def create_borrow_application(
        self,
        form: BorrowApplication,
        *,
        dry_run: bool = True,
    ) -> BorrowApplication:
        """Create a new venue-borrowing application.

        Defaults to dry_run per iron law. With dry_run=True, returns the
        serialized form without firing a network request. Pass dry_run=False
        to commit — the returned object has server-populated id and jhdh.

        Required fields (validate server-side, but typically):
            - applicant_name / applicant_phone
            - user_name / user_phone
            - semester (e.g. "2025-2026-2") OR xn + xq
            - headcount > 0
            - purpose (jyyy)
            - at least one BorrowDetail with room_code + time_slots
        """
        payload = form.to_api()
        if dry_run:
            return BorrowApplication.from_api(payload)
        raw = self._post(EP_CREATE, json_body=payload)
        if isinstance(raw, dict):
            code = raw.get("code")
            if code is not None:
                try:
                    if int(code) != 200:
                        raise BorrowError(
                            f"create borrow application: code={code} msg={raw.get('msg')!r}"
                        )
                except (ValueError, TypeError):
                    pass
        content = _strip_envelope(raw)
        return BorrowApplication.from_api(content) if content else form


# ── Singleton ─────────────────────────────────────────────────────────────────


def venue_borrow(
    *, live_client: Optional[LiveOccupancyClient] = None
) -> VenueBorrowClient:
    """Return a singleton VenueBorrowClient.

    Usage::

        from sustech_survival.tis.classroom.booking import venue_borrow
        c = venue_borrow()
        c.ensure_session()
        form = BorrowApplication(...)
        c.create_borrow_application(form, dry_run=True)
    """
    global _default_venue_borrow_client
    if _default_venue_borrow_client is None:
        _default_venue_borrow_client = VenueBorrowClient(
            live_client=live_client,
        )
    return _default_venue_borrow_client


_default_venue_borrow_client: Optional[VenueBorrowClient] = None


__all__ = [
    "VenueBorrowClient",
    "BorrowError",
    "venue_borrow",
    "WORKFLOW_CDJY",
    "EP_YZKG",
    "EP_SHZTLIST",
    "EP_OCCUPANCY",
    "EP_CREATE",
    "_strip_envelope",
    "_extract_rows",
]
