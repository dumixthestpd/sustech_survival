"""
sustech_survival.lib.booking.client — Live client for the IC library booking.

ONE class. ALL operations. ZERO local data (every call hits the live site).

Architecture mirrors `sustech_survival.booking.BookingClient` (ehall
35-venue) and `sustech_survival.pms.PMSClient`:

    LibBookingClient                   ← one client, all the methods
        .whoami()                          → auth/userInfo
        .home_summary()                    → home/page/room/idle
        .labs()                            → lab/devKindLabs
        .rooms(class_kind, kind_id, lab_id) → roomDevice/roomInfos
        .my_reservations(start, end)       → borrow/reserve/own
        .reservation_count()               → reserve/count
        .add_reservation(payload, dry_run) → reserve  (POST)
        .cancel_reservation(resv_id)       → reserve/delete  (POST)
        .resv_info(resv_id)                → reserve/resvInfo

Schema (`Room`, `Lab`, `Reservation`, `UserInfo`, ...) lives in
`schema.py` with classmethod `from_api()` parsers.

Auth is handled separately by `sustech_survival.lib.booking.auth.LibBookingAuth`.
This class is auth-agnostic — pass it any `requests.Session` that has
the `ic-cookie` set.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, List, Optional

import requests

from .schema import (
    CampusGroup,
    Lab,
    Reservation,
    Room,
    RoomIdleCategory,
    UserInfo,
    build_reservation_payload,
)
from sustech_survival.consequence import (
    Severity, Consequence, consequence_rich,
)


BOOKING_BASE = "https://booking.lib.sustech.edu.cn"
BOOKING_API = f"{BOOKING_BASE}/ic-web"

# Off-campus signal — SUSTech firewall returns the same plain-text body on
# 403 before any auth runs across all internal services. Canonical
# detection lives in `sustech_survival.sso._offcampus`.
from ...sso._offcampus import (
    OFF_CAMPUS_BODY,
    looks_off_campus as _looks_off_campus,
    off_campus_hint,
)

OFF_CAMPUS_HINT = off_campus_hint("IC library booking")

# Server-side auth-error messages that should trigger an auto-relogin.
# Captured during the 2026-06-29 probe.
AUTH_ERROR_MESSAGES = (
    "Authorization is NULL",
    "Authorization is invalid",
    "未登录",
    "请先登录",
    "用户未登录",
    "session 失效",
    "session 已失效",
)

# Default classKind — research rooms (讨论间 / 会议室 / etc.)
DEFAULT_CLASS_KIND = 1


class LibBookingError(RuntimeError):
    """Any failure from the IC library booking API or its auth flow."""


def _looks_auth_error(body: dict) -> bool:
    if body.get("code") == 0:
        return False
    msg = (body.get("message") or "").lower()
    return any(token.lower() in msg for token in AUTH_ERROR_MESSAGES)


def _looks_off_campus_response(r: requests.Response) -> bool:
    return _looks_off_campus(r)


class LibBookingClient:
    """One client object for the IC library booking system.

    Encapsulates session + all API operations. Construct with a session
    that has the `ic-cookie` set (use `LibBookingAuth` to obtain one).
    All operations are live HTTP calls — no local cache.
    """

    BASE_URL = BOOKING_BASE
    API_BASE = BOOKING_API

    # -- Construction --------------------------------------------------------

    def __init__(self, session: requests.Session, *, _auth=None):
        self.s = session
        # Optional handle to the LibBookingAuth singleton for auto-relogin
        # on auth-error responses. If None, errors propagate without retry.
        self._auth = _auth

    # -- Internal: API call with auth-error retry ---------------------------

    def _call(
        self, method: str, path: str, *, params: Optional[dict] = None,
        _is_retry: bool = False, json_body: Optional[dict] = None,
    ) -> Any:
        """Low-level API call. Returns the unwrapped `data` field on success.

        For read endpoints, use `params=` for query-string params. For
        write endpoints, use `json_body=` to send a JSON body with the
        proper Content-Type header.

        Raises `LibBookingError` on failure. On an auth-error response,
        re-runs the auth handshake once and retries — unless the caller
        is already the retry (which raises).
        """
        url = f"{BOOKING_API}{path}"
        kwargs = {"timeout": 10}
        if json_body is not None:
            kwargs["json"] = json_body
            # axios with JSON body sends this content-type
            kwargs.setdefault("headers", {})
            kwargs["headers"].setdefault("Content-Type", "application/json;charset=UTF-8")
        elif params is not None:
            kwargs["params"] = params
        try:
            r = self.s.request(method, url, **kwargs)
        except requests.RequestException as e:
            raise LibBookingError(f"HTTP {method} {path} failed: {e}") from e

        if _looks_off_campus_response(r):
            raise LibBookingError(OFF_CAMPUS_HINT)

        if r.status_code != 200:
            raise LibBookingError(
                f"HTTP {method} {path} returned {r.status_code}: {r.text[:200]}"
            )

        body = r.json()
        if _looks_auth_error(body):
            if _is_retry or not self._auth:
                raise LibBookingError(
                    f"Auth error from {method} {path}: {body.get('message')}"
                )
            # Auto-relogin + retry once
            try:
                self._auth.login_password(
                    self._auth.username, self._auth.password
                )
            except Exception as e:
                raise LibBookingError(f"Auto-relogin failed: {e}") from e
            # Re-apply cookies to session
            self.s.cookies.clear()
            for name, value in self._auth._session_cache.items():
                self.s.cookies.set(name, value)
            return self._call(method, path, params=params, json_body=json_body, _is_retry=True)

        if body.get("code") != 0:
            # Non-auth API error — propagate the message
            raise LibBookingError(
                f"API error from {method} {path}: "
                f"{body.get('message')} (code={body.get('code')})"
            )
        return body.get("data")

    # -- Read: whoami --------------------------------------------------------

    def whoami(self) -> UserInfo:
        """Return the current user's profile (from `auth/userInfo`)."""
        data = self._call("GET", "/auth/userInfo")
        return UserInfo.from_api(data)

    # -- Read: homepage summary ----------------------------------------------

    def home_summary(self) -> List[RoomIdleCategory]:
        """Return the homepage idle summary — 10 categories with idle counts.

        Source: `GET /home/page/room/idle`. No params needed.
        """
        data = self._call("GET", "/home/page/room/idle") or []
        return [RoomIdleCategory.from_api(r) for r in data]

    # -- Read: labs (楼层 / 区域) ---------------------------------------------

    def labs(self, class_kind: int = DEFAULT_CLASS_KIND) -> List[Lab]:
        """Return the list of labs for a given classKind.

        Source: `GET /lab/devKindLabs?classKind=1&kindIds=`.
        """
        data = self._call(
            "GET", "/lab/devKindLabs",
            params={"classKind": class_kind, "kindIds": ""},
        ) or []
        return [Lab.from_api(r) for r in data]

    # -- Read: rooms in a (kind, lab) ----------------------------------------

    def rooms(
        self,
        kind_id: int,
        lab_id: int,
        *,
        class_kind: int = DEFAULT_CLASS_KIND,
    ) -> List[CampusGroup]:
        """Return the full room inventory for a (kind, lab) pair.

        Source: `GET /roomDevice/roomInfos?classKind=1&kindId=...&labId=...`.

        Returns a list of `CampusGroup`s, each containing one or more
        `LabWithRooms`. Multiple campuses can appear (e.g. 涵泳讨论间 +
        一丹讨论间 are separate campus groups under the same kind).
        """
        data = self._call(
            "GET", "/roomDevice/roomInfos",
            params={"classKind": class_kind, "kindId": kind_id, "labId": lab_id},
        ) or []
        return [CampusGroup.from_api(c) for c in data]

    # -- Read: my reservations -----------------------------------------------

    def reservation_count(self) -> int:
        """Return the current reservation count for the logged-in user."""
        data = self._call("GET", "/reserve/count")
        return int(data or 0)

    def my_reservations(
        self,
        start: date,
        end: date,
        *,
        page: int = 1,
        page_size: int = 20,
        need_status: Optional[int] = None,
    ) -> List[Reservation]:
        """Return the current user's reservations between [start, end].

        Source: `GET /reserve/resvInfo?beginDate=...&endDate=...&page=...&pageNum=...`
        — the **same endpoint the SPA userinfo page hits** (verified by
        Playwright probe of /#/ic/userinfo on 2026-06-30).

        Wire shape (paginated list, rows in `data[]`):

            {
              "code": 0, "message": "查询成功",
              "data": [{resvId, uuid, testName, resvBeginTime, resvEndTime, ...}, ...],
              "count": N
            }

        Args:
            start, end: inclusive date range (date objects).
            page: 1-based page number.
            page_size: rows per page (server calls this `pageNum`).
            need_status: optional bitmask filter matching the SPA tabs —
                6 = 未开始 (default filter, upcoming), 4 = 已开始,
                16 = 已违约, 8 = 已结束. Pass None to get all statuses.

        Note: the OLD endpoint `GET /borrow/reserve/own` returns an
        empty list for this user — do not use it.
        """
        params = {
            "beginDate":  start.isoformat() if isinstance(start, date) else str(start),
            "endDate":    end.isoformat()   if isinstance(end,   date) else str(end),
            "page":    page,
            "pageNum": page_size,
            "orderKey":   "gmt_create",
            "orderModel": "desc",
        }
        if need_status is not None:
            params["needStatus"] = need_status
        data = self._call("GET", "/reserve/resvInfo", params=params)
        # `data` is a list directly (no rows/list wrapper)
        if isinstance(data, list):
            rows = data
        elif isinstance(data, dict):
            rows = data.get("data") or data.get("rows") or data.get("list") or []
        else:
            rows = []
        return [Reservation.from_api(r) for r in rows]

    def resv_info(self, resv_id: int) -> Optional[Reservation]:
        """Return the info for a single reservation.

        Source: `GET /reserve/resvInfo?beginDate=...&endDate=...&resvId=...`
        (verified 2026-06-30 — the endpoint requires a date range AND
        a resvId together; `resvId` alone returns an HTML error page).

        The date range is broad (last 30 days → next 365 days) since the
        server is strict about the window.

        Returns `None` if no row in the range has that resv_id.
        """
        today = date.today()
        from datetime import timedelta
        rows = self.my_reservations(
            start=today - timedelta(days=30),
            end=today + timedelta(days=365),
        )
        for r in rows:
            if r.resv_id == resv_id:
                return r
        return None

    # -- Write: create reservation (destructive — dry-run by default) --------

    @consequence_rich(Consequence(
        name="libbooking.add_reservation",
        severity=Severity.MEDIUM,
        irreversible=False,
        what_changes="Books a library room for the given time slot.",
        risk=("A wrongly-booked time/room persists; the system records "
              "misuse/penalties. Confirm the exact slot and co-applicants."),
        verify_url="{booking_base}/#/ic/booking",
    ))
    def add_reservation(
        self,
        *,
        dev_id: int,
        begin: datetime,
        end: datetime,
        title: str,
        class_kind: int = DEFAULT_CLASS_KIND,
        member_kind: int = 1,
        resv_member: Optional[List[int]] = None,
        memo: str = "",
        dry_run: bool = True,
        enforce_policy: bool = True,
    ) -> dict:
        """Create a reservation.

        `dry_run=True` (default) stages the payload, returns it as a dict,
        and exits without POSTing — the safe default.
        Set `dry_run=False` to actually commit.

        `enforce_policy=True` (default) validates against the library
        booking policy:
          - Max 2 days in advance (per "1.2 提前2天预约")
          - Max 2 hours per booking (per "1.2 每次最多2小时")
          - 3+ person rooms need 2+ co-applicants (per "1.3")

        The `dry_run=True` path does NOT enforce policy (you can stage
        any payload to inspect it). Set `enforce_policy=True` even with
        `dry_run=True` to validate without committing.

        The payload is built via `schema.build_reservation_payload` to
        match the verified wire shape (2026-06-29):
            POST /reserve
            params={
                sysKind, appAccNo, memberKind, resvMember,
                resvBeginTime, resvEndTime, testName,
                resvProperty, resvDev, memo,
            }
        The server echoes the created reservation in `data` on success.

        Requires `accNo` from whoami — the client auto-fetches it.

        Raises `LibBookingPolicyError` if a policy check fails (when
        `enforce_policy=True`).
        """
        me = self.whoami()
        payload = build_reservation_payload(
            acc_no=me.acc_no,
            dev_id=dev_id,
            begin=begin,
            end=end,
            title=title,
            class_kind=class_kind,
            member_kind=member_kind,
            resv_member=resv_member,
            memo=memo,
        )
        # -- Policy check --------------------------------------------------
        # For BOTH dry-run and commit paths: compute the warnings list
        # once, attach to the dry-run result, raise on commit. This
        # way dry-run ALWAYS stages the payload (you can inspect what
        # would be sent) — only the commit path refuses on policy
        # violations.
        policy_warnings: list = []
        if enforce_policy:
            policy_warnings = validate_against_policy(
                dev_id=dev_id, begin=begin, end=end,
                member_kind=member_kind, resv_member=resv_member,
                dev_name=self._dev_name(dev_id),
            )
        if dry_run:
            result: dict = {
                "__dry_run__": True,
                "payload": payload,
                "endpoint": "POST /reserve",
            }
            if policy_warnings:
                result["policy_warnings"] = [w.message for w in policy_warnings]
            return result
        # Commit path — block on policy errors
        if enforce_policy:
            errors = [w for w in policy_warnings if w.severity == "error"]
            if errors:
                raise LibBookingPolicyError(
                    "Policy violation — refusing to send the request:\n  " +
                    "\n  ".join(f"[{w.severity}] {w.message}" for w in policy_warnings)
                )
        result = self._call("POST", "/reserve", json_body=payload)
        # Cache the uuid so cancel_reservation can use it
        if isinstance(result, dict) and result.get("uuid"):
            self._last_resv_uuid = result["uuid"]
        if isinstance(result, dict) and result.get("resvId"):
            self._last_resv_id = result["resvId"]
        return result if result is not None else {}

    def _dev_name(self, dev_id: int) -> Optional[str]:
        """Best-effort lookup of a devId's display name (for policy checks).

        Walks the cached `roomDevice/roomInfos` inventory for the
        `classKind=1` (research rooms) + a small set of common lab
        pairs. Returns `None` if not found — the caller should treat
        `None` as "unknown, skip group-size check".
        """
        for lab_id in (1, 3, 4, 5, 6, 7, 8, 11, 12, 15):
            try:
                groups = self.rooms(kind_id=1, lab_id=lab_id)
            except Exception:
                continue
            for g in groups:
                for l in g.labs:
                    for r in l.rooms:
                        if r.dev_id == dev_id:
                            return r.dev_name
        return None

    # -- Write: cancel reservation (destructive — dry-run by default) --------

    @consequence_rich(Consequence(
        name="libbooking.cancel_reservation",
        severity=Severity.LOW,
        irreversible=True,
        what_changes="Cancels a library room reservation.",
        risk=("Cancellation is immediate and not reversible; if a no-show "
              "penalty rule applies, cancelling late may still incur it."),
        verify_url="{booking_base}/#/ic/userinfo",
    ))
    def cancel_reservation(
        self,
        resv_id: int = 0,
        *,
        uuid: str = "",
        dry_run: bool = True,
        enforce_policy: bool = True,
    ) -> dict:
        """Cancel a reservation.

        Two ways to call:
          - `cancel_reservation(uuid="abc...")`  — pass the uuid directly
            (from a previous create response or list call)
          - `cancel_reservation(resv_id=183442)`  — we'll look up the uuid
            via resv_info() automatically (1 extra HTTP call)

        `dry_run=True` (default) returns the staged request as a dict.
        Set `dry_run=False` to actually commit.

        `enforce_policy=True` (default) checks the 10-min cancellation
        deadline (per "1.6 提前10分钟取消"). If `now > begin - 10min`,
        raises `LibBookingPolicyError` (when committing) or returns
        a warning in the dry-run result.

        Source: `POST /reserve/delete` with JSON body `{"uuid": "..."}`.
        Verified live 2026-06-30: the server returns code=0 on success
        with `{"message": "删除成功"}`. The endpoint does NOT accept
        numeric resvId — only uuid.
        """
        # If uuid not given, look it up via resv_info (only if policy
        # checking is enabled, since that's the only reason we need
        # the begin_time from the lookup).
        # In dry_run mode, if we can't find the reservation we still
        # allow the dry-run (the caller wants to inspect the payload,
        # not commit). We only require a real uuid when committing.
        info: Optional[Reservation] = None
        lookup_attempted = False
        if not uuid and resv_id and enforce_policy:
            lookup_attempted = True
            try:
                info = self.resv_info(resv_id)
            except Exception:
                info = None
            if info is not None:
                uuid = info.uuid
        if not uuid and not dry_run:
            raise LibBookingError(
                f"Cannot find reservation {resv_id} to cancel "
                f"(may be outside the 30-day-back/365-day-forward window, "
                f"or policy lookup failed)"
            )
        if not uuid:
            # dry-run with unknown resv_id — use a placeholder so the
            # caller can still see the payload shape
            uuid = f"<resvId={resv_id}>"

        payload = {"uuid": uuid}

        # Policy check (reuse info from the uuid lookup if we have it)
        if enforce_policy:
            check = info
            # If we didn't lookup (uuid was given directly) and we have
            # a resv_id, do a fresh lookup for the policy check.
            if check is None and resv_id and not uuid and not lookup_attempted:
                try:
                    check = self.resv_info(resv_id)
                except Exception:
                    check = None
            if check and check.begin_time:
                warnings = validate_cancellation_timing(check.begin_time)
                if dry_run:
                    errors_present = any(w.severity == "error" for w in warnings)
                else:
                    errors_present = True  # any warning blocks the commit
                if errors_present and warnings:
                    if not dry_run:
                        raise LibBookingPolicyError(
                            "Cancellation too late — refusing to send:\n  " +
                            "\n  ".join(f"[{w.severity}] {w.message}" for w in warnings)
                        )
                    # dry-run: stash the warnings for the caller to inspect
                    result_warnings = [w.message for w in warnings]
                else:
                    result_warnings = None
            else:
                result_warnings = None
        else:
            result_warnings = None

        if dry_run:
            result: dict = {
                "__dry_run__": True,
                "payload": payload,
                "endpoint": "POST /reserve/delete",
            }
            if result_warnings:
                result["policy_warnings"] = result_warnings
            return result
        result = self._call("POST", "/reserve/delete", json_body=payload)
        return result if result is not None else {}


# -- Policy enforcement (per "讨论间使用办法" 2026-06-29) -----------------


class LibBookingPolicyError(LibBookingError):
    """Raised when a booking operation violates the library policy.

    Subclasses `LibBookingError` so existing error handlers catch it
    transparently. Distinguishable by isinstance check when needed.
    """


@dataclass
class PolicyWarning:
    """One policy check result. `severity` is "warning" (advisory) or
    "error" (blocks the request)."""
    severity: str
    message: str


def _is_3plus_person_room(dev_name: Optional[str]) -> Optional[bool]:
    """Heuristic: detect if a room is "1-3人" (no group) or "3+人" (needs group).

    The room's display name includes the capacity, e.g. "C105（1-3人）"
    or "G104（3-10人）". Returns `True` for 3+ person rooms (where the
    minimum capacity is 3+), `False` for 1-3 person rooms, `None` if
    the name doesn't carry the marker.

    A "1-3人" room can hold 1, 2, or 3 people — not a 3+ person room
    per policy 1.3 (which requires 2+ co-applicants for the 3+
    category). The check is on the LOWER bound.
    """
    if not dev_name:
        return None
    # Patterns: "（1-3人）", "（3-6人）", "（3-10人）"
    m = re.search(r"（(\d+)-(\d+)人）", dev_name)
    if m:
        lo = int(m.group(1))
        # 3+ person room if the MINIMUM capacity is 3 or more.
        # "（1-3人）" is 1-3 (not 3+). "（3-6人）" is 3+ (yes).
        return lo >= 3
    m = re.search(r"（(\d+)人以上）", dev_name)
    if m:
        # "（3人以上）" or "（4人以上）" — directly indicates minimum
        return int(m.group(1)) >= 3
    return None


def validate_against_policy(
    *,
    dev_id: int,
    begin: datetime,
    end: datetime,
    member_kind: int,
    resv_member: Optional[List[int]],
    dev_name: Optional[str] = None,
    now: Optional[datetime] = None,
) -> List[PolicyWarning]:
    """Validate a reservation against the library booking policy.

    Returns a list of `PolicyWarning`s. The caller decides whether
    warnings are advisory or blocking based on `severity`.

    Policy (per "讨论间使用办法" 1.2-1.6):
      - 1.2: max 2 days in advance
      - 1.2: max 2 hours per booking
      - 1.3: 3+ person rooms need 2+ co-applicants (resv_member >= 3)
    """
    warnings: List[PolicyWarning] = []
    now = now or datetime.now()

    # -- 1.2: max 2 days in advance --------------------------------------
    delta = begin - now
    if delta.total_seconds() > 2 * 24 * 3600:
        warnings.append(PolicyWarning(
            "error",
            f"Booking is {delta.days}d {delta.seconds // 3600}h ahead; "
            f"library policy 1.2 limits advance booking to 2 days.",
        ))
    elif delta.total_seconds() < 0:
        warnings.append(PolicyWarning(
            "warning",
            f"Booking begin time is in the past ({begin}); "
            f"the server will likely reject it.",
        ))

    # -- 1.2: max 2 hours per booking ------------------------------------
    duration = end - begin
    if duration.total_seconds() > 2 * 3600:
        hours = duration.total_seconds() / 3600
        warnings.append(PolicyWarning(
            "error",
            f"Booking is {hours:.1f}h long; library policy 1.2 limits "
            f"each reservation to 2 hours.",
        ))
    elif duration.total_seconds() <= 0:
        warnings.append(PolicyWarning(
            "error",
            f"Booking duration is non-positive ({duration}); "
            f"end must be after begin.",
        ))

    # -- 1.3: 3+ person rooms need 2+ co-applicants ----------------------
    is_3plus = _is_3plus_person_room(dev_name)
    if is_3plus is True:
        members = resv_member or []
        if len(members) < 3:  # booker + 2 co-applicants
            warnings.append(PolicyWarning(
                "error",
                f"Room '{dev_name}' is a 3+ person room; library policy 1.3 "
                f"requires booker + 2+ co-applicants (total {len(members)} given). "
                f"Pass --member-kind 2 and a list of accNos in --resv-member.",
            ))
    elif is_3plus is False and member_kind != 1:
        # 1-3 person room with group booking — usually fine but warn
        warnings.append(PolicyWarning(
            "warning",
            f"Room '{dev_name}' is for 1-3 people; group booking "
            f"(memberKind={member_kind}) is allowed but not required.",
        ))

    # -- 1.6: cancellation deadline (10 min before start) --------------
    # This is enforced in `cancel_reservation`, not here. But we can
    # still warn at create-time if the user creates a reservation
    # they wouldn't be able to cancel in time. The condition is:
    # begin - now < 10 min (i.e. the user will not be able to cancel
    # 10 min before start because the booking starts too soon).
    minutes_to_start = (begin - now).total_seconds() / 60
    if 0 <= minutes_to_start < 10:
        warnings.append(PolicyWarning(
            "warning",
            f"Only {minutes_to_start:.1f} minutes until booking start; "
            f"per policy 1.6, you will not be able to cancel this reservation "
            f"after it begins. (10-minute cancellation deadline.)",
        ))

    return warnings


def validate_cancellation_timing(
    begin: datetime,
    now: Optional[datetime] = None,
) -> List[PolicyWarning]:
    """Validate a cancellation against the 10-min cancellation deadline.

    Per policy 1.6: cancellation must happen >= 10 minutes BEFORE the
    reservation start time. If we cross the deadline:
      - 0 < minutes_to_start < 10: error (cancelling now would violate
        the policy AND the server will likely reject it)
      - minutes_to_start < 0: the reservation has already started; the
        server has different semantics (use endReserve for early end
        instead, not cancel). Warn.
    """
    warnings: List[PolicyWarning] = []
    now = now or datetime.now()
    minutes_to_start = (begin - now).total_seconds() / 60

    if minutes_to_start < 0:
        warnings.append(PolicyWarning(
            "warning",
            f"Reservation has already started (begin={begin}, now={now}); "
            f"use the 'end early' endpoint (POST /reserve/endReserve) "
            f"instead of cancel.",
        ))
    elif minutes_to_start < 10:
        warnings.append(PolicyWarning(
            "error",
            f"Only {minutes_to_start:.1f} minutes until reservation start; "
            f"library policy 1.6 requires cancellation at least 10 minutes "
            f"before start time. Cancelling now will likely be rejected by "
            f"the server AND marks a policy violation.",
        ))

    return warnings


# -- Singleton getter ---------------------------------------------------------


_BOOKING_INSTANCE: Optional[LibBookingClient] = None


def lib_booking() -> LibBookingClient:
    """Return a singleton `LibBookingClient`, lazily auto-authenticating.

    On first call, runs `LibBookingAuth.ensure()` and wraps the resulting
    session. Subsequent calls reuse the same instance.
    """
    global _BOOKING_INSTANCE
    if _BOOKING_INSTANCE is not None:
        return _BOOKING_INSTANCE

    from .auth import LibBookingAuth

    auth = LibBookingAuth()
    ok, reason = auth.ensure()
    if not ok:
        raise LibBookingError(
            f"IC library booking auth failed: {reason}. "
            f"Make sure credentials.txt is set and you're on campus Wi-Fi."
        )

    sess = requests.Session()
    sess.headers["User-Agent"] = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    sess.headers["X-Requested-With"] = "XMLHttpRequest"
    sess.headers["Content-Type"] = "application/json; charset=UTF-8"
    sess.headers["Accept"] = "application/json, text/javascript, */*; q=0.01"
    # Apply the ic-cookie (and any TGC) from the auth session. We set
    # the domain to a wildcard ".sustech.edu.cn" so cookies apply to
    # all subdomains (booking.lib, cas, etc.) — the TGC cookie lives
    # at cas.sustech.edu.cn and is forwarded by authcenter.
    for name, value in auth._session_cache.items():
        if name == "ic-cookie":
            sess.cookies.set(name, value, domain="booking.lib.sustech.edu.cn", path="/")
        elif name == "TGC":
            sess.cookies.set(name, value, domain="cas.sustech.edu.cn", path="/")
        else:
            sess.cookies.set(name, value, domain=".sustech.edu.cn", path="/")

    _BOOKING_INSTANCE = LibBookingClient(sess, _auth=auth)
    return _BOOKING_INSTANCE
