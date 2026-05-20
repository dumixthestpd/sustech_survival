# Backwards-compatibility shim — all authorizer symbols live in authorizer.py now.
from .authorizer import (
    Authorizer,
    AuthorizerError,
    register_auth,
    get_auth,
    require_auth,
    CAS_BASE,
    UA,
)

__all__ = [
    "Authorizer",
    "AuthorizerError",
    "register_auth",
    "get_auth",
    "require_auth",
    "CAS_BASE",
    "UA",
]
