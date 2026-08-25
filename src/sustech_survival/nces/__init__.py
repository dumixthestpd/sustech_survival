"""
sustech_survival.nces — NCES (Niuwa Curriculum Evaluation System) client.

NCES is a student-built community course evaluation platform at ncesnext.com.
Parallel to tis/bb/lib — has its own CAS-based SSO via cas-proxy.cra.moe.

Public data (course names, ratings, dimension aggregates) is accessible
without login via the listing pages, which are behind Anubis PoW.
We solve Anubis server-side and cache the data locally for fast lookup.

Login-only reviews (per-user review text) require full CAS auth via the
cas-proxy.cra.moe redirect — scaffolded but not yet implemented.

Install:
    pip install sustech_survival[nces]   # adds anubis-solver dep
"""
from __future__ import annotations

from typing import TYPE_CHECKING

__all__ = ["NCESAuth", "NCESScraper", "NCESCourse"]


def __getattr__(name: str):
    """PEP 562 lazy attribute access — real classes live in submodules.

    Loading nces.<X> pulls in anubis-solver (heavy optional dep) plus
    bs4/regex deps. Lazy-load so plain `import sustech_survival.nces`
    doesn't break code paths that don't need it.
    """
    if name == "NCESAuth":
        from .auth import NCESAuth
        return NCESAuth
    if name == "NCESCourse":
        from .scraper import NCESCourse
        return NCESCourse
    if name == "NCESScraper":
        from .scraper import NCESScraper
        return NCESScraper
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if TYPE_CHECKING:  # pragma: no cover
    from .auth import NCESAuth
    from .scraper import NCESScraper, NCESCourse