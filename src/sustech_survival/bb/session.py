# =============================================================================
# BB Session — CAS authentication for Blackboard
# =============================================================================

import re
import sys as _sys
from pathlib import Path as _Path

# sustech_survival/sso.py — ensure package root is importable when running standalone
_PKG_ROOT = str(_Path(__file__).resolve().parent.parent.parent)
if _PKG_ROOT not in _sys.path:
    _sys.path.insert(0, _PKG_ROOT)

import sustech_survival.sso as _sso
Authorizer = _sso.Authorizer
register_auth = _sso.register_auth

BB_DIR = _Path(__file__).resolve().parent
# Skill root is the parent of src/ (which is the skill dir)
SKILL_ROOT = BB_DIR.parent.parent.parent

BB_BASE = "https://bb.sustech.edu.cn"
BB_SSO = "https://bb.sustech.edu.cn/webapps/bb-sso-BBLEARN/index.jsp"
SESSION_FILE = BB_DIR / "session.json"
COURSES_FILE = BB_DIR / "courses.json"
STRUCTURE_FILE = BB_DIR / "structure.json"


class BBAuth(Authorizer):
    BASE_URL = BB_BASE
    SERVICE_URL = BB_SSO

    @property
    def session_file(self):
        # Session lives at skill root level, not alongside code in src/
        return _Path(self._skill_dir) / "bb" / "session.json"

    @property
    def creds_file(self):
        # Credentials live alongside session at bb/credentials.txt
        return _Path(self._skill_dir) / "bb" / "credentials.txt"

    @property
    def submodule_dir(self):
        return _Path(self._skill_dir) / "bb"

    def _reset_cached_data(self):
        # Courses and structure live at skill root level alongside session
        skill_bb = _Path(self._skill_dir) / "bb"
        for f in (skill_bb / "courses.json", skill_bb / "structure.json"):
            if f.exists():
                f.unlink()

    def refresh(self) -> bool:
        ok = super().refresh()
        if ok:
            self._reset_cached_data()
        return ok

    def login(self, *, headless: bool = False):
        ok = super().login(headless=headless)
        if ok:
            self._reset_cached_data()
        return ok


# Singleton registered by name
_auth = BBAuth(skill_dir=str(SKILL_ROOT), submodule_dir=str(BB_DIR))
register_auth("bb", _auth)


# ── Convenience wrappers ───────────────────────────────────────────────────

def load_session():
    raw = _auth.load()
    if isinstance(raw, list):
        return raw, raw
    pw = [{"name": k, "value": v, "domain": "bb.sustech.edu.cn", "path": "/"}
          for k, v in raw.items()]
    return raw, pw


def check_session():
    return _auth.check()


def ensure_session():
    return _auth.ensure()


def refresh():
    return _auth.refresh()


def login():
    return _auth.login()


# ── Slugify ─────────────────────────────────────────────────────────────

def slugify(name, keep_extension=True):
    if keep_extension and '.' in name:
        p = _Path(name)
        name_part = p.stem
        ext = p.suffix
        safe = re.sub(r'[\\/:*?"<>|\s]', '_', name_part).strip()[:80]
        return f"{safe}{ext}"
    return re.sub(r'[\\/:*?"<>|]', '_', name).strip()[:80]
