"""
sustech_survival.transit — CLI.

Usage:
    python -m sustech_survival.transit <command> [...]

Commands:
    facilities                List all buildings + gates
    find QUERY                Fuzzy name search
    stops [--line L] [--dir N]  List bus stops (optionally filtered)
    lines [--day workday|holiday]  List bus line configs
    schedule LINE_ID [--sub N] [--day workday|holiday]
                              Show departure times for a line
    live                      Poll live bus GPS positions
    route FROM TO [--mode walk|bus|transit] [--walk-radius N]
                              Find shortest path between two facilities
    export OUT_DIR            Bundle all data to GeoJSON + JSON for the web UI
    serve [--port N]          Start the web UI on a port (default 61019)
    web-build OUT_DIR         Write static web files to OUT_DIR (no server)

All output is plain text — readable for both humans and LLMs. Use --json for
machine-readable output.
"""
from __future__ import annotations

import argparse
import http.server
import json
import os
import socketserver
import sys
import time
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import (
    DAY_WORKDAY, DAY_HOLIDAY, ROUTE_XYBS1, ROUTE_XYBS2, DIR_CW, DIR_CCW,
    KIND_BUILDING, KIND_GATE, KIND_BUS_STOP,
)
from .transit import TransitClient, TransitError


def _client(args) -> TransitClient:
    return TransitClient()


def _now_min() -> int:
    n = datetime.now()
    return n.hour * 60 + n.minute


# ── Output formatting ───────────────────────────────────────────────────────

def _print_facility(f, *, json_out: bool):
    if json_out:
        print(json.dumps({
            "id": f.facility_id, "name": f.name, "name_en": f.name_en,
            "kind": f.kind, "lat": f.lat, "lng": f.lng, "routes": f.routes,
        }, ensure_ascii=False))
        return
    icon = {"building": "🏢", "gate": "🚪", "bus_stop": "🚏"}.get(f.kind, "·")
    print(f"{icon} {f.display_name}  ({f.facility_id})")


def _print_line(line, *, json_out: bool):
    if json_out:
        print(json.dumps({
            "id": line.id, "title": line.title,
            "routes": [{"name": r.name, "description": r.description,
                        "type": r.kind, "color": r.color,
                        "line_code": r.line_code, "direction": r.direction,
                        "sources": r.sources} for r in line.routes],
        }, ensure_ascii=False))
        return
    print(f"### {line.title}  [{line.id}]")
    for i, r in enumerate(line.routes):
        print(f"  {i}. {r.name}")
        print(f"     {r.description.replace(chr(10), ' / ')}")


def _print_schedule(s, *, json_out: bool):
    if json_out:
        print(json.dumps({
            "line_id": s.line_id, "title": s.title, "day_type": s.day_type,
            "sub_route": s.sub_route_name, "sub_desc": s.sub_route_desc,
            "color": s.color, "minute_on_road": s.minute_on_road,
            "times": s.times,
        }, ensure_ascii=False))
        return
    print(f"### {s.sub_route_name}  ({s.title})")
    print(f"**Day**: {s.day_type}  |  **Ride**: ~{s.minute_on_road} min")
    print(f"**Description**: {s.sub_route_desc}")
    print()
    nxt = s.next_departures(_now_min(), count=5)
    if nxt:
        print(f"**Next 5 departures**: {' '.join(nxt)}")
    else:
        print(f"**No more departures today**")
    print(f"**All times**: {', '.join(s.times[:20])}{'...' if len(s.times) > 20 else ''}")


def _print_live(bus, *, json_out: bool):
    if json_out:
        print(json.dumps({
            "id": bus.bus_id, "lat": bus.lat, "lng": bus.lng,
            "route_code": bus.route_code, "next_station": bus.next_station,
            "speed_kmh": bus.speed_kmh, "operating": bus.is_operating,
        }, ensure_ascii=False))
        return
    icon = "🚌" if bus.route_code.startswith("NKDH") else "🚐"
    print(f"{icon} {bus.route_code:<10s} {bus.next_station:<20s}  "
          f"({bus.lat:.5f}, {bus.lng:.5f})  speed={bus.speed_kmh:.1f}")


def _print_path(p, *, json_out: bool):
    if json_out:
        print(json.dumps({
            "origin": p.origin, "destination": p.destination,
            "total_minutes": p.total_minutes, "total_meters": p.total_meters,
            "steps": [{"mode": s.mode, "from": s.from_name, "to": s.to_name,
                       "duration_min": s.duration_min, "distance_m": s.distance_m,
                       "details": s.details} for s in p.steps],
        }, ensure_ascii=False))
        return
    print(p.to_markdown())


# ── Command handlers ────────────────────────────────────────────────────────

def cmd_facilities(args) -> int:
    c = _client(args)
    facs = c.list_facilities()
    if not args.json:
        b = sum(1 for f in facs if f.kind == KIND_BUILDING)
        g = sum(1 for f in facs if f.kind == KIND_GATE)
        print(f"# {len(facs)} facilities ({b} buildings, {g} gates)")
        print()
    for f in facs:
        _print_facility(f, json_out=args.json)
    return 0


def cmd_find(args) -> int:
    c = _client(args)
    hits = c.find_facility(args.query)
    if not args.json:
        print(f"# {len(hits)} matches for {args.query!r}")
        print()
    for f in hits[:args.limit]:
        _print_facility(f, json_out=args.json)
    return 0


def cmd_stops(args) -> int:
    c = _client(args)
    if args.line and args.dir is not None:
        stops = c.get_bus_stops(args.line, args.dir)
    else:
        stops = []
        for line in c._line_codes():
            for d in (DIR_CW, DIR_CCW):
                for s in c._bus_stops_for(line, d):
                    stops.append(s)
        # Deduplicate by station_id, preserve first occurrence order
        seen = set()
        uniq = []
        for s in stops:
            if s.facility_id not in seen:
                seen.add(s.facility_id)
                uniq.append(s)
        stops = uniq
    if not args.json:
        print(f"# {len(stops)} bus stops")
        print()
    for s in stops:
        _print_facility(s, json_out=args.json)
    return 0


def cmd_lines(args) -> int:
    c = _client(args)
    lines = c.list_bus_lines(day_type=args.day)
    if not args.json:
        print(f"# {len(lines)} bus lines (day: {args.day})")
        print()
    for line in lines:
        _print_line(line, json_out=args.json)
    return 0


def cmd_schedule(args) -> int:
    c = _client(args)
    s = c.get_schedule(args.line, sub_route_index=args.sub, day_type=args.day)
    _print_schedule(s, json_out=args.json)
    return 0


def cmd_live(args) -> int:
    c = _client(args)
    buses = c.get_live_positions(include_shuttles=not args.no_shuttles)
    if not args.json:
        print(f"# {len(buses)} buses live now ({datetime.now().strftime('%H:%M:%S')})")
        print()
    for b in buses:
        _print_live(b, json_out=args.json)
    return 0


def cmd_route(args) -> int:
    c = _client(args)
    # Resolve query → facility_id via fuzzy search
    def _resolve(q: str) -> Optional[str]:
        if q in {f.facility_id for f in c.list_facilities()}:
            return q
        hits = c.find_facility(q)
        return hits[0].facility_id if hits else None

    frm = _resolve(args.from_)
    to = _resolve(args.to)
    if not frm:
        print(f"❌ Could not resolve origin: {args.from_!r}", file=sys.stderr)
        return 2
    if not to:
        print(f"❌ Could not resolve destination: {args.to!r}", file=sys.stderr)
        return 2

    if not args.json:
        print(f"# {frm} → {to}\n")
    try:
        path = c.shortest_path(frm, to, mode=args.mode, walk_radius_m=args.walk_radius)
    except TransitError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1
    _print_path(path, json_out=args.json)
    return 0


def cmd_export(args) -> int:
    c = _client(args)
    out_dir = Path(args.out_dir)
    if not args.json:
        print(f"# Exporting to {out_dir} …")
    written = c.export_geojson(out_dir, with_elevation=not args.no_elevation)
    if args.json:
        print(json.dumps(written, ensure_ascii=False))
    else:
        for k, v in written.items():
            if isinstance(v, list):
                print(f"  {k}:")
                for p in v:
                    print(f"    {p}")
            else:
                print(f"  {k}: {v}")
    return 0


def cmd_serve(args) -> int:
    """Start the web UI server.

    DEPRECATED: the standalone transit web UI on its own port is now part
    of the unified ``sustech_survival.webui`` app (single port 61019). This
    command delegates to it, passing along --port and the exported data dir
    so the existing campus-map frontend keeps working at /transit.
    """
    import sys
    print("⚠ `transit serve` is deprecated → launching unified web UI",
          file=sys.stderr)
    from sustech_survival.webui.app import run as _run
    return _run(port=args.port, transit_data_dir=args.data_dir, debug=False)
    out_dir = Path(args.data_dir)
    if not out_dir.exists():
        print(f"❌ data dir not found: {out_dir}", file=sys.stderr)
        print(f"   Run: python -m sustech_survival.transit export {out_dir}",
              file=sys.stderr)
        return 2
    # Always have a transit client available — the /api/walk_route
    # endpoint needs it. If --refresh, also re-export data first.
    transit_client = _client(args)
    if args.refresh:
        transit_client.export_geojson(out_dir, with_elevation=not args.no_elevation)

    # Background live-bus refresher. The frontend polls /data/live_buses.geojson
    # every 30s, but the file was only written once at server startup — so after
    # midnight (when no buses are running) the page would keep showing the last
    # stale set of buses. A 30s background refresh re-polls the live API and
    # rewrites the file, so when the last bus of the day signs off, the
    # frontend's next poll sees an empty FeatureCollection and clears the map.
    #   (User feedback 2026-06-13: "stale buses on the map but it is already
    #    past 00:00 and there is no bus".)
    import threading
    import time as _time
    def _refresh_live_buses_loop():
        while True:
            try:
                live = transit_client.get_live_positions(include_shuttles=True)
                live_fc = {
                    "type": "FeatureCollection",
                    "features": [b.to_geojson_feature() for b in live],
                }
                (out_dir / "live_buses.geojson").write_text(
                    json.dumps(live_fc, ensure_ascii=False, indent=2)
                )
            except Exception as e:
                # Don't crash the thread on a single transient failure; the
                # frontend will see stale data until the next tick succeeds.
                print(f"[live-refresh] {e}", file=sys.stderr)
            _time.sleep(30)
    threading.Thread(target=_refresh_live_buses_loop, daemon=True, name="live-bus-refresh").start()

    web_dir = Path(__file__).parent / "web"
    if not (web_dir / "index.html").exists():
        print(f"❌ web UI files not found in {web_dir}", file=sys.stderr)
        return 2

    port = args.port

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(web_dir), **kw)

        def translate_path(self, path):
            # Serve data files from out_dir when requested via /data/*
            if path.startswith("/data/"):
                rel = path[len("/data/"):]
                return str(out_dir / rel)
            return super().translate_path(path)

        def end_headers(self):
            # Enable CORS for everything (we're local, this is harmless)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Range")
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def do_OPTIONS(self):
            # CORS preflight — needed for PMTiles byte-range requests
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Range")
            self.send_header("Access-Control-Max-Age", "86400")
            self.end_headers()

        def do_GET(self):
            # CORS proxy for the SUSTech PMTiles basemap. The mirror
            # mirrors.sustech.edu.cn doesn't respond to OPTIONS preflight
            # (returns 405), so the browser blocks byte-range fetches.
            # We proxy the GET (with Range) and re-add CORS headers.
            if self.path.startswith("/pmtiles-proxy/"):
                upstream = "https://" + self.path[len("/pmtiles-proxy/"):]
                headers = {}
                if "Range" in self.headers:
                    headers["Range"] = self.headers["Range"]
                try:
                    import requests
                    r = requests.get(upstream, headers=headers, timeout=30, stream=True)
                    self.send_response(r.status_code)
                    passthrough = ("Content-Type", "Content-Length", "Content-Range",
                                   "Accept-Ranges", "ETag", "Last-Modified")
                    for h in passthrough:
                        if h in r.headers:
                            self.send_header(h, r.headers[h])
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    for chunk in r.iter_content(chunk_size=64 * 1024):
                        if chunk:
                            try:
                                self.wfile.write(chunk)
                            except (BrokenPipeError, ConnectionResetError):
                                break
                except Exception as e:
                    self.send_error(502, str(e))
                return

            super().do_GET()

        def log_message(self, format, *args):  # noqa: A002
            if args and isinstance(args[0], str) and "404" in args[0]:
                return  # suppress noisy 404s
            sys.stderr.write(f"[{self.log_date_time_string()}] {format % args}\n")

    with socketserver.ThreadingTCPServer(("127.0.0.1", port), Handler) as httpd:
        url = f"http://localhost:{port}"
        print(f"✅ Web UI serving at {url}")
        print(f"   data: {out_dir}")
        print(f"   Ctrl-C to stop")
        if args.browser:
            threading.Timer(0.5, lambda: webbrowser.open(url)).start()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n👋 Stopped.")
    return 0


def cmd_web_build(args) -> int:
    """Copy web/ static files to OUT_DIR (no server)."""
    import shutil
    web_dir = Path(__file__).parent / "web"
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for src in web_dir.rglob("*"):
        if src.is_file():
            rel = src.relative_to(web_dir)
            dst = out_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            n += 1
    if not args.json:
        print(f"✅ Wrote {n} web files to {out_dir}")
    return 0


# ── Argument parser ─────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m sustech_survival.transit",
        description="SUSTech campus navigation + bus data",
    )
    p.add_argument("--json", action="store_true", help="machine-readable output")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("facilities",
                   help="list all buildings + gates").set_defaults(func=cmd_facilities)

    s_find = sub.add_parser("find", help="fuzzy name search")
    s_find.add_argument("query")
    s_find.add_argument("--limit", type=int, default=10)
    s_find.set_defaults(func=cmd_find)

    s_stops = sub.add_parser("stops", help="list bus stops")
    s_stops.add_argument("--line", help="filter by line code (e.g. XYBS1)")
    s_stops.add_argument("--dir", type=int, choices=[0, 1],
                         help="filter by direction (0=CW, 1=CCW)")
    s_stops.set_defaults(func=cmd_stops)

    s_lines = sub.add_parser("lines", help="list bus line configs")
    s_lines.add_argument("--day", choices=["workday", "holiday"], default="workday")
    s_lines.set_defaults(func=cmd_lines)

    s_sched = sub.add_parser("schedule", help="show departure times")
    s_sched.add_argument("line", help="line_id (e.g. line1, short_down)")
    s_sched.add_argument("--sub", type=int, default=0, help="sub-route index")
    s_sched.add_argument("--day", choices=["workday", "holiday"], default="workday")
    s_sched.set_defaults(func=cmd_schedule)

    s_live = sub.add_parser("live", help="poll live bus positions")
    s_live.add_argument("--no-shuttles", action="store_true")
    s_live.set_defaults(func=cmd_live)

    s_route = sub.add_parser("route", help="shortest path between two facilities")
    s_route.add_argument("from_", metavar="FROM", help="origin name or facility_id")
    s_route.add_argument("to", help="destination name or facility_id")
    s_route.add_argument("--mode", choices=["walk", "bus", "transit"], default="transit")
    s_route.add_argument("--walk-radius", type=int, default=250,
                         help="max walking distance to build graph edges (m)")
    s_route.set_defaults(func=cmd_route)

    s_export = sub.add_parser("export", help="bundle GeoJSON + JSON for the web UI")
    s_export.add_argument("out_dir", help="output directory (created if missing)")
    s_export.add_argument("--no-elevation", action="store_true",
                         help="skip Open-Elevation API fetch (faster export)")
    s_export.set_defaults(func=cmd_export)

    s_serve = sub.add_parser("serve", help="start web UI on a port")
    s_serve.add_argument("--port", type=int, default=61019)
    s_serve.add_argument("--data-dir", default="/tmp/transit_data",
                         help="directory of exported GeoJSON (must exist or use --refresh)")
    s_serve.add_argument("--refresh", action="store_true",
                         help="re-fetch live data before serving")
    s_serve.add_argument("--no-elevation", action="store_true",
                         help="skip elevation refresh on --refresh")
    s_serve.add_argument("--browser", action="store_true",
                         help="auto-open browser after starting")
    s_serve.set_defaults(func=cmd_serve)

    s_wb = sub.add_parser("web-build", help="write web/ static files to OUT_DIR")
    s_wb.add_argument("out_dir")
    s_wb.set_defaults(func=cmd_web_build)

    return p


def main(argv: Optional[list] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "json"):
        args.json = False
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())