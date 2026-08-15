"""
sustech_survival.consequence — the consequence-rich safety contract.

Every operation that mutates a student's real state on a SUSTech system is
"consequence-rich": a booking, a course drop, a BB submission, a PMS upload,
an evaluation, a bid submission. The user directive (2026-08) is:

  1. The *module* carries a short structured note that an operation is
     consequence-rich (a `Consequence` descriptor) so a CLI/agent can surface
     the risk before acting.
  2. A consequence-rich operation must be gated by an explicit confirmation
     step before it fires (`require_confirmation`), and report what it did +
     a verification URL after.
  3. The full human-readable risk explanation lives in the skill tree (the
     "sustech" skill), not in the module — this module only tags it.

This module is the single registry. It defines:

  - ``Consequence`` — descriptor of one risky operation.
  - ``consequence_rich`` — decorator that tags a write method
    (lowercase, like ``@dataclass``). ``CONSEQUENCE_RICH`` is a
    backwards-compatible alias.
  - ``consequence_of(method)`` — read back the descriptor.
  - ``require_confirmation`` — the CLI confirmation gate.

It carries no personal data and is framework-agnostic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional


class Severity(str, Enum):
    """How bad a mistake can be."""
    LOW = "low"              # reversible, cheap to undo
    MEDIUM = "medium"        # reversible but costly / easy to lose a slot
    HIGH = "high"            # hard to reverse; may lose a resource permanently
    CRITICAL = "critical"    # mostly irreversible; real academic/financial impact


@dataclass(frozen=True)
class Consequence:
    """Structured description of one consequence-rich operation.

    Attributes:
        name:         stable key, e.g. "selectcourse.drop_course"
        severity:     a :class:`Severity`.
        irreversible: True if undoing it is not guaranteed.
        what_changes: short "what changes on the platform" (one line).
        risk:         short human note of what the user stands to lose.
        verify_url:   optional template for a page the user can open to check.
                      Use ``{...}`` placeholders (e.g. ``{xn}-{xq}-{rwh}``).
        read_back:    optional endpoint name used to confirm after writing.
        docs:         optional pointer to the skill text that explains it fully.
        notes:        extra free-text (agent guidance).
    """

    name: str
    severity: Severity
    irreversible: bool = False
    what_changes: str = ""
    risk: str = ""
    verify_url: Optional[str] = None
    read_back: Optional[str] = None
    docs: Optional[str] = None
    notes: str = ""

    def prompt(self) -> str:
        """One to two lines a CLI/agent should show before confirming."""
        flag = "IRREVERSIBLE" if self.irreversible else "CARE"
        line = f"[{flag} / {self.severity.value}] {self.what_changes}"
        if self.risk:
            line += f"\n  Risk: {self.risk}"
        return line


# ── Registry ───────────────────────────────────────────────────────────────
# method -> Consequence. Populated by the CONSEQUENCE_RICH decorator.

_REGISTRY: dict[Callable, Consequence] = {}

# Allow lookup by name (e.g. `sustech consequence show <name>`).
_NAME_REGISTRY: dict[str, Consequence] = {}


def _register_name(consequence: Consequence) -> None:
    _NAME_REGISTRY[consequence.name] = consequence


def consequence_of(func: Callable) -> Optional[Consequence]:
    """Return the :class:`Consequence` tagged on ``func``, or None."""
    return getattr(func, "_consequence", None)


def is_consequence_rich(func: Callable) -> bool:
    """True if ``func`` is tagged consequence-rich."""
    return getattr(func, "_consequence", None) is not None


def consequence_by_name(name: str) -> Optional[Consequence]:
    return _NAME_REGISTRY.get(name)


def consequence_rich(consequence: Consequence):
    """Decorate a write method to tag it as consequence-rich.

    Also indexes the descriptor by ``consequence.name`` so a lookup by string
    works even where only the name is known (e.g. ``sustech consequence show
    selectcourse.drop_course``).

    Usage::

        @consequence_rich(Consequence(
            name="selectcourse.drop_course",
            severity=Severity.HIGH,
            irreversible=True,
            what_changes="Drops this course section on TIS",
            risk="A popular course can be re-taken by a vacancy-watcher.",
        ))
        def drop_course(self, rwh, *, dry_run=True, ...):
            ...
    """
    _register_name(consequence)

    def deco(func: Callable) -> Callable:
        _REGISTRY[func] = consequence
        func._consequence = consequence  # type: ignore[attr-defined]
        return func

    return deco


# Backwards-compatible alias (early adopters used the ALL-CAPS spelling).
CONSEQUENCE_RICH = consequence_rich


# ── CLI confirmation gate ──────────────────────────────────────────────────

class ConfirmationRequired(Exception):
    """Raised by the CLI gate when a consequence-rich op runs without --yes/--commit.

    The message is the human-readable prompt.
    """


def require_confirmation(
    consequence: Consequence,
    *,
    confirmed: bool,
    dry_run: bool,
    extra_prompt: str = "",
) -> None:
    """Enforce the warning-verification gate for one consequence-rich op.

    Rules:
      - A dry_run (not real) never needs confirmation.
      - If ``confirmed`` (e.g. ``--yes`` / ``--commit``) is True, proceed.
      - Otherwise raise :class:`ConfirmationRequired` with the risk prompt.

    Call this at the top of a CLI command that can commit a real change.
    """
    if dry_run:
        return
    if confirmed:
        return
    msg = consequence.prompt()
    if extra_prompt:
        msg += f"\n  {extra_prompt}"
    msg += "\n  Pass --commit/--yes to confirm this real action."
    raise ConfirmationRequired(msg)


__all__ = [
    "Severity",
    "Consequence",
    "consequence_rich",
    "CONSEQUENCE_RICH",  # backwards-compat alias
    "consequence_of",
    "is_consequence_rich",
    "consequence_by_name",
    "require_confirmation",
    "ConfirmationRequired",
]
