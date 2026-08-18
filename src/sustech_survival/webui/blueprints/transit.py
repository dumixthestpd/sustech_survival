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
from pathlib import Path
from typing import Optional

from flask import (Blueprint, Response, abort, current_app, jsonify,
                   request, send_from_directory)

bp = Blueprint("transit", __name__)

_TRANSIT_WEB = (Path(__file__).resolve().parents[2]
                / "transit" / "web")


def _active_skin_transit():
    """Path to the active skin's transit dir (``<skin>/transit``) if present,
    else ``None`` — a custom head that ships no transit dir has dropped the
    feature. The shipped default head falls back to the package ``transit/web``.
    """
    from flask import current_app
    from pathlib import Path as _Path
    root = current_app.config.get("SKIN_ROOT")
    if root:
        p = _Path(root) / "transit"
        if p.is_dir():
            return p
    return None


def _transit_root():
    """Resolve the transit web root for the active head."""
    from flask import current_app
    skin_t = _active_skin_transit()
    if skin_t is not None:
        return skin_t
    # Custom (non-default) skins get no transit fallback. The default head
    # uses the package transit/web.
    if current_app.config.get("SKIN_IS_DEFAULT", False):
        return _TRANSIT_WEB
    return None


def _data_dir() -> Optional[Path]:
    d = current_app.config.get("TRANSIT_DATA_DIR")
    return Path(d) if d else None


def _maybe_start_live_refresh():
    """DEPRECATED 2026-08-10: removed — frontend polls /api/transit/live
    directly now (already-implemented endpoint). The background thread
    was hammering the upstream bus GPS API every 30s with no idle
    detection (kept the Mac mini constantly busy even with zero open
    browser tabs) and writing a JSON file to disk on every tick — bad
    design. The /api/transit/live endpoint returns the same data with
    no Python-side state.
    """
    return


@bp.route("/transit")
def page():
    _maybe_start_live_refresh()
    _root = _transit_root()
    if not _root:
        abort(404)  # active head dropped the transit feature
    idx = _root / "index.html"
    if not idx.exists():
        return Response(
            "<h1>Transit web files not found</h1>"
            "<p>Expected transit/index.html in the active skin (or transit/web in the package).</p>", 500)
    return send_from_directory(idx.parent, "index.html")


# NOTE: transit's /static/<path> assets are served by the app-level
# /static/<path> handler in webui/app.py (which owns the single rule and
# resolves transit assets through _transit_root()). Registering a second
# /static/<path> rule here would shadow the app handler for ALL skins and
# break shared assets like /static/tis/tis.js.


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
