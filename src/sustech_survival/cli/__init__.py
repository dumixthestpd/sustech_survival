"""sustech-survival unified CLI — ``sustech <subcommand>`` dispatch.

Every subcommand group lives in a sibling module under ``cli/``
(``transit.py``, ``faculty.py``, ``booking.py``, …) and is registered
on the top-level Click ``cli`` group here.

Big external CLIs (bb, tis, ws, nces) re-mount from their module's own
``cli.py`` via ``_mount``.  Everything else calls the module's Python API
directly — no per-module Click wrapper needed.
"""
from __future__ import annotations

import click

from . import main as _main

# Re-export the Click group object so pyproject.toml [project.scripts]
# can point to sustech_survival.cli:cli
cli = _main.build_cli()

__all__ = ["cli"]
