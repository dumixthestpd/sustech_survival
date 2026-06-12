# transit reverse-engineering notes — 2026-06-12

Built `sustech_survival.transit` (submodule + CLI + Leaflet web UI on port 61019)
by walking the sustech.online + bus.sustcra.com source. This doc captures
the raw findings for future reference.

## Naming choice

User originally said "transportation" — asked for shorter. Picked `transit`:
- Short (7 chars)
- Covers buses + walking + navigation
- Doesn't conflict with anything else in sustech_survival

The user mentioned two sub-features: `nav` and `bus`. They're now
`TransitClient.shortest_path()` and the bus methods
(`get_schedule`, `get_live_positions`, etc.). Plus a web UI.

## Data sources

### sustech.online (汉典手册 — CRA-maintained)

| URL | Returns |
|-----|---------|
| `/bus_config.json` | {workday: [...], holiday: [...]} — line IDs + sub-route configs |
| `/bus_times/one_down.json` etc | {times: ["07:20", ...], minuteOnRoad: 25} |
| `/transport/bustimer.html` | SPA wrapper, links to the SVGs |

The two big SVG files referenced by bustimer.md are visual-only (no text extraction):

- `https://mirrors.sustech.edu.cn/site/sustech-online/img/campus-map/sustech_bus_map_2025.11.24.svg` (2 MB) — visual map with bus routes
- `https://mirrors.sustech.edu.cn/site/sustech-online/img/campus-map/sustech_bus_schedule_2025.11.24.svg` (1.5 MB) — schedule table

We don't parse these. The structured data lives in `/bus_config.json` + `/bus_times/*.json`.

### bus.sustcra.com (real-time GPS)

| Endpoint | Returns |
|----------|---------|
| `/geojson/sustech_bldg.json` | GeoJSON of 76 buildings (some duplicates) |
| `/geojson/sustech_gate.json` | GeoJSON of 7 gates |
| `/static/lines/NKDH1_clockwise.json` | GeoJSON LineString for the bus route path |
| `/static/lines/XYBS1_clockwise.json` | Same for line 1 |
| `/static/lines/XYBS2.json` | Same for line 2 (no suffix!) |
| `/api/v3/avail_route` | `{"routes": [{"name": "XYBS1", "direction": "0"}, ...]}` |
| `/api/v3/{line}/{dir}/stations` | GeoJSON of ordered bus stops with station_id |
| `/api/v2/monitor_osm/` | Live bus positions (NKDH1/NKDH2) |
| `/api/v2/monitor_sev_osm/` | Live shuttle (电瓶车) positions |

The line geometry files only exist for 3 routes:
- `NKDH1_clockwise` (Line 1 CW)
- `XYBS1_clockwise` (Line 1 CW, alternate naming)
- `XYBS2` (Line 2, no direction suffix)

So counter-clockwise routes (XYBS1/1, XYBS2/1) have NO geometry file. The `get_route_path_geojson` method tries multiple naming conventions and falls back gracefully.

## Bus line configuration (sustech.online/bus_config.json)

```json
{
  "workday": [
    {
      "id": "line1",
      "title": "1 路 / Line 1",
      "routes": [
        {
          "name": "1路 内环",
          "description": "顺时针 / Clockwise\n欣园 → 欣园 Joy Highland Loop)",
          "type": "loop",
          "color": "#00ab5b",
          "sources": [
            {"url": "/bus_times/one_down.json", "type": "bus"},
            {"url": "/bus_times/one_shuttle_down.json", "type": "shuttle"}
          ]
        }
      ]
    },
    ...more lines (line2, short_down, short_up, ipark, sofun)
  ],
  "holiday": [...]
}
```

Sources URL heuristic for figuring out line_code + direction:
- `one_*` or `short_down_*` → XYBS1, DIR_CW
- `two_*` or `short_up_*` → XYBS2, DIR_CCW
- `*shuttle_*` → no line code (we skip these)

The shuttle sources don't have geometry or live data — just static schedules.

## Bus stop names

The `/api/v3/.../stations` endpoint returns names like:

```json
{"name": "工学院\nCOE", "station_id": 1}
{"name": "欣园\nJoy Highland", "station_id": 14}
```

The `\n` separator splits Chinese and English. `Facility._split_bilingual()`
handles this.

## Schedule JSON format

```json
{
  "times": ["07:20", "07:30", "07:40", ...],
  "minuteOnRoad": 25
}
```

- `times`: list of "HH:MM" departure times from the terminus
- `minuteOnRoad`: total ride duration for the full route (used for "is bus currently running")

Effective from 2025.11.24 (corrected 2026.05.09 to actual schedule).

## Live positions format

```json
[{
  "id": "BS79689D",
  "time_mt": 1781276380,
  "lng": 113.99666,
  "lat": 22.61042333,
  "speed": "0.0",
  "course": 0,
  "is_operating": 1,
  "route_dir": "0",
  "route_sn": "1",
  "route_code": "NKDH2",       ← NOT XYBS2! use this for display
  "next_station_string": "慧园",
  "prev_station_id": "1"
}]
```

Note: `route_code` in live data is `NKDH1`/`NKDH2`/`SEV`, NOT `XYBS1`/`XYBS2`. Two separate naming systems. We use XYBS1/XYBS2 for the schedule graph and NKDH1/NKDH2 for the live feed — the mapping is implicit (Line 1 = XYBS1 ↔ NKDH1, Line 2 = XYBS2 ↔ NKDH2).

`monitor_osm/` returns empty array when no buses are running.

## Web UI architecture

```
GET /             → /index.html (Leaflet map UI)
GET /static/*     → /transit/web/static/* (CSS + JS)
GET /data/*.geojson → files from --data-dir (served from there)
GET /data/schedules.json → from --data-dir
GET /data/live_buses.geojson → from --data-dir
GET /data/bus_lines/*.geojson → from --data-dir
```

The frontend does:
1. Fetch all GeoJSON files on load
2. Render buildings (🏢), gates (🚪), bus stops (🚏), live buses (🚌)
3. Render bus line polylines in their config colors
4. Provide a from/to finder with autocomplete from facility names
5. Run Dijkstra client-side over a graph built from the same data
6. Render the path as a polyline on the map + steps list in the sidebar
7. Show the schedule (workday/holiday toggle) with next-departure highlighting
8. Auto-poll /data/live_buses.geojson every 30s

## Routing algorithm

Dijkstra over a graph with:
- **Nodes**: every facility (building + gate + bus stop), keyed by `facility_id`
- **Walking edges**: any pair within 250m → 4.5 km/h walking time
- **Bus edges**: consecutive stops on each line/direction → ~2.5 min/km ride time + 5 min transfer penalty

For `mode="transit"` we use both walking and bus edges. `mode="walk"` filters to walking only. `mode="bus"` filters to bus only (forces at least one bus ride; not useful in practice — transit mode is what you want).

## Sample route results

| Query | Mode | Time | Steps |
|-------|------|------|-------|
| `bus_stop:1 (工学院) → bus_stop:14 (欣园)` | walk | 20.3 min | 8 walks |
| `gate:一号门 → building:欣园` | transit | 24.0 min | 7 walks + 1 bus |
| `building:琳恩图书馆 → building:台州楼` | walk | ~5 min | 2-3 walks |

## Caveats / future work

- **`Path` vs `Route` naming**: originally called the dataclass `Path` but that shadowed `pathlib.Path` in transit.py. Renamed to `Route` (matches user's terminology) and kept `Path = Route` as alias.
- **Transfer penalty** is per-edge, not per-transfer. Would need a 2-layer graph for accurate cost.
- **Real wait time** could be computed from the schedule: `next_departure(now) - now`. Currently we use a constant `WAIT_HEADWAY_MIN/2 = 5 min` average.
- **Shuttle (电瓶车) lines** have schedule JSONs but no live GPS data — the monitor_sev_osm endpoint may or may not return data depending on time of day.
- **Anubis bot detection** blocks browser access to sustech.online (the iframe with the map refuses with "错误代码 4d1dbaddfcc0f385"). Our direct API calls work fine, but interactive browser viewing of the manual itself is blocked.

## Source files captured

- `https://sustech.online/transport/bustimer.html` (31 KB) — bus timer SPA wrapper
- `https://sustech.online/bus_config.json` (8.9 KB) — bus line configuration
- `https://sustech.online/bus_times/one_down.json` (815 B) — sample schedule
- `https://mirrors.sustech.edu.cn/site/sustech-online/img/campus-map/sustech_bus_map_2025.11.24.svg` (2 MB) — visual map (not parsed)
- `https://mirrors.sustech.edu.cn/site/sustech-online/img/campus-map/sustech_bus_schedule_2025.11.24.svg` (1.5 MB) — visual schedule (not parsed)
- `https://bus.sustcra.com/geojson/sustech_bldg.json` (14.7 KB) — buildings
- `https://bus.sustcra.com/geojson/sustech_gate.json` (1.4 KB) — gates
- `https://bus.sustcra.com/static/lines/XYBS1_clockwise.json` (27 KB) — line geometry
- `https://bus.sustcra.com/static/lines/XYBS2.json` (2.3 KB) — line geometry
- `https://bus.sustcra.com/api/v3/avail_route` — route list
- `https://bus.sustcra.com/api/v3/XYBS1/0/stations` — bus stops

All read in 2026-06-12.