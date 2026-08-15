"""
sustech_survival.webui — the SKIN LOADER head.

This is a THIN, replaceable layer. It loads an installed skin (default shipped
in ``webui/skins/default``) and serves it, plus the ``/api/*`` JSON contract.

The JSON contract is available two ways:
  * Flask-free data functions in ``sustech_survival.api`` — the stable contract
    any head (web UI, native app, CLI dashboard) can call directly.
  * The HTTP ``/api/*`` routes below, served by the built-in blueprints.

A skin is a folder with a ``manifest.json`` + static assets; whoever builds a
new head either imports ``sustech_survival.api``, or mounts these ``/api``
routes against their own frontend. ``sustech_survival`` core never imports this
module — dropping ``webui/`` leaves the whole API working.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from flask import Flask, render_template, send_from_directory

from sustech_survival.webui import loader

DEFAULT_PORT = 61019
HERE = Path(__file__).resolve().parent
TEMPLATES = HERE / "templates"
TIS_STATIC = HERE / "static" / "tis"
# Brand assets live in the package's resources/ dir (shipped in the wheel).
RESOURCES = Path(__file__).resolve().parent.parent / "resources"


def create_app(*, transit_data_dir: Optional[str] = None) -> Flask:
    """Build the skin-loader Flask app.

    ``transit_data_dir``: optional exported transit GeoJSON dir.
    """
    app = Flask(
        __name__,
        template_folder=str(TEMPLATES),
        static_folder=None,   # skin static served explicitly below
    )
    app.config["TRANSIT_DATA_DIR"] = transit_data_dir

    # ── Brand assets (logo / favicon) ───────────────────────────────────
    @app.route("/logo.svg")
    def _logo():
        return send_from_directory(str(RESOURCES), "logo.svg")

    @app.route("/favicon.svg")
    def _favicon():
        return send_from_directory(str(RESOURCES), "logo.svg")

    # ── Skin static assets ──────────────────────────────────────────────
    _skins = loader.installed_skins()
    _skin_root = _skins[0].root if _skins else loader.default_skin()

    @app.route("/static/<path:filename>")
    def _skin_static(filename):
        p = _skin_root / "static" / filename
        if p.is_file():
            return send_from_directory(_skin_root / "static", filename)
        # Legacy webui static (e.g. /static/tis/tis.js) as fallback.
        legacy = TIS_STATIC / filename
        if legacy.is_file():
            return send_from_directory(TIS_STATIC, filename)
        from flask import abort
        abort(404)

    # ── Landing page: prefer the active skin's entry; fall back to legacy.
    @app.route("/")
    def index():
        entry = _skin_root / "index.html"
        if entry.is_file():
            return send_from_directory(_skin_root, "index.html")
        return render_template("landing.html", port=app.config.get("PORT", DEFAULT_PORT))

    # ── Submodule blueprints: serve the full /api/* + pages ────────────
    # These wrap the same data as ``sustech_survival.api`` but also carry the
    # complex routes (enrolled/solve/bids/ical) via HTTP. They are the default
    # head's backend; a custom head calls ``sustech_survival.api`` instead.
    from .blueprints.tis import bp as tis_bp
    app.register_blueprint(tis_bp)
    from .blueprints.transit import bp as transit_bp
    app.register_blueprint(transit_bp, transit_data_dir=transit_data_dir)
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
    print(f"   Skin: {loader.installed_skins()[0].name if loader.installed_skins() else 'default'}")
    print("   Ctrl-C to stop")
    try:
        app.run(host=host, port=port, debug=debug, use_reloader=False)
    except KeyboardInterrupt:
        print("\n👋 Stopped.")
    return 0
