"""
CLI: python -m sustech_survival.webui

    serve [--port N] [--transit-data DIR] [--debug]
        Start the unified web UI (default :61019).

    --transit-data DIR   Directory of exported transit GeoJSON
                         (run: python -m sustech_survival.transit export DIR)
                         If omitted, /transit shows an empty map.
"""
from __future__ import annotations

import argparse
import sys

from .app import run, DEFAULT_PORT


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m sustech_survival.webui",
        description="Unified SUSTech web UI (course selector + transit map)",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="start the web UI")
    s.add_argument("--port", type=int, default=DEFAULT_PORT)
    s.add_argument("--transit-data", default=None,
                   help="directory of exported transit GeoJSON")
    s.add_argument("--debug", action="store_true")
    s.set_defaults(func=cmd_serve)

    args = p.parse_args(argv)
    return args.func(args)


def cmd_serve(args) -> int:
    return run(port=args.port, transit_data_dir=args.transit_data,
               debug=args.debug)


if __name__ == "__main__":
    sys.exit(main())
