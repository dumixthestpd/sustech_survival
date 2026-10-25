"""Narration that must never land on stdout.

Commands that promise machine-readable output (``--json``) hand stdout to a
parser, so anything that is only narration — "session refreshed", "credentials
rejected", "browser opened" — goes to stderr instead. ``authorizer.py`` and the
three auth subclasses used bare ``print()``, which put diagnostics in front of
the JSON payload and made ``sustech context --json`` unparseable.

``print(..., file=sys.stderr)`` is used rather than ``logging`` because these
lines are part of the CLI's user-facing voice, not log noise: they carry the
same ✅/❌ prefixes the rest of the CLI uses.
"""
from __future__ import annotations

import sys


def note(message: str) -> None:
    """Write one narration line to stderr (never stdout)."""
    print(message, file=sys.stderr)


__all__ = ["note"]
