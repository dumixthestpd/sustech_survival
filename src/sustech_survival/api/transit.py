"""
sustech_survival.api.transit — live transit data contract (Flask-free).

Returns JSON-ready dicts the UI/skins consume. No Flask.
"""
from __future__ import annotations

from typing import Any


def live(*, include_shuttles: bool = True) -> "list[dict[str, Any]]":
    """Live campus-shuttle positions.

    Mirrors the former ``/api/transit/live`` endpoint: each shuttle as
    ``{line, station, eta_sec}``.
    """
    from sustech_survival.transit.transit import TransitClient
    client = TransitClient()
    positions = client.get_live_positions(include_shuttles=include_shuttles)
    return [{
        "line": p.line, "station": p.station, "eta_sec": p.eta_sec,
    } for p in positions]


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
