"""
sustech_survival — exceptions used across the package.

Errors are named after the FAILURE MODE, not the system:
  APIError            — base class for all sustech_survival errors
  SessionExpired     — auth session expired or was revoked
  NotFound           — resource not found (404)
  NetworkError        — connection failure
  InvalidCredentials  — login rejected (wrong username/password)
  PermissionDenied    — authenticated but not authorized
"""

class APIError(Exception):
    """Base class for all sustech_survival errors."""

    def __init__(self, message: str = ""):
        super().__init__(message)
        self.message = message


class SessionExpired(APIError):
    """Auth session expired or revoked. Re-authenticate to recover."""
    pass


class NotFound(APIError):
    """Resource not found (HTTP 404)."""
    pass


class NetworkError(APIError):
    """Connection failure (timeout, DNS, refused, etc.)."""
    pass


class InvalidCredentials(APIError):
    """Login rejected — wrong username or password."""
    pass


class PermissionDenied(APIError):
    """Authenticated but not authorized for this resource."""
    pass


# -- Backwards-compatibility aliases (deprecated) -------------------------------

# BBError was the old blanket name for BB auth/session failures
BBError = SessionExpired

# TIS login failures are credential rejections, not session expiry
TISAuthError = InvalidCredentials

# Library (Primo) session failures are session expiry
LibraryAuthError = SessionExpired