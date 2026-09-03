"""Network timeout & retry configuration — reads the root config.json tree.

All outbound HTTP timing lives in **one place**: the ``timeouts`` section of
the root config.json (``~/.sustech_survival/config.json`` or under
``$SUSTECH_HOME``). The transport layer (``sso.authorizer.Authorizer`` and
friends) resolves every request/login timeout through here, so operators
tune a single JSON tree instead of code — SUSTech's TIS in particular is
notoriously slow and needs generous, network-dependent timeouts.

Canonical tree (every leaf optional; missing leaves fall back):

    {
      "timeouts": {
        "http": {
          "default": 30,     # seconds per request (fallback for all services)
          "attempts": 2      # retries for idempotent (GET) requests
        },
        "login": {
          "default": 30,     # seconds per login step (CAS ticket dance)
          "attempts": 3      # full login attempts before giving up
        },
        "services": {
          "tis": { "http": 45, "login": 45 },   # per-service overrides
          "bb":  { "http": 30 }
        }
      }
    }

Per-service entries may override ``http`` and/or ``login`` seconds; anything
not listed uses the section defaults.

Legacy flat keys from earlier versions are still honored and folded into the
tree: ``cas_login`` → ``login.default``, ``cas_attempts`` → ``login.attempts``,
``tis`` → ``services.tis.http`` — so existing config files keep working.

Lookups are cached briefly (10 s): live config edits take effect within
seconds without re-reading the file per request.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, Optional

from . import _cache

# ---------------------------------------------------------------------------
# Defaults (when config.json has no "timeouts" section or misses a leaf)
# ---------------------------------------------------------------------------

HTTP_DEFAULT: float = 30.0
HTTP_ATTEMPTS: int = 2
LOGIN_DEFAULT: float = 30.0
LOGIN_ATTEMPTS: int = 2

# Legacy flat keys → tree path (kept so earlier configs keep working).
_LEGACY_FLAT = {
    "cas_login": ("login", "default"),
    "cas_attempts": ("login", "attempts"),
    "tis": ("services", "tis", "http"),
}


@dataclass(frozen=True)
class _Timing:
    """One section of the tree: seconds per step + retry count."""
    default: float
    attempts: int


@dataclass(frozen=True)
class NetworkTimeouts:
    """Fully-resolved timeouts tree (one immutable snapshot per window)."""

    http: _Timing = field(default_factory=lambda: _Timing(HTTP_DEFAULT, HTTP_ATTEMPTS))
    login: _Timing = field(default_factory=lambda: _Timing(LOGIN_DEFAULT, LOGIN_ATTEMPTS))
    services: Dict[str, Dict[str, float]] = field(default_factory=dict)

    # -- resolution ---------------------------------------------------------

    def service_timeout(self, service: str) -> float:
        """Request (http) seconds for one service."""
        svc = self.services.get(service) or {}
        return float(svc.get("http", self.http.default))

    def service_login_timeout(self, service: str) -> float:
        """Login-step seconds for one service."""
        svc = self.services.get(service) or {}
        return float(svc.get("login", self.login.default))

    def request_attempts(self) -> int:
        """Retries for idempotent (GET) requests."""
        return max(1, self.http.attempts)

    def login_attempts(self) -> int:
        """Full login attempts before giving up."""
        return max(1, self.login.attempts)

    # -- parsing ------------------------------------------------------------

    @classmethod
    def from_config(cls, raw: Optional[dict]) -> "NetworkTimeouts":
        raw = raw or {}

        def _section(name: str, d_default: float, d_attempts: int) -> _Timing:
            sec = raw.get(name)
            d, a = d_default, d_attempts
            if isinstance(sec, dict):
                try:
                    d = float(sec.get("default", d))
                except (TypeError, ValueError):
                    pass
                try:
                    a = int(sec.get("attempts", a))
                except (TypeError, ValueError):
                    pass
            return _Timing(default=d, attempts=max(1, a))

        http = _section("http", HTTP_DEFAULT, HTTP_ATTEMPTS)
        login = _section("login", LOGIN_DEFAULT, LOGIN_ATTEMPTS)
        services: Dict[str, Dict[str, float]] = {}

        svc_raw = raw.get("services")
        if isinstance(svc_raw, dict):
            for name, entry in svc_raw.items():
                if isinstance(entry, dict):
                    clean: Dict[str, float] = {}
                    for leaf, val in entry.items():
                        try:
                            clean[leaf] = float(val)
                        except (TypeError, ValueError):
                            continue
                    if clean:
                        services[str(name)] = clean
                else:
                    # A bare number means an http override ("tis": 45).
                    try:
                        services[str(name)] = {"http": float(entry)}
                    except (TypeError, ValueError):
                        continue

        # Fold legacy flat keys into the tree.
        for legacy, path in _LEGACY_FLAT.items():
            if legacy not in raw:
                continue
            try:
                value = float(raw[legacy])
            except (TypeError, ValueError):
                continue
            if path[0] == "login":
                if path[1] == "default":
                    login = _Timing(default=value, attempts=login.attempts)
                else:
                    login = _Timing(default=login.default, attempts=max(1, int(value)))
            elif path[0] == "services":
                svc_name, leaf = path[1], path[2]
                services.setdefault(svc_name, {})[leaf] = value

        return cls(http=http, login=login, services=services)


# ---------------------------------------------------------------------------
# Cached accessor — one snapshot per 10 s window.
# ---------------------------------------------------------------------------

_cache_state: dict = {"at": 0.0, "snapshot": None}


def _raw_timeouts() -> dict:
    try:
        cfg = _cache.load_config()
    except Exception:
        cfg = {}
    return cfg.get("timeouts") or {}


def timeouts() -> NetworkTimeouts:
    now = time.time()
    if _cache_state["snapshot"] is None or now - _cache_state["at"] > 10:
        _cache_state["snapshot"] = NetworkTimeouts.from_config(_raw_timeouts())
        _cache_state["at"] = now
    return _cache_state["snapshot"]


# -- Thin wrappers kept for callers that predate the class -------------------

def timeout(name: str) -> float:
    """Legacy: request timeout by kind ('login'/'cas_login' or a service)."""
    snap = timeouts()
    if name in ("login", "cas_login"):
        return snap.login.default
    return snap.service_timeout(name)


def attempts(name: str = "http") -> int:
    """Legacy: retry count ('login'/'cas_attempts' → login attempts)."""
    snap = timeouts()
    if name in ("login", "cas_attempts"):
        return snap.login_attempts()
    return snap.request_attempts()


def service_timeout(service: str) -> float:
    """Request (http) seconds for one named service."""
    return timeouts().service_timeout(service)
