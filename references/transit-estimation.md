# Transit estimation models — formulas & tunable constants

This document describes how `sustech_survival.transit` estimates travel times
for walking, biking, and bus riding on the SUSTech campus. The web UI at
`http://localhost:61019/` uses the same formulas (in `web/static/app.js`,
function `segmentDuration`).

The models are intentionally **simple, transparent, and tunable** so you can
adjust them as you collect better ground-truth data.

## Speeds (constants in `state.PARAMS`)

| Constant | Default | What |
|----------|---------|------|
| `walkFlatKmh` | 4.5 km/h | Average pedestrian flat-ground speed |
| `bikeFlatKmh` | 16.0 km/h | Casual cyclist flat-ground speed |
| `toblerMaxKmh` | 6.0 km/h | Peak Tobler speed (at -5% downhill) |
| `toblerAscentCoef` | 3.5 | Tobler's `k` (slope sensitivity) |
| `bikeClimbCoef` | 10.0 | Bike climb-fraction multiplier |
| `transferPenaltyMin` | 5 min | Per-bus-transfer pad |
| `waitHeadwayMin` | 10 min | Typical bus headway |

All constants live in one place. Edit the values in `app.js` (the `PARAMS`
object in the IIFE state) to taste.

## Walk: Tobler's hiking function (1993)

For each segment between two map points we know `distance_m` and `climb_m`
(positive = uphill). Slope `s = climb_m / distance_m`.

```
v(slope) = toblerMaxKmh · exp(-toblerAscentCoef · |slope + 0.05|)
duration_min = (distance_m / 1000) / v · 60
```

The `+0.05` offset means the **peak speed is at slope = -5% (gentle downhill)**.
It falls off rapidly uphill: at +5% slope the speed is the same as at -15%
downhill. This is the classic Tobler result.

If `state.elevation` is empty (e.g. export ran with `--no-elevation`),
falls back to a flat 4.5 km/h.

## Bike: simple climb-penalty model

Cycling is dominated by the **climb fraction** (vertical gain / distance).
Downhill is free (gravity + freewheel); uphill requires real work.

```
climbFraction = max(0, climb_m) / max(distance_m, 1)
speed_kmh = bikeFlatKmh / (1 + bikeClimbCoef · climbFraction)
duration_min = (distance_m / 1000) / speed_kmh · 60
```

With defaults: 16 km/h flat, dropping to 8 km/h on a 6.25% climb (the kind
of grade you find between 荔园 and 欣园 over 茶光山). On a steep 15% climb
the model says 5.3 km/h — close to a slog.

## Bus: ~2.5 min/km + transfer penalty

```
duration_min = (distance_m / 1000) · 2.5 + 0.1 + transferPenaltyMin / 2
```

The `2.5 min/km` matches the campus bus schedule's `minute_on_road = 25`
across ~10 km/h average speed. The half-transfer penalty is an approximation
of "average wait time" — we add the full `transferPenaltyMin` only when the
route actually requires a transfer (in the path-reconstruction step, which
is a future TODO).

The bus model does NOT account for elevation — a diesel bus doesn't care
about 70 m of climb.

## Edge graph

The path graph has three node types and three edge types:

| Node type | Where they come from | Count (approx) |
|-----------|----------------------|-----------------|
| Facility | `facilities.geojson` + `bus_stops.geojson` | ~100 |
| Footway vertex | `footways.json` (OSM Overpass) | ~1400 |
| (bus edges are stops-to-stops; no bus-edge-only nodes) | | |

Edges:

| Type | From → To | Mode filter |
|------|-----------|-------------|
| Walk (footway) | consecutive vertices along an OSM footway/path | walk, bike, transit |
| Walk (access) | each facility ↔ nearest footway vertex (≤80 m) | walk, bike, transit |
| Bus | consecutive bus stops on each line/direction | bus, transit |

If `footways.json` is missing or empty, the graph falls back to direct
facility-to-facility edges within 250 m (the old "straight line" behavior).

## Pathfinding

Plain Dijkstra over the graph, mode-filtered edges:

| UI mode | Allowed edge modes |
|---------|-------------------|
| `walk` | walk only |
| `bike` | walk only (cyclist on the path network) |
| `bus` | bus only |
| `transit` | walk + bus |

Reconstruction walks the `prev` chain from `dst` back to `src`. The
returned edges preserve the actual footway geometry, so the polyline on the
map shows the real path — not a straight line through buildings.

## Future improvements

- **Per-transfer cost**: instead of padding every bus edge, charge the
  `transferPenaltyMin` only when the path actually changes bus line. Needs a
  small graph enhancement (record which line each edge belongs to).
- **Schedule-aware wait time**: instead of `waitHeadwayMin / 2`, look up
  the next departure of that line from the schedule and add that delta.
- **Real-time bus**: a "live bus ride" mode that catches a bus currently
  near your origin (from `/data/live_buses.geojson`).
- **Footway-aware facility access**: snap each facility to the nearest *two*
  footway vertices and add access edges to both, so route-finding doesn't
  backtrack through the facility.
- **Hill-aware bike routing**: currently the penalty uses `climb_fraction`
  (height/distance). A more accurate model uses power = m·g·v·sin(θ) +
  k·v³ (rolling + drag) but that's overkill for campus.
- **Custom user profile**: expose the `PARAMS` in the UI as sliders so
  users can tune their own walk/bike speeds ("I'm fast", "I hate hills").

## Why these formulas?

- **Tobler (1993)** is the canonical pedestrian speed model. Used by
  OSRM's `foot` profile, GraphHopper, and most academic routing work.
- **Bike climb fraction** is a simplified version of the "loaded bicycle
  power model" — good enough for campus-scale decisions where we're not
  trying to win a race.
- **Bus 2.5 min/km** is empirical: matches the campus schedule's
  `minuteOnRoad` of 25 min for the full inner loop (≈10 km).