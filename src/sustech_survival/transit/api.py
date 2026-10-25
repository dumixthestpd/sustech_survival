"""sustech_survival.transit.api — transit web API.

The transit frontend uses root-absolute asset paths (``/static/``,
``/data/``, ``/pmtiles-proxy/``). This module owns:

  * ``/transit``  → <skin>/transit/index.html (or <skin>/static/transit)
  * ``/data/<path>``     → the exported GeoJSON dir (config-supplied)
  * ``/pmtiles-proxy/<path>`` → SUSTech PMTiles mirror (root)

The ``/static/<path>`` assets for transit are served by the app-level
``/static/<path>`` handler (the single-rule resolver) — not here —
because Flask would otherwise shadow the app handler for ALL skins and
break shared assets like ``/static/tis/tis.js``.

The active skin's transit page is the entry point; this module just
exposes the data plane behind it.
"""
from __future__ import annotations
from .. import _net

import json
from pathlib import Path
from typing import Optional

from flask import (Blueprint, Response, abort, current_app, jsonify,
                   request, send_from_directory)

from sustech_survival.webui.api_registry import CollectorRegistry


def _mirror_url(upstream: str) -> Optional[str]:
    """Resolve only the map/glyph directory used by the shipped transit skin."""
    from urllib.parse import unquote, urlsplit
    target = urlsplit("https://" + upstream)
    path = unquote(target.path)
    if (target.netloc != "mirrors.sustech.edu.cn" or target.query or target.fragment
            or "\\" in path or any(part in (".", "..") for part in path.split("/"))
            or not path.startswith("/site/pmtiles-data/")
            or not path.endswith((".pmtiles", ".pbf"))):
        return None
    return "https://mirrors.sustech.edu.cn" + target.path


def register(reg: CollectorRegistry) -> None:
    """Wire up the transit endpoints under the collector."""

    @reg.page("transit.page", "/transit")
    def page():
        _root = _transit_root()
        if not _root:
            abort(404)  # active head dropped the transit feature
        idx = _root / "index.html"
        if idx.is_file():
            return send_from_directory(idx.parent, idx.name)
        return Response(
            "<h1>Transit web files not found</h1>"
            "<p>Expected transit/index.html in the active skin.</p>", 500)

    @reg.endpoint("transit.data", methods=["GET"], path="/data/<path:filename>")
    def data(filename: str):
        out_dir = _data_dir()
        if not out_dir or not out_dir.exists():
            # Frontend polls /data/*.geojson — return an empty FC so the
            # map renders cleanly when no data has been exported yet.
            if filename.endswith((".geojson", ".json")):
                return Response(
                    json.dumps({"type": "FeatureCollection", "features": []}),
                    mimetype="application/json")
            abort(404)
        return send_from_directory(out_dir, filename)

    @reg.endpoint("transit.pmtiles-proxy",
                  methods=["GET"],
                  path="/pmtiles-proxy/<path:upstream>")
    def pmtiles_proxy(upstream: str):
        """CORS proxy for the SUSTech PMTiles basemap mirror."""
        import requests
        url = _mirror_url(upstream)
        if url is None:
            abort(400, description="Expected a SUSTech PMTiles mirror resource")
        headers = {}
        if "Range" in request.headers:
            headers["Range"] = request.headers["Range"]
        try:
            r = requests.get(url, headers=headers, timeout=_net.service_timeout("transit"), stream=True, allow_redirects=False)
            if 300 <= r.status_code < 400:
                r.close()
                return Response("Map mirror redirected unexpectedly", status=502)
            passthrough = ("Content-Type", "Content-Length", "Content-Range",
                           "Accept-Ranges", "ETag", "Last-Modified")
            resp = Response(r.iter_content(chunk_size=64 * 1024),
                            status=r.status_code)
            for h in passthrough:
                if h in r.headers:
                    resp.headers[h] = r.headers[h]
            resp.headers["Access-Control-Allow-Origin"] = "*"
            resp.call_on_close(r.close)
            return resp
        except Exception as e:
            return Response(str(e), status=502)

    @reg.get("transit.live", "/api/transit/live")
    def api_live():
        """Direct live-bus JSON (no file refresh needed).

        Delegates to ``sustech_survival.api.transit.live`` so the HTTP route
        and the Flask-free contract can never drift into different shapes.
        """
        from sustech_survival.api import transit as transit_contract
        try:
            return jsonify(transit_contract.live(include_shuttles=True))
        except Exception as e:
            return jsonify({"error": str(e)}), 500


# -- module helpers used by the registered handlers above ------------------


def _active_skin_transit():
    """Path to the active skin's transit dir if present.

    A skin may ship transit as ``<skin>/transit`` (the documented layout)
    or as ``<skin>/static/transit`` (the layout the shipped default skin
    uses). ``None`` means the active head has dropped the transit
    feature; there is no package-level transit fallback.
    """
    from flask import current_app
    from pathlib import Path as _Path
    root = current_app.config.get("SKIN_ROOT")
    if root:
        p = _Path(root) / "transit"
        if p.is_dir():
            return p
        p = _Path(root) / "static" / "transit"
        if p.is_dir():
            return p
    return None


def _transit_root() -> Optional[Path]:
    """Resolve the transit web root for the active skin."""
    return _active_skin_transit()


def _data_dir() -> Optional[Path]:
    d = current_app.config.get("TRANSIT_DATA_DIR")
    return Path(d) if d else None
