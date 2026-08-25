"""
sustech_survival.webui — the SKIN LOADER head.

This is a THIN, replaceable layer. It loads an installed skin (default shipped
in ``webui/skins/default``) and serves it, plus the ``/api/*`` JSON contract.

The JSON contract is available two ways:
  * Flask-free data functions in ``sustech_survival.api`` — the stable contract
    any head (web UI, native app, CLI dashboard) can call directly.
  * The HTTP ``/api/*`` routes, mounted per-module from each submodule's
    ``api.py`` via :mod:`sustech_survival.webui.api_registry`.

A skin is a folder with a ``manifest.json`` + static assets; whoever builds a
new head either imports ``sustech_survival.api``, or mounts these ``/api``
routes against their own frontend. ``sustech_survival`` core never imports this
module — dropping ``webui/`` leaves the whole API working.
"""
from __future__ import annotations

import socket
import sys
from pathlib import Path
from typing import Optional

from flask import Flask, send_from_directory

from sustech_survival.webui import loader

DEFAULT_PORT = 20129  # SUSTech founding: September 2012 (2012-09)
HERE = Path(__file__).resolve().parent
# Brand assets live in the package's resources/ dir (shipped in the wheel).
RESOURCES = Path(__file__).resolve().parent.parent / "resources"


def create_app(*, transit_data_dir: Optional[str] = None,
               skin: Optional[str] = None,
               skin_path: Optional[str] = None) -> Flask:
    """Build the skin-loader Flask app.

    ``transit_data_dir``: optional exported transit GeoJSON dir.
    ``skin``: name of the skin to activate (see ``loader.find_skin``). When
      None, the first installed skin is used; if none are installed the shipped
      default is used. An unknown name raises ``KeyError`` with the available
      list (callers should surface it with an actionable message).
    ``skin_path``: serve a skin directly from a directory path (no install).
      Mutually exclusive with ``skin``; wins over any installed/name lookup.

    Skins are single-language: the loader has no locale machinery. A skin
    ships its pages in one language (``default`` = English, ``default_zh`` =
    Chinese) and is fully self-contained.
    """
    app = Flask(
        __name__,
        template_folder=None, # no shared package templates; skins own pages
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
    _skin_manifest = loader._read_manifest(_skin_root)
    app.config["SKIN"] = _skin.name
    app.config["SKIN_VERSION"] = _skin.version
    app.config["SKIN_ROOT"] = str(_skin_root)
    app.config["SKIN_REQUIRES"] = getattr(_skin, "requires", "")
    # If this skin needs a newer sustech_survival, surface that clearly. A
    # missing feature would otherwise fail confusingly at runtime.
    _req_warn = getattr(_skin, "check_requires", lambda: None)()
    if _req_warn:
        app.logger.warning(_req_warn)
        print(f"[!] {_req_warn}")
    # A custom (non-default) head is AUTHORITATIVE: the app serves only the
    # pages/assets the skin ships, and `/api/*` (the sustech_survival.api
    # contract) is the data surface. The shipped default head is just another
    # skin: it owns its landing, TIS, transit, and static assets too.
    app.config["SKIN_IS_DEFAULT"] = bool(_is_default)

    # A single /static/<path> handler owns ALL static assets. Resolving
    # transit's assets here (instead of a competing route in the transit
    # api.py) keeps route matching unambiguous. Skins are FULLY INDEPENDENT:
    # each serves ONLY the assets it ships under <skin_root>/static/ (e.g.
    # <skin>/static/transit/app.js). There is NO shared package JS any skin
    # can silently fall back to.
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
        from sustech_survival.transit.api import _transit_root
        troot = _transit_root()
        if troot is not None:
            tf = troot / "static" / filename
            if tf.is_file():
                return send_from_directory(troot / "static", filename)
        abort(404)

    # -- Landing page: the active skin's entry is authoritative. The entry
    #    file comes from the manifest (``entry``, default ``index.html``);
    #    there is no package-level template fallback.
    @app.route("/")
    def index():
        from flask import abort
        entry = _skin.index
        if entry.is_file():
            return send_from_directory(entry.parent, entry.name)
        abort(404)

    # -- Skin-driven API exposure ----------------------------------------
    # The active skin's ``manifest.api`` declares which endpoints it needs.
    # The head discovers every submodule's ``api.py`` and mounts ONLY the
    # requested ones — anything else stays cold. This is the inverse of
    # the old blanket "register every blueprint" model: each module owns
    # its surface, the skin picks what to expose.
    from .api_registry import discover_module_apis, mount_skin_apis
    discovered = discover_module_apis()
    skin_api = (_skin_manifest.get("api") or []) if _skin_manifest else []
    mounted, missing = mount_skin_apis(app, skin_api, discovered,
                                       logger=app.logger)

    # -- Skin-owned pages ------------------------------------------------
    # Each skin ships its own pages (e.g. ``<skin>/tis.html`` for ``/tis``,
    # ``<skin>/transit/index.html`` for ``/transit``). A catch-all route
    # serves them so the head never hardcodes the page list — a new skin
    # can ship new pages without touching this file. API / static / brand
    # namespaces are explicitly skipped (their literal routes win in Werkzeug
    # routing anyway; this is defence in depth).
    @app.route("/<path:page>", methods=["GET"])
    def _skin_page(page):
        from flask import abort
        from werkzeug.security import safe_join
        if page.startswith(("api/", "static/", "_")):
            abort(404)
        # Resolve strictly inside the skin root: ``safe_join`` rejects any
        # ``..`` segment, so a request can never escape the skin directory.
        for rel in (f"{page}.html", f"{page}/index.html"):
            joined = safe_join(str(_skin_root), rel)
            if joined is None:
                continue
            candidate = Path(joined)
            if candidate.is_file():
                return send_from_directory(_skin_root, rel)
        abort(404)

    return app


def _port_in_use(host: str, port: int) -> bool:
    """Probe whether ``(host, port)`` is already bound by another process.

    Without this check the dev server's own bind attempt raises a raw
    ``OSError`` (WinError 10048 / EADDRINUSE) that surfaces as a confusing
    traceback. Probing first lets :func:`run` fail with a clear message
    instead.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((host, port))
        return False
    except OSError:
        return True
    finally:
        s.close()


def _port_owner(host: str, port: int) -> str:
    """Best-effort description of the process holding ``(host, port)``.

    Returns ``""`` when the lookup fails or no listener matches — the
    caller treats it as decoration, never a hard error.
    """
    import re
    import subprocess
    try:
        if sys.platform == "win32":
            out = subprocess.run(["netstat", "-ano"], capture_output=True,
                                 text=True, timeout=5).stdout
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 5 and parts[3] == "LISTENING" \
                        and parts[1].rsplit(":", 1)[-1] == str(port):
                    pid = parts[-1]
                    if pid.isdigit():
                        return f" (PID {pid})"
        else:
            out = subprocess.run(["ss", "-ltnp"], capture_output=True,
                                 text=True, timeout=5).stdout
            m = re.search(rf":{port}\b.*?pid=(\d+)", out, re.S)
            if m:
                return f" (PID {m.group(1)})"
    except Exception:
        pass
    return ""


def run(*, port: int = DEFAULT_PORT, host: str = "0.0.0.0",
        transit_data_dir: Optional[str] = None,
        skin: Optional[str] = None,
        skin_path: Optional[str] = None,
        debug: bool = False) -> int:
    """Create the app and serve it forever. Returns 0 on clean exit.

    Returns 1 (without starting the server) when ``(host, port)`` is already
    in use — the usual cause is another ``sustech webui serve`` still running.
    """
    if _port_in_use(host, port):
        owner = _port_owner(host, port)
        print(f"[!] port {port} is already in use{owner} - is another "
              f"`sustech webui serve` running? stop it first, or pick a "
              f"different port with --port.")
        return 1
    app = create_app(transit_data_dir=transit_data_dir, skin=skin,
                     skin_path=skin_path)
    app.config["PORT"] = port
    skin_name = app.config.get("SKIN") or skin or (skin_path or "default")
    print(f"[OK] SUSTech web UI serving at http://localhost:{port}")
    print(f"   Skin: {skin_name}")
    print("   Ctrl-C to stop")
    try:
        app.run(host=host, port=port, debug=debug, use_reloader=False)
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0
