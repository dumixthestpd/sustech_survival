#!/usr/bin/env python3
"""
bb CLI entry point.
Run from sustech-survival/ directory: python3 run_bb.py <command>
"""
import sys
from pathlib import Path

# Add bb/ package directory to sys.path so 'from cli import cli' works
_bb_dir = Path(__file__).parent / "bb"
sys.path.insert(0, str(_bb_dir))

from cli import cli

if __name__ == "__main__":
    sys.exit(cli())
