#!/usr/bin/env python3
"""
Lightweight file-based cache for BB scraper results.

Storage layout (uniform across the package):

    <cwd>/__sustech_cache__/bb/{prefix}_{arg1}_{arg2}.json

Each entry is a JSON file:
    {"ts": unix_timestamp, "ttl": seconds, "data": ...}

The previous location (``<skill_root>/.cache/bb/``) is no longer written.
"""
import json, time
from pathlib import Path

from sustech_survival import _cache as _pkg_cache

CACHE_DIR = _pkg_cache.cache_path("bb")
# NOT created at import — cache_path must stay side-effect free (iron law:
# read-only probes never touch disk). set() ensures the dir before writing.

DEFAULT_TTL = 3600  # 1 hour


def cache_key(prefix, *args) -> str:
    """Build a safe filename from prefix + args."""
    parts = [prefix] + [str(a).replace("/", "_").replace("=", "_") for a in args]
    return "_".join(parts) + ".json"


def get(prefix: str, *args, ttl: int = DEFAULT_TTL):
    """
    Return cached data if fresh (within TTL seconds), else None.
    Returns (data, is_cached) tuple.
    """
    key_file = CACHE_DIR / cache_key(prefix, *args)
    if not key_file.exists():
        return None, False
    try:
        with open(key_file) as f:
            entry = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None, False
    age = time.time() - entry.get("ts", 0)
    if age > ttl:
        return None, False
    return entry.get("data"), True


def set(prefix: str, data, *args, ttl: int = DEFAULT_TTL):
    """Write data to cache with current timestamp."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key_file = CACHE_DIR / cache_key(prefix, *args)
    entry = {"ts": time.time(), "ttl": ttl, "data": data}
    with open(key_file, "w") as f:
        json.dump(entry, f)


def invalidate(prefix: str, *args):
    """Remove a specific cache entry."""
    key_file = CACHE_DIR / cache_key(prefix, *args)
    if key_file.exists():
        key_file.unlink()


def invalidate_all(prefix: str = None):
    """Remove all cache entries, or only those matching prefix (substring match)."""
    if prefix is None:
        for f in CACHE_DIR.glob("*"):
            f.unlink()
    else:
        for f in CACHE_DIR.glob("*"):
            if prefix in f.name:
                f.unlink()
