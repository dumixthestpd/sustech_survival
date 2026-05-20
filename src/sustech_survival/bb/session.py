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

BB_DIR = _Path(__file__).resolve().parent
# Skill root is the parent of src/ (which is the skill dir)
SKILL_ROOT = BB_DIR.parent.parent.parent

BB_BASE = "https://bb.sustech.edu.cn"
BB_SSO = "https://bb.sustech.edu.cn/webapps/bb-sso-BBLEARN/index.jsp"
SESSION_FILE = BB_DIR / "session.json"
COURSES_FILE = BB_DIR / "courses.json"
STRUCTURE_FILE = BB_DIR / "structure.json"


# ── BBAuth class factory ─────────────────────────────────────────────────────
# sso is imported AFTER this function is defined to avoid circular import.
# When session.py is loaded via  sustech_survival.__init__ → bb → items → session,
# sso/__init__.py is still initialising (waiting on authlib). Importing sso here
# would get a partially-initialised module. By making this a factory called AFTER
# the full import chain completes, we get a fully-initialised sso.Authorizer.
def _make_bbauth(authorizer_cls):
    class BBAuth(authorizer_cls):
        BASE_URL = BB_BASE
        SERVICE_URL = BB_SSO

        @property
        def session_file(self):
            # Session lives at skill root level, not alongside code in src/
            return _Path(self._skill_dir) / "bb" / "session.json"

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

    return BBAuth


# ── Deferred sso import (after sustech_survival is fully initialised) ───────────
# At this point the import chain that reached session.py is:
#   sustech_survival init → sso/__init__ → authlib/__init__ → bb/__init__
#     → items.py → session.py
# authlib/__init__ now uses lazy imports so it returns immediately without waiting
# on cloudscraper-dependent modules. sso/__init__.py finishes, then bb loads
# fully, then items → session. By the time we reach here, sso is fully initialised.
import sustech_survival.sso as _sso

# Singleton — sso is fully loaded at this point
BBAuth = _make_bbauth(_sso.Authorizer)
_auth = BBAuth(skill_dir=str(SKILL_ROOT), submodule_dir=str(BB_DIR))
_sso.register_auth("bb", _auth)


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
