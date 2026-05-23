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
_auth = LibAuth(skill_dir=_PKG_ROOT)


def main():
    print(f"=== SUSTech Library Login ===")
    print(f"Session file: {_auth.session_file}")

    # Step 1: Check
    ok, reason = _auth.check()
    if ok:
        print("✓ Already logged in.")
        return
    print(f"Session check: {reason}")

    # Step 2: Refresh via requests
    print("[2/3] Attempting requests-based refresh...")
    if _auth.refresh():
        print("✓ Refresh successful!")
        return

    # Step 3: Playwright headful login
    print("[3/3] Opening browser for manual CAS login...")
    _auth.login()

    # Verify
    ok, reason = _auth.check()
    print("✓ Logged in successfully!" if ok else f"⚠ {reason}")


if __name__ == "__main__":
    main()
