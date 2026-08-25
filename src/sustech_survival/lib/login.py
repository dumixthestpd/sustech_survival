#!/usr/bin/env python3
"""
SUSTech Library (Primo) Login.

Checks the in-memory session via ``ensure()`` first; that already
auto-refreshes if the session is missing or expired. Falls back to a
Playwright headful login only when headless refresh fails.

Usage:
    python3 login.py
    # Reads credentials from <skill_root>/credentials.txt

Public auth API lives in :mod:`sustech_survival.sso`. ``ensure()`` is the
recommended entry point — it checks the session and refreshes
automatically when possible.
"""
import sys as _sys
from pathlib import Path as _Path

_PKG_ROOT = str(_Path(__file__).resolve().parent.parent.parent)
if _PKG_ROOT not in _sys.path:
    _sys.path.insert(0, _PKG_ROOT)

from sustech_survival.sso import LibAuth

# Use the LibAuth singleton
auth_singleton = LibAuth(skill_dir=_PKG_ROOT)


def main() -> None:
    print("=== SUSTech Library Login ===")

    # Step 1: Ensure — checks the session and auto-refreshes if expired.
    ok, reason = auth_singleton.ensure()
    if ok:
        print("✓ Already logged in.")
        return
    print(f"Session check: {reason}")

    # Step 2: Playwright headful login as last resort.
    print("[2/2] Opening browser for manual CAS login...")
    auth_singleton.login()

    # Verify
    ok, reason = auth_singleton.ensure()
    print("✓ Logged in successfully!" if ok else f"⚠ {reason}")


if __name__ == "__main__":
    main()