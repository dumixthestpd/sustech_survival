"""
sustech_survival._settings — small, principled runtime settings.

Only a curated set of values that can legitimately change at runtime are
registered here and honour an override chain::

    built-in default  >  env var  >  user config file (JSON)

The overriding rule: **do NOT register the static SUSTech API endpoints.**
``tis.sustech.edu.cn``, ``bb.sustech.edu.cn``, ``pms.sustech.edu.cn`` etc. are
institutional infrastructure — overriding them would break auth and every
request, so they are deliberately left as module constants and are NOT part of
this registry.

You register a setting only when a user might reasonably want to change it,
e.g. "I run my own sustech-calendar mirror" (a detailed/local calendar), or
"put the cache somewhere writable instead of next to site-packages".

Settings:

  calendar.repo_base
      Base URL of the academic-calendar source (before the ``<year>`` path
      segment). Defaults to the GitHub-hosted ``sustech-calendar`` repo. Set it
      to any HTTP(S) URL *or* a local directory path (``file://`` or a plain
      path) to use your own, possibly more detailed calendar.
      Env: ``SUSTECH_CALENDAR_REPO``
      Config key: ``"calendar" -> {"repo_base": "..."}``

  cache.dir
      Directory used for regenerable on-disk caches (currently the package's
      own ``tmp/``). Override to redirect cache writes somewhere writable on a
      system-install (e.g. ``~/.cache/sustech_survival``).
      Env: ``SUSTECH_CACHE_DIR``
      Config key: ``"cache" -> {"dir": "..."}``
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


# -- user config file discovery ---------------------------------------------

def _user_config_path() -> Path:
    """``~/.config/sustech_survival/config.json`` on Linux/macOS-style HOME."""
    return Path.home() / ".config" / "sustech_survival" / "config.json"


def _load_user_config() -> dict:
    p = _user_config_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


@dataclass(frozen=True)
class Setting:
    """One override-able runtime value."""
    name: str
    default: Any
    env: Optional[str]
    kind: str = "str"          # str | bool | int | path
    doc: str = ""

    def resolve(self, config: dict) -> Any:
        """default -> env -> user config, highest precedence wins."""
        # config file
        if config and self.name in config:
            return _coerce(self.kind, config[self.name])
        # env var
        if self.env:
            raw = os.environ.get(self.env)
            if raw is not None:
                return _coerce(self.kind, raw)
        return self.default


def _coerce(kind: str, raw: Any) -> Any:
    if kind == "bool":
        if isinstance(raw, bool):
            return raw
        return str(raw).lower() in ("1", "true", "yes", "on")
    if kind == "int":
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 0
    if kind == "path":
        return raw  # kept as the raw string; consumers wrap in Path()
    return str(raw)


# -- registry ---------------------------------------------------------------

@dataclass(frozen=True)
class Settings:
    """Compiled, resolved settings (defaults + env + config file)."""
    calendar_repo_base: str
    cache_dir: str

    _raw: dict = field(default_factory=dict, repr=False)

    @property
    def calendar_repo(self) -> str:
        """Calendar source base URL (before ``/<year>``), override-able."""
        return self.calendar_repo_base

    @property
    def cache_root(self) -> Path:
        """Absolute path to use for regenerable caches."""
        return Path(self.cache_dir).expanduser()


def load(user_config: Optional[dict] = None) -> Settings:
    """Build a resolved Settings from defaults + env + (given) config file.

    ``user_config``: optional raw dict (tests inject it); default reads the
    user config file if present.
    """
    cfg = user_config if user_config is not None else _load_user_config()

    # Normalise nested config {"calendar": {"repo_base": ...}} -> flat keys
    flat: dict[str, Any] = {}
    for section in ("calendar", "cache"):
        sec = (cfg or {}).get(section)
        if isinstance(sec, dict):
            for k, v in sec.items():
                flat[f"{section}.{k}"] = v

    cal = Setting("calendar.repo_base",
                  "https://raw.githubusercontent.com/dumixthestpd/sustech-calendar/main",
                  "SUSTECH_CALENDAR_REPO", "str",
                  "Academic-calendar source base URL or local path.")
    cache = Setting("cache.dir",
                    str(Path(__file__).resolve().parent / "tmp"),
                    "SUSTECH_CACHE_DIR", "path",
                    "Directory for regenerable caches.")

    return Settings(
        calendar_repo_base=cal.resolve(flat),
        cache_dir=cache.resolve(flat),
        _raw=flat,
    )


# Eagerly build once at import so modules can `from . import _settings`.
_DEFAULT = load()
calendar_repo_base = _DEFAULT.calendar_repo_base
cache_dir = _DEFAULT.cache_dir


def reload() -> Settings:
    """Re-read env + user config and refresh the module-level defaults.

    Useful after a user edits ``config.json`` or sets an env var at runtime.
    """
    global _DEFAULT, calendar_repo_base, cache_dir
    _DEFAULT = load()
    calendar_repo_base = _DEFAULT.calendar_repo_base
    cache_dir = _DEFAULT.cache_dir
    return _DEFAULT


# Public alias used by tooling / docs.
user_config_path = _user_config_path


__all__ = ["Settings", "Setting", "load", "reload", "calendar_repo_base",
           "cache_dir", "user_config_path"]
