"""
Dedicated tests for sustech_survival.consequence — the consequence-rich
safety contract (registry, decorator, confirmation gate).

These are OFFLINE: no network, no auth, framework-agnostic.
"""
from __future__ import annotations

import pytest

from sustech_survival.consequence import (
    Severity,
    Consequence,
    consequence_rich,
    consequence_of,
    is_consequence_rich,
    consequence_by_name,
    require_confirmation,
    ConfirmationRequired,
    CONSEQUENCE_RICH,
)


def _drop_consequence() -> Consequence:
    return Consequence(
        name="selectcourse.drop_course",
        severity=Severity.HIGH,
        irreversible=True,
        what_changes="Drops this course section on TIS",
        risk="A popular course can be re-taken by a vacancy-watcher.",
    )


# ── Severity + Consequence descriptors ──────────────────────────────────────

def test_severity_values():
    assert Severity.LOW.value == "low"
    assert Severity.CRITICAL.value == "critical"
    # Must be a str-enum so it can be echoed / stored
    assert issubclass(Severity, str)


def test_consequence_prompt_irreversible():
    c = _drop_consequence()
    p = c.prompt()
    assert "IRREVERSIBLE" in p
    assert "Drops this course section" in p
    assert "vacancy-watcher" in p


def test_consequence_prompt_reversible_flags_care():
    c = Consequence(name="pms.upload", severity=Severity.LOW,
                    what_changes="Uploads a print job")
    p = c.prompt()
    assert "CARE" in p  # not irreversible
    assert "IRREVERSIBLE" not in p


# ── Decorator + registry ───────────────────────────────────────────────────

def test_consequence_rich_tags_and_registers():
    c = _drop_consequence()

    @consequence_rich(c)
    def drop_course(self, rwh, *, dry_run=True):
        return rwh

    assert is_consequence_rich(drop_course) is True
    assert consequence_of(drop_course) is c
    # registered by name for `sustech consequence show selectcourse.drop_course`
    assert consequence_by_name("selectcourse.drop_course") is c


def test_consequence_rich_alias_capsexists():
    # Early adopters used the ALL-CAPS spelling; it must still work.
    assert CONSEQUENCE_RICH is consequence_rich


def test_untagged_function_is_not_consequence_rich():
    def plain():
        pass
    assert is_consequence_rich(plain) is False
    assert consequence_of(plain) is None
    assert consequence_by_name("nope.does-not-exist") is None


def test_duplicate_name_last_wins():
    # Two ops with the same stable key: the last registration wins for lookup.
    a = Consequence(name="x.y", severity=Severity.LOW, what_changes="a")
    b = Consequence(name="x.y", severity=Severity.MEDIUM, what_changes="b")

    @consequence_rich(a)
    def f1(): pass
    @consequence_rich(b)
    def f2(): pass

    assert consequence_by_name("x.y") is b


# ── Confirmation gate ──────────────────────────────────────────────────────

def test_require_confirmation_dry_run_never_blocks():
    c = _drop_consequence()
    # dry_run=True is always safe — no confirmation needed.
    require_confirmation(c, confirmed=False, dry_run=True)
    require_confirmation(c, confirmed=False, dry_run=True, extra_prompt="x")


def test_require_confirmation_confirmed_passes():
    c = _drop_consequence()
    require_confirmation(c, confirmed=True, dry_run=False)


def test_require_confirmation_raises_when_not_confirmed_not_dryrun():
    c = _drop_consequence()
    with pytest.raises(ConfirmationRequired) as e:
        require_confirmation(c, confirmed=False, dry_run=False)
    msg = str(e.value)
    assert "IRREVERSIBLE" in msg
    assert "--commit/--yes" in msg


def test_require_confirmation_includes_extra_prompt():
    c = _drop_consequence()
    with pytest.raises(ConfirmationRequired) as e:
        require_confirmation(c, confirmed=False, dry_run=False,
                             extra_prompt="This drops ALL courses.")
    assert "This drops ALL courses." in str(e.value)


# ── Real-world write surfaces are tagged (smoke) ───────────────────────────

def test_real_write_ops_are_tagged_consequence_rich():
    """Concrete mutating methods in the package are tagged with the contract."""
    from sustech_survival.selectcourse import writes as sc_writes
    # selectcourse.writes should expose at least one consequence-rich function.
    tagged = [
        getattr(sc_writes, n) for n in dir(sc_writes)
        if callable(getattr(sc_writes, n, None))
    ]
    assert any(is_consequence_rich(f) for f in tagged), (
        "selectcourse.writes should tag its write functions consequence-rich")


def test_single_bid_update_is_tagged_consequence_rich():
    from sustech_survival.selectcourse.writes import update_bid

    assert is_consequence_rich(update_bid)


def test_require_confirmation_is_importable_anywhere():
    # The gate is the same object referenced by CLI modules.
    from sustech_survival.consequence import require_confirmation as g
    assert g is require_confirmation
