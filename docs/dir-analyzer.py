#!/usr/bin/env python3
"""
Dir Analyzer — dumps a readable directory structure for reference/sharing.
Run on Windows, paste output to an agent.

Usage:
    python dir-analyzer.py [path] [--depth N] [--exclude pattern]

Example:
    python dir-analyzer.py C:\\Users\\dumix\\Documents
    python dir-analyzer.py . --depth 3 --exclude "node_modules"
"""

import os
import sys
import argparse
from pathlib import Path


def format_size(size_bytes):
    if size_bytes < 1024:
        return f"{size_bytes}B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f}KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024*1024):.1f}MB"
    else:
        return f"{size_bytes / (1024*1024*1024):.1f}GB"


def should_exclude(name, exclude_patterns):
    for pat in exclude_patterns:
        if pat in name:
            return True
    return False


def analyze(path, depth=99, exclude_patterns=None, indent=0, max_per_dir=20):
    if exclude_patterns is None:
        exclude_patterns = []

    indent_str = "    " * indent
    prefix = "└── " if indent > 0 else ""

    try:
        entries = os.listdir(path)
    except PermissionError:
        return []
    except FileNotFoundError:
        return []

    lines = []

    # Separate dirs and files
    dirs = []
    files = []
    for e in entries:
        if should_exclude(e, exclude_patterns):
            continue
        full = os.path.join(path, e)
        if os.path.isdir(full):
            dirs.append(e)
        else:
            files.append(e)

    # Show dirs first
    for d in sorted(dirs):
        if depth <= 0:
            lines.append(f"{indent_str}{prefix}{d}/  [truncated]")
            continue
        lines.append(f"{indent_str}{prefix}{d}/")
        sub_lines = analyze(
            os.path.join(path, d),
            depth=depth - 1,
            exclude_patterns=exclude_patterns,
            indent=indent + 1,
            max_per_dir=max_per_dir
        )
        lines.extend(sub_lines)

    # Then files (limit shown)
    shown = sorted(files)[:max_per_dir]
    hidden = len(files) - len(shown)
    for f in shown:
        fpath = os.path.join(path, f)
        try:
            size = os.path.getsize(fpath)
            size_str = format_size(size)
            lines.append(f"{indent_str}{prefix}{f}  ({size_str})")
        except OSError:
            lines.append(f"{indent_str}{prefix}{f}")

    if hidden > 0:
        lines.append(f"{indent_str}{prefix}... (+{hidden} more files)")

    return lines


def main():
    parser = argparse.ArgumentParser(description="Analyze directory structure")
    parser.add_argument("path", nargs="?", default=".", help="Path to analyze")
    parser.add_argument("--depth", type=int, default=99, help="Max depth")
    parser.add_argument("--exclude", action="append", default=[], help="Exclude patterns (substring match)")
    parser.add_argument("--max-per-dir", type=int, default=20, help="Max files shown per directory")
    args = parser.parse_args()

    target = Path(args.path).resolve()

    if not target.exists():
        print(f"Path does not exist: {target}", file=sys.stderr)
        sys.exit(1)

    print(f"# Directory: {target}")
    print(f"# Depth: {args.depth} | Exclude: {args.exclude or 'none'} | Max files/dir: {args.max_per_dir}")
    print()

    lines = analyze(target, depth=args.depth, exclude_patterns=args.exclude, max_per_dir=args.max_per_dir)
    for line in lines:
        print(line)


if __name__ == "__main__":
    main()
