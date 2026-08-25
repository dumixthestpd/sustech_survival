"""sustech_survival unified CLI — ``sustech <subcommand>`` dispatch.

Every subcommand group lives in a sibling module under ``cli/``
(``transit.py``, ``faculty.py``, ``booking.py``, …) and is registered
on the top-level Click ``cli`` group here.

Big external CLIs (bb, tis, ws, nces) re-mount from their module's own
``cli.py`` via ``_mount``.  Everything else calls the module's Python API
directly — no per-module Click wrapper needed.
"""
from __future__ import annotations

import sys

import click

from . import main as _main

# Windows consoles often use a legacy codepage (cp936/GBK on Chinese
# systems) that cannot encode the emoji used across CLI output (✅ ⚠️ ❌ …).
# Without this, ANY command that prints one of those characters dies with
# UnicodeEncodeError before doing its job. Reconfigure stdout/stderr so
# unencodable characters are replaced instead of raising.
for _stream_name in ("stdout", "stderr"):
    _stream = getattr(sys, _stream_name, None)
    reconfigure = getattr(_stream, "reconfigure", None)
    if reconfigure is not None:
        try:
            reconfigure(errors="replace")
        except Exception:  # pragma: no cover - stream may be closed/None
            pass
del _stream_name, _stream, reconfigure

# Re-export the Click group object so pyproject.toml [project.scripts]
# can point to sustech_survival.cli:cli
cli = _main.build_cli()

__all__ = ["cli"]
