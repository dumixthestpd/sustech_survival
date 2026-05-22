# =============================================================================
# BB Session — CAS authentication for Blackboard
# =============================================================================

import sys as _sys
from pathlib import Path as _Path

# sustech_survival/sso.py — ensure package root is importable when running standalone
_PKG_ROOT = str(_Path(__file__).resolve().parent.parent.parent)
if _PKG_ROOT not in _sys.path:
    _sys.path.insert(0, _PKG_ROOT)

BB_DIR = _Path(__file__).resolve().parent
# Skill root is the parent of src/ (which is the skill dir)
SKILL_ROOT = BB_DIR.parent.parent.parent

SESSION_FILE = BB_DIR / "session.json"
COURSES_FILE = BB_DIR / "courses.json"
STRUCTURE_FILE = BB_DIR / "structure.json"

# ── Import enhanced BBAuth from authlib ─────────────────────────────────────
# BBAuth is defined in sso/authlib/__init__.py with session_file override,
# _reset_cached_data(), and overridden refresh()/login() methods.
from sustech_survival.sso.authlib import BB as BBAuth

# Singleton — use the enhanced BBAuth already registered by authlib
_auth = BBAuth(skill_dir=str(SKILL_ROOT))

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

import re


def slugify(name, keep_extension=True):
    if keep_extension and '.' in name:
        p = _Path(name)
        name_part = p.stem
        ext = p.suffix
        safe = re.sub(r'[\\/:*?"<>|\s]', '_', name_part).strip()[:80]
        return f"{safe}{ext}"
    return re.sub(r'[\\/:*?"<>|]', '_', name).strip()[:80]
