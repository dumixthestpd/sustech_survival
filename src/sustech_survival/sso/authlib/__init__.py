# authlib — SUSTech institutional authorizers
# ─────────────────────────────────────────────────────────────────────────────
# All auth classes (even simple ones) are defined and registered here.
# Enhanced subclasses stay in authlib — subpackages import from here.
#
# Registration:
#   TISAuth, BBAuth, LibAuth are registered as "tis", "bb", "lib"
#   Subpackages (bb/, lib/) import from authlib, NOT create their own classes.
#
# Complex auth classes (browser/CARSI/OAuth flows) stay in their own files.
# Lazy-loaded modules: wos, rsc, cnki, ieee, jstor, pubmed, acs, wiley, springer, scopus

import logging
import sys
from importlib import import_module
from pathlib import Path

logging.getLogger(__name__).setLevel(logging.DEBUG)

# ── Skill dir path ─────────────────────────────────────────────────────────────
# authlib/__init__.py → authlib/ → sso/ → sustech_survival/ → src/ → skill_root/
_SKILL_DIR = str(Path(__file__).resolve().parent.parent.parent.parent.parent)

# ── CAS headless auth classes (inlined here) ────────────────────────────────────

from ..providers.cas import CASAuthorizer
from ..authorizer import register_auth


class TISAuth(CASAuthorizer):
    BASE_URL = "https://tis.sustech.edu.cn"
    SERVICE_URL = "https://tis.sustech.edu.cn/cas"
    SESSION_SUBDIR = "tis"
    XHR_MODE = True
    SUBMIT_VALUE = ""  # TIS CAS has no submit button value in POST body


class BBAuth(CASAuthorizer):
    BASE_URL = "https://bb.sustech.edu.cn"
    SERVICE_URL = "https://bb.sustech.edu.cn/webapps/bb-sso-BBLEARN/index.jsp"
    SESSION_SUBDIR = "bb"

    @property
    def session_file(self):
        # Session lives at <skill_root>/bb/session.json alongside other bb data
        return Path(self._skill_dir) / "bb" / "session.json"

    def _reset_cached_data(self):
        # Courses and structure are invalidated on re-auth
        skill_bb = Path(self._skill_dir) / "bb"
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


class LibAuth(CASAuthorizer):
    BASE_URL = "https://sustc.primo.exlibrisgroup.com.cn"
    SERVICE_URL = "https://sustc.primo.exlibrisgroup.com.cn/infra/casRedirect?ctx=/primaws"
    SESSION_SUBDIR = "lib"

    @property
    def session_file(self):
        # Session lives at <skill_root>/lib/session.json alongside other lib data
        return Path(self._skill_dir) / "lib" / "session.json"


# Register instances
register_auth("tis", TISAuth(skill_dir=_SKILL_DIR))
register_auth("bb", BBAuth(skill_dir=_SKILL_DIR))
register_auth("lib", LibAuth(skill_dir=_SKILL_DIR))

# Module-level aliases so `from sustech_survival.sso.authlib import TIS` works
TIS = TISAuth
BB = BBAuth
LIB = LibAuth

# Clean up class names — only expose instances
del TISAuth, BBAuth, LibAuth

__all__ = ["TIS", "BB", "LIB"]

# ── Complex auth classes stay in their own files ────────────────────────────────

# ── Lazy-load optional authlib submodules ─────────────────────────────────────
# Modules that need optional deps (cloudscraper) are loaded on first access via
# __getattr__ so a missing package doesn't kill the entire authlib layer.

_LAZY = frozenset({"wos", "rsc", "cnki", "ieee", "jstor", "pubmed", "acs", "wiley", "springer", "scopus"})
_LOADED = {}


def __getattr__(name):
    if name in _LAZY and name not in _LOADED:
        try:
            _LOADED[name] = import_module(f"sustech_survival.sso.authlib.{name}")
            globals()[name] = _LOADED[name]
            __all__.append(name)
            return _LOADED[name]
        except ImportError as exc:
            logging.getLogger(__name__).debug(
                "authlib.%s unavailable (missing dep): %s", name, exc
            )
            raise
    elif name in _LOADED:
        return _LOADED[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
