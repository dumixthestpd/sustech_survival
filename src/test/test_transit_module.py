"""
test_transit_module.py — Module surface + live API tests (marked @pytest.mark.live).

Most tests are offline; live tests verify the end-to-end API flow.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from sustech_survival.transit import (
    TransitClient, transit,
    Facility, BusLine, BusSubRoute, BusSchedule, LiveBus, Route, PathStep,
    TransitError,
    KIND_BUILDING, KIND_GATE, KIND_BUS_STOP,
    ROUTE_XYBS1, ROUTE_XYBS2, DIR_CW, DIR_CCW,
    DAY_WORKDAY, DAY_HOLIDAY,
    WALK_SPEED_KMH, WALK_CONNECT_RADIUS_M,
)


# ── Module surface ──────────────────────────────────────────────────────────

class TestModuleExports:
    def test_all_classes(self):
        for cls in [TransitClient, Facility, BusLine, BusSubRoute,
                    BusSchedule, LiveBus, Route, PathStep, TransitError]:
            assert cls is not None

    def test_all_constants(self):
        assert ROUTE_XYBS1 == "XYBS1"
        assert ROUTE_XYBS2 == "XYBS2"
        assert DIR_CW == 0
        assert DIR_CCW == 1
        assert DAY_WORKDAY == "workday"
        assert DAY_HOLIDAY == "holiday"
        assert KIND_BUILDING == "building"
        assert KIND_GATE == "gate"
        assert KIND_BUS_STOP == "bus_stop"
        assert WALK_SPEED_KMH > 0
        assert WALK_CONNECT_RADIUS_M > 0


# ── Construction ───────────────────────────────────────────────────────────

class TestTransitClientConstruction:
    def test_default_session(self):
        import requests
        c = TransitClient()
        assert isinstance(c.session, requests.Session)

    def test_custom_session(self):
        import requests
        sess = requests.Session()
        c = TransitClient(session=sess)
        assert c.session is sess

    def test_user_agent_set(self):
        c = TransitClient()
        assert "Macintosh" in c.session.headers["User-Agent"]


# ── Live API tests ─────────────────────────────────────────────────────────

@pytest.mark.live
class TestLiveAPI:
    """Run with: pytest src/test/test_transit_module.py -m live

    Requires live internet access to bus.sustcra.com + sustech.online.
    """

    def test_list_buildings(self):
        c = TransitClient()
        bldgs = c.list_buildings()
        assert len(bldgs) > 0
        assert all(isinstance(b, Facility) for b in bldgs)
        assert any(b.kind == KIND_BUILDING for b in bldgs)

    def test_list_gates(self):
        c = TransitClient()
        gates = c.list_gates()
        assert len(gates) >= 7  # SUSTech has 7 gates
        assert all(g.kind == KIND_GATE for g in gates)

    def test_find_facility(self):
        c = TransitClient()
        hits = c.find_facility("欣园")
        assert len(hits) > 0
        names = {h.name for h in hits}
        assert "欣园" in names

    def test_find_facility_no_match(self):
        c = TransitClient()
        hits = c.find_facility("nonexistent_xyzzy")
        assert hits == []

    def test_list_bus_lines_workday(self):
        c = TransitClient()
        lines = c.list_bus_lines(day_type=DAY_WORKDAY)
        assert len(lines) > 0
        line_ids = {l.id for l in lines}
        assert "line1" in line_ids

    def test_get_schedule(self):
        c = TransitClient()
        s = c.get_schedule("line1", sub_route_index=0, day_type=DAY_WORKDAY)
        assert len(s.times) > 0
        assert s.minute_on_road > 0
        # All times should be HH:MM
        for t in s.times:
            assert ":" in t
            h, m = t.split(":")
            assert 0 <= int(h) < 24
            assert 0 <= int(m) < 60

    def test_get_bus_stops(self):
        c = TransitClient()
        stops = c.get_bus_stops("XYBS1", DIR_CW)
        assert len(stops) > 0
        # All should have station_id
        for s in stops:
            assert s.meta.get("station_id") is not None

    def test_route_path_geojson(self):
        c = TransitClient()
        geo = c.get_route_path_geojson("XYBS1", DIR_CW)
        assert geo["type"] == "FeatureCollection"
        assert len(geo.get("features", [])) > 0

    def test_shortest_path_walk(self):
        c = TransitClient()
        # 工学院 (bus_stop:1) → 欣园 (bus_stop:14) via walking only
        path = c.shortest_path("bus_stop:1", "bus_stop:14", mode="walk",
                               walk_radius_m=500)
        assert path.total_minutes > 0
        assert len(path.steps) > 0
        # All steps should be walks
        assert all(s.mode == "walk" for s in path.steps)

    def test_shortest_path_transit(self):
        c = TransitClient()
        # gate:一号门 → 欣园 (Joy Highland 1), should use bus
        path = c.shortest_path("gate:一号门", "building:欣园1栋",
                               mode="transit", walk_radius_m=250)
        assert path.total_minutes > 0
        # Should have at least one walk + possibly a bus
        modes = {s.mode for s in path.steps}
        assert "walk" in modes or "bus" in modes

    def test_shortest_path_unknown_raises(self):
        c = TransitClient()
        with pytest.raises(ValueError):
            c.shortest_path("nonsense_id_xyz", "bus_stop:1")

    def test_export_geojson(self, tmp_path):
        c = TransitClient()
        written = c.export_geojson(tmp_path)
        assert "facilities" in written
        assert "bus_stops" in written
        assert "live_buses" in written
        assert "schedules" in written
        # Verify files actually exist
        for k, v in written.items():
            if isinstance(v, list):
                for p in v:
                    assert Path(p).exists()
            else:
                assert Path(v).exists()