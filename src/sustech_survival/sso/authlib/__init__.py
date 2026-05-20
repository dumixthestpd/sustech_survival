# authlib — SUSTech institutional authorizers
# Re-export all auth modules so `from sustech_survival.sso.authlib import wos` works.
# Importing any authlib subpackage triggers its register_auth() call at module load.
#
# Modules that need optional deps (cloudscraper) are loaded on first access via
# __getattr__ so a missing package doesn't kill the entire sso layer.

import logging
import sys
from importlib import import_module

logging.getLogger(__name__).setLevel(logging.DEBUG)

# Core modules — no optional deps, always available
from . import bb, tis, lib, wos, rsc, cnki  # noqa: F401  (Playwright/CARSI)

__all__ = ["bb", "tis", "lib", "wos", "rsc", "cnki"]

# Optional modules — loaded lazily on first access.
# If a module's top-level code raises ImportError (e.g. missing cloudscraper),
# that error propagates normally and the module stays unavailable.
_LAZY = {"ieee", "jstor", "pubmed", "acs", "wiley", "springer", "scopus"}
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
