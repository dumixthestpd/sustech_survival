"""
sustech_survival.transit — Live client for SUSTech campus navigation + bus data.

ONE class. ALL operations. ZERO local data. Every call hits the live API.

Architecture mirrors `sustech_survival.faculty.FacultyClient`:

    TransitClient               ← one client, all methods
        .list_facilities()           ← buildings + gates (live from sustech.online/geojson)
        .find_facility(query)        ← fuzzy search by Chinese or English name
        .list_bus_lines(day_type)    ← all bus line configs (workday/holiday)
        .get_schedule(line, ...)     ← departure times for one sub-route
        .get_bus_route(line, dir)    ← ordered bus stops for a line
        .get_live_positions()        ← live bus GPS + next-station info
        .shortest_path(from, to)     ← Dijkstra over walking + bus graph
        .export_geojson(out_dir)     ← bundle everything for the website

Schema classes (`Facility`, `BusLine`, `BusSubRoute`, `BusSchedule`,
`LiveBus`, `Path`, `PathStep`) live in `schema.py` with classmethod parsers.
"""
from __future__ import annotations

import heapq
import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

from .schema import (
    Facility, BusLine, BusSubRoute, BusSchedule, LiveBus, Route, PathStep,
    KIND_BUILDING, KIND_GATE, KIND_BUS_STOP,
    ROUTE_XYBS1, ROUTE_XYBS2, DIR_CW, DIR_CCW,
    DAY_WORKDAY, DAY_HOLIDAY,
    WALK_SPEED_KMH, WALK_CONNECT_RADIUS_M, TRANSFER_PENALTY_MIN, WAIT_HEADWAY_MIN,
    haversine_m,
)


# -- Endpoint URLs -----------------------------------------------------------

LIVE_API = "https://bus.sustcra.com"          # live bus GPS + station GeoJSON
SCHEDULE_BASE = "https://sustech.online"      # bus config + times + buildings


class TransitClient:
    """One client object for SUSTech campus transit (nav + bus).

    Encapsulates the session + all operations. All data is fetched live.
    No local cache.
    """

    LIVE_API = LIVE_API
    SCHEDULE_BASE = SCHEDULE_BASE

    def __init__(self, *, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()
        # Force the UA — setdefault() won't override python-requests/2.x default
        self.session.headers["User-Agent"] = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

    # -- Facilities (buildings + gates) ----------------------------------------

    def list_buildings(self) -> List[Facility]:
        """Fetch all buildings from sustech.online (bus.sustcra.com/geojson)."""
        r = self.session.get(f"{LIVE_API}/geojson/sustech_bldg.json", timeout=15)
        r.raise_for_status()
        return [Facility.from_bldg(f) for f in r.json().get("features", [])]

    def list_gates(self) -> List[Facility]:
        r = self.session.get(f"{LIVE_API}/geojson/sustech_gate.json", timeout=15)
        r.raise_for_status()
        return [Facility.from_gate(f) for f in r.json().get("features", [])]

    def list_facilities(self) -> List[Facility]:
        """Buildings + gates combined, deduplicated by facility_id."""
        seen = {}
        for f in self.list_buildings() + self.list_gates():
            seen.setdefault(f.facility_id, f)
        return list(seen.values())

    def find_facility(self, query: str) -> List[Facility]:
        """Fuzzy name search across all facilities (buildings, gates, bus stops).

        Matches case-insensitively against Chinese name, English name, and
        substring. Returns matches sorted by how short the name is (shorter
        names rank higher — they're more specific).
        """
        q = query.strip().lower()
        if not q:
            return []
        candidates = list(self.list_facilities())
        # Also include bus stops so users can search for them
        for line in self._line_codes():
            for d in (DIR_CW, DIR_CCW):
                for f in self._bus_stops_for(line, d):
                    candidates.append(f)

        scored = []
        for f in candidates:
            aliases = [a.lower() for a in f.search_aliases()]
            score = None
            # Exact alias match → top score
            if q in aliases:
                score = -10  # highest priority (negative sorts first)
            # Substring match in any alias
            else:
                for a in aliases:
                    if q in a:
                        # shorter match + q-length bonus = more specific
                        score = len(a) - len(q) * 2
                        break
            # facility_id match
            if score is None and q in f.facility_id.lower():
                score = len(f.facility_id) - len(q) * 2
            if score is not None:
                scored.append((score, f))

        scored.sort(key=lambda x: x[0])
        # Deduplicate by facility_id (bus stops appear under multiple lines)
        seen = set()
        out = []
        for _, f in scored:
            if f.facility_id not in seen:
                seen.add(f.facility_id)
                out.append(f)
        return out

    # -- Bus lines + schedules ------------------------------------------------

    def list_bus_lines(self, day_type: str = DAY_WORKDAY) -> List[BusLine]:
        """Fetch bus config for a day type. workday or holiday."""
        if day_type not in (DAY_WORKDAY, DAY_HOLIDAY):
            raise ValueError(f"day_type must be workday or holiday, got {day_type!r}")
        r = self.session.get(f"{SCHEDULE_BASE}/bus_config.json", timeout=15)
        r.raise_for_status()
        data = r.json().get(day_type, [])
        lines = []
        for raw in data:
            subs = [BusSubRoute.from_api(s, raw["id"]) for s in raw.get("routes", [])]
            lines.append(BusLine(id=raw["id"], title=raw.get("title", ""), routes=subs))
        return lines

    def get_schedule(
        self,
        line_id: str,
        sub_route_index: int = 0,
        day_type: str = DAY_WORKDAY,
    ) -> BusSchedule:
        """Fetch departure times for one sub-route.

        Args:
            line_id: the BusLine.id (e.g. "line1", "short_down")
            sub_route_index: which sub-route in BusLine.routes (default: first)
            day_type: workday or holiday
        """
        lines = self.list_bus_lines(day_type=day_type)
        line = next((l for l in lines if l.id == line_id), None)
        if line is None:
            raise ValueError(f"Unknown line_id: {line_id!r}. "
                             f"Known: {[l.id for l in lines]}")
        if not line.routes:
            raise ValueError(f"Line {line_id} has no sub-routes")
        if sub_route_index >= len(line.routes):
            raise IndexError(
                f"sub_route_index {sub_route_index} out of range (line has {len(line.routes)} sub-routes)")

        sub = line.routes[sub_route_index]
        # Pick the first 'bus'-type source
        source = next((s for s in sub.sources if s.get("type") == "bus"), sub.sources[0])
        url = source["url"]
        if not url.startswith("http"):
            url = f"{SCHEDULE_BASE}{url}"

        r = self.session.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()

        return BusSchedule(
            line_id=line_id,
            title=line.title,
            day_type=day_type,
            sub_route_name=sub.name,
            sub_route_desc=sub.description,
            color=sub.color,
            times=data.get("times", []),
            minute_on_road=data.get("minuteOnRoad", 25),
        )

    # -- Bus routes (stops + path geometry) -----------------------------------

    def _line_codes(self) -> List[str]:
        """Available route codes (XYBS1, XYBS2)."""
        r = self.session.get(f"{LIVE_API}/api/v3/avail_route", timeout=10)
        r.raise_for_status()
        seen = []
        for entry in r.json().get("routes", []):
            if entry["name"] not in seen:
                seen.append(entry["name"])
        return seen

    def get_bus_stops(self, line_code: str, direction: int) -> List[Facility]:
        """Ordered bus stops for a line+direction.

        Returns Facilities keyed by station_id (so a stop on Line 1 CW and Line 2 CCW
        sharing the same station_id is the same Facility).
        """
        return self._bus_stops_for(line_code, direction)

    def _bus_stops_for(self, line_code: str, direction: int) -> List[Facility]:
        r = self.session.get(
            f"{LIVE_API}/api/v3/{line_code}/{direction}/stations", timeout=15
        )
        r.raise_for_status()
        return [
            Facility.from_bus_stop(f, line_code, direction)
            for f in r.json().get("features", [])
        ]

    def get_route_path_geojson(self, line_code: str, direction: int) -> dict:
        """Fetch the line geometry (as GeoJSON LineString) for a bus route.

        Tries multiple naming conventions; the server only has 3 actual files
        (NKDH1_clockwise, XYBS1_clockwise, XYBS2.json) for live routes.
        """
        candidates = [
            f"{LIVE_API}/static/lines/{line_code}_clockwise.json",
            f"{LIVE_API}/static/lines/{line_code}_counter_clockwise.json",
            f"{LIVE_API}/static/lines/{line_code}.json",
        ]
        for url in candidates:
            try:
                r = self.session.get(url, timeout=10)
                if r.status_code == 200:
                    return r.json()
            except requests.RequestException:
                continue
        raise requests.RequestException(
            f"No line geometry file found for {line_code} (dir {direction}). "
            f"Tried: {candidates}"
        )

    # -- Live bus positions --------------------------------------------------

    def get_live_positions(self, include_shuttles: bool = True) -> List[LiveBus]:
        """Poll the live feed. Returns every active bus + (optionally) EV shuttle.

        Source: /api/v2/monitor_osm/ (buses) + /api/v2/monitor_sev_osm/ (shuttles).
        """
        out: List[LiveBus] = []
        urls = [f"{LIVE_API}/api/v2/monitor_osm/"]
        if include_shuttles:
            urls.append(f"{LIVE_API}/api/v2/monitor_sev_osm/")
        for url in urls:
            try:
                r = self.session.get(url, timeout=10)
                r.raise_for_status()
                for raw in r.json():
                    out.append(LiveBus.from_api(raw))
            except requests.RequestException:
                continue  # monitor endpoint may go down — don't fail the whole call
        return out

    # -- Navigation -----------------------------------------------------------

    def shortest_path(
        self,
        from_facility_id: str,
        to_facility_id: str,
        *,
        mode: str = "transit",
        walk_radius_m: int = WALK_CONNECT_RADIUS_M,
    ) -> Route:
        """Find the shortest-time route between two facilities.

        Args:
            from_facility_id: origin facility_id (e.g. "building:工学院")
            to_facility_id:   destination facility_id
            mode: "walk" (only walking), "bus" (force bus), or "transit" (mixed)
            walk_radius_m: how close two facilities must be to add a walking edge

        Returns:
            Path with steps (walk / bus legs) and totals.

        Raises:
            ValueError if no path exists (caller passed IDs that aren't in graph).
        """
        # Build the graph
        nodes, walks, bus_edges = self._build_graph(walk_radius_m=walk_radius_m)

        if from_facility_id not in nodes:
            raise ValueError(f"Unknown origin facility_id: {from_facility_id!r}")
        if to_facility_id not in nodes:
            raise ValueError(f"Unknown destination facility_id: {to_facility_id!r}")

        # Dijkstra
        dist = {nid: float("inf") for nid in nodes}
        prev: Dict[str, Optional[Tuple[str, float, float, dict]]] = {nid: None for nid in nodes}
        dist[from_facility_id] = 0.0
        pq = [(0.0, from_facility_id)]
        while pq:
            d, nid = heapq.heappop(pq)
            if d > dist[nid]:
                continue
            if nid == to_facility_id:
                break
            for nid2, w_min, edge_data in self._neighbors(nid, walks, bus_edges, mode):
                nd = d + w_min
                if nd < dist[nid2]:
                    dist[nid2] = nd
                    # prev: (prev_id, duration_min, distance_m, edge_meta)
                    prev[nid2] = (
                        nid, w_min,
                        edge_data.get("distance_m", 0),
                        edge_data,
                    )
                    heapq.heappush(pq, (nd, nid2))

        if dist[to_facility_id] == float("inf"):
            raise TransitError(
                f"No path from {from_facility_id} to {to_facility_id} "
                f"(mode={mode!r}, walk_radius_m={walk_radius_m}). "
                "Try increasing walk_radius_m or use mode='walk'."
            )

        # Reconstruct
        steps: List[PathStep] = []
        total_m = 0.0
        rev_path = []
        cur = to_facility_id
        while cur != from_facility_id:
            p, dur_min, dist_m, edge_meta = prev[cur]
            rev_path.append((p, cur, dur_min, dist_m, edge_meta))
            cur = p
        rev_path.reverse()

        for a, b, dur_min, dist_m, edge_meta in rev_path:
            na, nb = nodes[a], nodes[b]
            steps.append(PathStep(
                mode=edge_meta["mode"],
                from_name=na.display_name,
                to_name=nb.display_name,
                duration_min=dur_min,
                distance_m=dist_m,
                details=edge_meta.get("details", ""),
            ))
            total_m += dist_m

        return Route(
            origin=nodes[from_facility_id].display_name,
            destination=nodes[to_facility_id].display_name,
            steps=steps,
            total_minutes=dist[to_facility_id],
            total_meters=total_m,
        )

    def _build_graph(self, *, walk_radius_m: int) -> Tuple[
        Dict[str, Facility], Dict[str, List[Tuple[str, float, dict]]],
        Dict[str, List[Tuple[str, float, dict]]],
    ]:
        """Build the routing graph: nodes + walk edges + bus edges.

        Returns (nodes, walk_edges, bus_edges) where each *edges is
        {facility_id: [(other_id, weight_min, edge_meta), ...]}.
        """
        # Collect all facilities
        nodes: Dict[str, Facility] = {}
        for f in self.list_facilities():
            nodes[f.facility_id] = f
        for line in self._line_codes():
            for d in (DIR_CW, DIR_CCW):
                for f in self._bus_stops_for(line, d):
                    # If station_id already known, merge routes list
                    if f.facility_id in nodes:
                        nodes[f.facility_id].routes = sorted(
                            set(nodes[f.facility_id].routes) | set(f.routes))
                    else:
                        nodes[f.facility_id] = f

        # Walking edges (any node within radius → walk at WALK_SPEED_KMH)
        walks: Dict[str, List[Tuple[str, float, dict]]] = defaultdict(list)
        ids = list(nodes.keys())
        for i, aid in enumerate(ids):
            a = nodes[aid]
            for bid in ids[i + 1:]:
                b = nodes[bid]
                d_m = a.distance_to(b)
                if d_m <= walk_radius_m:
                    dur = d_m / 1000.0 / WALK_SPEED_KMH * 60.0
                    walks[aid].append((bid, dur, {
                        "mode": "walk", "distance_m": d_m,
                        "details": f"~{d_m:.0f} m walk",
                    }))
                    walks[bid].append((aid, dur, {
                        "mode": "walk", "distance_m": d_m,
                        "details": f"~{d_m:.0f} m walk",
                    }))

        # Bus edges (consecutive stops on the same line/direction)
        bus_edges: Dict[str, List[Tuple[str, float, dict]]] = defaultdict(list)
        for line in self._line_codes():
            for d in (DIR_CW, DIR_CCW):
                stops = self._bus_stops_for(line, d)
                for i in range(len(stops) - 1):
                    a, b = stops[i], stops[i + 1]
                    d_m = a.distance_to(b)
                    # Estimate inter-stop ride time: linear scaling from full-route time
                    # crude but works for "transit" planning
                    dur = d_m / 1000.0 * 2.5  # ~2.5 min/km in campus traffic
                    bus_edges[a.facility_id].append((b.facility_id, dur, {
                        "mode": "bus",
                        "distance_m": d_m,
                        "details": f"{line} (dir {d}): {a.name} → {b.name}",
                    }))
                    bus_edges[b.facility_id].append((a.facility_id, dur, {
                        "mode": "bus",
                        "distance_m": d_m,
                        "details": f"{line} (dir {d}): {b.name} → {a.name}",
                    }))

        return nodes, walks, bus_edges

    def _neighbors(self, nid, walks, bus_edges, mode):
        """Yield (neighbor_id, weight_min, edge_meta) for Dijkstra."""
        if mode in ("walk", "transit"):
            for tgt, w, meta in walks.get(nid, []):
                yield tgt, w, meta
        if mode in ("bus", "transit"):
            # Add wait_time to bus edges: assume half-headway on average
            for tgt, w, meta in bus_edges.get(nid, []):
                yield tgt, w + WAIT_HEADWAY_MIN / 2.0, meta
        if mode == "transit":
            # Add transfer penalty for switching buses (counted per node arrival)
            # This is a hack — better modeled at path reconstruction, but a
            # conservative per-edge pad is acceptable for short campus routes.
            pass  # we leave it; full transfer penalty would need a 2-layer graph

    # -- GeoJSON export (for the website) ------------------------------------

    def fetch_elevation(self, points: List[tuple]) -> dict:
        """Batch-fetch elevation (m) from Open-Elevation API.

        Args:
            points: list of (lat, lng) tuples

        Returns:
            dict mapping "lat,lng" (rounded to 5 decimals) → elevation in meters.
            Returns {} if the API is unavailable; callers should treat missing
            elevations as flat ground.
        """
        if not points:
            return {}
        # Open-Elevation accepts up to ~100 points per request
        out = {}
        url = "https://api.open-elevation.com/api/v1/lookup"
        try:
            for i in range(0, len(points), 100):
                batch = points[i:i + 100]
                locations = [{"latitude": lat, "longitude": lng}
                             for lat, lng in batch]
                r = self.session.post(url, json={"locations": locations}, timeout=30)
                r.raise_for_status()
                for result in r.json().get("results", []):
                    key = f"{round(result['latitude'], 5)},{round(result['longitude'], 5)}"
                    out[key] = result.get("elevation")
        except requests.RequestException as e:
            print(f"[transit] elevation fetch failed: {e}", file=__import__("sys").stderr)
        return out

    def fetch_footways(self, bbox: tuple = (22.595, 113.985, 22.615, 114.005)) -> dict:
        """Fetch OSM pedestrian paths via Overpass API as a GeoJSON FeatureCollection.

        Args:
            bbox: (south_lat, west_lon, north_lat, east_lon) in degrees.
                  Default covers SUSTech.

        Returns:
            GeoJSON FeatureCollection of LineString features (highway=footway/path/etc.)
            or an empty FeatureCollection on failure.
        """
        south, west, north, east = bbox
        # Pedestrian-priority ways: footways, paths, pedestrian streets,
        # plus service/living_street/residential where bikes can go.
        # residential is also commonly walkable on campus.
        q = (
            f'[out:json][timeout:30];('
            f'way["highway"="footway"]({south},{west},{north},{east});'
            f'way["highway"="path"]({south},{west},{north},{east});'
            f'way["highway"="pedestrian"]({south},{west},{north},{east});'
            f'way["highway"="living_street"]({south},{west},{north},{east});'
            f'way["highway"="service"]({south},{west},{north},{east});'
            f'way["highway"="residential"]({south},{west},{north},{east});'
            f'way["highway"="unclassified"]({south},{west},{north},{east});'
            f');out body;>;out skel qt;'
        )
        try:
            r = self.session.post(
                "https://overpass-api.de/api/interpreter",
                data={"data": q},
                headers={"Accept": "application/json", "User-Agent": "sustech_survival/1.0"},
                timeout=60,
            )
            r.raise_for_status()
        except requests.RequestException as e:
            print(f"[transit] Overpass fetch failed: {e}", file=__import__("sys").stderr)
            return {"type": "FeatureCollection", "features": []}
        data = r.json()
        # Build node lookup, then attach coords to ways
        nodes = {n["id"]: (n["lat"], n["lon"]) for n in data["elements"]
                 if n.get("type") == "node"}
        features = []
        for w in data["elements"]:
            if w.get("type") != "way":
                continue
            nd_ids = w.get("nodes", [])
            coords = [nodes[nid] for nid in nd_ids if nid in nodes]
            if len(coords) < 2:
                continue
            t = w.get("tags", {})
            features.append({
                "type": "Feature",
                "geometry": {"type": "LineString",
                             "coordinates": [[c[1], c[0]] for c in coords]},
                "properties": {"highway": t.get("highway", "footway"),
                               "name": t.get("name", "")},
            })
        return {"type": "FeatureCollection", "features": features}

    # -- Routing (removed 2026-06-13) ----------------------------------------
    # The OSMnx-based walking route was a series of half-fixes that kept
    # degrading into worse UX (edgey/pointy polylines, scattered-dots
    # look, straight-line shortcuts through buildings). Per user request
    # ("delete the nav system entirely"), find_walking_path() and the
    # campus walk graph cache are removed. The basemap + building/gate/
    # bus-stop dots + live buses + bus schedule remain — those work.
    def find_walking_path(  # pragma: no cover — kept as a stub so legacy
        self,                       # callers don't AttributeError. Will
        from_lng: float, from_lat: float,  # be removed in a follow-up.
        to_lng: float, to_lat: float,
    ) -> Dict:
        raise TransitError("Routing is disabled in this build. Use the bus stop / building dot click to inspect locations.")

    def _get_walk_graph(self, cache_path: str = "~/.sustech_survival/cache/transit/campus_walk_graph.graphml"):  # pragma: no cover
        return None


    def export_geojson(self, out_dir: Path, *, with_elevation: bool = True) -> Dict[str, str]:
        """Bundle all facilities + bus lines + route paths to GeoJSON files.

        Writes:
          - {out_dir}/facilities.geojson       — all buildings + gates
          - {out_dir}/bus_stops.geojson        — all bus stops
          - {out_dir}/bus_lines/*.geojson      — line geometry per line+direction
          - {out_dir}/live_buses.geojson       — current bus positions
          - {out_dir}/schedules.json           — all departure times

        Returns dict of name → written path (for the caller / web server).
        """
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        lines_dir = out_dir / "bus_lines"
        lines_dir.mkdir(exist_ok=True)
        written: Dict[str, str] = {}

        # Facilities
        bldgs = self.list_buildings()
        gates = self.list_gates()
        facs = bldgs + gates
        fac_fc = {"type": "FeatureCollection", "features": [f.to_geojson_feature() for f in facs]}
        p = out_dir / "facilities.geojson"
        p.write_text(json.dumps(fac_fc, ensure_ascii=False, indent=2))
        written["facilities"] = str(p)

        # Bus stops (per line+dir, merged by station_id)
        bus_stops_by_id: Dict[str, Facility] = {}
        for line in self._line_codes():
            for d in (DIR_CW, DIR_CCW):
                for f in self._bus_stops_for(line, d):
                    bus_stops_by_id.setdefault(f.facility_id, f)
        stops_fc = {
            "type": "FeatureCollection",
            "features": [f.to_geojson_feature() for f in bus_stops_by_id.values()],
        }
        p = out_dir / "bus_stops.geojson"
        p.write_text(json.dumps(stops_fc, ensure_ascii=False, indent=2))
        written["bus_stops"] = str(p)

        # Bus line geometries
        for line in self._line_codes():
            for d in (DIR_CW, DIR_CCW):
                try:
                    geo = self.get_route_path_geojson(line, d)
                    p = lines_dir / f"{line}_{d}.geojson"
                    p.write_text(json.dumps(geo, ensure_ascii=False, indent=2))
                    written.setdefault("bus_lines", []).append(str(p))
                except requests.RequestException:
                    pass  # some lines may not have geometry

        # Live positions
        live = self.get_live_positions(include_shuttles=True)
        live_fc = {
            "type": "FeatureCollection",
            "features": [b.to_geojson_feature() for b in live],
        }
        p = out_dir / "live_buses.geojson"
        p.write_text(json.dumps(live_fc, ensure_ascii=False, indent=2))
        written["live_buses"] = str(p)

        # Schedules (workday + holiday)
        schedules = {"workday": [], "holiday": []}
        for day in (DAY_WORKDAY, DAY_HOLIDAY):
            for line in self.list_bus_lines(day_type=day):
                for i, sub in enumerate(line.routes):
                    try:
                        s = self.get_schedule(line.id, sub_route_index=i, day_type=day)
                        schedules[day].append({
                            "line_id": s.line_id,
                            "line_title": s.title,
                            "sub_name": s.sub_route_name,
                            "sub_desc": s.sub_route_desc,
                            "color": s.color,
                            "times": s.times,
                            "minute_on_road": s.minute_on_road,
                        })
                    except Exception:
                        pass
        p = out_dir / "schedules.json"
        p.write_text(json.dumps(schedules, ensure_ascii=False, indent=2))
        written["schedules"] = str(p)

        # Pedestrian path network (OpenStreetMap via Overpass API). The web UI
        # uses this to draw real walking paths (not straight lines) and to run
        # Dijkstra over the actual footway network.
        try:
            fw = self.fetch_footways()
            if fw.get("features"):
                p = out_dir / "footways.json"
                p.write_text(json.dumps(fw, ensure_ascii=False, indent=2))
                written["footways"] = str(p)
        except Exception as e:
            print(f"[transit] footways fetch failed: {e}", file=__import__("sys").stderr)

        # Elevation (m) for every facility + bus stop, plus path network nodes.
        # Used by the web UI's Dijkstra to compute walk/bike time via Tobler's
        # hiking function (climb-aware). Fetched from Open-Elevation API;
        # skip if --no-elevation or the API is unavailable (graph falls back
        # to flat-ground estimates).
        if with_elevation:
            points: List[tuple] = []
            for f in facs:
                points.append((f.lat, f.lng))
            for f in bus_stops_by_id.values():
                points.append((f.lat, f.lng))
            # Also include path network nodes from the OSM-derived footway
            # graph (fetched separately, not the live OSM API). This is a
            # no-op if footways.json doesn't exist.
            footways_path = out_dir / "footways.json"
            if footways_path.exists():
                try:
                    fw = json.loads(footways_path.read_text())
                    for feat in fw.get("features", []):
                        for lng, lat in feat["geometry"]["coordinates"]:
                            points.append((lat, lng))
                except Exception:
                    pass
            if points:
                elev = self.fetch_elevation(points)
                if elev:
                    p = out_dir / "elevation.json"
                    p.write_text(json.dumps(elev, ensure_ascii=False, indent=2))
                    written["elevation"] = str(p)

        return written


# -- Errors ------------------------------------------------------------------

class TransitError(Exception):
    """Raised when transit APIs return an error or no path exists."""


# -- Module-level singleton -------------------------------------------------

def _build_default_client() -> TransitClient:
    return TransitClient()


_client: Optional[TransitClient] = None


def transit() -> TransitClient:
    """Module-level singleton TransitClient."""
    global _client
    if _client is None:
        _client = _build_default_client()
    return _client