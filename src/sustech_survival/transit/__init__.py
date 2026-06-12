"""
sustech_survival.transit — Live campus navigation + bus data.

ONE client. ~12 operations. ZERO local data.

Public API:
    from sustech_survival.transit import transit, TransitClient, ...

Singleton:
    transit() — returns a TransitClient.

Schema (live-parsed via `from_api()` classmethods):
    Facility        — buildings + gates + bus stops (unified with facility_id)
    BusLine         — line config (e.g. "line1", "short_down")
    BusSubRoute     — one direction of a line
    BusSchedule     — departure times + minute_on_road for one sub-route
    LiveBus         — real-time GPS + route_code + next_station
    Path, PathStep  — routing result

Constants:
    DAY_WORKDAY / DAY_HOLIDAY
    ROUTE_XYBS1 / ROUTE_XYBS2
    DIR_CW / DIR_CCW
    KIND_BUILDING / KIND_GATE / KIND_BUS_STOP
"""
from __future__ import annotations

from .schema import (
    Facility, BusLine, BusSubRoute, BusSchedule, LiveBus, Route, PathStep,
    Path,  # alias for Route
    TransitError,
    KIND_BUILDING, KIND_GATE, KIND_BUS_STOP,
    ROUTE_XYBS1, ROUTE_XYBS2,
    DIR_CW, DIR_CCW,
    DAY_WORKDAY, DAY_HOLIDAY,
    WALK_SPEED_KMH, WALK_CONNECT_RADIUS_M, TRANSFER_PENALTY_MIN, WAIT_HEADWAY_MIN,
    haversine_m,
)
from .transit import TransitClient, transit


__all__ = [
    # Client
    "TransitClient", "transit",
    # Schema
    "Facility", "BusLine", "BusSubRoute", "BusSchedule", "LiveBus",
    "Route", "Path", "PathStep",
    # Constants
    "DAY_WORKDAY", "DAY_HOLIDAY",
    "ROUTE_XYBS1", "ROUTE_XYBS2",
    "DIR_CW", "DIR_CCW",
    "KIND_BUILDING", "KIND_GATE", "KIND_BUS_STOP",
    "WALK_SPEED_KMH", "WALK_CONNECT_RADIUS_M",
    "TRANSFER_PENALTY_MIN", "WAIT_HEADWAY_MIN",
    # Errors + helpers
    "TransitError", "haversine_m",
]