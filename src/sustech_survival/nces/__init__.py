"""
sustech_survival.nces — NCES (南科大课程评价社区) client stub.

This submodule is intentionally minimal — the legacy ``auth`` and ``eval``
modules were lost in a refactor and not yet reimplemented. Most users
should go through the unified web UI's ``/api/tis/nces?code=X`` endpoint,
which serves direct URLs to ncesnext.com.

If you need programmatic NCES access, the legacy code path is to scrape
ncesnext.com directly — it's a JS-rendered site with bot protection, so
server-side fetching is unreliable. Use a headless browser instead.

Submodule CLI / public symbols are lazy-imported so importing this package
doesn't break unrelated code.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

__all__ = ["NCESAuthorizer", "NCESSurvey"]


def __getattr__(name: str):
    """PEP 562 lazy attribute access — raise a clear error if anything tries
    to use the not-yet-reimplemented NCES classes."""
    if name in __all__:
        raise NotImplementedError(
            f"sustech_survival.nces.{name} is not implemented yet. "
            "Use the web UI at /api/tis/nces?code=X for now, or scrape "
            "ncesnext.com directly via a headless browser."
        )
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if TYPE_CHECKING:  # pragma: no cover
    from typing import Any

    NCESAuthorizer: Any
    NCESSurvey: Any