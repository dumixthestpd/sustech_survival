# Backwards-compatibility shim — all authorizer symbols live in authorizer.py now.
from .authorizer import (
    Authorizer,
    AuthorizerError,
    require_auth,
    CAS_BASE,
    UA,
)

__all__ = [
    "Authorizer",
    "AuthorizerError",
    "require_auth",
    "CAS_BASE",
    "UA",
]