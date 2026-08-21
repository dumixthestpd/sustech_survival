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

from flask import Flask, Response, send_from_directory

from sustech_survival.webui import loader

DEFAULT_PORT = 20129  # SUSTech founding: September 2012 (2012-09)
HERE = Path(__file__).resolve().parent
# Brand assets live in the package's resources/ dir (shipped in the wheel).
RESOURCES = Path(__file__).resolve().parent.parent / "resources"

# Languages understood by the built-in skin loader. Skins are free to ship
# only a subset; the loader falls back to the un-suffixed English file.
SUPPORTED_LOCALES = ("en", "zh")


def _locale() -> str:
    """Resolve the active UI locale for this request.

    Order: ``?lang=`` query > app-level ``LANG`` config > English.
    """
    from flask import current_app, request
    raw = request.args.get("lang") or current_app.config.get("LANG") or "en"
    lang = raw.split("_")[0].split("-")[0].lower()
    return lang if lang in SUPPORTED_LOCALES else "en"


def _localized(skin_root, base: str, lang: str) -> Path | None:
    """Return ``<skin_root>/<base>.<lang>.html`` if present, else the
    un-suffixed ``<skin_root>/<base>.html``. Returns ``None`` when neither
    exists, so the caller can decide whether to fall back or 404."""
    root = Path(skin_root)
    if lang != "en":
        for name in (f"{base}.{lang}.html", f"{base}_{lang}.html"):
            candidate = root / name
            if candidate.is_file():
                return candidate
    plain = root / f"{base}.html"
    return plain if plain.is_file() else None


def create_app(*, transit_data_dir: Optional[str] = None,
               skin: Optional[str] = None,
               skin_path: Optional[str] = None,
               lang: Optional[str] = None) -> Flask:
    """Build the skin-loader Flask app.

    ``transit_data_dir``: optional exported transit GeoJSON dir.
    ``skin``: name of the skin to activate (see ``loader.find_skin``). When
      None, the first installed skin is used; if none are installed the shipped
      default is used. An unknown name raises ``KeyError`` with the available
      list (callers should surface it with an actionable message).
    ``skin_path``: serve a skin directly from a directory path (no install).
      Mutually exclusive with ``skin``; wins over any installed/name lookup.
    ``lang``: default UI locale for skins that ship localized pages. When
      omitted it is read from ``config.json`` (``webui.lang``) and falls back
      to English. The per-request ``?lang=`` query parameter overrides this.
      Built-in locales are ``en`` and ``zh``; skins may support only a subset
      and the loader falls back to the un-suffixed English page.
    """
    app = Flask(
        __name__,
        template_folder=None, # no shared package templates; skins own pages
        static_folder=None,   # skin static served explicitly below
    )
    app.config["TRANSIT_DATA_DIR"] = transit_data_dir
    if lang:
        lang = lang.split("_")[0].split("-")[0].lower()
        if lang not in SUPPORTED_LOCALES:
            raise ValueError(
                f"unsupported webui language {lang!r}; choose from "
                f"{', '.join(SUPPORTED_LOCALES)}"
            )
    else:
        from sustech_survival import _cache
        configured_lang = (_cache.load_config().get("webui") or {}).get("lang")
        if configured_lang:
            lang = str(configured_lang).split("_")[0].split("-")[0].lower()
            if lang not in SUPPORTED_LOCALES:
                lang = "en"
        else:
            lang = "en"
    app.config["LANG"] = lang

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
    # Resolution order: explicit skin_path -> explicit skin name -> the
    # default skin saved in ~/.sustech_survival/config.json (webui.skin) ->
    # first installed -> shipped default. create_app still works with ZERO
    # installed skins (the user just gets the in-package default head).
    if skin_path is not None:
        try:
            _skin = loader.skin_from_path(skin_path)
        except ValueError as e:
            raise ValueError(f"cannot serve --skin-path: {e}") from None
        _is_default = (_skin.name == "default")
    elif skin is not None:
        _skin = loader.find_skin(skin)          # raises KeyError if unknown
        _is_default = (_skin.name == "default")
    else:
        _skins = loader.installed_skins()
        configured = None
        if _skins:
            from sustech_survival import _cache
            configured = (_cache.load_config().get("webui") or {}).get("skin")
            if configured:
                try:
                    _skin = loader.find_skin(configured)
                except KeyError:
                    _skin = _skins[0]
            else:
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
    app.config["SKIN_REQUIRES"] = getattr(_skin, "requires", "")
    # If this skin needs a newer sustech_survival, surface that clearly. A
    # missing feature would otherwise fail confusingly at runtime.
    _req_warn = getattr(_skin, "check_requires", lambda: None)()
    if _req_warn:
        app.logger.warning(_req_warn)
        print(f"⚠️  {_req_warn}")
    # A custom (non-default) head is AUTHORITATIVE: the app serves only the
    # pages/assets the skin ships, and `/api/*` (the sustech_survival.api
    # contract) is the data surface. The shipped default head is just another
    # skin: it owns its landing, TIS, transit, and static assets too.
    app.config["SKIN_IS_DEFAULT"] = bool(_is_default)

    # A single /static/<path> handler owns ALL static assets. Resolving
    # transit's assets here (instead of a competing route in the transit
    # blueprint) keeps Route match unambiguous. Skins are FULLY INDEPENDENT:
    # each serves ONLY the assets it ships under <skin_root>/static/ (e.g.
    # <skin>/static/tis/tis.js). There is NO shared package JS any skin can
    # silently fall back to.
    @app.route("/static/<path:filename>")
    def _skin_static(filename):
        from flask import abort
        # 1) The active skin's own static/ dir is authoritative.
        p = _skin_root / "static" / filename
        if p.is_file():
            return send_from_directory(_skin_root / "static", filename)
        # 2) Transit assets, resolved through the same transit-root logic
        #    the /transit page uses: the active skin's <skin>/transit/static
        #    or <skin>/static/transit/static. No shared package fallback.
        from .blueprints.transit import _transit_root
        troot = _transit_root()
        if troot is not None:
            tf = troot / "static" / filename
            if tf.is_file():
                return send_from_directory(troot / "static", filename)
        abort(404)

    # -- Landing page: the active skin's entry is authoritative. Each skin
    #    owns its localized pages (``index.html`` / ``index.zh.html``); there
    #    is no package-level template fallback.
    @app.route("/")
    def index():
        lang = _locale()
        entry = _localized(_skin_root, "index", lang)
        if entry is not None:
            return send_from_directory(entry.parent, entry.name)
        plain = _skin_root / "index.html"
        if plain.is_file() and lang != "en":
            html = plain.read_text(encoding="utf-8").replace(
                '<html lang="en">', f'<html lang="{lang}">', 1)
            return Response(html, mimetype="text/html")
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
        skin_path: Optional[str] = None,
        lang: Optional[str] = None,
        debug: bool = False) -> int:
    """Create the app and serve it forever. Returns 0 on clean exit."""
    app = create_app(transit_data_dir=transit_data_dir, skin=skin,
                     skin_path=skin_path, lang=lang)
    app.config["PORT"] = port
    skin_name = app.config.get("SKIN") or skin or (skin_path or "default")
    print(f"✅ SUSTech web UI serving at http://localhost:{port}")
    print(f"   Skin: {skin_name}  Language: {app.config.get('LANG', 'en')}")
    print("   Ctrl-C to stop")
    try:
        app.run(host=host, port=port, debug=debug, use_reloader=False)
    except KeyboardInterrupt:
        print("\n👋 Stopped.")
    return 0
