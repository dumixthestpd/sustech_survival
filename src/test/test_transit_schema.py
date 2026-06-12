"""
test_transit_schema.py — Offline schema parsing tests.

Uses fixture dicts that mimic the real bus.sustcra.com + sustech.online
API responses. No network.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from sustech_survival.transit.schema import (
    Facility, BusLine, BusSubRoute, BusSchedule, LiveBus,
    Route, PathStep,
    KIND_BUILDING, KIND_GATE, KIND_BUS_STOP,
    ROUTE_XYBS1, ROUTE_XYBS2, DIR_CW, DIR_CCW,
    DAY_WORKDAY, DAY_HOLIDAY,
    haversine_m,
)


# ── Haversine ──────────────────────────────────────────────────────────────

class TestHaversine:
    def test_same_point_zero(self):
        assert haversine_m(113.99, 22.60, 113.99, 22.60) == 0.0

    def test_short_distance(self):
        # 1 degree of longitude at lat 22.6 ≈ 102 km (cos(22.6°) × 111km)
        d = haversine_m(113.99, 22.60, 114.00, 22.60)
        assert 1000 < d < 1060  # ~1026m

    def test_latitude_distance(self):
        # 1 degree of latitude ≈ 111 km always
        d = haversine_m(113.99, 22.60, 113.99, 23.60)
        assert 110000 < d < 112000  # ~110.6km

    def test_sustech_campus_distance(self):
        # 工学院 → 欣园 ~1.5km
        d = haversine_m(113.990176, 22.603264, 113.997557, 22.610640)
        assert 800 < d < 1500


# ── Facility parsing ───────────────────────────────────────────────────────

class TestFacilityFromBldg:
    def test_basic(self):
        f = Facility.from_bldg({
            "type": "Feature",
            "properties": {"name": "台州楼 Taizhou Hall", "styleUrl": "#m_ylw-pushpin0"},
            "geometry": {"type": "Point", "coordinates": [113.9907631537436, 22.59765486387274, 0.0]},
        })
        assert f.facility_id == f"{KIND_BUILDING}:台州楼"
        assert f.name == "台州楼"
        assert f.name_en == "Taizhou Hall"
        assert f.kind == KIND_BUILDING
        assert f.lat == pytest.approx(22.59765)
        assert f.lng == pytest.approx(113.99076)

    def test_chinese_only(self):
        f = Facility.from_bldg({
            "type": "Feature",
            "properties": {"name": "行政楼 Administration Bldg.", "styleUrl": "#x"},
            "geometry": {"type": "Point", "coordinates": [113.99, 22.60, 0.0]},
        })
        assert f.name == "行政楼"
        assert f.name_en == "Administration Bldg."

    def test_distance_to(self):
        a = Facility(facility_id="a", name="A", lat=22.60, lng=113.99)
        b = Facility(facility_id="b", name="B", lat=22.61, lng=113.99)
        d = a.distance_to(b)
        assert 1100 < d < 1200  # ~1.1 km

    def test_to_geojson(self):
        f = Facility(facility_id="building:X", name="X", name_en="X-EN",
                     kind=KIND_BUILDING, lat=22.60, lng=113.99)
        gj = f.to_geojson_feature()
        assert gj["type"] == "Feature"
        assert gj["geometry"]["coordinates"] == [113.99, 22.60]
        assert gj["properties"]["facility_id"] == "building:X"


class TestFacilityFromGate:
    def test_basic(self):
        f = Facility.from_gate({
            "type": "Feature",
            "properties": {"name": "一号门 Gate1", "styleUrl": "#x"},
            "geometry": {"type": "Point", "coordinates": [113.994, 22.595, 0.0]},
        })
        assert f.kind == KIND_GATE
        assert f.name == "一号门"
        assert f.name_en == "Gate1"


class TestFacilityFromBusStop:
    def test_basic(self):
        f = Facility.from_bus_stop({
            "type": "Feature",
            "properties": {"name": "工学院\nCOE", "station_id": 1, "dist": 0},
            "geometry": {"type": "Point", "coordinates": [113.99, 22.60]},
        }, line_code="XYBS1", direction=0)
        assert f.kind == KIND_BUS_STOP
        assert f.facility_id == f"{KIND_BUS_STOP}:1"
        assert f.name == "工学院"
        assert f.name_en == "COE"
        assert "XYBS1/0" in f.routes
        assert f.meta["station_id"] == 1


# ── BusSubRoute parsing ───────────────────────────────────────────────────

class TestBusSubRoute:
    def test_basic(self):
        sub = BusSubRoute.from_api({
            "name": "1路 内环",
            "description": "顺时针 / Clockwise\n欣园 → 欣园 Joy Highland Loop)",
            "type": "loop",
            "color": "#00ab5b",
            "sources": [
                {"url": "/bus_times/one_down.json", "type": "bus"},
            ],
        }, line_id="line1")
        assert sub.name == "1路 内环"
        assert sub.line_code == ROUTE_XYBS1
        assert sub.direction == DIR_CW
        assert sub.color == "#00ab5b"

    def test_short_down(self):
        sub = BusSubRoute.from_api({
            "name": "区间快速下行 A",
            "description": "test",
            "sources": [{"url": "/bus_times/short_down_a.json", "type": "bus"}],
        }, line_id="short_down")
        assert sub.line_code == ROUTE_XYBS1
        assert sub.direction == DIR_CW


# ── BusSchedule ───────────────────────────────────────────────────────────

class TestBusSchedule:
    def _sched(self):
        return BusSchedule(
            line_id="line1",
            title="1 路 / Line 1",
            day_type=DAY_WORKDAY,
            sub_route_name="1路 内环",
            sub_route_desc="顺时针",
            color="#00ab5b",
            times=["07:20", "07:30", "08:00", "12:00", "18:00"],
            minute_on_road=25,
        )

    def test_next_departures(self):
        s = self._sched()
        # 09:00 → next are 12:00 and 18:00
        nxt = s.next_departures(9 * 60)
        assert nxt == ["12:00", "18:00"]

    def test_next_departures_late(self):
        s = self._sched()
        # 23:00 → no more
        assert s.next_departures(23 * 60) == []

    def test_next_departures_early(self):
        s = self._sched()
        # 07:25 → next are 07:30, 08:00, 12:00, 18:00
        nxt = s.next_departures(7 * 60 + 25)
        assert nxt == ["07:30", "08:00", "12:00", "18:00"]

    def test_is_running_now(self):
        s = self._sched()
        # 07:30 → 07:30 to 07:55 → running
        assert s.is_running_now(7 * 60 + 30)
        # 08:30 → 08:30 > 07:55 → not running
        assert not s.is_running_now(8 * 60 + 30)


# ── LiveBus ─────────────────────────────────────────────────────────────────

class TestLiveBus:
    def test_basic(self):
        b = LiveBus.from_api({
            "id": "BS123",
            "time_mt": 1781276380,
            "lng": 113.99666,
            "lat": 22.61042,
            "speed": "0.0",
            "course": 0,
            "is_operating": 1,
            "route_dir": "0",
            "route_sn": "1",
            "route_code": "NKDH2",
            "next_station_string": "慧园",
            "prev_station_id": "1",
        })
        assert b.bus_id == "BS123"
        assert b.lat == pytest.approx(22.61042)
        assert b.lng == pytest.approx(113.99666)
        assert b.route_code == "NKDH2"
        assert b.next_station == "慧园"
        assert b.is_operating

    def test_to_geojson(self):
        b = LiveBus(bus_id="X", lat=22.6, lng=114.0,
                    route_code="NKDH1", next_station="A", speed_kmh=10)
        gj = b.to_geojson_feature()
        assert gj["geometry"]["coordinates"] == [114.0, 22.6]


# ── Route (Path) ───────────────────────────────────────────────────────────

class TestRoute:
    def test_to_markdown(self):
        p = Route(
            origin="A / A-EN",
            destination="B / B-EN",
            steps=[
                PathStep(mode="walk", from_name="A", to_name="C",
                         duration_min=2.0, distance_m=150),
                PathStep(mode="bus", from_name="C", to_name="D",
                         duration_min=10.0, distance_m=2000,
                         details="Line 1 (CW): C → D"),
            ],
            total_minutes=12.0,
            total_meters=2150,
        )
        md = p.to_markdown()
        assert "Route: A" in md and "→" in md and "B / B-EN" in md
        assert "12.0 min" in md
        assert "🚶" in md
        assert "🚌" in md
        assert "Line 1 (CW)" in md