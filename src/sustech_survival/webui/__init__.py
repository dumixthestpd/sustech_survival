"""
sustech_survival.webui — unified web UI for the SUSTech toolkit.

One Flask app, one port (:20129 by default). A landing page at ``/``
navigates to submodule pages (TIS course selector, transit map), each
backed by a JSON REST API under ``/api/<submodule>/...``.

This is an OPTIONAL submodule — it depends on Flask (``pip install
"sustech_survival[webui]"``). No other submodule imports Flask; the
blueprints are registered lazily, so a plain ``pip install
sustech_survival`` is unaffected.

The browser never talks to SUSTech directly. Every ``/api/*`` route
calls the existing Python clients (``SelectCourseClient``,
``TransitClient``, NCES) server-side, so credentials and cookies never
leave the process.

Quick start::

    python -m sustech_survival.webui serve            # http://localhost:20129
    python -m sustech_survival.webui serve --port 7000
"""
from __future__ import annotations

from .app import create_app, run

__all__ = ["create_app", "run"]