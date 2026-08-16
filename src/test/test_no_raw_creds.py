"""
Iron law #12 enforcement: NOTHING outside ``sso/authorizer.py`` may read
``credentials.txt``, hardcode ``Path.home()``, or touch a ``session.json``
file directly. This test greps the source tree for violations.

Allowed exemptions (listed explicitly below):
  - ``sso/authorizer.py`` — the one accessor (``_read_creds``, ``_resolve_skill_dir``)
  - ``sso/authlib/rsc_inject.py`` — has a legacy FILE fallback for Playwright
    cookie injection, but prefers the Authorizer in-memory session first
  - ``lib/booking/auth.py`` — ``_save_session`` / ``refresh_from_disk`` are
    no-op stubs for backward compat (do NOT persist to disk)
  - ``bb/session.py`` — ``SESSION_FILE`` constant is vestigial; auth goes
    through ``BBAuth``; marked with a ``# legacy`` comment

If you add a new exemption, add it here AND explain why in the exemption list.
Otherwise the test fails and CI blocks the merge.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

SRC_DIR = Path(__file__).resolve().parent.parent / "sustech_survival"

# Files that are ALLOWED to contain credential/session patterns.
# Each entry is (relative_path, reason).
EXEMPTIONS: dict[str, str] = {
    "sso/authorizer.py": "The one accessor — _read_creds, _resolve_skill_dir, _creds_file",
    "sso/authlib/rsc_inject.py": "Legacy Playwright cookie bridge — prefers Authorizer in-memory, falls back to file",
    "lib/booking/auth.py": "_save_session/refresh_from_disk are no-op stubs for backward compat",
    "bb/session.py": "SESSION_FILE is vestigial, marked # legacy; auth goes through BBAuth",
    "bb/download.py": "Uses ~/Downloads for file output — not credentials/auth",
    # Test files can reference these patterns in assertions
    "tests/test_no_raw_creds.py": "This test itself",
    "webui/loader.py": "User skin cache under ~/.config/... — per-user skin dir, NOT credentials/auth",
}

# Patterns that violate iron law #12 when found OUTSIDE exempted files.
# Each is (regex, description).
VIOLATIONS: list[tuple[str, str]] = [
    # Raw credential file reads — open("*credentials*")
    (r'open\s*\([^)]*credentials', "Direct open() of credentials file — use Authorizer._read_creds()"),
    # Path.home() followed by / — breaks on non-default HOME.
    # Regex requires the trailing / to distinguish actual code from docstring mentions.
    (r'Path\.home\s*\(\s*\)\s*/', "Path.home()/ — breaks on non-default HOME. Use package-relative resolution."),
    # session.json literal in code (not comments) — disk-persisted sessions are the anti-pattern
    (r'["\']session\.json["\']', 'session.json disk persistence — use Authorizer in-memory TTL (iron law #12)'),
]


def _is_exempt(rel_path: str) -> bool:
    """Check if a file is in the exemption list."""
    # Normalize OS-specific separators (Windows uses '\') to '/' so the
    # forward-slash keys in EXEMPTIONS match on every platform.
    return rel_path.replace("\\", "/") in EXEMPTIONS


def _scan_file(path: Path) -> list[tuple[str, int, str, str]]:
    """Scan one file for violations. Returns [(pattern_desc, line_num, line_text, rel_path)]."""
    rel = str(path.relative_to(SRC_DIR))
    if _is_exempt(rel):
        return []

    hits: list[tuple[str, int, str, str]] = []
    for line_num, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        # Skip comment-only lines (heuristic — # or // at start after whitespace)
        stripped = line.lstrip()
        if stripped.startswith("#") or stripped.startswith("//"):
            continue
        for pattern, desc in VIOLATIONS:
            if re.search(pattern, line):
                hits.append((desc, line_num, line.rstrip(), rel))
    return hits


def test_no_raw_credential_reads():
    """No file outside sso/authorizer.py may open credentials.txt directly."""
    py_files = sorted(SRC_DIR.rglob("*.py"))
    all_hits: list[tuple[str, int, str, str]] = []
    for f in py_files:
        all_hits.extend(_scan_file(f))

    if all_hits:
        lines = [f"  {h[3]}:{h[1]} — {h[0]}" for h in all_hits]
        msg = (
            f"\n❌ Iron law #12 violations found ({len(all_hits)}):\n"
            + "\n".join(lines)
            + "\n\nUse Authorizer._read_creds() / TISAuth().ensure() instead."
        )
        pytest.fail(msg)