"""
bb result — Result type for BB submission operations.

Replaces the previous (ok: bool | None, message: str) tuple. The old shape had
three problems:
  1. ok=None was a magic "DUPLICATE detected" sentinel — type-checker blind,
     callers had to remember to handle it.
  2. All structured data (destinationUrl, attempt_id, link_titles, row_count,
     staged_path, confirmation_uuid) was flattened into a free-text string.
  3. Adding a new field silently truncated unpacking callers.

SubmitResult is a frozen dataclass with an explicit status enum. Backwards-
compatible: still truthy/falsy (True ⇔ status ∈ {SUCCESS, DRY_RUN}).

Design notes:
  - `status` is a string enum so it serializes to JSON cleanly.
  - `__bool__` returns True iff the operation is in a successful state.
  - `is_duplicate` is a property so callers can use `match result.status` for
    exhaustive checking without losing the convenience of `if result.is_duplicate:`.
  - `message` is always set (best-effort human-readable summary).
  - `diagnostics` is a free-form dict for any extras a specific code path wants
    to surface (HTTP status, BB destinationUrl, etc.).
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Optional


class SubmitStatus(str, Enum):
    """Terminal states of a BB submission attempt.

    Values are lowercase strings so they serialize/deserialize cleanly via JSON
    and roundtrip through `str(SubmitStatus.SUCCESS) == "success"`.
    """
    SUCCESS = "success"           # submitted; BB accepted the attempt
    FAILURE = "failure"           # could not submit; see message + diagnostics
    DUPLICATE = "duplicate"       # dedup check found a prior attempt with same file
    LATE_BLOCKED = "late_blocked" # deadline passed; force_late=False
    DRY_RUN = "dry_run"           # would-have-submitted, did not actually submit

    @property
    def is_ok(self) -> bool:
        """True if this status represents a successful (or would-have-been) submit."""
        return self in (SubmitStatus.SUCCESS, SubmitStatus.DRY_RUN)


@dataclass(frozen=True)
class SubmitResult:
    """Result of a BB submission attempt.

    Immutable. Use `with_message(...)`, `with_diagnostic(...)`, etc. if you
    need to derive a new result (the frozen dataclass forbids mutation).

    Common usage:
        result = submit_assignment_rest(...)
        if result:
            print(f"Submitted: {result.destination_url}")
        elif result.is_duplicate:
            print("Already submitted; passing --skip-dedup to override")
        else:
            print(f"Failed: {result.message}")

    The old API (ok, msg) is preserved by `result.to_tuple()` for any caller
    we haven't migrated yet.
    """
    status: SubmitStatus
    message: str = ""
    destination_url: Optional[str] = None
    attempt_id: Optional[str] = None
    confirmation_uuid: Optional[str] = None
    staged_path: Optional[Path] = None
    link_titles: tuple[str, ...] = ()
    row_count: int = 0
    diagnostics: dict[str, Any] = field(default_factory=dict)

    # ── Convenience properties ────────────────────────────────────────────

    @property
    def ok(self) -> bool:
        """True if status is SUCCESS or DRY_RUN. For the legacy `result.ok` API."""
        return self.status.is_ok

    @property
    def is_duplicate(self) -> bool:
        return self.status == SubmitStatus.DUPLICATE

    @property
    def is_dry_run(self) -> bool:
        return self.status == SubmitStatus.DRY_RUN

    # ── Pythonic protocol hooks ────────────────────────────────────────────

    def __bool__(self) -> bool:
        """`if result:` is True for SUCCESS/DRY_RUN. Use `is_duplicate` for the
        dedup case, `match result.status` for exhaustive handling."""
        return self.ok

    # ── Backwards compat ──────────────────────────────────────────────────

    def to_tuple(self) -> tuple:
        """Migrate old `(ok, msg)` callers: `ok=bool`, `msg=str(message)`.

        Note: this loses the dedup signal (collapses to False). Prefer the
        dataclass fields. Use this only as a transitional shim.
        """
        # DUPLICATE → None (old magic value), LATE_BLOCKED → False,
        # SUCCESS/DRY_RUN → True, FAILURE → False
        if self.status == SubmitStatus.DUPLICATE:
            return None, self.message
        if self.status == SubmitStatus.LATE_BLOCKED:
            return False, self.message
        return self.ok, self.message

    def to_dict(self) -> dict:
        """JSON-serializable view. `staged_path` → str if present."""
        d = asdict(self)
        if self.staged_path is not None:
            d["staged_path"] = str(self.staged_path)
        d["status"] = self.status.value
        return d

    # ── Derive new result (frozen → use these instead of mutation) ────────

    def with_message(self, msg: str) -> "SubmitResult":
        return SubmitResult(
            status=self.status, message=msg,
            destination_url=self.destination_url, attempt_id=self.attempt_id,
            confirmation_uuid=self.confirmation_uuid, staged_path=self.staged_path,
            link_titles=self.link_titles, row_count=self.row_count,
            diagnostics=dict(self.diagnostics),
        )

    def with_diagnostic(self, key: str, value: Any) -> "SubmitResult":
        d = dict(self.diagnostics)
        d[key] = value
        return SubmitResult(
            status=self.status, message=self.message,
            destination_url=self.destination_url, attempt_id=self.attempt_id,
            confirmation_uuid=self.confirmation_uuid, staged_path=self.staged_path,
            link_titles=self.link_titles, row_count=self.row_count,
            diagnostics=d,
        )


# ── Factory helpers ────────────────────────────────────────────────────────

def success(
    message: str = "",
    *,
    destination_url: Optional[str] = None,
    attempt_id: Optional[str] = None,
    confirmation_uuid: Optional[str] = None,
    staged_path: Optional[Path] = None,
    link_titles: tuple[str, ...] = (),
    row_count: int = 0,
    **diagnostics: Any,
) -> SubmitResult:
    """Build a SUCCESS SubmitResult. All fields except status/message are kwargs."""
    return SubmitResult(
        status=SubmitStatus.SUCCESS,
        message=message,
        destination_url=destination_url,
        attempt_id=attempt_id,
        confirmation_uuid=confirmation_uuid,
        staged_path=staged_path,
        link_titles=link_titles,
        row_count=row_count,
        diagnostics=dict(diagnostics),
    )


def failure(message: str, **diagnostics: Any) -> SubmitResult:
    """Build a FAILURE SubmitResult. Diagnostics kwargs go into diagnostics dict."""
    return SubmitResult(
        status=SubmitStatus.FAILURE,
        message=message,
        diagnostics=dict(diagnostics),
    )


def duplicate(message: str, **diagnostics: Any) -> SubmitResult:
    return SubmitResult(
        status=SubmitStatus.DUPLICATE,
        message=message,
        diagnostics=dict(diagnostics),
    )


def late_blocked(message: str, **diagnostics: Any) -> SubmitResult:
    return SubmitResult(
        status=SubmitStatus.LATE_BLOCKED,
        message=message,
        diagnostics=dict(diagnostics),
    )


def dry_run(
    message: str = "",
    *,
    staged_path: Optional[Path] = None,
    link_titles: tuple[str, ...] = (),
    row_count: int = 0,
    **diagnostics: Any,
) -> SubmitResult:
    return SubmitResult(
        status=SubmitStatus.DRY_RUN,
        message=message,
        staged_path=staged_path,
        link_titles=link_titles,
        row_count=row_count,
        diagnostics=dict(diagnostics),
    )


__all__ = [
    "SubmitStatus",
    "SubmitResult",
    "success", "failure", "duplicate", "late_blocked", "dry_run",
]
