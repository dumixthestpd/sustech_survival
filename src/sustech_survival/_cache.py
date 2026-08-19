"""Unified on-disk store under the user's home: ~/.sustech_survival/.

All user-owned data sustech_survival persists lives in ONE dot-directory in
the user's home, ``~/.sustech_survival/``, managed exclusively by this module:

- ``~/.sustech_survival/cache/<module>/`` — disposable caches (calendar,
  BB, classroom, selectcourse) plus any per-module working files. This
  replaces the old cwd-relative ``__sustech_cache__`` root.
- ``~/.sustech_survival/skins/``     — user-installed webui skins.
- ``~/.sustech_survival/config.json``— the one user-editable settings file.
- ``~/.sustech_survival/credentials.txt`` — shared credentials (default).

Rationale for a home dotdir (vs the previous cwd ``__sustech_cache__``):
  - Deterministic across working directories — data no longer lands in
    *whichever* directory the CLI happened to be run from.
  - A dotfile is the conventional home for durable user state.
  - Caches and user-owned data are kept apart: disposable derived data under
    ``cache/``, things the user actually owns (skins / credentials / config)
    elsewhere under the same root.

Every module that caches on disk should use these helpers rather than
constructing its own paths. The canonical roots are :func:`config_root`
(user data) and :func:`tmp_root`/`cache_path` (cache). There is no separate
scratch dir — staging and working files live under ``cache/<module>/`` like
everything else, so ``clear_cache`` means exactly "clear the cache".

Overrides:
  - ``$SUSTECH_HOME`` — relocate the WHOLE tree. Defaults to the user's home
    so the dir is ``~/.sustech_survival``; e.g. ``SUSTECH_HOME=D:/data`` puts
    everything under ``D:/data/.sustech_survival/``.
  - ``$SUSTECH_CONFIG_DIR`` — direct override of the dot-directory itself.
  - ``$SUSTECH_CACHE_DIR`` — relocate ONLY the cache root elsewhere (e.g.
    tests point this at ``tmp_path``). When unset the cache lives at
    ``config_root() / "cache"``.
  - ``root=`` kwarg to :func:`cache_path` / :func:`tmp_root` still wins.
The single user settings file is :func:`config_file`/`load_config`
(``config.json``); other than that — env vars and kwargs only.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional, Tuple


_PACKAGE_ROOT: Path = Path(__file__).resolve().parent
# Back-compat constant: the old default root next to the package. New code
# must call tmp_root() — the active cache root defaults to
# ~/.sustech_survival/cache and honours $SUSTECH_CACHE_DIR.
TMP_ROOT: Path = _PACKAGE_ROOT / "tmp"

# The single home dot-directory that holds all user-owned sustech_survival
# data (skins, credentials, config.json, and the default cache root). Its
# anchor defaults to the user's home (so the dir is ~/.sustech_survival) and
# can be relocated with $SUSTECH_HOME.
DEFAULT_CONFIG_DIR = ".sustech_survival"
# Disposable cache root name inside the config dir. May be relocated entirely
# via the SUSTECH_CACHE_DIR env var or an explicit root= kwarg.
CACHE_SUBDIR = "cache"


def package_root() -> Path:
    """The ``sustech_survival/`` directory containing this module."""
    return _PACKAGE_ROOT


def user_home() -> Path:
    """The current user's home directory.

    Resolved via ``~`` expansion (``Path("~").expanduser()``), which respects
    ``$HOME`` / ``USERPROFILE``. Kept as a small helper so callers and tests
    can redirect the home base deterministically.
    """
    return Path("~").expanduser()


def home_root(root: Optional[Path] = None) -> Path:
    """The anchor that holds the user data dot-directory.

    Precedence: explicit ``root`` kwarg > ``$SUSTECH_HOME`` env var >
    the user's home (``~``). ``$SUSTECH_HOME`` makes the whole
    ``.sustech_survival`` tree relocatable. Relative values resolve against
    the home dir.
    """
    raw = root or os.environ.get("SUSTECH_HOME")
    if raw:
        p = Path(raw).expanduser()
        return p if p.is_absolute() else user_home() / p
    return user_home()


def config_root(root: Optional[Path] = None) -> Path:
    """The home dot-directory holding user data: ``~/.sustech_survival``.

    Precedence: ``$SUSTECH_CONFIG_DIR`` env var (direct dotdir override) >
    ``home_root() / ".sustech_survival"`` (i.e. ``$SUSTECH_HOME/.sustech_survival``
    or the default ``~/.sustech_survival``). An explicit ``root`` kwarg wins.
    The directory is NOT created; callers create paths as needed.
    """
    direct = os.environ.get("SUSTECH_CONFIG_DIR")
    if direct:
        p = Path(direct).expanduser()
        return p if p.is_absolute() else user_home() / p
    return home_root(root) / DEFAULT_CONFIG_DIR


def config_file(filename: str = "config.json", root: Optional[Path] = None) -> Path:
    """A user-owned config file inside the dotdir: ``config_root()/filename``."""
    return config_root(root) / filename


def load_config(root: Optional[Path] = None) -> dict:
    """Read ``config_root()/config.json`` (empty dict if missing/corrupt).

    This is the project's single user-editable settings file. No schema is
    enforced here — consumers read the keys they care about.
    """
    return load_json(config_file(root=root)) or {}


def tmp_root(root: Optional[Path] = None) -> Path:
    """The active cache root.

    Precedence: explicit ``root`` kwarg > ``$SUSTECH_CACHE_DIR`` env var >
    ``config_root() / "cache"`` (i.e. ``~/.sustech_survival/cache`` by
    default). An explicit ``$SUSTECH_CACHE_DIR`` is absolute or resolves
    against the working directory at call time. Reading this (not the bare
    ``TMP_ROOT`` constant) is the correct way to locate the cache.
    """
    raw = root or os.environ.get("SUSTECH_CACHE_DIR")
    if raw:
        p = Path(raw).expanduser()
        return p if p.is_absolute() else Path.cwd() / p
    return config_root() / CACHE_SUBDIR


def cache_path(module: str, *parts: str, root: Optional[Path] = None) -> Path:
    """Return ``<root>/<module>/<parts...>`` where ``<root>`` is the active
    cache root (:func:`tmp_root` — kwarg ``root``, env ``SUSTECH_CACHE_DIR``,
    or the default ``~/.sustech_survival/cache``).

    The directory is NOT created — call :func:`ensure_cachedir` before
    writing. This split lets read-only probes (e.g. "does this cache file
    exist?") succeed without side effects.
    """
    if not module or "/" in module or "\\" in module or module in (".", ".."):
        raise ValueError(f"invalid cache module name: {module!r}")
    root = tmp_root(root)
    if parts:
        return root / module / Path(*parts)
    return root / module


def ensure_cachedir(path: Path) -> Path:
    """``mkdir -p`` on the given path; return the same path."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def clear_cache(module: str, root: Optional[Path] = None) -> int:
    """Delete every cached file under ``<root>/<module>/``.

    ``root`` defaults to the active cache root (:func:`tmp_root` — kwarg,
    env, or default unified dir). Returns the number of files removed.
    No-op (returns 0) if the module has no cache yet. Granular cleanup (e.g.
    "only year 2026 of the calendar cache") is the responsibility of the
    module that owns the cache layout — this helper wipes everything for a
    module in one shot.
    """
    import shutil
    if not module or "/" in module or "\\" in module or module in (".", ".."):
        raise ValueError(f"invalid cache module name: {module!r}")
    target = tmp_root(root) / module
    if not target.exists():
        return 0
    count = sum(1 for _ in target.rglob("*") if _.is_file())
    shutil.rmtree(target, ignore_errors=True)
    return count


def save_json(target: Path, data: Any) -> Path:
    """Atomically write JSON to ``target``.

    Uses the standard tmp-file-then-rename pattern so a reader never
    observes a half-written file, even if the process is killed mid-write.
    The ``.tmp`` sibling is created in the same directory (same filesystem)
    so the final ``replace`` is atomic.
    """
    ensure_cachedir(target.parent)
    fd, tmp_name = tempfile.mkstemp(
        prefix=target.name + ".",
        suffix=".tmp",
        dir=str(target.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, target)
    except Exception:
        # Don't leave the tmp file behind on failure.
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return target


def load_json(target: Path) -> Optional[Any]:
    """Load JSON from ``target``; return ``None`` if missing or corrupt.

    Corrupt files are silently ignored (treated as cache miss). Callers
    that want strict behaviour should ``open()`` themselves.
    """
    if not target.exists():
        return None
    try:
        with open(target, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def sha1_bytes(data: bytes) -> str:
    """Lowercase hex SHA-1, 40 chars."""
    return hashlib.sha1(data).hexdigest()


def sha1_file(target: Path) -> Optional[str]:
    """SHA-1 of a file's bytes; ``None`` if unreadable."""
    try:
        h = hashlib.sha1()
        with open(target, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def http_get_with_etag(
    url: str,
    etag: Optional[str] = None,
    timeout: float = 15.0,
) -> Tuple[Optional[bytes], Optional[str], int]:
    """HTTP GET with optional ``If-None-Match`` for conditional fetch.

    Returns ``(body, etag, status)``:

    - ``(None, etag, 304)`` — server says our cached copy is still fresh;
      body is ``None`` and the ETag echoed back is the one we sent.
    - ``(body, new_etag, 200)`` — fresh content; ``new_etag`` may be
      ``None`` if the server didn't send one.
    - Other status codes raise ``HTTPError`` (caller's responsibility).

    Used by the calendar module to avoid re-downloading JSONs that
    haven't changed upstream.
    """
    req = urllib.request.Request(url)
    if etag:
        req.add_header("If-None-Match", etag)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read(), resp.headers.get("ETag"), resp.status
    except urllib.error.HTTPError as e:
        if e.code == 304:
            return None, etag, 304
        raise