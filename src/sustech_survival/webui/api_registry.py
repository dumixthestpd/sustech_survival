"""sustech_survival.webui.api_registry — the skin-driven API exposure model.

Each submodule that wants to expose web endpoints declares them in its own
``api.py`` (mirrors Django's per-app pattern — no central ``api/`` package to
drift). The active skin's ``manifest.json`` lists which endpoints (or whole
modules) it needs. The head module reads the manifest and registers ONLY
those routes — anything else stays cold and is not reachable.

Two shapes are accepted in the skin's ``manifest.api`` list:

  * bare module name — e.g. ``"tis"`` — pulls in every endpoint whose name
    starts with that module's namespace prefix (``tis.*``).
  * dotted endpoint name — e.g. ``"tis.info"`` — pulls in exactly one
    endpoint. This is for skins that want to trim a module's surface.

End result:
  * No central route table → no drift. Each module owns its routes.
  * The skin is the contract: it declares what it uses, no more.
  * Drift is loud: a rename in a module that breaks a skin's manifest
    shows up as a startup warning, not a runtime 404.

Public surface:
  - ``EndpointSpec`` — one route (name, methods, path, handler).
  - ``ModuleApi`` — the bag of endpoints one ``api.py`` registers.
  - ``CollectorRegistry`` — what an ``api.py`` calls ``register(reg)`` with.
  - ``discover_module_apis(package=...)`` — walks ``<package>.*.api``.
  - ``mount_skin_apis(app, manifest_api, discovered)`` — picks + mounts.
"""
import importlib
import logging
import pkgutil
from dataclasses import dataclass, field
from typing import Callable, Iterable, List, Optional, Tuple

from flask import Flask

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class EndpointSpec:
    """One web endpoint registered by a submodule's ``api.py``."""
    name: str                                # e.g. "tis.info"
    methods: Tuple[str, ...]                 # e.g. ("GET",)
    path: str                                # URL path, e.g. "/api/tis/info"
    handler: Callable                        # the Flask view function


@dataclass
class ModuleApi:
    """What a submodule's ``api.py`` exports.

    ``name`` is the module's namespace prefix — endpoints whose name starts
    with ``name + "."`` belong to this module. ``endpoints`` are the routes
    the head will consider mounting. ``extras`` is a free-form list for
    side-effects the module wants to run during ``create_app`` (e.g.
    registering a process-wide resource) — currently unused but kept for
    future extension without changing the API shape.
    """
    name: str
    version: str = ""                        # module version, for mismatch
    endpoints: List[EndpointSpec] = field(default_factory=list)
    extras: List = field(default_factory=list)


class CollectorRegistry:
    """Helper a module's ``api.py`` calls ``register(reg)`` against.

    Provides convenience decorators so an ``api.py`` is mostly a flat list
    of decorated functions, one per route.
    """

    def __init__(self, module_name: str):
        self._module_name = module_name
        self._module_name_override: str = ""
        self._endpoints: list[EndpointSpec] = []
        self._extras: list = []
        self.version = ""

    @property
    def name(self) -> str:
        """Module name as the manifest will see it. Defaults to the
        package dir name; override with ``reg.set_name('foo')`` to use
        a different key (e.g. when ``selectcourse/api.py`` wants to be
        referenced as ``tis``)."""
        if self._module_name_override:
            return self._module_name_override
        return self._module_name

    def set_name(self, name: str) -> None:
        """Override the module name used for manifest matching."""
        self._module_name_override = name

    def _add(self, name: str, methods: Tuple[str, ...], path: str,
             handler: Callable) -> Callable:
        if "." not in name:
            raise ValueError(
                f"endpoint name {name!r} must be dotted "
                f"(expected '<module>.<endpoint>', e.g. 'tis.info')")
        self._endpoints.append(EndpointSpec(
            name=name, methods=methods, path=path, handler=handler))
        return handler

    @staticmethod
    def _validate_name(name: str) -> None:
        """Eagerly reject undotted endpoint names — caught at decorator
        creation time so a typo in an ``api.py`` fails loudly before any
        Flask app is built."""
        if "." not in name:
            raise ValueError(
                f"endpoint name {name!r} must be dotted "
                f"(expected '<module>.<endpoint>', e.g. 'tis.info')")

    def endpoint(self, name: str, *, methods: Iterable[str],
                 path: str) -> Callable:
        """Generic endpoint decorator. Use ``get``/``post`` for the common case."""
        methods = tuple(methods)
        if not methods:
            raise ValueError(f"endpoint {name!r}: methods must be non-empty")
        self._validate_name(name)

        def deco(fn: Callable) -> Callable:
            return self._add(name, methods, path, fn)
        return deco

    def get(self, name: str, path: str) -> Callable:
        """Decorator: bind ``fn`` to ``GET path`` under endpoint name."""
        self._validate_name(name)

        def deco(fn: Callable) -> Callable:
            return self._add(name, ("GET",), path, fn)
        return deco

    def post(self, name: str, path: str) -> Callable:
        """Decorator: bind ``fn`` to ``POST path`` under endpoint name."""
        self._validate_name(name)

        def deco(fn: Callable) -> Callable:
            return self._add(name, ("POST",), path, fn)
        return deco

    def page(self, name: str, path: str) -> Callable:
        """Decorator for an HTML page route (currently same shape as ``get``)."""
        return self.get(name, path)

    def add_extra(self, obj) -> None:
        """Attach a side-effect object the head may want to process."""
        self._extras.append(obj)

    def to_module_api(self) -> ModuleApi:
        # Three-level resolution for the public ``name``:
        #   1. author override (``reg.set_name('tis')``) wins
        #   2. the first endpoint's prefix (so the manifest can refer to
        #      it by the same prefix as the endpoints use)
        #   3. the package dir name (set by ``discover_module_apis``)
        if self._module_name_override:
            effective_name = self._module_name_override
        elif self._endpoints:
            effective_name = self._endpoints[0].name.split(".", 1)[0]
        else:
            effective_name = self._module_name
        return ModuleApi(
            name=effective_name,
            version=self.version,
            endpoints=list(self._endpoints),
            extras=list(self._extras),
        )


def discover_module_apis(
        package: str = "sustech_survival") -> dict:
    """Walk ``<package>.*.api`` modules and collect their ``ModuleApi``.

    Returns ``{module_name: ModuleApi}``. A submodule without an ``api.py``
    is skipped silently. A submodule whose ``api.py`` fails to import or
    raises inside ``register()`` is logged and skipped (so a broken optional
    module never crashes the whole app).

    Two ``api.py`` shapes are supported:
      1. ``def register(reg: CollectorRegistry) -> None`` — the standard
         shape; ``reg`` collects endpoints via its decorators.
      2. ``api: ModuleApi`` — pre-built module-level instance (escape hatch
         for modules that need full control over their endpoint list).
    """
    out: dict[str, ModuleApi] = {}
    try:
        pkg = importlib.import_module(package)
    except ImportError as e:
        log.warning("api discovery: cannot import %r: %s", package, e)
        return out
    pkg_path = getattr(pkg, "__path__", None)
    if pkg_path is None:
        return out
    for info in pkgutil.iter_modules(pkg_path):
        name = info.name
        if name.startswith("_"):
            continue
        # Skip webui itself — its own api would be a meta-recursive trap.
        if name == "webui":
            continue
        full = f"{package}.{name}.api"
        try:
            mod = importlib.import_module(full)
        except ModuleNotFoundError:
            continue  # submodule has no api.py — fine
        except Exception as e:
            log.warning("api discovery: %s failed to import: %s", full, e)
            continue
        register = getattr(mod, "register", None)
        if callable(register):
            reg = CollectorRegistry(name)
            try:
                register(reg)
            except Exception as e:
                log.warning("api discovery: %s.register() failed: %s",
                            full, e)
                continue
            api = reg.to_module_api()
            # Key the discovered module under its effective name (the
            # prefix the endpoints use). For ``selectcourse/api.py``,
            # ``api.name`` is ``tis`` because all endpoints use that
            # prefix, even though the package dir is ``selectcourse``.
            # The skin manifest refers to modules by prefix, so the
            # dict lookup needs the same shape. Two packages whose
            # effective names collide (rare — usually a rename bug)
            # produce a loud warning instead of silent overwrite.
            if api.name in out and out[api.name] is not api:
                log.warning(
                    "api discovery: %s declared effective name %r "
                    "but %s already registered under it — later wins",
                    full, api.name,
                    next(k for k, v in out.items() if v is out[api.name]))
            out[api.name] = api
            continue
        api = getattr(mod, "api", None)
        if isinstance(api, ModuleApi):
            out[api.name] = api
    return out


def _expand_manifest(manifest_api: list,
                     discovered: dict) -> Tuple[set, set]:
    """Translate the skin's manifest entries into a concrete set of endpoint
    names plus a set of module-level references the head should log.

    Returns ``(wanted_names, wanted_module_names)``. A bare entry like
    ``"tis"`` expands to all endpoints whose name starts with ``"tis."``.
    A dotted entry like ``"tis.info"`` is taken as-is.
    """
    wanted_names: set[str] = set()
    wanted_module_names: set[str] = set()
    for entry in manifest_api:
        if not entry:
            continue
        if "." in entry:
            wanted_names.add(entry)
        else:
            wanted_module_names.add(entry)
    # Also accept any dotted endpoint under a requested module.
    for mod_name in list(wanted_module_names):
        mod_api = discovered.get(mod_name)
        if mod_api is None:
            continue
        for ep in mod_api.endpoints:
            wanted_names.add(ep.name)
    return wanted_names, wanted_module_names


def mount_skin_apis(app: Flask, manifest_api: list,
                    discovered: dict,
                    *, logger: Optional[logging.Logger] = None
                    ) -> Tuple[list, list]:
    """Mount only the endpoints the skin asked for.

    Returns ``(mounted_names, missing_names)``. ``mounted_names`` is sorted
    for deterministic startup logs. Missing names — entries in the manifest
    that no module provides — are returned and ALSO logged at WARNING level
    so they're visible without parsing return values.
    """
    log_ = logger or log
    wanted_names, wanted_modules = _expand_manifest(manifest_api, discovered)

    # Index all available endpoints by name.
    available: dict[str, EndpointSpec] = {}
    for mod_api in discovered.values():
        for ep in mod_api.endpoints:
            if ep.name in available:
                log_.warning(
                    "api: duplicate endpoint name %r (overwritten by %s)",
                    ep.name, mod_api.name)
            available[ep.name] = ep

    mounted: list[str] = []
    for ep_name in sorted(wanted_names):
        ep = available.get(ep_name)
        if ep is None:
            continue
        app.add_url_rule(ep.path, endpoint=ep.name, view_func=ep.handler,
                         methods=list(ep.methods))
        mounted.append(ep_name)

    # Build the "missing" list the same way the manifest was given so the
    # user sees exactly which entry failed (not the exploded list).
    missing: list[str] = []
    for entry in manifest_api:
        if not entry:
            continue
        if "." in entry:
            if entry not in available:
                missing.append(entry)
        else:
            if entry not in discovered:
                missing.append(entry)
    if missing:
        log_.warning("skin requested missing APIs: %s", missing)
    log_.info("mounted %d skin APIs: %s", len(mounted), mounted)
    return mounted, missing


__all__ = [
    "CollectorRegistry",
    "EndpointSpec",
    "ModuleApi",
    "discover_module_apis",
    "mount_skin_apis",
]