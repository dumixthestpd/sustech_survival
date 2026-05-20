# ── Public API ────────────────────────────────────────────────────────────────

from .base import Authorizer, AuthorizerError, CAS_BASE, UA, register_auth, get_auth, require_auth
from .providers.cas import CASAuthorizer
from .providers.shibboleth import ShibbolethAuthorizer


# ── Credentials ───────────────────────────────────────────────────────────────

class Credentials:
    """
    Load SUSTech CAS username/password from credentials file.

    File: <skill_root>/credentials.txt
    Format: username:password
    """

    CREDENTIALS_FILENAME = "credentials.txt"

    def __init__(self, path: str = None):
        from pathlib import Path
        if path:
            self._path = Path(path)
        else:
            # Search upward from sso/__init__.py for credentials.txt (skill root)
            # __file__ = .../skills/sustech_survival/src/sustech_survival/sso/__init__.py
            here = Path(__file__).resolve().parent  # sso/
            for parent in [here, here.parent, here.parent.parent, here.parent.parent.parent]:
                if (parent / self.CREDENTIALS_FILENAME).exists():
                    self._path = parent / self.CREDENTIALS_FILENAME
                    break
            else:
                # Fallback: assume standard skills/ layout
                self._path = here.parent.parent.parent / self.CREDENTIALS_FILENAME

    @property
    def username(self) -> str:
        return self.load()[0]

    @property
    def password(self) -> str:
        return self.load()[1]

    def load(self):
        """Return (username, password) tuple."""
        from pathlib import Path
        p = Path(self._path)
        if not p.exists():
            return None, None
        line = p.read_text().strip()
        if ':' not in line:
            return None, None
        return line.split(':', 1)[0].strip(), line.split(':', 1)[1].strip()

    def __repr__(self):
        u, _ = self.load()
        return f"Credentials(user={u!r})"


__all__ = [
    "Authorizer",
    "AuthorizerError",
    "CAS_BASE",
    "UA",
    "CASAuthorizer",
    "ShibbolethAuthorizer",
    "Credentials",
    "register_auth",
    "get_auth",
    "require_auth",
]

# ── Auto-register all authlib modules ────────────────────────────────────────
# Importing any authlib subpackage triggers its register_auth("name", obj) call,
# populating the global _auth_registry in base.py.
# We import the top-level authlib package which re-exports everything.
from . import authlib  # noqa: F401
