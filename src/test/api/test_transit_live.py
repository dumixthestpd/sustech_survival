"""``api.transit.live`` must describe the fields the live feed actually has.

The endpoint used to ask every ``LiveBus`` for ``line``/``station``/``eta_sec``
— attributes that never existed — so ``GET /api/transit/live`` answered 500
whenever the feed returned data, and an empty ``[]`` hid the bug when it did
not. The feed schema is the contract; these tests pin it.
"""
from __future__ import annotations

import pytest

from sustech_survival.api import transit as api_transit
from sustech_survival.transit.schema import LiveBus

EXPECTED = {
    "bus_id": "868120327159106",
    "route_code": "SEV",
    "next_station": "-1",
    "prev_station_id": "7",
    "lat": 22.610736,
    "lng": 113.997216,
    "speed_kmh": 0.0,
    "course": 232,
    "is_operating": True,
    "timestamp": 1761000000,
}


@pytest.fixture
def stub_feed(monkeypatch):
    """Serve one live bus without touching the network."""
    from sustech_survival.transit.transit import TransitClient

    def _positions(self, include_shuttles=True):  # noqa: ARG001
        return [LiveBus(**EXPECTED)]

    monkeypatch.setattr(TransitClient, "get_live_positions", _positions)


def test_live_reports_the_livebus_fields(stub_feed):
    assert api_transit.live() == [dict(EXPECTED)]


def test_every_field_is_json_ready(stub_feed):
    import json

    rows = api_transit.live()
    assert json.loads(json.dumps(rows)) == rows


def test_http_route_serves_the_same_contract(stub_feed):
    """The Flask route must not keep its own copy of the shape."""
    from flask import Flask

    from sustech_survival.transit.api import register
    from sustech_survival.webui.api_registry import CollectorRegistry

    registry = CollectorRegistry("transit")
    register(registry)
    spec = next(e for e in registry.to_module_api().endpoints
                if e.name == "transit.live")
    app = Flask(__name__)
    with app.app_context():
        payload = spec.handler().get_json()
    assert payload == api_transit.live()
