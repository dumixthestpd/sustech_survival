"""
Transit blueprint — mounts the existing campus-map frontend into the
unified app.

Transit's frontend (``transit/web/``) uses root-absolute asset paths
(``/static/``, ``/data/``, ``/pmtiles-proxy/``). To integrate without
touching the working files, this blueprint:

  * serves ``/transit``  → transit/web/index.html
  * serves ``/static/<path>``  → transit/web/static  (root, no prefix)
  * serves ``/data/<path>``     → the exported GeoJSON dir (root)
  * proxies ``/pmtiles-proxy/<path>`` → SUSTech PMTiles mirror (root)
  * runs the 30s live-bus refresh thread in the background

The webui's own landing/tis pages inline their CSS/JS, so there is no
``/static/`` collision.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from flask import (Blueprint, Response, abort, current_app, jsonify,
                   request, send_from_directory)

bp = Blueprint("transit", __name__)

_TRANSIT_WEB = (Path(__file__).resolve().parents[2]
                / "transit" / "web")
_live_thread_started = False


def _data_dir() -> Optional[Path]:
    d = current_app.config.get("TRANSIT_DATA_DIR")
    return Path(d) if d else None


def _maybe_start_live_refresh():
    """Start the 30s live-bus refresher once per process."""
    global _live_thread_started
    if _live_thread_started:
        return
    out_dir = _data_dir()
    if not out_dir or not out_dir.exists():
        return
    try:
        from sustech_survival.transit.transit import TransitClient
    except Exception:
        return
    _live_thread_started = True
    client = TransitClient()

    def _loop():
        while True:
            try:
                live = client.get_live_positions(include_shuttles=True)
                fc = {"type": "FeatureCollection",
                      "features": [b.to_geojson_feature() for b in live]}
                (out_dir / "live_buses.geojson").write_text(
                    json.dumps(fc, ensure_ascii=False))
            except Exception as e:  # transient — don't crash the thread
                print(f"[transit-live] {e}", file=sys.stderr)
            time.sleep(30)

    threading.Thread(target=_loop, daemon=True,
                     name="transit-live-refresh").start()


@bp.route("/transit")
def page():
    _maybe_start_live_refresh()
    idx = _TRANSIT_WEB / "index.html"
    if not idx.exists():
        return Response(
            "<h1>Transit web files not found</h1>"
            "<p>Expected transit/web/index.html in the package.</p>", 500)
    return send_from_directory(_TRANSIT_WEB, "index.html")


@bp.route("/static/<path:filename>")
def static(filename: str):
    # Transit frontend assets at root /static/.
    f = _TRANSIT_WEB / "static" / filename
    if f.is_file():
        return send_from_directory(_TRANSIT_WEB / "static", filename)
    abort(404)


@bp.route("/data/<path:filename>")
def data(filename: str):
    out_dir = _data_dir()
    if not out_dir or not out_dir.exists():
        # Frontend polls /data/*.geojson — return an empty FC so the map
        # renders cleanly when no data has been exported yet.
        if filename.endswith((".geojson", ".json")):
            return Response(
                json.dumps({"type": "FeatureCollection", "features": []}),
                mimetype="application/json")
        abort(404)
    return send_from_directory(out_dir, filename)


@bp.route("/pmtiles-proxy/<path:upstream>")
def pmtiles_proxy(upstream: str):
    """CORS proxy for the SUSTech PMTiles basemap mirror."""
    import requests
    url = "https://" + upstream
    headers = {}
    if "Range" in request.headers:
        headers["Range"] = request.headers["Range"]
    try:
        r = requests.get(url, headers=headers, timeout=30, stream=True)
        passthrough = ("Content-Type", "Content-Length", "Content-Range",
                       "Accept-Ranges", "ETag", "Last-Modified")
        resp = Response(r.iter_content(chunk_size=64 * 1024),
                        status=r.status_code)
        for h in passthrough:
            if h in r.headers:
                resp.headers[h] = r.headers[h]
        resp.headers["Access-Control-Allow-Origin"] = "*"
        return resp
    except Exception as e:
        return Response(str(e), status=502)


@bp.route("/api/transit/live")
def api_live():
    """Direct live-bus JSON (no file refresh needed)."""
    try:
        from sustech_survival.transit.transit import TransitClient
        client = TransitClient()
        positions = client.get_live_positions(include_shuttles=True)
        return jsonify_safe([{
            "line": p.line, "station": p.station, "eta_sec": p.eta_sec,
        } for p in positions])
    except Exception as e:
        return jsonify_safe({"error": str(e)}), 500


def jsonify_safe(obj):
    return jsonify(obj)
