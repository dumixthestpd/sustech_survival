# ── Public API ────────────────────────────────────────────────────────────────

from .authorizer import Authorizer, AuthorizerError, CAS_BASE, UA, register_auth, get_auth, require_auth
from .providers.cas import CASAuthorizer
from .providers.shibboleth import ShibbolethAuthorizer


__all__ = [
    "Authorizer",
    "AuthorizerError",
    "CAS_BASE",
    "UA",
    "CASAuthorizer",
    "ShibbolethAuthorizer",
    "Credentials",      # backwards compat — redirects to Authorizer.username/password
    "register_auth",
    "get_auth",
    "require_auth",
]

# Backwards-compat shim: Credentials was merged into Authorizer.
# Keep the name working so old code doesn't break.
Credentials = Authorizer


# ── Auto-register all authlib modules ────────────────────────────────────────
# Importing any authlib subpackage triggers its register_auth("name", obj) call,
# populating the global _auth_registry in authorizer.py.
# We import the top-level authlib package which re-exports everything.
from . import authlib  # noqa: F401

# Re-export authlib submodules at sso namespace level AND register them in
# sys.modules so "from sustech_survival.sso.rsc import ..." works.
# Python checks sys.modules before package.__dict__ for submodule imports.
import sys as _sys
for _name in ("bb", "tis", "lib", "wos", "rsc", "cnki"):
    _mod = getattr(authlib, _name)
    globals()[_name] = _mod
    _sys.modules[f"sustech_survival.sso.{_name}"] = _mod

# ── Lazy-load optional authlib submodules (acs, wiley, springer, etc.) ───────
# These modules need optional deps (cloudscraper).  They are loaded on first
# access via authlib.__getattr__, keeping the sso layer intact even if deps are
# missing.
_LAZY_NAMES = frozenset({"acs", "wiley", "springer",
                          "scopus", "jstor", "pubmed", "ieee"})

def __getattr__(name):
    if name in _LAZY_NAMES:
        import sys
        from importlib import import_module
        # Delegate to authlib (which has its own lazy loading)
        if "sustech_survival.sso.authlib" not in sys.modules:
            import_module("sustech_survival.sso.authlib")
        authlib = sys.modules["sustech_survival.sso.authlib"]
        return getattr(authlib, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
