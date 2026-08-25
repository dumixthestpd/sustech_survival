"""
sustech_survival.api — the core JSON data contract for the web/skin head.

This package exposes **Flask-free** functions that return the exact JSON-ready
dicts the UI consumes. It is the stable contract a skin/mod/bespoke UI builds
against, independent of any particular head (Flask webui, a native app, a CLI
dashboard, …).

- ``api.tis``    — course info/catalog/enrolled + write proxies (add/drop/cart)
- ``api.transit``— live bus positions, facilities
- ``api.nces``   — course-evaluation listing/search/detail

None of these import Flask. The webui blueprints wire these data functions
into the HTTP ``/api/*`` routes; a bespoke head (native app, CLI dashboard,
skin) can call them directly.
"""
from __future__ import annotations

from . import tis, transit, nces

__all__ = ["tis", "transit", "nces"]
