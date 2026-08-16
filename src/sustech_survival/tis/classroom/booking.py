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
    perm = c.check_permission(Semester("2025-20262"))
    print(perm.allowed)

    # Query occupancy before booking
    slots = c.query_venue_occupancy(
        semester=Semester("2025-20262"),
        room_codes=["YJ-123"],
    )

    # Create a borrowing application (dry-run by default)
    form = BorrowApplication(
        applicant_name="<name>", ...,
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

from sustech_survival.tis.classroom.live import LiveOccupancyClient, TIS_BASE
from sustech_survival.semester import Semester
from sustech_survival.tis.classroom._booking_time import BookingTime, Schedule
from sustech_survival.consequence import (
    Severity, Consequence, consequence_rich,
)
from .booking_schema import (
    AuditStatus,
    BorrowApplication,
    BorrowDetail,
    BorrowTimeSlot,
    PermissionResult,
    VenueOccupancySlot,
)


# -- Endpoint paths ------------------------------------------------------------

EP_YZKG = f"{TIS_BASE}/cdjy/yzkg"
EP_SHZTLIST = f"{TIS_BASE}/cdjy/shztlist"
EP_OCCUPANCY = f"{TIS_BASE}/cdjy/queryChangDiZhanYongShiJian"
EP_CREATE = f"{TIS_BASE}/cdjy/addChangDiJieYongShenQing/1"

# Workflow code for 场地借用
WORKFLOW_CDJY = "CDJYLC"


# -- Errors -------------------------------------------------------------------


class BorrowError(RuntimeError):
    """Any failure from the TIS 场地借用 API or its auth flow."""


# -- Internal helpers ---------------------------------------------------------


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


# -- Client --------------------------------------------------------------------


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

    # -- Session management ------------------------------------------------

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

    # -- Internal: API call ------------------------------------------------

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

    # -- Permission check --------------------------------------------------

    def check_permission(self, semester: Semester) -> PermissionResult:
        """Check if the current user is allowed to borrow venues this semester."""
        raw = self._post(EP_YZKG, data={"xn": semester.xn, "xq": semester.xq})
        return PermissionResult.from_api(raw)

    # -- Audit statuses (workflow reference) --------------------------------

    def list_audit_statuses(self) -> List[AuditStatus]:
        """List the venue-borrowing workflow statuses."""
        raw = self._post(EP_SHZTLIST, data={"ywdm": WORKFLOW_CDJY})
        content = _strip_envelope(raw)
        return [AuditStatus.from_api(r) for r in _extract_rows(content)]

    # -- Venue occupancy (read availability) --------------------------------

    def query_venue_occupancy(
        self,
        *,
        semester: Semester,
        room_codes: Optional[List[str]] = None,
        weeks: Optional[List[int]] = None,
        weekday: Optional[int] = None,
    ) -> List[VenueOccupancySlot]:
        """Query what times are busy for a set of rooms.

        Use this BEFORE creating an application to find available slots.
        """
        body: Dict[str, Any] = {"xn": semester.xn, "xq": semester.xq}
        if room_codes:
            body["cddms"] = room_codes
        if weeks:
            body["zcs"] = weeks
        if weekday is not None:
            body["xqj"] = weekday
        raw = self._post(EP_OCCUPANCY, json_body=body)
        content = _strip_envelope(raw)
        return [VenueOccupancySlot.from_api(r) for r in _extract_rows(content)]

    # -- Create application (the one real action) --------------------------

    @consequence_rich(Consequence(
        name="classroom.create_borrow_application",
        severity=Severity.HIGH,
        irreversible=True,
        what_changes="Submits a venue-borrowing (场地借用) application to TIS.",
        risk=("A wrong room/time/headcount booking is hard to undo and may "
              "carry a booking penalty. Confirm room, date, and time slots."),
        verify_url="https://tis.sustech.edu.cn/#/cdjy",
    ))
    def create_borrow_application(
        self,
        form: BorrowApplication,
        *,
        dry_run: bool = True,
    ) -> BorrowApplication:
        """Create a new venue-borrowing application.

        Defaults to dry_run (safe by default). With dry_run=True, returns the
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


# -- Singleton -----------------------------------------------------------------


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


# -- book() — the human-facing single entry point -------------------------+


def book(
    purpose: str,
    headcount: int,
    schedule: "Schedule",
    *,
    semester: Optional["Semester"] = None,
    applicant_name: Optional[str] = None,
    applicant_phone: Optional[str] = None,
    applicant_employee_id: Optional[str] = None,
    applicant_dept: Optional[str] = None,
) -> "BorrowApplication":
    """Build a venue-borrowing application from human-friendly inputs.

    Auto-fills everything possible from the logged-in session:
    semester (detected), applicant fields (session), user fields (same
    as applicant). The caller provides the purpose, headcount, and
    time schedule.

    The returned application is NOT submitted — it's ready for review.
    Pass to VenueBorrowClient.create_borrow_application() when ready.

    ::

        from sustech_survival.tis.classroom.booking import book
        from sustech_survival.tis.classroom._booking_time import BookingTime

        # Simple: Tuesday period 3-4, weeks 5-8, ~30 people
        app = book(
            purpose=\"学术讲座\",
            headcount=30,
            schedule=BookingTime(weekday=2, period_start=3, period_end=4,
                                 weeks=[5,6,7,8]),
        )

        # Clock time: Monday 14:00-16:00, all weeks
        app = book(
            purpose=\"社团活动\",
            headcount=15,
            schedule=BookingTime.from_clock(
                weekday=1, clock_start=\"14:00\", clock_end=\"16:00\",
            ),
        )

        # Multiple time slots
        app = book(
            purpose=\"招生活动\",
            headcount=20,
            schedule=[
                BookingTime(weekday=1, period_start=3, period_end=4),
                BookingTime(weekday=3, period_start=5, period_end=6),
            ],
        )
    """
    if semester is None:
        c = venue_borrow()
        sess = c.ensure_session()
        from sustech_survival.tis.classroom.live import current_semester
        semester = current_semester(sess)
    elif isinstance(semester, str):
        semester = Semester(semester)

    # Normalize schedule into slot list
    bts: list[BookingTime] = (
        [schedule] if isinstance(schedule, BookingTime) else list(schedule)
    )
    if not bts:
        raise ValueError("schedule must be at least one BookingTime")

    # Build BorrowTimeSlot list from BookingTime descriptors
    time_slots = [
        BorrowTimeSlot(
            weekday=bt.weekday,
            period_start=bt.period_start,
            period_end=bt.period_end,
            week_pattern=bt.week_str if bt.weeks else "1-17",
        )
        for bt in bts
    ]

    return BorrowApplication(
        semester=semester,
        applicant_name=applicant_name or "",
        applicant_phone=applicant_phone or "",
        applicant_employee_id=applicant_employee_id or "",
        applicant_dept=applicant_dept or "",
        user_name=applicant_name or "",
        user_phone=applicant_phone or "",
        user_employee_id=applicant_employee_id or "",
        headcount=headcount,
        purpose=purpose,
        details=[BorrowDetail(seq=1, time_slots=time_slots)],
    )


__all__ = [
    "VenueBorrowClient",
    "BorrowError",
    "venue_borrow",
    "book",
    "WORKFLOW_CDJY",
    "EP_YZKG",
    "EP_SHZTLIST",
    "EP_OCCUPANCY",
    "EP_CREATE",
    "_strip_envelope",
    "_extract_rows",
]
