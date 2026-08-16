# authlib — External service authorizers
# -----------------------------------------------------------------------------
# External services: wos, rsc, cnki, ieee, jstor, pubmed, acs, wiley,
# springer, scopus.  Each is lazy-loaded on first attribute access.
#
# Internal services (TISAuth, BBAuth, LibAuth) live in sso/__init__.py.
# =============================================================================

import logging
from importlib import import_module

logging.getLogger(__name__).setLevel(logging.DEBUG)


# =============================================================================
# Lazy-load external service modules
# =============================================================================

_LAZY = frozenset({"wos", "rsc", "cnki", "ieee", "jstor", "pubmed", "acs", "wiley", "springer", "scopus", "pms", "booking"})
_LOADED = {}


def __getattr__(name):
    if name in _LAZY and name not in _LOADED:
        try:
            _LOADED[name] = import_module(f"sustech_survival.sso.authlib.{name}")
            globals()[name] = _LOADED[name]
            return _LOADED[name]
        except ImportError as exc:
            logging.getLogger(__name__).debug(
                "authlib.%s unavailable (missing dep): %s", name, exc
            )
            raise
    elif name in _LOADED:
        return _LOADED[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
