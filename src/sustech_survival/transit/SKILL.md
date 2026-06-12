---
name: transit
description: SUSTech campus navigation + bus schedule + live positions. Live client, no cache. Includes a Leaflet web UI on port 61019. Sub-skill of sustech_survival.
owner: Faux
category: sustech
last_updated: 2026-06-12
parent: sustech_survival
---

> **Canonical code lives in the OpenClaw workspace**, not here.
> Real implementation:
> `~/.openclaw/workspace/skills/sustech_survival/src/sustech_survival/transit/`
> Web UI assets: `.../transit/web/`

# transit — SUSTech Campus Navigation &amp; Bus Data (sub-skill)

ONE client. **~12 operations**. ZERO local data. Every call hits the live API.

Two data sources, both pulled live:

| Source | What |
|--------|------|
| `bus.sustcra.com` | Live bus GPS, station coordinates, line geometry |
| `sustech.online` | Bus schedule config + per-line time tables + building/gate coordinates |

## What it does

- `transit.nav` — find the shortest-time route between any two campus
  facilities (buildings, gates, bus stops) using Dijkstra over a graph
  with walking edges (≤250m by default) + bus edges along each line.
- `transit.bus` — query departure schedules, see live bus positions.
- `transit.web` — bundled Leaflet map UI served on port 61019 (or any port).

## Quick start (Python API)

```python
import sys
sys.path.insert(0, '/Users/dumix/.openclaw/workspace/skills/sustech_survival/src')

from sustech_survival.transit import transit

c = transit()

# 76 buildings + 7 gates + 14 bus stops = ~80 facilities
for f in c.list_facilities()[:5]:
    print(f"  {f.display_name}")

# Find by name (Chinese or English)
hits = c.find_facility("欣园")
print(f"\nMatches for '欣园': {len(hits)}")

# Bus schedule — all departures for Line 1 (workday)
s = c.get_schedule("line1")
print(f"\nLine 1: {len(s.times)} departures, ~{s.minute_on_road} min ride")
print(f"  Next 5: {' '.join(s.next_departures(__import__('datetime').datetime.now().hour*60 + __import__('datetime').datetime.now().minute))}")

# Route from 一号门 (Gate 1) to 欣园 (Joy Highland)
path = c.shortest_path("gate:一号门", "building:欣园")
print(path.to_markdown())
```

## Quick start (CLI)

```bash
cd ~/.openclaw/workspace/skills/sustech_survival
PYTHONPATH=src python -m sustech_survival.transit <command>

Commands:
  facilities                  List buildings + gates
  find QUERY                  Fuzzy name search
  stops [--line L] [--dir N]  List bus stops
  lines [--day workday|holiday]  List bus line configs
  schedule LINE_ID [--sub N] [--day workday|holiday]
                              Show departure times
  live                        Poll live bus GPS positions
  route FROM TO [--mode walk|bus|transit] [--walk-radius N]
                              Shortest path between two facilities
  export OUT_DIR              Bundle GeoJSON + JSON for the web UI
  serve [--port N]            Start web UI on port 61019 (or custom)
  web-build OUT_DIR           Write static web files to OUT_DIR (no server)

Global:
  --json                      Machine-readable JSON output
```

Examples:

```bash
# All facilities
PYTHONPATH=src python -m sustech_survival.transit facilities

# Search for a building (Chinese or English)
PYTHONPATH=src python -m sustech_survival.transit find 琳恩图书馆

# Bus schedule
PYTHONPATH=src python -m sustech_survival.transit schedule line1

# Live bus positions
PYTHONPATH=src python -m sustech_survival.transit live

# Find a route
PYTHONPATH=src python -m sustech_survival.transit route 一号门 欣园 --mode transit

# Export data + start web UI on port 61019
PYTHONPATH=src python -m sustech_survival.transit export /tmp/transit_data
PYTHONPATH=src python -m sustech_survival.transit serve --port 61019 --data-dir /tmp/transit_data
```

## Quick start (Web UI)

```bash
# One-shot: export + serve
PYTHONPATH=src python -m sustech_survival.transit export /tmp/transit_data
PYTHONPATH=src python -m sustech_survival.transit serve --port 61019 --data-dir /tmp/transit_data --browser

# Open http://localhost:61019/
```

The web UI shows:
- **Map** (Leaflet + OpenStreetMap tiles) with buildings, gates, bus stops,
  bus line polylines, and live bus positions
- **Route finder** — type any name to autocomplete from/to; computes shortest
  path client-side via Dijkstra over the same graph the Python API uses
- **Bus schedule** — tab between Workday/Weekend, browse all lines + departures;
  the next 5 departures from now are highlighted
- **Live buses** — auto-refreshes every 30 seconds

## API surface

### `TransitClient(session=None)` — one client, all methods

| Method | Endpoint | Returns |
|--------|----------|---------|
| `list_buildings()` | `bus.sustcra.com/geojson/sustech_bldg.json` | `list[Facility]` |
| `list_gates()` | `bus.sustcra.com/geojson/sustech_gate.json` | `list[Facility]` |
| `list_facilities()` | buildings + gates (deduped) | `list[Facility]` |
| `find_facility(query)` | fuzzy name search across all | `list[Facility]` |
| `list_bus_lines(day_type)` | `sustech.online/bus_config.json` | `list[BusLine]` |
| `get_schedule(line_id, sub_route_index, day_type)` | `sustech.online/bus_times/<name>.json` | `BusSchedule` |
| `get_bus_stops(line_code, direction)` | `bus.sustcra.com/api/v3/{code}/{dir}/stations` | `list[Facility]` |
| `get_route_path_geojson(line_code, direction)` | `bus.sustcra.com/static/lines/<name>.json` | `GeoJSON` |
| `get_live_positions(include_shuttles=True)` | `bus.sustcra.com/api/v2/monitor_osm/` + `monitor_sev_osm/` | `list[LiveBus]` |
| `shortest_path(from_id, to_id, mode, walk_radius_m)` | (pure client-side Dijkstra) | `Route` |
| `export_geojson(out_dir)` | bundles everything above | `dict[str, str]` (paths) |

### Module-level singleton

```python
from sustech_survival.transit import transit
c = transit()
```

### Schema (in `sustech_survival.transit.schema`)

| Class | Parses | Key fields |
|-------|--------|-----------|
| `Facility` | `geojson/sustech_bldg.json`, `sustech_gate.json`, `/api/v3/.../stations` | `facility_id`, `name`, `name_en`, `kind`, `lat`, `lng`, `routes` |
| `BusLine` | `bus_config.json` | `id`, `title`, `routes: list[BusSubRoute]` |
| `BusSubRoute` | one entry in BusLine.routes | `name`, `description`, `kind`, `color`, `line_code`, `direction`, `sources` |
| `BusSchedule` | `bus_times/<name>.json` | `times: list[str]`, `minute_on_road`, `next_departures()`, `is_running_now()` |
| `LiveBus` | `monitor_osm/` + `monitor_sev_osm/` | `bus_id`, `lat`, `lng`, `speed_kmh`, `route_code`, `next_station` |
| `Route` | (output of `shortest_path`) | `steps: list[PathStep]`, `total_minutes`, `total_meters`, `to_markdown()`, `to_geojson()` |
| `PathStep` | one leg of a Route | `mode` ("walk"/"bus"), `from_name`, `to_name`, `duration_min`, `distance_m`, `details` |

All have `from_api()` classmethod parsers and `to_markdown()` for AI output.

### Constants

```python
DAY_WORKDAY = "workday", DAY_HOLIDAY = "holiday"
ROUTE_XYBS1 = "XYBS1", ROUTE_XYBS2 = "XYBS2"
DIR_CW = 0, DIR_CCW = 1
KIND_BUILDING = "building", KIND_GATE = "gate", KIND_BUS_STOP = "bus_stop"
WALK_SPEED_KMH = 4.5
WALK_CONNECT_RADIUS_M = 250     # max walking distance to add graph edges
TRANSFER_PENALTY_MIN = 5        # minutes added per bus transfer
WAIT_HEADWAY_MIN = 10           # typical bus headway — used for wait estimates
```

## Architecture

```
sustech_survival/transit/
├── __init__.py        exports TransitClient + schema types + singleton
├── transit.py         TransitClient (one class, all methods)
├── schema.py          Facility, BusLine, BusSubRoute, BusSchedule,
│                      LiveBus, Route, PathStep (all from_api + to_markdown)
├── __main__.py        CLI (human + agent friendly, --json for LLMs)
├── SKILL.md           this file
└── web/
    ├── index.html     Leaflet map UI
    └── static/
        ├── style.css
        └── app.js     Front-end: Dijkstra in JS + Leaflet
```

- **One client class** (TransitClient) — all operations, no scattered functions.
- **Schema classes with classmethod parsers** (`Facility.from_bldg()`, etc.) — never loose `parse_*()` functions.
- **Module-level singleton** (`transit()`) — auto-built, lazy.
- **Web UI on port 61019** — Leaflet map + Dijkstra pathfinding + bus schedule; auto-refreshes live bus positions every 30s.

## Field-name quirks (PMS bus data)

| Endpoint | Field | Notes |
|----------|-------|-------|
| `/api/v3/{line}/{dir}/stations` | `station_id` (int) | Unified key across all bus stops |
| `/api/v3/.../stations` | `name` | `\n`-separated bilingual "中文\nEnglish" |
| `bus_config.json` | `sources[].url` | Relative path `/bus_times/<name>.json` |
| `bus_config.json` | `sources[].type` | "bus" or "shuttle" |
| `monitor_osm/` | `route_code` | NKDH1 / NKDH2 / SEV (not XYBS1/XYBS2) |
| `monitor_osm/` | `next_station_string` | Chinese name of upcoming stop |
| `static/lines/<name>.json` | `clockwise` suffix | Only 3 files exist: NKDH1_clockwise, XYBS1_clockwise, XYBS2 |

## Caveats

- **Live data only** — every call hits the network. No local cache.
- **Routing is approximate.** Walking time uses 4.5 km/h. Bus ride time estimates
  ~2.5 min/km (linear scaling) plus 5 min transfer penalty. Doesn't account
  for actual bus schedules (you might wait longer than expected at off-peak).
- **Transfer penalty** is a per-edge padding in Dijkstra, not a true
  per-transfer cost. For accurate transfer time, would need a 2-layer graph.
- **Live buses** may be empty at off-hours (no buses running).
- **The 6 campus shuttle lines** in `bus_config.json` (ipark, sofun, etc.)
  have schedule JSONs but no live tracking. Schedules work, live doesn't.
- **`bus_stop:1` and `bus_stop:14`** look like raw IDs but they're real
  facility_ids — `工学院` is station_id=1, `欣园` is station_id=14.
- **Browser headless rendering** of the web UI works in normal browsers;
  our headless test browser has CSP/timeout issues with the live tile
  servers. Curl tests confirm the server returns correct data.

## Testing

```bash
cd ~/.openclaw/workspace/skills/sustech_survival
./venv/bin/python -m pytest src/test/test_transit_*.py -v
```

Two test files:
- `test_transit_schema.py` — offline parser tests, haversine, schedule helpers
- `test_transit_module.py` — module surface + live API tests (`@pytest.mark.live`)

The live tests auto-run by default (they're fast). Skip with `pytest -m "not live"`.

## See also

- `sustech_survival` — parent skill (TIS, BB, faculty, PMS, etc.)
- `references/transit-flow-analysis-2026-06-12.md` — the reverse-engineering
  notes for this module (TODO: write after first real use)