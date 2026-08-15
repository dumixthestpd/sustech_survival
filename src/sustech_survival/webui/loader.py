"""
sustech_survival.webui.loader — the skin loader (the "head").

This is a THIN, replaceable layer. It does two things:

  1. picks the active skin and serves its static assets + entry page, and
  2. mounts the ``/api/*`` JSON contract, implemented in
     ``sustech_survival.api`` (the core, Flask-free data layer).

Skins are self-contained folders under ``webui/skins/`` (shipped default) or
``~/.config/sustech-survival/webui/skins/`` (user-installed). Each skin has a
``manifest.json`` describing its name, entry page, and which ``/api/*``
endpoints it needs.

Core ``sustech_survival`` never imports this module; the CLI's ``sustech
webui serve`` lazily imports it. A user can drop ``webui/`` entirely and the
whole ``sustech_survival`` API still works (via ``sustech_survival.api`` /
the CLI).

Layout of a skin::

    my-skin/
      manifest.json      # {"name", "version", "entry": "index.html"}
      index.html         # served at / when the skin is active
      static/            # served at /static/<path> (skin-static)
      api-note.md        # (optional) which /api/* this skin uses
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

# Shipped default skin lives in this package under skins/default.
_PKG_SKINS = Path(__file__).resolve().parent / "skins"
# User-installed skins cache.
_USER_SKINS = Path.home() / ".config" / "sustech-survival" / "webui" / "skins"


@dataclass(frozen=True)
class Skin:
    """One installed skin."""
    name: str
    version: str
    root: Path
    entry: str = "index.html"

    @property
    def index(self) -> Path:
        return self.root / self.entry


def _read_manifest(skin_dir: Path) -> dict:
    mf = skin_dir / "manifest.json"
    if not mf.exists():
        return {"name": skin_dir.name, "version": "0", "entry": "index.html"}
    return json.loads(mf.read_text(encoding="utf-8"))


def _is_valid_skin(skin_dir: Path) -> bool:
    mf = _read_manifest(skin_dir)
    return (skin_dir / (mf.get("entry") or "index.html")).is_file()


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
            mf = _read_manifest(d)
            name = mf.get("name", d.name)
            if name in seen:
                continue
            seen.add(name)
            out.append(Skin(name=name, version=str(mf.get("version", "0")),
                            root=d, entry=mf.get("entry", "index.html")))
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
           "install_skin", "_PKG_SKINS", "_USER_SKINS"]
