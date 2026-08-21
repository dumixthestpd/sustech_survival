"""
sustech_survival.webui.loader — the skin loader (the "head").

This is a THIN, replaceable layer. It does two things:

  1. picks the active skin and serves its static assets + entry page, and
  2. provides the ``sustech_survival.api`` Flask-free data contract.

The HTTP ``/api/*`` routes themselves are implemented by the webui
blueprints (``webui/blueprints/*``) and wrap the ``sustech_survival.api``
data functions. A custom head may call ``sustech_survival.api`` directly
instead of going through the web UI.

Skins are self-contained folders under ``webui/skins/`` (shipped default) or
the user's home dot-directory (user-installed — ``~/.sustech_survival/skins/``,
override ``$SUSTECH_CONFIG_DIR``; see :mod:`sustech_survival._cache`). Each
skin has a ``manifest.json`` describing its name, entry page, which ``/api/*``
endpoints it needs, and the minimum ``sustech_survival`` module version it
requires (``requires``).

Core ``sustech_survival`` never imports this module; the CLI's ``sustech
webui serve`` lazily imports it. A user can drop ``webui/`` entirely and the
whole ``sustech_survival`` API still works (via ``sustech_survival.api`` /
the CLI).

Layout of a skin::

    my-skin/
      manifest.json      # {"name", "version", "entry", "requires", ...}
      index.html         # served at / when the skin is active
      static/            # served at /static/<path> (skin-static)
        index.zh.html     # optional localized entry page (?lang=zh / --lang zh)
        tis.html           # optional TIS page (tis.zh.html for Chinese)

      api-note.md        # (optional) which /api/* this skin uses
        index.zh.html     # optional localized entry page (?lang=zh / --lang zh)
        tis.html           # optional TIS page (tis.zh.html for Chinese)


``manifest.json`` fields:
  - ``name``   required            — the skin's unique name
  - ``entry``  optional (default ``index.html``) — entry page
  - ``version`` optional (default ``0``)          — the skin's own version
  - ``requires`` optional          — minimum ``sustech_survival`` module
                        version this skin needs, e.g. ``"2026.8.16"``.
                        If the running module is older, the loader warns
                        (or errors when ``strict=True``).
  - ``api``    optional            — the ``/api/*`` endpoints the skin calls
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from .._cache import config_root
from .._version import __version__

# Shipped default skin lives in this package under skins/default.
_PKG_SKINS = Path(__file__).resolve().parent / "skins"
# User-installed skins live in the user's home dot-directory
# (`~/.sustech_survival/skins`, or $SUSTECH_CONFIG_DIR/skins) — OWNED user
# data, so it sits beside (not inside) the disposable cache. Consistent with
# the project's unified on-disk store (see sustech_survival._cache).
_USER_SKINS = config_root() / "skins"


def _parse_version(v: str) -> tuple:
    """Best-effort numeric version tuple for comparisons.

    ``sustech_survival`` versions look like ``2026.8.16.dev0220``; we compare
    the leading integer dotted segments numerically and ignore any trailing
    alpha/dev suffix.
    """
    import re
    parts = []
    for seg in re.split(r"[.-]", str(v)):
        m = re.match(r"(\d+)", seg)
        if m is None:
            break
        parts.append(int(m.group(1)))
    return tuple(parts)


def _version_ge(installed: str, required: str) -> bool:
    """True if ``installed`` >= ``required`` (numeric dotted comparison)."""
    return _parse_version(installed) >= _parse_version(required)


@dataclass(frozen=True)
class Skin:
    """One installed skin."""
    name: str
    version: str
    root: Path
    entry: str = "index.html"
    requires: str = ""               # minimum sustech_survival version, if any

    @property
    def index(self) -> Path:
        return self.root / self.entry

    def check_requires(self) -> str | None:
        """Return a warning string if this skin needs a newer sustech_survival."""
        if not self.requires:
            return None
        if not _version_ge(__version__, self.requires):
            return (
                f"skin {self.name!r} requires sustech_survival >= "
                f"{self.requires}, but the installed module is {__version__}"
            )
        return None


def _read_manifest(skin_dir: Path) -> dict:
    mf = skin_dir / "manifest.json"
    if not mf.exists():
        return {"name": skin_dir.name, "version": "0", "entry": "index.html"}
    return json.loads(mf.read_text(encoding="utf-8"))


def _is_valid_skin(skin_dir: Path) -> bool:
    mf = _read_manifest(skin_dir)
    return (skin_dir / (mf.get("entry") or "index.html")).is_file()


def _to_skin(d: Path) -> Skin:
    mf = _read_manifest(d)
    return Skin(
        name=mf.get("name", d.name),
        version=str(mf.get("version", "0")),
        root=d,
        entry=mf.get("entry", "index.html"),
        requires=str(mf.get("requires", "") or ""),
    )


def default_skin() -> Path:
    """Path to the shipped default skin."""
    return _PKG_SKINS / "default"


def installed_skins() -> "list[Skin]":
    """Return skins available to load: user cache first, then shipped default."""
    out: list[Skin] = []
    seen: set[str] = set()
    for base in (_USER_SKINS, _PKG_SKINS):
        if not base.exists():
            continue
        for d in sorted(base.iterdir()):
            if not d.is_dir() or not _is_valid_skin(d):
                continue
            s = _to_skin(d)
            if s.name in seen:
                continue
            seen.add(s.name)
            out.append(s)
    return out


def find_skin(name: str) -> Skin:
    """Resolve a skin by name (user cache first, then shipped default).

    Raises ``KeyError`` with the available skin names when no match is found.
    """
    try:
        return next(s for s in installed_skins() if s.name == name)
    except StopIteration:
        available = ", ".join(sorted(s.name for s in installed_skins())) or "(none)"
        raise KeyError(
            f"skin {name!r} is not installed. available skins: {available}") from None


def skin_from_path(path: Path | str) -> Skin:
    """Build a ``Skin`` from a literal directory, without installing it.

    Used by ``sustech webui serve --skin-path <dir>`` so a skin can be
    served directly from anywhere (no copy into the cache needed). Raises
    ``ValueError`` if ``path`` isn't a valid skin directory.
    """
    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"not a directory: {root}")
    if not _is_valid_skin(root):
        raise ValueError(
            f"not a valid skin (missing manifest.json or entry page): {root}")
    return _to_skin(root)


def install_skin(src: Path | str, *, default: bool = False) -> Path:
    """Install a skin (a dir with a manifest.json) into the user cache.

    ``default=True`` copies the shipped default skin (so the user can then mod
    it without touching the installed package). Otherwise ``src`` is a path to
    a skin directory.
    """
    src = Path(src)
    if default:
        src = default_skin()
    if not _is_valid_skin(src):
        raise ValueError(
            f"not a valid skin (missing manifest.json or entry page): {src}")
    mf = _read_manifest(src)
    name = mf.get("name") or src.name
    dst = _USER_SKINS / name
    dst.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst, dirs_exist_ok=True)
    return dst


__all__ = ["Skin", "default_skin", "find_skin", "installed_skins",
           "install_skin", "skin_from_path", "_PKG_SKINS", "_USER_SKINS"]
