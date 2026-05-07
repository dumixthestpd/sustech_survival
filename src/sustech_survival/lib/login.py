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

import sustech_survival.sso as _sso
Authorizer = _sso.Authorizer
register_auth = _sso.register_auth

PRIMO_HOME = "https://sustc.primo.exlibrisgroup.com.cn/discovery/search?vid=86SUSTC_INST:86SUSTC"
PRIMO_CAS_SERVICE = (
    "https%3A%2F%2Fsustc.primo.exlibrisgroup.com.cn%2Finfra%2FcasRedirect%3Fctx%3D%2Fprimaws"
)

LIB_DIR = _Path(__file__).resolve().parent
# Skill root is the parent of src/ (which is the skill dir)
SKILL_ROOT = LIB_DIR.parent.parent.parent


class LibAuth(Authorizer):
    BASE_URL = "https://sustc.primo.exlibrisgroup.com.cn"
    SERVICE_URL = PRIMO_CAS_SERVICE

    @property
    def session_file(self):
        # Session lives at skill root level, not alongside code in src/
        return _Path(self._skill_dir) / "lib" / "session.json"

    @property
    def submodule_dir(self):
        return _Path(self._skill_dir) / "lib"

    @property
    def _domain(self) -> str:
        return "sustc.primo.exlibrisgroup.com.cn"


# Singleton
_auth = LibAuth(skill_dir=str(SKILL_ROOT), submodule_dir=str(LIB_DIR))
register_auth("lib", _auth)


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
