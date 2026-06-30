#!/usr/bin/env python3
"""
SUSTech Library (Primo) Login.

Checks session → requests-based refresh → Playwright headful login.

Usage:
    python3 login.py
    # Reads credentials from <skill_root>/credentials.txt
"""
import sys as _sys
from pathlib import Path as _Path

_PKG_ROOT = str(_Path(__file__).resolve().parent.parent.parent)
if _PKG_ROOT not in _sys.path:
    _sys.path.insert(0, _PKG_ROOT)

from sustech_survival.sso import LibAuth

# Use the LibAuth singleton
auth_singleton = LibAuth(skill_dir=_PKG_ROOT)


def main():
    print(f"=== SUSTech Library Login ===")

    # Step 1: Ensure
    ok, reason = auth_singleton.ensure()
    if ok:
        print("✓ Already logged in.")
        return
    print(f"Session check: {reason}")

    # Step 2: Refresh via requests
    print("[2/3] Attempting requests-based refresh...")
    if auth_singleton.refresh():
        print("✓ Refresh successful!")
        return

    # Step 3: Playwright headful login
    print("[3/3] Opening browser for manual CAS login...")
    auth_singleton.login()

    # Verify
    ok, reason = auth_singleton.ensure()
    print("✓ Logged in successfully!" if ok else f"⚠ {reason}")


if __name__ == "__main__":
    main()
