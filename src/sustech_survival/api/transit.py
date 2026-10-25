"""
sustech_survival.api.transit — live transit data contract (Flask-free).

Returns JSON-ready dicts the UI/skins consume. No Flask.
"""
from __future__ import annotations

from typing import Any


def live(*, include_shuttles: bool = True) -> "list[dict[str, Any]]":
    """Live campus-shuttle positions.

    Each bus is one flat dict holding the whole ``LiveBus`` record. The old
    shape asked for ``line``/``station``/``eta_sec``, none of which the feed
    provides, so every call raised ``AttributeError``.
    """
    from sustech_survival.transit.transit import TransitClient
    client = TransitClient()
    positions = client.get_live_positions(include_shuttles=include_shuttles)
    return [_live_bus_payload(bus) for bus in positions]


def _live_bus_payload(bus: Any) -> "dict[str, Any]":
    """One ``LiveBus`` as JSON-ready data — the contract skins and agents read."""
    return {
        "bus_id": bus.bus_id,
        "route_code": bus.route_code,
        "next_station": bus.next_station,
        "prev_station_id": bus.prev_station_id,
        "lat": bus.lat,
        "lng": bus.lng,
        "speed_kmh": bus.speed_kmh,
        "course": bus.course,
        "is_operating": bus.is_operating,
        "timestamp": bus.timestamp,
    }


def facilities() -> "list[dict[str, Any]]":
    """Known buildings + gates (from the transit static catalog)."""
    from sustech_survival.transit.transit import TransitClient
    client = TransitClient()
    facs = client.list_facilities()
    return [{
        "id": f.facility_id, "name": f.name, "name_en": f.name_en,
        "kind": f.kind, "lat": f.lat, "lng": f.lng, "routes": f.routes,
    } for f in facs]


__all__ = ["live", "facilities"]
