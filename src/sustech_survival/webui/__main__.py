"""``python -m sustech_survival.webui`` — the unified web UI entry point.

Supports the documented form::

    python -m sustech_survival.webui serve [--port N] [--host H] \\
        [--transit-data DIR] [--skin NAME] [--skin-path DIR] [--debug]

With NO subcommand it prints usage and exits — it never starts a server
implicitly; ``serve`` must be explicit. Also reachable via the unified CLI
``sustech webui serve`` / ``sustech webui open``.
"""
from __future__ import annotations

import sys

from sustech_survival.webui.app import DEFAULT_PORT, run

_USAGE = ("usage: python -m sustech_survival.webui serve [--port N] [--host H] "
          "[--transit-data DIR] [--skin NAME] [--skin-path DIR] [--debug]")


def main() -> int:
    argv = sys.argv[1:]
    debug = "--debug" in argv or "-d" in argv
    port = None
    host = "0.0.0.0"
    transit_data = None
    skin = None
    skin_path = None

    if not argv:
        print(_USAGE)
        return 2  # missing subcommand — show usage, do not serve
    if argv[0] != "serve":
        if argv[0] in ("--help", "-h"):
            print(_USAGE)
            return 0
        print(_USAGE)
        print(f"error: unknown subcommand {argv[0]!r} — only `serve` is supported")
        return 2
    argv = argv[1:]
    # parse --port/-p, --host/-H, --transit-data, --skin, --skin-path
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--port", "-p") and i + 1 < len(argv):
            port = int(argv[i + 1]); i += 2; continue
        if a in ("--host", "-H") and i + 1 < len(argv):
            host = argv[i + 1]; i += 2; continue
        if a == "--transit-data" and i + 1 < len(argv):
            transit_data = argv[i + 1]; i += 2; continue
        if a == "--skin" and i + 1 < len(argv):
            skin = argv[i + 1]; i += 2; continue
        if a == "--skin-path" and i + 1 < len(argv):
            skin_path = argv[i + 1]; i += 2; continue
        if a in ("--debug", "-d"):
            i += 1; continue
        if a in ("--help", "-h"):
            print(_USAGE)
            return 0
        i += 1

    return run(port=port or DEFAULT_PORT, host=host,
               transit_data_dir=transit_data, skin=skin, skin_path=skin_path,
               debug=debug)


if __name__ == "__main__":
    raise SystemExit(main())
