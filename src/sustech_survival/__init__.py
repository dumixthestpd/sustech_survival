# sustech_survival — SUSTech Academic Toolkit
# =============================================================================
# A unified Python package for SUSTech academic systems.
#
# Usage:
#     import sustech_survival as sustech
#     sustech.bb.courses()
#     sustech.tis.courses()
#     sustech.lib.login()
#     sustech.papers.search_and_fetch(queries=["electrochromic polymer"])
#
# Or import submodules directly:
#     from sustech_survival import bb, tis, lib, sso, papers
#     from sustech_survival.sso import Authorizer, require_auth
# =============================================================================

from pathlib import Path

__all__ = ["bb", "tis", "lib", "sso", "papers", "Context", "Level"]

_PKG_ROOT = Path(__file__).resolve().parent

# ── bb ────────────────────────────────────────────────────────────────────
from . import bb

# ── tis ───────────────────────────────────────────────────────────────────
from . import tis

# ── lib ───────────────────────────────────────────────────────────────────
from . import lib

# ── sso ───────────────────────────────────────────────────────────────────
from . import sso

# ── papers ─────────────────────────────────────────────────────────────────
from . import papers

# ── context (replaces old quickcontext) ─────────────────────────────────
from .context import Context, Level  # noqa: F401