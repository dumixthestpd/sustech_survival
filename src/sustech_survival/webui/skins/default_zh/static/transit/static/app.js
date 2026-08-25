// sustech_survival.transit web UI — main client script
// MapLibre GL + Protomaps PMTiles (the real SUSTech campus basemap,
// properly GPS-aligned, served as vector tiles via HTTP-range reads).
//
// As of 2026-06-13 the route-finding feature is GONE. The hand-rolled
// dijkstra and the OSMnx integration both produced broken/edgey paths
// in OSM-sparse areas and the user asked to delete the entire nav
// system. What remains: the basemap, the building/gate/bus-stop dots
// (with hover tooltips), the live bus markers, the bus schedule, and
// the live-bus list.

(function () {
  "use strict";

  // -- State ----------------------------------------------------------------
  const state = {
    facilities: [],
    busStops: [],
    busLines: [],                // line geometries (orange/blue polylines on the map)
    liveBuses: [],
    schedules: { workday: [], holiday: [] },
    facilitiesById: {},
    day: "workday",
  };

  // -- Map setup -----------------------------------------------------------
  // We serve a modified copy of the style locally at /static/pmtiles-style.json
  // with all external URLs replaced with local proxy URLs (to avoid CORS
  // issues — see server's /pmtiles-proxy/ endpoint).
  const styleUrl = "/static/pmtiles-style.json";

  // PMTiles: register the custom protocol
  const protocol = new pmtiles.Protocol();
  maplibregl.addProtocol("pmtiles", protocol.tile);

  // Fetch the style JSON and inject our custom sources + layers
  fetch(styleUrl).then(r => r.json()).then(style => {
  // Add our custom sources. The basemap source (protomaps) is already
  // in the style JSON. The 'route' source was here pre-removal.
  style.sources.facilities = { type: "geojson", data: "/data/facilities.geojson" };
  style.sources.bus_stops  = { type: "geojson", data: "/data/bus_stops.geojson" };

  // pmtiles:// requires an absolute URL (scheme+host+path), but the
  // upstream PMTiles lives on the SAME host as the page (served via
  // our /pmtiles-proxy/ reverse proxy). So we patch the URL to be
  // absolute against window.location.origin, regardless of what port
  // the server happens to be running on. The style file ships with
  // pmtiles:///pmtiles-proxy/... (relative) so it doesn't bake in a
  // port number — a hardcoded localhost port was the cause of the
  // "basemap gone" bug when the server port changed.
  const origin = window.location.origin;
  if (style.sources.protomaps && style.sources.protomaps.url) {
    const u = style.sources.protomaps.url;
    if (u.startsWith("pmtiles:///")) {
      style.sources.protomaps.url = "pmtiles://" + origin + u.slice("pmtiles://".length);
    }
  }
  if (style.glyphs && style.glyphs.startsWith("/")) {
    style.glyphs = origin + style.glyphs;
  }

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
  // Dots default to invisible — they only appear when (a) the user
  // hovers near them ("near" state, set on map mousemove), (b) the cursor
  // is directly on them ("hover" state). Live buses are always visible
  // (animated, can't be hovered).
  //
  // We use a minimum opacity of 0.01 (essentially invisible) so that
  // MapLibre's hit-test still dispatches click events to the layer.
  // Truly-zero-opacity features don't get hit-tested.
  const RADIUS_EXPR = (base_zoom_14, base_zoom_16, base_zoom_18, hover_radius) => [
    "interpolate", ["linear"], ["zoom"],
    14, ["case", ["==", ["feature-state", "hover"], true], hover_radius, base_zoom_14],
    16, ["case", ["==", ["feature-state", "hover"], true], hover_radius, base_zoom_16],
    18, ["case", ["==", ["feature-state", "hover"], true], hover_radius, base_zoom_18],
  ];
  const OPACITY_EXPR = [
    "case",
    ["==", ["feature-state", "hover"], true], 1.0,
    ["==", ["feature-state", "near"], true], 0.9,
    0.01,  // tiny non-zero so click hit-test still works
  ];
  const COLOR_EXPR = (hover_color) => [
    "case",
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
        ["==", ["feature-state", "hover"], true], 2,
        ["==", ["feature-state", "near"], true], 1.2,
        0.5,
      ],
      "circle-opacity": OPACITY_EXPR,
    },
  });
  // Live bus markers are rendered as HTML elements (see renderLiveBusMarkers
  // below) — a single rotating SVG per bus with the body and the
  // direction chevron in one shape. We do NOT also draw a MapLibre
  // circle layer underneath, because the two would visibly separate
  // during panning (one is GPU-rendered, the other is JS-positioned) and
  // produce the "two dots for a single bus" effect.
  // Bus line polylines — drawn on the basemap so the user can see the
  // route shape. Kept very subtle (thin + low opacity) so they don't
  // compete with the basemap.
  style.sources.bus_lines_layer = {
    type: "geojson",
    data: { type: "FeatureCollection", features: [] },
  };
  style.layers.push({
    id: "transit-bus-lines",
    type: "line",
    source: "bus_lines_layer",
    minzoom: 14,
    layout: { "line-cap": "round", "line-join": "round" },
    paint: {
      "line-color": [
        "match", ["get", "line_code"],
        "XYBS1", "#f7911d",   // Line 1 = orange
        "XYBS2", "#29abe2",   // Line 2 = blue
        "#888888",
      ],
      "line-width": [
        "interpolate", ["linear"], ["zoom"],
        14, 1,
        18, 2.5,
      ],
      "line-opacity": 0.28,
    },
  });

  map.addControl(new maplibregl.NavigationControl(), "top-right");

  // -- Legend (bottom-right) ----------------------------------------------
  // Color-coded by line so the user knows which is which. Buildings /
  // gates / bus stops render gray on the map until you hover near them,
  // so the legend explains what each color means when revealed.
  const legend = document.createElement("div");
  legend.className = "maplibregl-ctrl map-legend";
  legend.innerHTML = `
  <div class="legend-item"><span class="legend-dot" style="background:#888"></span> Idle dot (hover to reveal)</div>
  <div class="legend-item"><span class="legend-dot" style="background:#3388ff"></span> Building</div>
  <div class="legend-item"><span class="legend-dot" style="background:#ff8c00"></span> Gate</div>
  <div class="legend-item"><span class="legend-dot" style="background:#e91e63"></span> Bus stop</div>
  <div class="legend-item" style="border-top:1px solid #ccc;margin-top:4px;padding-top:4px">
    <span class="legend-line" style="background:#f7911d"></span> Line 1 (内环 CW)
  </div>
  <div class="legend-item">
    <span class="legend-line" style="background:#29abe2"></span> Line 2 (外环 CCW)
  </div>
  <div class="legend-item">
    <span class="legend-bus" style="--c:#f7911d"></span> Live bus (dot + arrow = bearing)
  </div>
`;
  document.getElementById("map").appendChild(legend);

  // Interactive: click → popup with facility info
  function popupFromFeature(e) {
    const props = e.features[0].properties;
    const coords = e.features[0].geometry.coordinates.slice();
    const html = popupHTML(props);
    new maplibregl.Popup({ offset: 12 })
      .setLngLat(coords)
      .setHTML(html)
      .addTo(window._map);
  }
  map.on("click", "transit-buildings", popupFromFeature);
  map.on("click", "transit-gates", popupFromFeature);
  map.on("click", "transit-bus-stops", popupFromFeature);
  // (Live buses use HTML markers — click → popup is wired in
  //  renderLiveBusMarkers, no MapLibre click handler needed.)

  // -- Proximity-based dot visibility --------------------------------------
  // Dots default to invisible. They appear when:
  //   - cursor is within PROXIMITY_PX of them ("near" state)
  //   - cursor is directly on them ("hover" state)
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

  // -- Hover tooltips for facility dots ------------------------------------
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
                   (props.name_en ? `<div class="name-en">${esc(props.name_en)}</div>` : "");
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

  // -- Loaders --------------------------------------------------------------
  async function loadJSON(path) {
    const r = await fetch(path);
    if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
    return r.json();
  }

  async function loadAll() {
    setLastUpdate("Loading…");
    try {
      const [fac, stops, schedules, live] = await Promise.all([
        loadJSON("/data/facilities.geojson"),
        loadJSON("/data/bus_stops.geojson"),
        loadJSON("/data/schedules.json"),
        loadJSON("/data/live_buses.geojson"),
      ]);
      state.facilities = fac.features || [];
      state.busStops = stops.features || [];
      state.schedules = schedules;
      state.liveBuses = live.features || [];

      // Load bus line geometries in parallel (used for the orange/blue
      // polylines on the basemap).
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
        .map(x => {
          // The bus_lines/*.geojson files are each a FeatureCollection
          // wrapping a single LineString Feature. Unwrap so each item
          // is a real GeoJSON Feature we can push to the bus_lines_layer
          // source for rendering.
          const feat = (x.g.features && x.g.features[0]) || x.g;
          return {
            ...feat,
            properties: {
              ...(feat.properties || {}),
              line_code: x.key.split("_")[0],
              direction: parseInt(x.key.split("_")[1]),
            },
          };
        });

      // Push bus line polylines to the bus_lines_layer source so they
      // render on the basemap (with a colored line per route).
      const busLinesFC = {
        type: "FeatureCollection",
        features: state.busLines,
      };
      const m = window._map;
      if (m && m.getSource("bus_lines_layer")) {
        m.getSource("bus_lines_layer").setData(busLinesFC);
      }

      // Index facilities by id and name (for tooltip and lookup).
      state.facilitiesById = {};
      [...state.facilities, ...state.busStops].forEach(f => {
        const p = f.properties;
        state.facilitiesById[p.facility_id] = f;
      });

      // Push to map sources
      const map = window._map;
      if (map && map.getSource("facilities")) map.getSource("facilities").setData(fac);
      if (map && map.getSource("bus_stops")) map.getSource("bus_stops").setData(stops);

      renderSchedule();
      renderLiveList();
      setLastUpdate(new Date().toLocaleTimeString());
    } catch (e) {
      console.error(e);
      setLastUpdate("Error: " + e.message, true);
    }
  }

  // Pulls both live buses AND schedule. Both can change minute-to-minute
  // (especially around the work day start, lunch, evening, and weekend
  // transitions), so we re-fetch them together every 30s. The schedule
  // used to be loaded only by loadAll() and required a manual Refresh
  // click to refresh; the user reported this as a bug.
  async function refreshLive() {
    try {
      const [live, schedules] = await Promise.all([
        loadJSON("/data/live_buses.geojson"),
        loadJSON("/data/schedules.json"),
      ]);
      state.liveBuses = live.features || [];
      state.schedules = schedules;
      const map = window._map;
      if (map && map.getSource("live_buses")) {
        map.getSource("live_buses").setData(live);
      }
      renderSchedule();
      renderLiveList();
      setLastUpdate(new Date().toLocaleTimeString());
    } catch (_) {}
  }

  // -- Renderers (sidebar only — map renders via MapLibre layers) ----------

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
      const lineBadge = p.route_code
        ? `<span class="live-line-badge" style="background:${liveBusColor(p.route_code)}">${esc(p.route_code)}</span>`
        : `<span class="live-line-badge" style="background:#888">—</span>`;
      const next = (p.next_station && p.next_station !== "--")
        ? esc(p.next_station) : "—";
      const speed = p.speed_kmh != null ? `${p.speed_kmh} km/h` : "";
      return `<div class="live-bus">
        ${lineBadge}
        <span class="next-station">${next}</span>
        <span class="live-speed">${speed}</span>
      </div>`;
    }).join("");
    // Also render the bus markers on the map.
    renderLiveBusMarkers();
  }

  // Live-bus color by route_code (mirrors the MapLibre `match` expression
  // in the transit-live-buses layer so the sidebar badge and the map dot
  // are always the same color).
  function liveBusColor(routeCode) {
    if (routeCode === "NKDH1") return "#f7911d";
    if (routeCode === "NKDH2") return "#29abe2";
    if (routeCode === "SEV")   return "#888888";
    return "#00ab5b";
  }

  // -- Live bus markers (single rotating SVG, body + chevron) --------------
  // Each live bus is a single MapLibre Marker whose element is an SVG
  // shaped like a teardrop / map-pin: a colored circle body with a
  // white triangle embedded on the right side, pointing in the bus's
  // direction of travel. The whole SVG rotates together so the body
  // and the direction indicator stay visually attached.
  let liveBusMarkers = [];
  function renderLiveBusMarkers() {
    const map = window._map;
    if (!map) return;
    // Drop any existing markers — we recreate them each refresh.
    liveBusMarkers.forEach(m => m.remove());
    liveBusMarkers = [];
    state.liveBuses.forEach(f => {
      const p = f.properties;
      const [lng, lat] = f.geometry.coordinates;
      const course = Number(p.course) || 0;
      const color = liveBusColor(p.route_code);

      // SVG teardrop / play-button shape: a 22×22 circle with an
      // integrated white triangle "tail" at the right side, all
      // rotated as one unit. The triangle is large enough to read
      // direction at a glance but small enough not to overpower the
      // body. anchor:"center" puts the SVG center on the bus
      // coordinate, so rotation pivots correctly.
      const el = document.createElement("div");
      el.className = "live-bus-marker";
      el.style.setProperty("--bus-color", color);
      el.innerHTML = `
        <svg viewBox="0 0 24 24" width="24" height="24" style="transform: rotate(${course}deg)">
          <circle cx="10" cy="12" r="7" fill="${color}" stroke="#fff" stroke-width="1.8"/>
          <polygon points="14,7 19,12 14,17" fill="#fff"/>
        </svg>
      `;

      // Hover: scale the whole marker. Feature-state is propagated
      // to the underlying circle layer so it also enlarges.
      el.addEventListener("mouseenter", () => {
        el.classList.add("hovered");
        try { map.setFeatureState({ source: "live_buses", id: p.bus_id }, { hover: true }); } catch (_) {}
      });
      el.addEventListener("mouseleave", () => {
        el.classList.remove("hovered");
        try { map.setFeatureState({ source: "live_buses", id: p.bus_id }, { hover: false }); } catch (_) {}
      });

      // Click → popup.
      el.addEventListener("click", (e) => {
        e.stopPropagation();
        new maplibregl.Popup({ closeButton: true, offset: 14, className: "bus-popup" })
          .setLngLat([lng, lat])
          .setHTML(busPopupHTML(p))
          .addTo(map);
      });

      const marker = new maplibregl.Marker({ element: el, anchor: "center" })
        .setLngLat([lng, lat])
        .addTo(map);
      liveBusMarkers.push(marker);
    });
  }

  // Build the HTML for a bus popup. We don't reuse popupHTML() because
  // live buses have totally different fields (route_code, next_station,
  // speed_kmh, course, bus_id) than buildings/stops (name, name_en,
  // routes, facility_id).
  function busPopupHTML(p) {
    const lineBadge = p.route_code
      ? `<span class="bus-popup-line" style="background:${liveBusColor(p.route_code)}">${esc(p.route_code)}</span>`
      : "";
    const plate = p.bus_id ? `粤B${esc(p.bus_id.slice(2))}` : "";
    const speed = p.speed_kmh != null ? `<div class="bus-popup-row">${p.speed_kmh} km/h</div>` : "";
    const next = (p.next_station && p.next_station !== "--")
      ? `<div class="bus-popup-row"><span class="bus-popup-label">下站 Next stop</span><b>${esc(p.next_station)}</b></div>` : "";
    const course = (p.course != null && p.course !== 0)
      ? `<div class="bus-popup-row"><span class="bus-popup-label">航向 Heading</span>${Math.round(p.course)}°</div>` : "";
    return `<div class="bus-popup-inner">
      <div class="bus-popup-header">${lineBadge} ${esc(plate)}</div>
      ${speed}${next}${course}
    </div>`;
  }

  // -- Utilities ------------------------------------------------------------
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

  // -- Auto-refresh countdown -----------------------------------------------
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

  // -- Wiring --------------------------------------------------------------
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
