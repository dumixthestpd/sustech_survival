"""Every discovered module must report the package version.

``nces``, ``selectcourse`` and ``transit`` used to stamp ``reg.version`` in a
module-level ``try`` block, outside ``register()``, where ``reg`` was unbound:
the assignment always raised ``NameError`` and ``except Exception: pass`` hid
it, so ``ModuleApi.version`` stayed empty and the skin-mismatch check could
never fire. The registry now stamps the version when it is constructed.
"""
from __future__ import annotations

from sustech_survival import _version
from sustech_survival.webui.api_registry import CollectorRegistry, discover_module_apis


def test_registry_carries_the_package_version():
    assert CollectorRegistry("anything").version == _version.__version__


def test_every_discovered_module_reports_its_version():
    apis = discover_module_apis()
    assert apis, "api discovery found no modules"
    empty = sorted(name for name, api in apis.items() if not api.version)
    assert not empty, f"modules with no version: {empty}"
    wrong = {name: api.version for name, api in apis.items()
             if api.version != _version.__version__}
    assert not wrong, f"modules with a foreign version: {wrong}"
