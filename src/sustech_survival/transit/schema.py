"""
sustech_survival.transit.schema — Dataclasses for the SUSTech campus transit layer.

Mirrors the JSON returned by:
  - bus.sustcra.com (live bus positions + station GeoJSON + route line geometry)
  - sustech.online/bus_config.json + bus_times/*.json (schedules)
  - bus.sustcra.com/geojson/sustech_bldg.json + sustech_gate.json (facilities)

All parsers are classmethods. No loose `parse_*` functions.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import List, Optional

# -- Constants ----------------------------------------------------------------

# Day types in /bus_config.json
DAY_WORKDAY = "workday"
DAY_HOLIDAY = "holiday"

# Bus route codes (from /api/v3/avail_route)
ROUTE_XYBS1 = "XYBS1"   # 1路 / Line 1
ROUTE_XYBS2 = "XYBS2"   # 2路 / Line 2

# Directions (0 = clockwise/cw, 1 = counter-clockwise/ccw)
DIR_CW = 0
DIR_CCW = 1

# Route codes used in live-position feed (v2 monitor_osm)
LIVE_ROUTE_NKDH1 = "NKDH1"   # 1路 内环 顺时针 CW
LIVE_ROUTE_NKDH2 = "NKDH2"   # 2路 外环 逆时针 CCW
LIVE_ROUTE_SEV = "SEV"       # 电瓶车 / EV shuttle

# Facility kinds (used to disambiguate IDs from different sources)
KIND_BUILDING = "building"
KIND_GATE = "gate"
KIND_BUS_STOP = "bus_stop"

# Routing tunables
WALK_SPEED_KMH = 4.5        # average pedestrian
WALK_CONNECT_RADIUS_M = 250 # build walking edges to anything within 250m
TRANSFER_PENALTY_MIN = 5    # minutes added per bus transfer
WAIT_HEADWAY_MIN = 10       # typical bus headway — used as wait estimate


def haversine_m(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    """Great-circle distance in meters between two WGS84 points."""
    r = 6371000.0  # earth radius in meters
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# -- Facility (building / gate / bus stop) ----------------------------------

@dataclass
class Facility:
    """A named place on campus. The unified key for all routing."""
    facility_id: str              # "{kind}:{id}" — globally unique
    name: str                     # Chinese
    name_en: str = ""             # English (if available)
    kind: str = KIND_BUILDING
    lat: float = 0.0
    lng: float = 0.0
    routes: List[str] = field(default_factory=list)  # bus route codes that stop here
    meta: dict = field(default_factory=dict)         # extra raw data

    @classmethod
    def from_bldg(cls, raw: dict) -> "Facility":
        """Parse from bus.sustcra.com/geojson/sustech_bldg.json."""
        name_raw = raw["properties"]["name"]
        name_zh_raw, name_en = _split_bilingual(name_raw)
        # Synthesize a unique Chinese name when the raw name is generic
        # (e.g. 17 dorm buildings all share the Chinese name "宿舍").
        name_zh = _synthesize_unique_name(name_zh_raw, name_en)
        # Build a unique slug from the synthesized name (so dorms get
        # "building:宿舍13栋" not the colliding "building:宿舍").
        slug = _slug_from_name(name_zh, name_en)
        coords = raw["geometry"]["coordinates"]
        return cls(
            facility_id=f"{KIND_BUILDING}:{slug}",
            name=name_zh,
            name_en=name_en,
            kind=KIND_BUILDING,
            lat=coords[1],
            lng=coords[0],
        )

    @classmethod
    def from_gate(cls, raw: dict) -> "Facility":
        name_raw = raw["properties"]["name"]
        name_zh, name_en = _split_bilingual(name_raw)
        coords = raw["geometry"]["coordinates"]
        return cls(
            facility_id=f"{KIND_GATE}:{name_zh}",
            name=name_zh,
            name_en=name_en,
            kind=KIND_GATE,
            lat=coords[1],
            lng=coords[0],
        )

    @classmethod
    def from_bus_stop(cls, raw: dict, line_code: str, direction: int) -> "Facility":
        """Parse from /api/v3/{line}/{dir}/stations."""
        props = raw["properties"]
        name_raw = props["name"]
        name_zh, name_en = _split_bilingual(name_raw)
        coords = raw["geometry"]["coordinates"]
        sid = props["station_id"]
        return cls(
            facility_id=f"{KIND_BUS_STOP}:{sid}",
            name=name_zh,
            name_en=name_en,
            kind=KIND_BUS_STOP,
            lat=coords[1],
            lng=coords[0],
            routes=[f"{line_code}/{direction}"],
            meta={"station_id": sid, "line": line_code, "direction": direction},
        )

    @property
    def display_name(self) -> str:
        if self.name_en:
            return f"{self.name} / {self.name_en}"
        return self.name

    def search_aliases(self) -> List[str]:
        """Other strings this facility should match in fuzzy search.

        For example, "Dorm Block 13" → ["Dorm 13", "dorm 13", "宿舍楼13"]
        so users can find a dorm by typing "dorm 13" without "Block".
        """
        aliases: List[str] = []
        if self.name_en:
            aliases.append(self.name_en)
            # "Dorm Block 13" → "Dorm 13" / "dorm 13"
            stripped = re.sub(r"\bBlock\b", "", self.name_en, flags=re.I).strip()
            if stripped != self.name_en:
                aliases.append(stripped)
                aliases.append(stripped.lower())
            # "Apartment 2" → "Apt 2" / "apt 2"
            apt = re.sub(r"\bApartment\b", "Apt", self.name_en)
            if apt != self.name_en:
                aliases.append(apt.lower())
            # "Bldg" → "Building" alias
            bldg = re.sub(r"\bBldg\.?\b", "Building", self.name_en)
            if bldg != self.name_en:
                aliases.append(bldg.lower())
            aliases.append(self.name_en.lower())
        if self.name:
            aliases.append(self.name)
        # Common Chinese aliases
        if "宿舍" in self.name and any(c.isdigit() for c in self.name):
            # 宿舍13栋 → 宿舍楼13, dorm 13 (pinyin-ish)
            n_match = re.search(r"(\d+)", self.name)
            if n_match:
                n = n_match.group(1)
                aliases.extend([f"宿舍楼{n}", f"宿舍{n}号", f"dorm {n}", f"dorm{n}"])
        if self.name_en and "Hall" in self.name_en:
            # Lecture Hall 1 → Hall 1, hall 1
            stripped = re.sub(r"\bLecture\s+Hall\b", "Hall", self.name_en)
            if stripped != self.name_en:
                aliases.append(stripped.lower())
        if self.name_en and "Stadium" in self.name_en:
            aliases.append(self.name_en.replace("Stadium", "场").lower())
        return list(dict.fromkeys(aliases))  # dedup preserving order

    def distance_to(self, other: "Facility") -> float:
        return haversine_m(self.lng, self.lat, other.lng, other.lat)

    def to_geojson_feature(self) -> dict:
        return {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [self.lng, self.lat]},
            "properties": {
                "facility_id": self.facility_id,
                "name": self.name,
                "name_en": self.name_en,
                "kind": self.kind,
                "routes": self.routes,
            },
        }

    def to_markdown(self) -> str:
        routes = ", ".join(self.routes) if self.routes else "—"
        return f"### {self.display_name}\n- **Kind**: {self.kind}\n- **Routes**: {routes}\n- **GPS**: {self.lat:.6f}, {self.lng:.6f}\n"


def _split_bilingual(name_raw: str) -> tuple[str, str]:
    """Split a "中文\nEnglish" or "中文 English" string."""
    name_raw = name_raw.strip()
    if "\n" in name_raw:
        zh, en = name_raw.split("\n", 1)
        return zh.strip(), en.strip()
    # Sometimes "中文 English" (space-separated)
    parts = name_raw.split(" ", 1)
    if any(ord(c) > 127 for c in parts[0]) and len(parts) > 1:
        return parts[0], parts[1].strip()
    return name_raw, ""


# Building names whose Chinese part is generic (no distinguishing number).
# When we see one of these with a numbered English suffix like "Dorm Block 13",
# we synthesize a unique Chinese name like "宿舍13栋" so the user can
# distinguish them. The English name's trailing number is the disambiguator.
_GENERIC_ZH_NAMES = {"宿舍", "教师公寓", "创园", "荔园", "慧园", "欣园", "荔园南站"}


def _synthesize_unique_name(name_zh: str, name_en: str) -> str:
    """If name_zh is generic and name_en has a distinguishing number,
    synthesize a unique Chinese name by appending the English number.

    Example: ('宿舍', 'Dorm Block 13') → '宿舍13栋'
             ('创园', 'ChuangYuan 5')    → '创园5栋'
             ('台州楼', 'Taizhou Hall')   → '台州楼' (no change)
    """
    if name_zh not in _GENERIC_ZH_NAMES or not name_en:
        return name_zh
    # Pull the trailing integer from the English name
    m = re.search(r"(\d+)\s*$", name_en)
    if not m:
        return name_zh
    n = m.group(1)
    return f"{name_zh}{n}栋"


def _slug_from_name(name_zh: str, name_en: str) -> str:
    """Build a unique facility_id slug from Chinese + English names.

    If the Chinese name was synthesized to include a number (because the
    original was generic), the slug will include that number and be unique.
    Otherwise we fall back to a slug derived from name_zh + a counter.
    """
    # Prefer the synthesized Chinese name if it has a number
    if name_zh and any(c.isdigit() for c in name_zh):
        return name_zh
    # Generic Chinese + numbered English → use "name_zh{N}"
    if name_zh in _GENERIC_ZH_NAMES and name_en:
        m = re.search(r"(\d+)\s*$", name_en)
        if m:
            return f"{name_zh}{m.group(1)}"
    # Otherwise just use the Chinese name; uniqueness is the caller's job
    return name_zh or name_en or "unknown"


# -- Bus route / line --------------------------------------------------------

@dataclass
class BusLine:
    """A bus route configuration."""
    id: str                       # "line1", "short_down", etc.
    title: str                    # bilingual title
    routes: List["BusSubRoute"]   # the actual route definitions


@dataclass
class BusSubRoute:
    """One direction of a bus line."""
    name: str                     # "1路 内环"
    description: str              # "顺时针 / Clockwise\n欣园 → 欣园"
    kind: str = "loop"            # "loop" or "point-to-point"
    color: str = "#888"
    line_code: str = ""           # XYBS1 / XYBS2 (live API code)
    direction: int = 0            # 0=CW, 1=CCW
    sources: List[dict] = field(default_factory=list)

    @classmethod
    def from_api(cls, raw: dict, line_id: str) -> "BusSubRoute":
        """Parse one route entry from bus_config.json."""
        # Try to figure out line_code + direction from sources URLs
        # e.g. /bus_times/one_down.json → Line 1, CW (since XYBS1/0 is CW)
        line_code = ""
        direction = 0
        for s in raw.get("sources", []):
            url = s.get("url", "")
            if "one_" in url or "short_down" in url:
                line_code = ROUTE_XYBS1; direction = DIR_CW
            elif "two_" in url or "short_up" in url:
                line_code = ROUTE_XYBS2; direction = DIR_CCW
            elif "shuttle" in url.lower():
                pass  # shuttle uses different codes
        return cls(
            name=raw.get("name", ""),
            description=raw.get("description", ""),
            kind=raw.get("type", "loop"),
            color=raw.get("color", "#888"),
            line_code=line_code,
            direction=direction,
            sources=raw.get("sources", []),
        )


# -- Bus schedule ------------------------------------------------------------

@dataclass
class BusSchedule:
    """Departure times for one sub-route on one day-type."""
    line_id: str
    title: str
    day_type: str                 # "workday" or "holiday"
    sub_route_name: str
    sub_route_desc: str
    color: str
    times: List[str] = field(default_factory=list)     # ["07:20", "07:30", ...]
    minute_on_road: int = 25      # ride duration for the full route

    def next_departures(self, now_min: int, *, count: int = 5) -> List[str]:
        """Return the next `count` departure times after `now_min` (today only).

        now_min = current time as minutes since 00:00 (e.g. 14:35 → 875).
        """
        def to_min(t: str) -> int:
            h, m = t.split(":")
            return int(h) * 60 + int(m)
        return [t for t in self.times if to_min(t) >= now_min][:count]

    def is_running_now(self, now_min: int) -> bool:
        """Is there a bus that has left the terminus within the last `minute_on_road` minutes?"""
        def to_min(t: str) -> int:
            h, m = t.split(":")
            return int(h) * 60 + int(m)
        for t in self.times:
            start = to_min(t)
            if start <= now_min <= start + self.minute_on_road:
                return True
        return False

    def to_markdown(self) -> str:
        times_str = ", ".join(self.times[:10])
        if len(self.times) > 10:
            times_str += f" … ({len(self.times)} total)"
        return (
            f"### {self.sub_route_name} — {self.title}\n"
            f"- **Day**: {self.day_type}\n"
            f"- **Description**: {self.sub_route_desc}\n"
            f"- **Ride duration**: ~{self.minute_on_road} min\n"
            f"- **First departures**: {times_str}\n"
        )


# -- Live bus -----------------------------------------------------------------

@dataclass
class LiveBus:
    """Real-time bus position (polled from /api/v2/monitor_osm)."""
    bus_id: str
    lat: float
    lng: float
    speed_kmh: float = 0.0
    course: int = 0              # bearing in degrees (0=N, 90=E)
    is_operating: bool = True
    route_code: str = ""          # NKDH1 / NKDH2 / SEV
    next_station: str = ""
    prev_station_id: str = ""
    timestamp: int = 0           # epoch seconds

    @classmethod
    def from_api(cls, raw: dict) -> "LiveBus":
        return cls(
            bus_id=raw.get("id", ""),
            lat=float(raw.get("lat", 0)),
            lng=float(raw.get("lng", 0)),
            speed_kmh=float(raw.get("speed", 0) or 0),
            course=int(raw.get("course", 0)),
            is_operating=bool(int(raw.get("is_operating", 0))),
            route_code=raw.get("route_code", ""),
            next_station=raw.get("next_station_string", ""),
            prev_station_id=str(raw.get("prev_station_id", "")),
            timestamp=int(raw.get("time_mt", 0)),
        )

    def to_geojson_feature(self) -> dict:
        return {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [self.lng, self.lat]},
            "properties": {
                "bus_id": self.bus_id,
                "route_code": self.route_code,
                "next_station": self.next_station,
                "speed_kmh": self.speed_kmh,
                "course": self.course,           # bearing 0-360 (0=N, 90=E) — used for arrow rotation
                "is_operating": self.is_operating,
                "timestamp": self.timestamp,
            },
        }


# -- Routing ----------------------------------------------------------------

@dataclass
class PathStep:
    """One leg of a route — either a walk or a bus ride."""
    mode: str                       # "walk" or "bus"
    from_name: str
    to_name: str
    duration_min: float             # estimated
    distance_m: float               # for walk: meters; for bus: km or stops
    details: str = ""               # free-form: "Line 1 (CW)" or "via 慧园"

    def to_markdown(self) -> str:
        icon = "🚶" if self.mode == "walk" else "🚌"
        return (
            f"{icon} **{self.mode.upper()}** {self.from_name} → {self.to_name}  "
            f"({self.duration_min:.1f} min, {self.distance_m:.0f} m)"
            + (f"  \n   _{self.details}_" if self.details else "")
        )


@dataclass
class Route:
    """A complete route from origin to destination."""
    origin: str
    destination: str
    steps: List["PathStep"] = field(default_factory=list)
    total_minutes: float = 0.0
    total_meters: float = 0.0

    def to_markdown(self) -> str:
        lines = [f"### Route: {self.origin} → {self.destination}"]
        lines.append(f"**Total**: {self.total_minutes:.1f} min, {self.total_meters:.0f} m, {len(self.steps)} steps")
        lines.append("")
        for i, step in enumerate(self.steps, 1):
            lines.append(f"{i}. {step.to_markdown()}")
        return "\n".join(lines)

    def to_geojson(self) -> dict:
        """One LineString per leg, plus a FeatureCollection."""
        features = []
        for s in self.steps:
            features.append({
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": []},
                "properties": {"mode": s.mode, "details": s.details,
                               "duration_min": s.duration_min,
                               "from": s.from_name, "to": s.to_name},
            })
        return {"type": "FeatureCollection", "features": features}


# Keep old name as alias for backwards compatibility (matches user's request "Route")
Path = Route


# -- Errors ------------------------------------------------------------------

class TransitError(Exception):
    """Raised when transit APIs return an error."""