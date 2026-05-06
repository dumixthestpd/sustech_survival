#!/usr/bin/env python3
"""bb — DEPRECATED shim. Use run_bb.py or 'import bb' from sustech-survival/."""
import sys
from pathlib import Path

# Add sustech-survival/ so 'import bb' resolves to the package (bb/__init__.py)
_parent = Path(__file__).resolve().parent.parent
if str(_parent) not in sys.path:
    sys.path.insert(0, str(_parent))

# Delegate to the actual CLI
from bb.cli import cli
sys.exit(cli())
