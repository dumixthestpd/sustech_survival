"""
Flask application factory for the unified SUSTech web UI.

Submodules register themselves as blueprints (see ``blueprints/``).
The app owns the landing page (``/``); each submodule owns its own
page + ``/api/<sub>/*`` routes.

Transit's frontend uses root-absolute asset paths (``/static/``,
``/data/``, ``/pmtiles-proxy/``), so the transit blueprint mounts those
at root (no url_prefix) and only its HTML index lives at ``/transit``.
The TIS page serves its JS at ``/static/tis/`` (see ``_tis_static``
below) to keep both submodules' static assets separate.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from flask import Flask, send_from_directory

DEFAULT_PORT = 61019
HERE = Path(__file__).resolve().parent
TEMPLATES = HERE / "templates"
TIS_STATIC = HERE / "static" / "tis"
# Brand assets live in the package's resources/ dir (shipped in the wheel).
RESOURCES = Path(__file__).resolve().parent.parent / "resources"


def create_app(*, transit_data_dir: Optional[str] = None) -> Flask:
    """Build the unified Flask app.

    ``transit_data_dir``: directory of exported transit GeoJSON. If
    provided, the transit blueprint serves live data from it; if None,
    ``/transit`` shows a "data not exported" hint.
    """
    app = Flask(
        __name__,
        template_folder=str(TEMPLATES),
        static_folder=None,   # we inline webui assets; no /static mount
    )
    app.config["TRANSIT_DATA_DIR"] = transit_data_dir

    # ── Brand assets (logo / favicon) ───────────────────────────────────
    @app.route("/logo.svg")
    def _logo():
        return send_from_directory(str(RESOURCES), "logo.svg")

    @app.route("/favicon.svg")
    def _favicon():
        return send_from_directory(str(RESOURCES), "logo.svg")

    # ── TIS static assets (extracted from the template) ────────────────
    # Transit's own blueprint mounts /static at root for its own files;
    # TIS lives under /static/tis/ to avoid collision.
    @app.route("/static/tis/<path:filename>")
    def _tis_static(filename: str):
        return send_from_directory(str(TIS_STATIC), filename)

    # ── Landing page ────────────────────────────────────────────────────
    @app.route("/")
    def index():
        from flask import render_template
        return render_template("landing.html", port=app.config.get("PORT", DEFAULT_PORT))

    # ── Submodule blueprints (lazy import → Flask is optional for them) ─
    from .blueprints.tis import bp as tis_bp
    app.register_blueprint(tis_bp)

    from .blueprints.transit import bp as transit_bp
    app.register_blueprint(transit_bp, transit_data_dir=transit_data_dir)

    # NCES is optional — only register if the [nces] extra is installed.
    try:
        from .blueprints.nces import bp as nces_bp
        app.register_blueprint(nces_bp)
    except ImportError as e:
        app.logger.info(f"NCES blueprint not registered: {e}")

    return app


def run(*, port: int = DEFAULT_PORT, host: str = "0.0.0.0",
        transit_data_dir: Optional[str] = None,
        debug: bool = False) -> int:
    """Create the app and serve it forever. Returns 0 on clean exit."""
    app = create_app(transit_data_dir=transit_data_dir)
    app.config["PORT"] = port
    print(f"✅ SUSTech web UI serving at http://localhost:{port}")
    print("   Ctrl-C to stop")
    try:
        app.run(host=host, port=port, debug=debug, use_reloader=False)
    except KeyboardInterrupt:
        print("\n👋 Stopped.")
    return 0