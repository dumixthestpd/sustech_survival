"""Uniform cache layout: <sustech_survival>/tmp/<module>/...

All persistent caches in sustech_survival live under the package's own
directory (resolved via ``Path(__file__).parent``), so:

- One canonical location, no env-var dance, no XDG branching.
- When running from a clone, cache is inside the repo (``src/sustech_survival/tmp/``)
  and is naturally gitignored.
- When installed via ``pip``, cache lives next to the package code in
  ``site-packages`` (writable on user installs on macOS / ``--user`` on Linux).

Every module that needs to cache anything on disk should use these helpers
rather than constructing its own paths. The canonical location is the
single path returned by :func:`tmp_root` — there are no legacy locations.
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
# Default cache root lives next to the package. The override-able setting
# `cache.dir` (see _settings) may redirect it to a writable dir for a
# system install; tmp_root() honours that. Modules that cache must call
# tmp_root()/cache_path(), not read TMP_ROOT directly.
TMP_ROOT: Path = _PACKAGE_ROOT / "tmp"


def package_root() -> Path:
    """The ``sustech_survival/`` directory containing this module."""
    return _PACKAGE_ROOT


def tmp_root() -> Path:
    """The active cache root — default `<package>/tmp`, overridable via settings.

    Reading this (not the bare ``TMP_ROOT`` constant) is the correct way to
    locate the cache, so a ``SUSTECH_CACHE_DIR``/config override is honoured.
    """
    from . import _settings
    return Path(_settings.cache_dir) if _settings.cache_dir else TMP_ROOT


def cache_path(module: str, *parts: str) -> Path:
    """Return ``<root>/<module>/<parts...>`` where ``<root>`` is the active
    cache root (:func:`tmp_root`, which honours the ``cache.dir`` setting).

    The directory is NOT created — call :func:`ensure_cachedir` before
    writing. This split lets read-only probes (e.g. "does this cache file
    exist?") succeed without side effects.
    """
    if not module or "/" in module or "\\" in module or module in (".", ".."):
        raise ValueError(f"invalid cache module name: {module!r}")
    root = tmp_root()
    if parts:
        return root / module / Path(*parts)
    return root / module


def ensure_cachedir(path: Path) -> Path:
    """``mkdir -p`` on the given path; return the same path."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def clear_cache(module: str) -> int:
    """Delete every cached file under ``<root>/<module>/`` where ``<root>`` is
    the active cache root (:func:`tmp_root`).

    Returns the number of files removed. No-op (returns 0) if the module
    has no cache yet. Granular cleanup (e.g. "only year 2026 of the
    calendar cache") is the responsibility of the module that owns the
    cache layout — this helper wipes everything for a module in one shot.
    """
    import shutil
    if not module or "/" in module or "\\" in module or module in (".", ".."):
        raise ValueError(f"invalid cache module name: {module!r}")
    target = tmp_root() / module
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