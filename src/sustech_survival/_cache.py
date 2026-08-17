"""Uniform cache layout: <cwd>/__sustech_cache__/<module>/...

All persistent caches in sustech_survival live in ONE unified directory
named ``__sustech_cache__`` (pytest-style), resolved against the working
directory and managed exclusively by this module:

- One canonical location next to wherever the user runs the program —
  no scattered dirs, no XDG branching, no writes into the user profile.
- When running inside a clone, the cache is ``<cwd>/__sustech_cache__/``
  and is meant to be gitignored (see the repo's .gitignore).
- When installed via ``pip``, the cache lands in the working directory the
  user invokes the tool from — always writable, always one dir.

Every module that needs to cache anything on disk should use these helpers
rather than constructing its own paths. The canonical root is the single
path returned by :func:`tmp_root` — there are no legacy locations.

Override: set ``$SUSTECH_CACHE_DIR`` (absolute or relative — relative
resolves against the working directory at call time), or pass ``root=`` to
:func:`cache_path` / :func:`tmp_root`-based functions explicitly.
No config file, no settings registry — kwargs and one env var.
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
# must call tmp_root() — the active root defaults to <cwd>/__sustech_cache__
# and honours $SUSTECH_CACHE_DIR.
TMP_ROOT: Path = _PACKAGE_ROOT / "tmp"

# Default unified cache dir name (pytest-style). May be overridden by the
# SUSTECH_CACHE_DIR env var or an explicit root= kwarg.
DEFAULT_CACHE_DIR = "__sustech_cache__"


def package_root() -> Path:
    """The ``sustech_survival/`` directory containing this module."""
    return _PACKAGE_ROOT


def tmp_root(root: Optional[Path] = None) -> Path:
    """The active cache root.

    Precedence: explicit ``root`` kwarg > ``$SUSTECH_CACHE_DIR`` env var >
    ``<cwd>/__sustech_cache__``. Relative values resolve against the working
    directory at call time. Reading this (not the bare ``TMP_ROOT``
    constant) is the correct way to locate the cache.
    """
    raw = root or os.environ.get("SUSTECH_CACHE_DIR") or DEFAULT_CACHE_DIR
    p = Path(raw).expanduser()
    return p if p.is_absolute() else Path.cwd() / p


def cache_path(module: str, *parts: str, root: Optional[Path] = None) -> Path:
    """Return ``<root>/<module>/<parts...>`` where ``<root>`` is the active
    cache root (:func:`tmp_root` — kwarg ``root``, env ``SUSTECH_CACHE_DIR``,
    or the default ``<cwd>/__sustech_cache__``).

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