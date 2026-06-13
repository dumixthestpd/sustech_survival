// sustech_survival.transit web UI — main client script
// MapLibre GL + Protomaps PMTiles (the real SUSTech campus basemap,
// properly GPS-aligned, served as vector tiles via HTTP-range reads).

(function () {
  "use strict";

  // ── State ────────────────────────────────────────────────────────────────
  const state = {
    facilities: [],
    busStops: [],
    busLines: [],   // populated async from /data/bus_lines/*.geojson
    footways: { features: [] },   // OSM pedestrian network
    elevation: {},               // "lat,lng" → meters
    liveBuses: [],
    schedules: { workday: [], holiday: [] },
    facilitiesById: {},
    facilitiesByName: {},
    day: "workday",
    // Tunable speed + terrain model. Edit these to taste; the formulas
    // are documented in references/transit-estimation.md.
    PARAMS: {
      walkFlatKmh: 4.5,            // pedestrian flat-ground speed
      bikeFlatKmh: 16.0,           // cyclist flat-ground speed
      toblerAscentCoef: 3.5,       // Tobler v = 6·exp(-k·|slope + 0.05|) k
      toblerMaxKmh: 6.0,           // peak Tobler speed (at -5% downhill)
      bikeClimbCoef: 10.0,         // bike multiplier for climb fraction
      transferPenaltyMin: 5,       // minutes added per bus transfer
      waitHeadwayMin: 10,          // typical bus headway — used for wait estimate
    },
  };

  // ── Map setup ───────────────────────────────────────────────────────────
  // Use the same Protomaps vector basemap that sustech.online uses.
  // We serve a modified copy of the style locally at /static/pmtiles-style.json
  // with all external URLs replaced with local proxy URLs (to avoid CORS
  // issues — see server's /pmtiles-proxy/ endpoint).
  const styleUrl = "/static/pmtiles-style.json";

  // PMTiles: register the custom protocol
  const protocol = new pmtiles.Protocol();
  maplibregl.addProtocol("pmtiles", protocol.tile);

  // Fetch the style JSON and inject our custom sources + layers
  fetch(styleUrl).then(r => r.json()).then(style => {
  // Add our custom sources to the style
  style.sources.facilities = { type: "geojson", data: "/data/facilities.geojson" };
  style.sources.bus_stops = { type: "geojson", data: "/data/bus_stops.geojson" };
  style.sources.live_buses = { type: "geojson", data: "/data/live_buses.geojson" };
  style.sources.route = {
    type: "geojson",
    data: { type: "FeatureCollection", features: [] },
  };
  style.sources.footways = {
    type: "geojson",
    data: { type: "FeatureCollection", features: [] },
  };

  // Create map
  const map = new maplibregl.Map({
    container: "map",
    style: style,
    center: [113.995, 22.604],
    zoom: 15,
    attributionControl: { compact: true },
  });
  window._map = map;

  // Add our custom layers ON TOP of the basemap.
  // All dots default to invisible — they only appear when (a) the user
  // hovers near them ("near" state, set on map mousemove), (b) the cursor
  // is directly on them ("hover" state), or (c) they're selected as an
  // endpoint (click-to-set or via the search box). Live buses are always
  // visible (animated, can't be hovered).
  //
  // We use a minimum opacity of 0.01 (essentially invisible) so that
  // MapLibre's hit-test still dispatches click events to the layer.
  // Truly-zero-opacity features don't get hit-tested.
  const RADIUS_EXPR = (base_zoom_14, base_zoom_16, base_zoom_18,
                       hover_radius) => [
    "interpolate", ["linear"], ["zoom"],
    14, ["case", ["==", ["feature-state", "hover"], true], hover_radius, base_zoom_14],
    16, ["case", ["==", ["feature-state", "hover"], true], hover_radius, base_zoom_16],
    18, ["case", ["==", ["feature-state", "hover"], true], hover_radius, base_zoom_18],
  ];
  const OPACITY_EXPR = [
    "case",
    ["==", ["feature-state", "selected"], true], 1.0,
    ["==", ["feature-state", "hover"], true], 1.0,
    ["==", ["feature-state", "near"], true], 0.9,
    0.01,  // tiny non-zero so click hit-test still works
  ];
  const COLOR_EXPR = (hover_color) => [
    "case",
    ["==", ["feature-state", "selected"], true], hover_color,
    ["==", ["feature-state", "hover"], true], hover_color,
    ["==", ["feature-state", "near"], true], hover_color,
    "rgba(120,120,120,0.6)",  // dim gray for any state that escapes the case
  ];

style.layers.push({
  id: "transit-buildings",
  type: "circle",
  source: "facilities",
  filter: ["==", ["get", "kind"], "building"],
  minzoom: 14,
  paint: {
    "circle-radius": RADIUS_EXPR(2.5, 3.5, 5, 7),
    "circle-color": COLOR_EXPR("#3388ff"),
    "circle-stroke-color": "#fff",
    "circle-stroke-width": [
      "case",
      ["==", ["feature-state", "selected"], true], 2.5,
      ["==", ["feature-state", "hover"], true], 2,
      ["==", ["feature-state", "near"], true], 1.2,
      0.5,
    ],
    "circle-opacity": OPACITY_EXPR,
  },
});
style.layers.push({
  id: "transit-gates",
  type: "circle",
  source: "facilities",
  filter: ["==", ["get", "kind"], "gate"],
  minzoom: 13,
  paint: {
    "circle-radius": RADIUS_EXPR(3, 4.5, 6.5, 9),
    "circle-color": COLOR_EXPR("#ff8c00"),
    "circle-stroke-color": "#fff",
    "circle-stroke-width": [
      "case",
      ["==", ["feature-state", "selected"], true], 2.5,
      ["==", ["feature-state", "hover"], true], 2,
      ["==", ["feature-state", "near"], true], 1.2,
      0.5,
    ],
    "circle-opacity": OPACITY_EXPR,
  },
});
style.layers.push({
  id: "transit-bus-stops",
  type: "circle",
  source: "bus_stops",
  minzoom: 14,
  paint: {
    "circle-radius": RADIUS_EXPR(3, 4.5, 6.5, 9),
    "circle-color": COLOR_EXPR("#e91e63"),
    "circle-stroke-color": "#fff",
    "circle-stroke-width": [
      "case",
      ["==", ["feature-state", "selected"], true], 2.5,
      ["==", ["feature-state", "hover"], true], 2,
      ["==", ["feature-state", "near"], true], 1.2,
      0.5,
    ],
    "circle-opacity": OPACITY_EXPR,
  },
});
style.layers.push({
  id: "transit-live-buses",
  type: "circle",
  source: "live_buses",
  minzoom: 13,
  paint: {
    "circle-radius": 7,
    "circle-color": "#00ab5b",
    "circle-stroke-color": "#fff",
    "circle-stroke-width": 2,
  },
});
style.layers.push({
  id: "transit-route",
  type: "line",
  source: "route",
  layout: { "line-cap": "round", "line-join": "round" },
  paint: {
    "line-color": "#0066ff",
    "line-width": 5,
    "line-opacity": 0.75,
    "line-dasharray": [2, 1.5],
  },
});

map.addControl(new maplibregl.NavigationControl(), "top-right");

// ── Legend (bottom-right) ──────────────────────────────────────────────
// Most dots render as small gray circles; their kind-specific color
// appears only on hover. Legend reminds you what each color means.
const legend = document.createElement("div");
legend.className = "maplibregl-ctrl map-legend";
legend.innerHTML = `
  <div class="legend-item"><span class="legend-dot" style="background:#888"></span> Idle dot</div>
  <div class="legend-item"><span class="legend-dot" style="background:#3388ff"></span> Building</div>
  <div class="legend-item"><span class="legend-dot" style="background:#ff8c00"></span> Gate</div>
  <div class="legend-item"><span class="legend-dot" style="background:#e91e63"></span> Bus stop</div>
  <div class="legend-item"><span class="legend-dot" style="background:#00ab5b"></span> Live bus</div>
  <div class="legend-item" style="border-top:1px solid #ccc;margin-top:4px;padding-top:4px">━ Planned route</div>
`;
document.getElementById("map").appendChild(legend);

// Interactive: click → popup with facility info
map.on("click", "transit-buildings", popupFromFeature);
map.on("click", "transit-gates", popupFromFeature);
map.on("click", "transit-bus-stops", popupFromFeature);
map.on("click", "transit-live-buses", popupFromFeature);

// ── Proximity-based dot visibility ──────────────────────────────────────
// Dots default to invisible. They appear when:
//   - cursor is within PROXIMITY_PX of them ("near" state)
//   - cursor is directly on them ("hover" state)
//   - they're selected as an endpoint ("selected" state)
const PROXIMITY_PX = 30;
const FEATURE_LAYERS = ["transit-buildings", "transit-gates",
                        "transit-bus-stops"];

// Track which features are currently in the "near" state so we can
// clear them when the cursor moves away.
const nearIds = new Set();  // `${source}|${id}` strings

function clearAllNear() {
  nearIds.forEach(key => {
    const [source, id] = key.split("|");
    try { map.removeFeatureState({ source, id }); } catch (_) {}
  });
  nearIds.clear();
}

// Throttled mousemove: project facilities to screen space and mark
// those within PROXIMITY_PX of the cursor as "near". We project from
// source features rather than using queryRenderedFeatures because
// the latter skips features that are entirely transparent (opacity=0).
let lastNearUpdate = 0;
map.on("mousemove", (e) => {
  const now = performance.now();
  if (now - lastNearUpdate < 80) return;
  lastNearUpdate = now;

  const cpx = e.point.x, cpy = e.point.y;
  const candidates = [];
  // Build a list of all facility candidates
  for (const srcName of ["facilities", "bus_stops"]) {
    const src = map.getSource(srcName);
    if (!src) continue;
    const data = src._data;
    if (!data || !data.features) continue;
    for (const f of data.features) {
      if (f.geometry?.type !== "Point") continue;
      const [lng, lat] = f.geometry.coordinates;
      const p = map.project([lng, lat]);
      const dx = p.x - cpx, dy = p.y - cpy;
      const d2 = dx * dx + dy * dy;
      if (d2 <= PROXIMITY_PX * PROXIMITY_PX) {
        candidates.push({ source: srcName, id: f.properties.facility_id, d2 });
      }
    }
  }

  // Clear old "near" states that aren't in the new set
  const newKeys = new Set(candidates.map(c => `${c.source}|${c.id}`));
  for (const oldKey of nearIds) {
    if (!newKeys.has(oldKey)) {
      const [source, id] = oldKey.split("|");
      try { map.removeFeatureState({ source, id }); } catch (_) {}
      nearIds.delete(oldKey);
    }
  }
  // Set "near" on the new ones
  for (const c of candidates) {
    const key = `${c.source}|${c.id}`;
    if (!nearIds.has(key)) {
      try {
        map.setFeatureState({ source: c.source, id: c.id }, { near: true });
      } catch (_) {}
      nearIds.add(key);
    }
  }
});
map.on("mouseout", () => {
  clearAllNear();
});

// ── Click-to-select endpoints ────────────────────────────────────────
// Click a dot → if from is empty, fill from; else fill to; else reset both.
// Once both are set, automatically run findRoute().
state.selectedFrom = null;
state.selectedTo = null;

function setSelectedFeatureState(facilityId, on) {
  // Feature may live in either facilities or bus_stops source.
  ["facilities", "bus_stops"].forEach(source => {
    try { map.setFeatureState({ source, id: facilityId }, { selected: on }); }
    catch (_) {}
  });
}

function syncInputFromState() {
  const fromInput = document.getElementById("from-input");
  const toInput = document.getElementById("to-input");
  fromInput.value = state.selectedFrom
    ? (state.facilitiesById[state.selectedFrom]?.properties?.name || state.selectedFrom)
    : "";
  toInput.value = state.selectedTo
    ? (state.facilitiesById[state.selectedTo]?.properties?.name || state.selectedTo)
    : "";
}

function onFacilityClick(e) {
  const feat = e.features[0];
  const fid = feat.properties.facility_id;
  const name = feat.properties.name || fid;

  // Clear previous selections
  if (state.selectedFrom) setSelectedFeatureState(state.selectedFrom, false);
  if (state.selectedTo) setSelectedFeatureState(state.selectedTo, false);

  if (!state.selectedFrom) {
    state.selectedFrom = fid;
    setSelectedFeatureState(fid, true);
    syncInputFromState();
  } else if (fid !== state.selectedFrom && !state.selectedTo) {
    state.selectedTo = fid;
    setSelectedFeatureState(fid, true);
    syncInputFromState();
  } else {
    // Third click on either endpoint — reset both
    state.selectedFrom = fid;
    state.selectedTo = null;
    setSelectedFeatureState(fid, true);
    syncInputFromState();
  }

  // Auto-find route when both endpoints are set
  if (state.selectedFrom && state.selectedTo) {
    // Close any open popup that might block the route polyline
    hoverPopup.remove();
    setTimeout(() => findRoute(), 50);
  }
}

FEATURE_LAYERS.forEach(layer => {
  map.on("click", layer, onFacilityClick);
});

// ── Hover tooltips for facility dots ────────────────────────────────────
// MapLibre doesn't have Leaflet's bindTooltip; we manage a single Popup
// that follows the cursor on mouseenter and hides on mouseleave.
// Also: gray dots turn colored on hover via feature-state.
const hoverPopup = new maplibregl.Popup({
  closeButton: false,
  closeOnClick: false,
  offset: 10,
  className: "hover-tooltip",
});
let hoveredFeature = null;  // {feature, layerId} or null

FEATURE_LAYERS.forEach(id => {
  map.on("mouseenter", id, (e) => {
    map.getCanvas().style.cursor = "pointer";
    if (hoveredFeature && hoveredFeature.layerId === id) {
      try {
        map.removeFeatureState(
          { source: hoveredFeature.feature.source,
            id: hoveredFeature.feature.id },
          "hover"
        );
      } catch (_) {}
    }
    hoveredFeature = { feature: e.features[0], layerId: id };
    try {
      map.setFeatureState(
        { source: e.features[0].source, id: e.features[0].id },
        { hover: true }
      );
    } catch (_) {}

    const props = e.features[0].properties;
    const html = `<div class="name-zh">${esc(props.name || "")}</div>` +
                 (props.name_en ? `<div class="name-en">${esc(props.name_en)}</div>` : "") +
                 `<div class="hint">Click to set as endpoint</div>`;
    hoverPopup.setLngLat(e.features[0].geometry.coordinates.slice())
              .setHTML(html)
              .addTo(map);
  });
  map.on("mousemove", id, (e) => {
    if (hoverPopup.isOpen()) {
      hoverPopup.setLngLat(e.features[0].geometry.coordinates.slice());
    }
  });
  map.on("mouseleave", id, () => {
    map.getCanvas().style.cursor = "";
    if (hoveredFeature && hoveredFeature.layerId === id) {
      try {
        map.removeFeatureState(
          { source: hoveredFeature.feature.source,
            id: hoveredFeature.feature.id },
          "hover"
        );
      } catch (_) {}
    }
    hoveredFeature = null;
    hoverPopup.remove();
  });
});

  map.on("load", () => {
    // Load data after the map style is ready
    loadAll();
    // Setup live refresh
    setInterval(refreshLive, 30000);
  });
  }).catch(err => {
    console.error("Failed to load basemap style:", err);
    document.getElementById("map").innerHTML =
      `<div style="padding:20px;color:#c00">Failed to load basemap: ${err.message}</div>`;
  });

  // ── Loaders ──────────────────────────────────────────────────────────────
  async function loadJSON(path) {
    const r = await fetch(path);
    if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
    return r.json();
  }

  async function loadAll() {
    setLastUpdate("Loading…");
    try {
      const [fac, stops, schedules, live, footways, elevation] = await Promise.all([
        loadJSON("/data/facilities.geojson"),
        loadJSON("/data/bus_stops.geojson"),
        loadJSON("/data/schedules.json"),
        loadJSON("/data/live_buses.geojson"),
        loadJSON("/data/footways.json").catch(() => ({ features: [] })),
        loadJSON("/data/elevation.json").catch(() => ({})),
      ]);
      state.facilities = fac.features || [];
      state.busStops = stops.features || [];
      state.schedules = schedules;
      state.liveBuses = live.features || [];
      state.footways = footways || { features: [] };
      state.elevation = elevation || {};

      // Load bus line geometries in parallel (used for polyline drawing
      // when the bus segment of a route is traversed).
      const lineKeys = ["XYBS1_0", "XYBS1_1", "XYBS2_0", "XYBS2_1"];
      const lineFetches = await Promise.all(
        lineKeys.map(k =>
          loadJSON(`/data/bus_lines/${k}.geojson`)
            .then(g => ({ key: k, g }))
            .catch(() => null)
        )
      );
      state.busLines = lineFetches
        .filter(x => x !== null)
        .map(x => ({
          ...x.g,
          properties: {
            line_code: x.key.split("_")[0],
            direction: parseInt(x.key.split("_")[1]),
          },
        }));

      // Index facilities
      state.facilitiesById = {};
      state.facilitiesByName = {};
      [...state.facilities, ...state.busStops].forEach(f => {
        const p = f.properties;
        state.facilitiesById[p.facility_id] = f;
        if (p.name) {
          (state.facilitiesByName[p.name] ||= []).push(f);
          (state.facilitiesByName[p.name.toLowerCase()] ||= []).push(f);
        }
        if (p.name_en) {
          (state.facilitiesByName[p.name_en] ||= []).push(f);
          (state.facilitiesByName[p.name_en.toLowerCase()] ||= []).push(f);
        }
      });

      // Push to map layers
      const map = window._map;
      if (map && map.getSource("facilities")) map.getSource("facilities").setData(fac);
      if (map && map.getSource("bus_stops")) map.getSource("bus_stops").setData(stops);
      if (map && map.getSource("live_buses")) map.getSource("live_buses").setData(live);

      renderSchedule();
      renderLiveList();
      setLastUpdate(new Date().toLocaleTimeString());
    } catch (e) {
      console.error(e);
      setLastUpdate("Error: " + e.message, true);
    }
  }

  async function refreshLive() {
    try {
      const live = await loadJSON("/data/live_buses.geojson");
      state.liveBuses = live.features || [];
      const map = window._map;
      if (map && map.getSource("live_buses")) {
        map.getSource("live_buses").setData(live);
      }
      renderLiveList();
      setLastUpdate(new Date().toLocaleTimeString());
    } catch (_) {}
  }

  function popupFromFeature(e) {
    const props = e.features[0].properties;
    const coords = e.features[0].geometry.coordinates.slice();
    const html = popupHTML(props);
    new maplibregl.Popup({ offset: 12 })
      .setLngLat(coords)
      .setHTML(html)
      .addTo(window._map);
  }

  // ── Fuzzy resolve (with aliases: "dorm 13" → "Dorm Block 13") ──────────

  function aliasesFor(f) {
    // Mirrors Facility.search_aliases() in schema.py
    const out = [];
    if (f.properties.name_en) {
      out.push(f.properties.name_en);
      const stripped = f.properties.name_en.replace(/\bBlock\b/gi, "").trim();
      if (stripped !== f.properties.name_en) {
        out.push(stripped);
        out.push(stripped.toLowerCase());
      }
      out.push(f.properties.name_en.toLowerCase());
    }
    if (f.properties.name) {
      out.push(f.properties.name);
      // 宿舍13栋 → 宿舍楼13, dorm 13, dorm13
      const m = f.properties.name.match(/(\d+)/);
      if (m && f.properties.name.includes("宿舍")) {
        const n = m[1];
        out.push(`宿舍楼${n}`, `宿舍${n}号`, `dorm ${n}`, `dorm${n}`);
      }
    }
    return [...new Set(out)];
  }

  function resolveFacilityId(text) {
    if (!text) return null;
    if (state.facilitiesById[text]) return text;
    const t = text.toLowerCase();
    const all = [...state.facilities, ...state.busStops];

    // Try exact alias match first
    for (const f of all) {
      const aliases = aliasesFor(f).map(a => a.toLowerCase());
      if (aliases.includes(t)) return f.properties.facility_id;
    }
    // Substring match in any alias
    const scored = [];
    for (const f of all) {
      const aliases = aliasesFor(f).map(a => a.toLowerCase());
      for (const a of aliases) {
        if (a.includes(t)) {
          // shorter = better match
          scored.push({ score: a.length - t.length * 2, f });
          break;
        }
      }
    }
    scored.sort((x, y) => x.score - y.score);
    return scored.length ? scored[0].f.properties.facility_id : null;
  }

  // ── Renderers (sidebar only — map renders via MapLibre layers) ──────────

  function renderSchedule() {
    const target = document.getElementById("schedule-content");
    const lines = state.schedules[state.day] || [];
    if (!lines.length) {
      target.innerHTML = "<em>No schedule data loaded.</em>";
      return;
    }
    const nowMin = nowMinutes();
    let html = "";
    lines.forEach(line => {
      const times = line.times || [];
      const next = times.filter(t => toMinutes(t) >= nowMin).slice(0, 5);
      const pills = times.map(t => {
        const m = toMinutes(t);
        const cls = m >= nowMin && m <= nowMin + 30 ? "time-pill next" : "time-pill";
        return `<span class="${cls}">${t}</span>`;
      }).join("");
      const colorDot = line.color
        ? `<span class="color-dot" style="background:${esc(line.color)}"></span>`
        : "";
      const nextList = next.length
        ? `<span class="meta"><span class="meta-label">Next:</span>${next.join(" · ")}</span>`
        : "";
      html += `
        <div class="schedule-line">
          <h3>${colorDot}${esc(line.sub_name)}</h3>
          <div class="desc">${esc((line.sub_desc || "").replace(/\n/g, " / "))}</div>
          <div class="meta"><span class="meta-label">⏱</span>${line.minute_on_road} min ride · ${times.length} departures</div>
          ${nextList}
          <div class="times">${pills}</div>
        </div>
      `;
    });
    target.innerHTML = html;
  }

  function renderLiveList() {
    const target = document.getElementById("live-content");
    if (!state.liveBuses.length) {
      target.innerHTML = "<em>No buses currently running.</em>";
      return;
    }
    target.innerHTML = state.liveBuses.map(f => {
      const p = f.properties;
      return `<div class="live-bus">
        <span class="route">${esc(p.route_code)}</span>
        <span>→</span>
        <span class="next-station">${esc(p.next_station || "?")}</span>
      </div>`;
    }).join("");
  }

  // ── Suggestion / search ──────────────────────────────────────────────────

  function attachSuggestion(inputId, listId, onPick) {
    const input = document.getElementById(inputId);
    const list = document.getElementById(listId);
    let activeIdx = -1;

    input.addEventListener("input", () => {
      const q = input.value.trim().toLowerCase();
      if (!q) {
        list.classList.remove("show");
        list.innerHTML = "";
        return;
      }
      const all = [...state.facilities, ...state.busStops];
      const scored = [];
      for (const f of all) {
        const aliases = aliasesFor(f).map(a => a.toLowerCase());
        let score = null;
        if (aliases.includes(q)) score = -10;
        else {
          for (const a of aliases) {
            if (a.includes(q)) {
              score = a.length - q.length * 2;
              break;
            }
          }
        }
        if (score !== null) scored.push({ score, f });
      }
      scored.sort((x, y) => x.score - y.score);
      const matches = scored.slice(0, 8).map(s => s.f);
      if (!matches.length) {
        list.innerHTML = "<li><em>No matches</em></li>";
      } else {
        list.innerHTML = matches.map((f, i) => {
          const p = f.properties;
          const kind = p.kind || "building";
          return `<li data-id="${esc(p.facility_id)}" data-idx="${i}">
            <span class="kind-badge ${kind}">${kind.replace("_", " ")}</span>
            ${esc(p.name)}${p.name_en ? " <span style='color:#888'>/ " + esc(p.name_en) + "</span>" : ""}
          </li>`;
        }).join("");
      }
      list.classList.add("show");
      activeIdx = -1;
    });

    function highlightActive() {
      const items = list.querySelectorAll("li[data-id]");
      items.forEach((it, i) => {
        const active = i === activeIdx;
        it.style.background = active ? "#e0eaff" : "";
        if (active) it.scrollIntoView({ block: "nearest" });
      });
    }

    input.addEventListener("keydown", (e) => {
      const items = list.querySelectorAll("li[data-id]");
      if (!items.length) return;
      if (e.key === "ArrowDown") {
        e.preventDefault();
        activeIdx = Math.min(items.length - 1, activeIdx + 1);
        highlightActive();
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        activeIdx = Math.max(0, activeIdx - 1);
        highlightActive();
      } else if (e.key === "Enter") {
        e.preventDefault();
        const pick = activeIdx >= 0 ? items[activeIdx] : items[0];
        if (pick) onPick(pick.dataset.id);
      } else if (e.key === "Escape") {
        list.classList.remove("show");
      }
    });

    list.addEventListener("click", (e) => {
      const li = e.target.closest("li[data-id]");
      if (li) onPick(li.dataset.id);
    });

    document.addEventListener("click", (e) => {
      if (e.target !== input) list.classList.remove("show");
    });
  }

  // ── Routing (client-side Dijkstra) ───────────────────────────────────────

  // ── Pathfinding ──────────────────────────────────────────────────────────
  // The graph combines:
  //   - facility nodes (buildings + gates + bus stops), from GeoJSON
  //   - OSM footway path nodes (from /data/footways.json)
  // Edges:
  //   - walk: along consecutive footway vertices (real pedestrian paths)
  //   - bus: consecutive bus stops on each line/direction
  //   - access: each facility ↔ nearest footway node (radius 80 m)
  //
  // Edge duration depends on mode + slope:
  //   - "walk":   Tobler v = 6·exp(-3.5·|slope+0.05|) km/h
  //   - "bike":   16 km/h flat × 1/(1+10·climb_fraction), no penalty downhill
  //   - "bus":    ~2.5 min/km + 5 min transfer penalty (constant)
  //
  // If state.elevation is empty, falls back to flat-ground estimates.
  function elevAt(lat, lng) {
    const k = `${lat.toFixed(5)},${lng.toFixed(5)}`;
    return state.elevation[k];
  }

  // Estimate minutes for a single segment (between two coords).
  // mode: "walk" | "bike" | "bus"
  function segmentDuration(lat1, lng1, lat2, lng2, mode) {
    const d_m = haversine({ lat: lat1, lng: lng1 }, { lat: lat2, lng: lng2 });
    const d_km = d_m / 1000;
    const elev1 = elevAt(lat1, lng1);
    const elev2 = elevAt(lat2, lng2);
    const hasElev = elev1 !== undefined && elev2 !== undefined;
    const climb_m = hasElev ? (elev2 - elev1) : 0;
    const slope = hasElev ? climb_m / Math.max(d_m, 1) : 0;  // unitless

    if (mode === "bus") {
      // Bus: ~2.5 min/km + a small constant for stop dwell time
      return d_km * 2.5 + 0.1;
    }

    if (mode === "walk") {
      // Tobler's hiking function (1993). Faster downhill (max 6 km/h at -5%),
      // much slower uphill. Slope is signed (positive = uphill).
      if (!hasElev) {
        return d_km / 4.5 * 60;  // fallback flat
      }
      const v = state.PARAMS.toblerMaxKmh * Math.exp(
        -state.PARAMS.toblerAscentCoef * Math.abs(slope + 0.05)
      );
      return (d_km / v) * 60;
    }

    if (mode === "bike") {
      // 16 km/h flat, with climb penalty proportional to fraction gained.
      // Downhill is free (cyclists coast or pedal easily).
      if (!hasElev) {
        return d_km / state.PARAMS.bikeFlatKmh * 60;
      }
      const climbFraction = Math.max(0, climb_m) / Math.max(d_m, 1);  // unitless
      const speed = state.PARAMS.bikeFlatKmh / (1 + state.PARAMS.bikeClimbCoef * climbFraction);
      return (d_km / speed) * 60;
    }

    return d_km / 4.5 * 60;  // default fallback
  }

  function buildClientGraph() {
    const all = [...state.facilities, ...state.busStops];
    const nodes = {};  // id → {id, lat, lng, kind}
    const meta = {};   // id → facility properties

    // 1) Facility nodes
    all.forEach(f => {
      const p = f.properties;
      const [lng, lat] = f.geometry.coordinates;
      nodes[p.facility_id] = { id: p.facility_id, lat, lng, kind: p.kind };
      meta[p.facility_id] = p;
    });

    // 2) Walk/bike network — every footway vertex becomes a node.
    //    Edges are within a way (consecutive vertices). Each edge stores
    //    its full polyline geometry (just the two endpoints for the simple
    //    case, but could be more for curved ways — we keep it simple here).
    const footwayNodeKeys = new Set();
    const walkEdges = [];  // walk + bike use these
    const facilityEdges = [];  // facility ↔ footway access + cross-campus

    if (state.footways.features && state.footways.features.length) {
      const keyOf = (lat, lng) => `${lat.toFixed(5)},${lng.toFixed(5)}`;
      for (const feat of state.footways.features) {
        const coords = feat.geometry.coordinates; // [[lng,lat], ...]
        if (!coords || coords.length < 2) continue;
        const hw = feat.properties?.highway || "footway";
        let prevKey = null;
        for (let i = 0; i < coords.length; i++) {
          const [lng, lat] = coords[i];
          const k = keyOf(lat, lng);
          if (!nodes[k]) {
            nodes[k] = { id: k, lat, lng, kind: "footway" };
            footwayNodeKeys.add(k);
          }
          if (prevKey) {
            const d = haversine(nodes[prevKey], nodes[k]);
            const durWalk = segmentDuration(
              nodes[prevKey].lat, nodes[prevKey].lng,
              nodes[k].lat, nodes[k].lng, "walk"
            );
            const durBike = segmentDuration(
              nodes[prevKey].lat, nodes[prevKey].lng,
              nodes[k].lat, nodes[k].lng, "bike"
            );
            walkEdges.push({
              a: prevKey, b: k, mode: "walk",
              dur_min: durWalk,
              bike_dur_min: durBike,
              dist_m: d,
              geometry: [  // for polyline drawing
                [nodes[prevKey].lng, nodes[prevKey].lat],
                [nodes[k].lng, nodes[k].lat],
              ],
              details: `${Math.round(d)} m ${hw}`,
            });
          }
          prevKey = k;
        }
      }
      // Snap each facility to its nearest footway vertex (up to 250 m).
      // Bumped from 150 m to cover isolated buildings like 欣园2栋.
      for (const f of all) {
        const p = f.properties;
        const fp = nodes[p.facility_id];
        let best = null, bestD = 250;
        for (const k of footwayNodeKeys) {
          const fn = nodes[k];
          const d = haversine(fp, fn);
          if (d < bestD) { bestD = d; best = k; }
        }
        if (best) {
          const durWalk = segmentDuration(fp.lat, fp.lng,
                                           nodes[best].lat, nodes[best].lng, "walk");
          const durBike = segmentDuration(fp.lat, fp.lng,
                                           nodes[best].lat, nodes[best].lng, "bike");
          // Bidirectional access edges. Geometry is just the two endpoints
          // because there isn't a real path between them.
          facilityEdges.push({
            a: p.facility_id, b: best, mode: "walk",
            dur_min: durWalk, bike_dur_min: durBike, dist_m: bestD,
            geometry: [
              [fp.lng, fp.lat],
              [nodes[best].lng, nodes[best].lat],
            ],
            details: `${Math.round(bestD)} m to path`,
          });
          facilityEdges.push({
            a: best, b: p.facility_id, mode: "walk",
            dur_min: durWalk, bike_dur_min: durBike, dist_m: bestD,
            geometry: [
              [nodes[best].lng, nodes[best].lat],
              [fp.lng, fp.lat],
            ],
            details: `${Math.round(bestD)} m from path`,
          });
        }
        // Cross-campus walking fallback: direct facility ↔ facility edges
        // within 300 m. Keeps the graph connected across OSM-sparse regions.
        // Geometry is the straight line between the two facilities.
        for (const g of all) {
          if (g === f) continue;
          const gp = g.properties;
          if (nodes[gp.facility_id] === undefined) continue;
          const d = haversine(fp, nodes[gp.facility_id]);
          if (d > 0 && d <= 300) {
            const durWalk = segmentDuration(fp.lat, fp.lng,
                                             nodes[gp.facility_id].lat,
                                             nodes[gp.facility_id].lng, "walk");
            const durBike = segmentDuration(fp.lat, fp.lng,
                                             nodes[gp.facility_id].lat,
                                             nodes[gp.facility_id].lng, "bike");
            // Cross-campus walks are penalized 3× so the real footway
            // network is preferred when both options exist. The penalty
            // reflects "you can't actually cut straight through buildings
            // and lawns" — these edges are last-resort fallbacks.
            facilityEdges.push({
              a: p.facility_id, b: gp.facility_id, mode: "walk",
              dur_min: durWalk * 3, bike_dur_min: durBike * 3, dist_m: d,
              geometry: [
                [fp.lng, fp.lat],
                [nodes[gp.facility_id].lng, nodes[gp.facility_id].lat],
              ],
              details: `${Math.round(d)} m cross-campus walk`,
            });
          }
        }
      }
    } else {
      // No footways: fall back to direct facility↔facility edges.
      const ids = Object.keys(nodes);
      for (let i = 0; i < ids.length; i++) {
        for (let j = i + 1; j < ids.length; j++) {
          const a = nodes[ids[i]], b = nodes[ids[j]];
          const d = haversine(a, b);
          if (d <= 300) {
            const dur = segmentDuration(a.lat, a.lng, b.lat, b.lng, "walk");
            facilityEdges.push({
              a: a.id, b: b.id, mode: "walk",
              dur_min: dur, dist_m: d,
              geometry: [[a.lng, a.lat], [b.lng, b.lat]],
              details: `${Math.round(d)} m walk`,
            });
            facilityEdges.push({
              a: b.id, b: a.id, mode: "walk",
              dur_min: dur, dist_m: d,
              geometry: [[b.lng, b.lat], [a.lng, a.lat]],
              details: `${Math.round(d)} m walk`,
            });
          }
        }
      }
    }

    // 3) Bus edges — each consecutive pair of stops on a line gets an
    //    edge with the actual bus line geometry as the polyline.
    //    To do this, we project the bus line onto its ordered stops by
    //    walking along the line and finding the nearest segment to each
    //    stop. The slice between consecutive stop positions becomes the
    //    edge's geometry.
    const busEdges = [];
    const stopsByLine = {};
    state.busStops.forEach(f => {
      const p = f.properties;
      const routes = p.routes || [];
      routes.forEach(r => {
        if (!stopsByLine[r]) stopsByLine[r] = [];
        stopsByLine[r].push({
          id: p.facility_id,
          station_id: p.station_id || 0,
          name: p.name,
          lat: f.geometry.coordinates[1],
          lng: f.geometry.coordinates[0],
        });
      });
    });

    // Helper: find the index along a polyline (as [lng,lat][]) that is
    // closest to (lat, lng). Returns {i, t} where t in [0,1] is the
    // fractional position along segment i.
    function projectOntoLine(lineCoords, lat, lng) {
      let bestI = 0, bestT = 0, bestD = Infinity;
      for (let i = 0; i < lineCoords.length - 1; i++) {
        const [x1, y1] = lineCoords[i];
        const [x2, y2] = lineCoords[i + 1];
        const dx = x2 - x1, dy = y2 - y1;
        const len2 = dx * dx + dy * dy;
        if (len2 === 0) continue;
        const t = Math.max(0, Math.min(1, ((lng - x1) * dx + (lat - y1) * dy) / len2));
        const px = x1 + t * dx, py = y1 + t * dy;
        // Project lat/lng to "distance" using a small approximation
        // (good enough for ordering along the line; we just need monotonic
        // positions to slice between)
        const d = (px - lng) * (px - lng) + (py - lat) * (py - lat);
        if (d < bestD) { bestD = d; bestI = i; bestT = t; }
      }
      // Convert (i, t) to a single position index along the line, with
      // sub-segment offset encoded as a fraction.
      return bestI + bestT;
    }

    Object.entries(stopsByLine).forEach(([key, stops]) => {
      stops.sort((a, b) => a.station_id - b.station_id);

      // Find the bus line geometry for this key
      const lineCode = key.split("/")[0];
      const dir = parseInt(key.split("/")[1] || "0");
      const lineGeo = state.busLines.find(b => b.properties?.line_code === lineCode && b.properties?.direction === dir);

      // Project each stop onto the line to find its position
      let stopsWithPos = stops;
      if (lineGeo) {
        const lineCoords = (lineGeo.features || []).flatMap(f => f.geometry?.coordinates || []);
        if (lineCoords.length > 1) {
          stopsWithPos = stops.map(s => ({
            ...s,
            pos: projectOntoLine(lineCoords, s.lat, s.lng),
          }));
          // Sort by position (some bus lines may not be in station_id order along the line)
          stopsWithPos.sort((a, b) => a.pos - b.pos);
        }
      }

      for (let i = 0; i < stopsWithPos.length - 1; i++) {
        const a = stopsWithPos[i], b = stopsWithPos[i + 1];
        const d = haversine(a, b);
        const dur = segmentDuration(a.lat, a.lng, b.lat, b.lng, "bus")
                  + state.PARAMS.transferPenaltyMin / 2;
        // Build the polyline geometry for this segment by slicing the
        // bus line between the two stops' positions on the line.
        let geometry = [[a.lng, a.lat], [b.lng, b.lat]];  // fallback
        if (lineGeo && a.pos !== undefined && b.pos !== undefined) {
          const lineCoords = (lineGeo.features || []).flatMap(f => f.geometry?.coordinates || []);
          if (lineCoords.length > 1) {
            const startIdx = Math.floor(a.pos);
            const endIdx = Math.floor(b.pos);
            const startFrac = a.pos - startIdx;
            const endFrac = b.pos - endIdx;
            geometry = [];
            // Include first point at fractional offset
            if (startIdx < lineCoords.length) {
              const [x1, y1] = lineCoords[startIdx];
              const [x2, y2] = lineCoords[Math.min(startIdx + 1, lineCoords.length - 1)];
              geometry.push([
                x1 + startFrac * (x2 - x1),
                y1 + startFrac * (y2 - y1),
              ]);
            }
            // Include all intermediate vertices
            for (let j = startIdx + 1; j <= endIdx && j < lineCoords.length; j++) {
              geometry.push(lineCoords[j]);
            }
            // Include last point at fractional offset
            if (endIdx < lineCoords.length) {
              const [x1, y1] = lineCoords[endIdx];
              const [x2, y2] = lineCoords[Math.min(endIdx + 1, lineCoords.length - 1)];
              geometry.push([
                x1 + endFrac * (x2 - x1),
                y1 + endFrac * (y2 - y1),
              ]);
            }
            // If slicing produced weird results, fall back
            if (geometry.length < 2) geometry = [[a.lng, a.lat], [b.lng, b.lat]];
          }
        }
        busEdges.push({
          a: a.id, b: b.id, mode: "bus",
          dur_min: dur, dist_m: d,
          geometry,
          details: `${key}: ${a.name} → ${b.name}`,
        });
        busEdges.push({
          a: b.id, b: a.id, mode: "bus",
          dur_min: dur, dist_m: d,
          geometry: [...geometry].reverse(),
          details: `${key}: ${b.name} → ${a.name}`,
        });
      }
    });

    return {
      nodes,
      meta,
      edges: [...facilityEdges, ...walkEdges, ...busEdges],
    };
  }

  function dijkstra(graph, src, dst, mode) {
    const dist = {}, prev = {};
    Object.keys(graph.nodes).forEach(id => {
      dist[id] = Infinity; prev[id] = null;
    });
    dist[src] = 0;
    const pq = [[0, src]];
    while (pq.length) {
      pq.sort((a, b) => a[0] - b[0]);
      const [d, u] = pq.shift();
      if (d > dist[u]) continue;
      if (u === dst) break;
      graph.edges.forEach(e => {
        if (e.a !== u) return;
        // Mode filter: walk/bike use walk edges, bus uses bus edges,
        // transit allows any.
        if (mode === "walk" && e.mode !== "walk") return;
        if (mode === "bike" && e.mode !== "walk") return;
        if (mode === "bus" && e.mode !== "bus") return;
        // Use the mode-specific duration
        const edgeDur = mode === "bike" && e.bike_dur_min !== undefined
          ? e.bike_dur_min
          : e.dur_min;
        const nd = d + edgeDur;
        if (nd < dist[e.b]) {
          dist[e.b] = nd;
          prev[e.b] = e;
          pq.push([nd, e.b]);
        }
      });
    }
    if (dist[dst] === Infinity) return null;
    const pathEdges = [];
    let cur = dst;
    while (cur !== src) {
      const e = prev[cur];
      if (!e) break;
      pathEdges.push(e);
      cur = e.a;
    }
    pathEdges.reverse();
    return { total_min: dist[dst], edges: pathEdges };
  }

  function findRoute() {
    const fromInput = document.getElementById("from-input");
    const toInput = document.getElementById("to-input");
    const fromId = resolveFacilityId(fromInput.value.trim());
    const toId = resolveFacilityId(toInput.value.trim());
    const resultDiv = document.getElementById("route-result");
    const mode = document.querySelector('input[name=mode]:checked').value;

    if (!fromId || !toId) {
      resultDiv.innerHTML = `<div class="error">Pick both endpoints (or type names that match facilities).</div>`;
      return;
    }
    if (fromId === toId) {
      // Try harder: if user typed names that look different but resolved the same,
      // they probably meant different places. Show them what we picked.
      const f = state.facilitiesById[fromId];
      const fromDisplay = fromInput.value.trim();
      resultDiv.innerHTML = `<div class="error">
        Both endpoints resolved to the same place:<br>
        <strong>${esc(f?.properties?.name || fromId)}</strong>
        <span class="facility-id">${esc(fromId)}</span><br><br>
        Try being more specific — e.g. "dorm 13" or "欣园".
      </div>`;
      return;
    }

    // For "bus" mode, treat it like "transit" so non-bus-stop endpoints
    // still work (the bus edges will only be traversed if they're optimal).
    const effectiveMode = mode === "bus" ? "transit" : mode;

    const graph = buildClientGraph();
    const path = dijkstra(graph, fromId, toId, effectiveMode);
    if (!path) {
      resultDiv.innerHTML = `<div class="error">No route found (mode=${mode}). Try a different mode.</div>`;
      return;
    }

    // Build polyline from edge geometry. Each edge contributes its
    // geometry, and we dedup consecutive duplicate points.
    const map = window._map;
    const allCoords = [];
    let totalM = 0;
    path.edges.forEach((e, idx) => {
      if (!e.geometry || e.geometry.length < 2) return;
      if (idx === 0) {
        // First edge: include its first point
        allCoords.push(e.geometry[0]);
      }
      // For subsequent points, only add if not the same as the last
      for (let i = 1; i < e.geometry.length; i++) {
        const pt = e.geometry[i];
        const last = allCoords[allCoords.length - 1];
        if (!last || Math.abs(last[0] - pt[0]) > 1e-7 || Math.abs(last[1] - pt[1]) > 1e-7) {
          allCoords.push(pt);
        }
      }
      totalM += e.dist_m;
    });

    if (map) {
      // Build a single LineString from all edge geometries (deduped)
      const fc = {
        type: "FeatureCollection",
        features: [{
          type: "Feature",
          geometry: { type: "LineString", coordinates: allCoords },
          properties: {},
        }],
      };
      const src = map.getSource("route");
      if (src) src.setData(fc);

      // Fit bounds to the route
      if (allCoords.length > 0) {
        let minLng = Infinity, maxLng = -Infinity, minLat = Infinity, maxLat = -Infinity;
        allCoords.forEach(([lng, lat]) => {
          minLng = Math.min(minLng, lng); maxLng = Math.max(maxLng, lng);
          minLat = Math.min(minLat, lat); maxLat = Math.max(maxLat, lat);
        });
        map.fitBounds([[minLng, minLat], [maxLng, maxLat]], { padding: 60, duration: 600 });
      }
    }

    // Render step list
    let html = `<div class="summary">${path.total_min.toFixed(1)} min · ${path.edges.length} steps · ${Math.round(totalM)} m</div>`;
    // Collapse consecutive footway edges between anonymous vertices into
    // a single step so the user sees a readable list, not 30 steps of
    // "node A → node B → node C". Only the first/last edge of a run gets
    // the step entry; we show the cumulative distance/duration.
    let collapsed = [];
    for (const e of path.edges) {
      const fromName = graph.meta[e.a]?.name;
      const toName = graph.meta[e.b]?.name;
      const fromIsFacility = !!fromName;
      const toIsFacility = !!toName;
      // Same mode + same direction (a→b vs b→a), neither end is a facility
      const last = collapsed[collapsed.length - 1];
      if (last && last.e.mode === e.mode && !fromIsFacility) {
        // Continue the previous run
        last.e = e;  // extend to current edge
        last.totalDur += e.dur_min;
        last.totalDist += e.dist_m;
        last.toName = toName || last.toName;
        last.edgeCount++;
      } else {
        collapsed.push({
          e, fromName, toName, fromIsFacility, toIsFacility,
          totalDur: e.dur_min, totalDist: e.dist_m, edgeCount: 1,
        });
      }
    }
    collapsed.forEach(c => {
      const e = c.e;
      // Use the actual route mode (not edge mode, since walk/bike share
      // the same edge graph). The edge mode only differentiates walk/bus.
      const icon = e.mode === "bus" ? "🚌" : (mode === "bike" ? "🚴" : "🚶");
      // Label the from/to. For footway vertices, show "via path" or omit.
      const fromLabel = c.fromName || (c.edgeCount > 1 ? "via path" : "path");
      const toLabel = c.toName || (c.edgeCount > 1 ? "via path" : "path");
      const detailsExtra = c.edgeCount > 1
        ? ` · ${c.edgeCount} segments along the path`
        : "";
      html += `<div class="step mode-${e.mode}">
        <strong>${icon} ${fromLabel} → ${toLabel}</strong>
        <div class="meta">${c.totalDur.toFixed(1)} min · ${Math.round(c.totalDist)} m · ${esc(e.details)}${detailsExtra}</div>
      </div>`;
    });
    html += `<div class="how-we-estimate"><a href="/static/estimation.html" target="_blank">ⓘ How we estimate</a></div>`;
    resultDiv.innerHTML = html;
  }

  // ── Utilities ────────────────────────────────────────────────────────────
  function esc(s) { return String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
  function popupHTML(props) {
    const nameZh = props.name || "";
    const nameEn = props.name_en ? `<div class="name-en">${esc(props.name_en)}</div>` : "";
    // routes may be undefined (buildings/gates), an empty array, or a non-empty array of strings
    let routesList = [];
    if (Array.isArray(props.routes)) {
      routesList = props.routes;
    } else if (typeof props.routes === "string" && props.routes) {
      routesList = [props.routes];
    }
    const routes = routesList.length
      ? `<div class="meta">Routes: ${routesList.map(esc).join(", ")}</div>` : "";
    return `<div class="name-zh">${esc(nameZh)}</div>${nameEn}${routes}<div class="meta"><span class="facility-id">${esc(props.facility_id)}</span></div>`;
  }
  function haversine(a, b) {
    const R = 6371000;
    const toRad = d => d * Math.PI / 180;
    const dLat = toRad(b.lat - a.lat);
    const dLng = toRad(b.lng - a.lng);
    const x = Math.sin(dLat / 2) ** 2
            + Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLng / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(x));
  }
  function toMinutes(t) {
    const [h, m] = t.split(":").map(Number);
    return h * 60 + m;
  }
  function nowMinutes() {
    const d = new Date();
    return d.getHours() * 60 + d.getMinutes();
  }
  function setLastUpdate(text, isError) {
    const el = document.getElementById("last-update");
    el.textContent = text;
    el.style.color = isError ? "#ffcccc" : "rgba(255,255,255,0.85)";
  }

  // ── Auto-refresh countdown ───────────────────────────────────────────────
  let refreshCountdown = 30;
  const REFRESH_INTERVAL_S = 30;
  setInterval(() => {
    refreshCountdown -= 1;
    if (refreshCountdown <= 0) refreshCountdown = REFRESH_INTERVAL_S;
    const el = document.getElementById("last-update");
    if (el && !el.dataset.manualUpdate) {
      el.textContent = `↻ ${refreshCountdown}s`;
    }
    el.dataset.manualUpdate = "";  // clear flag set by manual refresh
  }, 1000);

  // ── Load bus line geometries (best-effort) ──────────────────────────────
  // Loaded inside loadAll() so findRoute can await the geometries for
  // the polyline drawing.

  // ── Wiring ──────────────────────────────────────────────────────────────
  attachSuggestion("from-input", "from-suggestions", (id) => {
    document.getElementById("from-input").value = state.facilitiesById[id]?.properties.name || id;
  });
  attachSuggestion("to-input", "to-suggestions", (id) => {
    document.getElementById("to-input").value = state.facilitiesById[id]?.properties.name || id;
  });
  document.getElementById("route-btn").addEventListener("click", findRoute);
  document.getElementById("refresh-btn").addEventListener("click", () => {
    // Pause the auto-refresh countdown for one cycle so user sees "Updated HH:MM:SS"
    const el = document.getElementById("last-update");
    el.dataset.manualUpdate = "1";
    loadAll();
  });

  document.querySelectorAll(".day-toggle button").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".day-toggle button").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      state.day = btn.dataset.day;
      renderSchedule();
    });
  });
})();