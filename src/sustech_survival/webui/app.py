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

DEFAULT_PORT = 20129  # SUSTech founding: September 2012 (2012-09)
HERE = Path(__file__).resolve().parent
TEMPLATES = HERE / "templates"
# Shared legacy webui static assets (e.g. webui/static/tis/tis.js) served at
# /static/<path>. Kept out of any skin so skins can reuse packaged JS.
WEBUI_STATIC = HERE / "static"
# Brand assets live in the package's resources/ dir (shipped in the wheel).
RESOURCES = Path(__file__).resolve().parent.parent / "resources"


def create_app(*, transit_data_dir: Optional[str] = None,
               skin: Optional[str] = None) -> Flask:
    """Build the skin-loader Flask app.

    ``transit_data_dir``: optional exported transit GeoJSON dir.
    ``skin``: name of the skin to activate (see ``loader.find_skin``). When
      None, the first installed skin is used; if none are installed the shipped
      default is used. An unknown name raises ``KeyError`` with the available
      list (callers should surface it with an actionable message).
    """
    app = Flask(
        __name__,
        template_folder=str(TEMPLATES),
        static_folder=None,   # skin static served explicitly below
    )
    app.config["TRANSIT_DATA_DIR"] = transit_data_dir

    # -- Brand assets (logo / favicon) -----------------------------------
    # Icon (favicon + page logo mark) = the square torch-only lockup.
    # Document-front / home-page hero = the full (torch + wordmark) lockup.
    @app.route("/logo.svg")
    def _logo():
        return send_from_directory(str(RESOURCES), "logo.svg")

    @app.route("/logo-full.svg")
    def _logo_full():
        return send_from_directory(str(RESOURCES), "logo-full-transparent.svg")

    @app.route("/favicon.svg")
    def _favicon():
        return send_from_directory(str(RESOURCES), "logo.svg")

    # -- Active skin -----------------------------------------------------
    # Prefer the explicitly requested skin; else the first installed; else
    # the shipped default. create_app still works with ZERO installed skins
    # (the user just gets the in-package default head).
    if skin is not None:
        _skin = loader.find_skin(skin)          # raises KeyError if unknown
        _is_default = (_skin.name == "default")
    else:
        _skins = loader.installed_skins()
        if _skins:
            _skin = _skins[0]
            _is_default = (_skin.name == "default")
        else:
            from .loader import Skin
            _skin = Skin(name="default", version="0", root=loader.default_skin())
            _is_default = True
    _skin_root = _skin.root
    app.config["SKIN"] = _skin.name
    app.config["SKIN_VERSION"] = _skin.version
    app.config["SKIN_ROOT"] = str(_skin_root)
    # A custom (non-default) head is AUTHORITATIVE: the app serves only the
    # pages/assets the skin ships, and `/api/*` (the sustech_survival.api
    # contract) is the data surface. The shipped default head additionally
    # falls back to the package templates/transit it owns.
    app.config["SKIN_IS_DEFAULT"] = bool(_is_default)

    # A single /static/<path> handler owns ALL static assets. Resolving
    # transit's assets here (instead of a competing route in the transit
    # blueprint) keeps Route match unambiguous — a second /static/<path>
    # rule would shadow this one (Flask picks the last-registered rule)
    # and break shared assets like /static/tis/tis.js on custom skins.
    @app.route("/static/<path:filename>")
    def _skin_static(filename):
        from flask import abort
        # 1) The active skin's own static/ dir is authoritative.
        p = _skin_root / "static" / filename
        if p.is_file():
            return send_from_directory(_skin_root / "static", filename)
        # 2) Legacy shared webui static (e.g. /static/tis/tis.js) — served
        #    regardless of skin so any skin can reuse the packaged JS.
        legacy = WEBUI_STATIC / filename
        if legacy.is_file():
            return send_from_directory(WEBUI_STATIC, filename)
        # 3) Transit assets, resolved through the same transit-root logic
        #    the /transit page uses: a custom skin's <skin>/transit/static,
        #    or the packaged transit/web/static for the default head.
        from .blueprints.transit import _transit_root
        troot = _transit_root()
        if troot is not None:
            tf = troot / "static" / filename
            if tf.is_file():
                return send_from_directory(troot / "static", filename)
        abort(404)

    # -- Landing page: the active skin's entry (authoritative for custom
    #    heads); the shipped default head falls back to the package landing.
    @app.route("/")
    def index():
        entry = _skin_root / "index.html"
        if entry.is_file():
            return send_from_directory(_skin_root, "index.html")
        if app.config.get("SKIN_IS_DEFAULT", False):
            return render_template("landing.html", port=app.config.get("PORT", DEFAULT_PORT))
        from flask import abort
        abort(404)

    # -- Submodule blueprints: serve the full /api/* + pages ------------
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
        skin: Optional[str] = None,
        debug: bool = False) -> int:
    """Create the app and serve it forever. Returns 0 on clean exit."""
    app = create_app(transit_data_dir=transit_data_dir, skin=skin)
    app.config["PORT"] = port
    skin_name = app.config.get("SKIN") or skin or "default"
    print(f"✅ SUSTech web UI serving at http://localhost:{port}")
    print(f"   Skin: {skin_name}")
    print("   Ctrl-C to stop")
    try:
        app.run(host=host, port=port, debug=debug, use_reloader=False)
    except KeyboardInterrupt:
        print("\n👋 Stopped.")
    return 0
