// sustech_survival.transit web UI — main client script
// Pure-frontend; reads pre-exported GeoJSON/JSON from /data/* via the local server.

(function () {
  "use strict";

  // ── State ────────────────────────────────────────────────────────────────
  const state = {
    facilities: [],        // GeoJSON features (buildings + gates)
    busStops: [],          // GeoJSON features
    busLines: {},          // { "XYBS1_0": GeoJSON, "XYBS1_1": ..., }
    liveBuses: [],         // GeoJSON features
    schedules: { workday: [], holiday: [] },
    facilitiesById: {},    // id → facility feature
    day: "workday",
    routeLayer: null,      // L.LayerGroup for current route polyline
  };

  // ── Map setup ────────────────────────────────────────────────────────────
  const map = L.map("map", { zoomControl: true }).setView([22.603, 113.994], 15);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "© OpenStreetMap contributors",
  }).addTo(map);

  // Layer groups
  const layers = {
    buildings: L.layerGroup().addTo(map),
    gates: L.layerGroup().addTo(map),
    stops: L.layerGroup().addTo(map),
    lines: L.layerGroup().addTo(map),
    live: L.layerGroup().addTo(map),
    route: L.layerGroup().addTo(map),
  };

  // Legend
  const legend = L.control({ position: "bottomright" });
  legend.onAdd = function () {
    const div = L.DomUtil.create("div", "legend");
    div.innerHTML = `
      <div class="legend-item"><span class="legend-dot" style="background:#3388ff"></span> Building</div>
      <div class="legend-item"><span class="legend-dot" style="background:#ff8c00"></span> Gate</div>
      <div class="legend-item"><span class="legend-dot" style="background:#e91e63"></span> Bus stop</div>
      <div class="legend-item"><span class="legend-dot" style="background:#00ab5b"></span> 1 路 / Line 1</div>
      <div class="legend-item"><span class="legend-dot" style="background:#f0608f"></span> 2 路 / Line 2</div>
      <div class="legend-item">🚌 Live bus</div>
      <div class="legend-item">━ Planned route</div>
    `;
    return div;
  };
  legend.addTo(map);

  // ── Loaders ──────────────────────────────────────────────────────────────
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

      // Build facilitiesById
      state.facilitiesById = {};
      [...state.facilities, ...state.busStops].forEach(f => {
        state.facilitiesById[f.properties.facility_id] = f;
      });

      // Bus line geometries (best-effort, may 404 for some lines)
      try {
        const promises = [];
        for (const code of ["XYBS1", "XYBS2"]) {
          for (const dir of [0, 1]) {
            promises.push(loadJSON(`/data/bus_lines/${code}_${dir}.geojson`)
              .then(g => state.busLines[`${code}_${dir}`] = g)
              .catch(() => {}));  // ignore failures
          }
        }
        await Promise.all(promises);
      } catch (_) {}

      renderAll();
      setLastUpdate(new Date().toLocaleTimeString());
    } catch (e) {
      console.error(e);
      setLastUpdate("Error: " + e.message, true);
    }
  }

  // ── Renderers ────────────────────────────────────────────────────────────
  function renderAll() {
    renderFacilities();
    renderBusStops();
    renderBusLines();
    renderLiveBuses();
    renderSchedule();
    renderLiveList();
  }

  function popupHTML(props) {
    const nameZh = props.name || "";
    const nameEn = props.name_en ? `<div class="name-en">${esc(props.name_en)}</div>` : "";
    const routes = (props.routes || []).length
      ? `<div class="meta">Routes: ${(props.routes || []).join(", ")}</div>` : "";
    return `<div class="name-zh">${esc(nameZh)}</div>${nameEn}${routes}<div class="meta"><span class="facility-id">${esc(props.facility_id)}</span></div>`;
  }

  function renderFacilities() {
    layers.buildings.clearLayers();
    layers.gates.clearLayers();
    state.facilities.forEach(f => {
      const p = f.properties;
      const [lng, lat] = f.geometry.coordinates;
      const icon = p.kind === "gate"
        ? L.divIcon({ className: "facility-icon", html: "🚪", iconSize: [20, 20], iconAnchor: [10, 10] })
        : L.divIcon({ className: "facility-icon", html: "🏢", iconSize: [18, 18], iconAnchor: [9, 9] });
      const marker = L.marker([lat, lng], { icon })
        .bindPopup(popupHTML(p))
        .bindTooltip(p.name);
      layers[p.kind === "gate" ? "gates" : "buildings"].addLayer(marker);
    });
  }

  function renderBusStops() {
    layers.stops.clearLayers();
    state.busStops.forEach(f => {
      const p = f.properties;
      const [lng, lat] = f.geometry.coordinates;
      const icon = L.divIcon({ className: "bus-stop-icon", html: "🚏", iconSize: [16, 16], iconAnchor: [8, 8] });
      L.marker([lat, lng], { icon })
        .bindPopup(popupHTML(p))
        .bindTooltip(p.name)
        .addTo(layers.stops);
    });
  }

  function renderBusLines() {
    layers.lines.clearLayers();
    const colorMap = {
      "XYBS1_0": "#00ab5b",  // 1路 CW
      "XYBS1_1": "#00ab5b",  // 1路 CCW
      "XYBS2_0": "#f0608f",  // 2路 CW
      "XYBS2_1": "#f0608f",  // 2路 CCW
    };
    Object.entries(state.busLines).forEach(([key, fc]) => {
      const color = colorMap[key] || "#666";
      L.geoJSON(fc, {
        style: { color, weight: 4, opacity: 0.85 },
      }).addTo(layers.lines);
    });
  }

  function renderLiveBuses() {
    layers.live.clearLayers();
    state.liveBuses.forEach(f => {
      const p = f.properties;
      const [lng, lat] = f.geometry.coordinates;
      const icon = L.divIcon({
        className: "live-bus-icon",
        html: "🚌",
        iconSize: [24, 24],
        iconAnchor: [12, 12],
      });
      L.marker([lat, lng], { icon })
        .bindPopup(`<div class="name-zh">${esc(p.route_code)}</div>
                    <div class="meta">→ ${esc(p.next_station || "?")}</div>
                    <div class="meta">speed: ${p.speed_kmh} km/h</div>`)
        .addTo(layers.live);
    });
  }

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
      html += `
        <div class="schedule-line">
          <h3>${esc(line.sub_name)} <span class="badge">${esc(line.color || "")}</span></h3>
          <div class="desc">${esc((line.sub_desc || "").replace(/\\n/g, " / "))}</div>
          <div class="meta">${times.length} departures · ${line.minute_on_road} min ride</div>
          ${next.length ? `<div class="meta">Next: ${next.join(" ")}</div>` : ""}
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
      const matches = all.filter(f => {
        const p = f.properties;
        return (p.name || "").toLowerCase().includes(q)
            || (p.name_en || "").toLowerCase().includes(q)
            || (p.facility_id || "").toLowerCase().includes(q);
      }).slice(0, 8);
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

    input.addEventListener("keydown", (e) => {
      const items = list.querySelectorAll("li[data-id]");
      if (!items.length) return;
      if (e.key === "ArrowDown") { e.preventDefault(); activeIdx = Math.min(items.length - 1, activeIdx + 1); }
      else if (e.key === "ArrowUp") { e.preventDefault(); activeIdx = Math.max(0, activeIdx - 1); }
      else if (e.key === "Enter") {
        e.preventDefault();
        const pick = activeIdx >= 0 ? items[activeIdx] : items[0];
        if (pick) onPick(pick.dataset.id);
      } else if (e.key === "Escape") {
        list.classList.remove("show");
      }
      items.forEach((it, i) => it.style.background = i === activeIdx ? "#e0eaff" : "");
    });

    list.addEventListener("click", (e) => {
      const li = e.target.closest("li[data-id]");
      if (li) onPick(li.dataset.id);
    });

    document.addEventListener("click", (e) => {
      if (e.target !== input) list.classList.remove("show");
    });
  }

  // ── Routing (we call the backend via fetch — simple POST would need a route)
  //     For pure-client UX, we use a JS-only Dijkstra here. The Python API
  //     remains the source of truth for the canonical graph; this is a UX nicety.
  //
  //     We avoid the server complexity: build a simple graph from facilities + bus
  //     stops + live bus lines, run Dijkstra in JS for instant in-browser routes.

  function buildClientGraph() {
    // Nodes: every facility (building/gate/bus_stop). Edges: walking (<=250m)
    // and bus (consecutive stops on same line/dir).
    const all = [...state.facilities, ...state.busStops];
    const nodes = {};  // id → {id, lat, lng}
    const meta = {};   // id → facility properties
    all.forEach(f => {
      const p = f.properties;
      const [lng, lat] = f.geometry.coordinates;
      nodes[p.facility_id] = { id: p.facility_id, lat, lng };
      meta[p.facility_id] = p;
    });
    const edges = [];  // [{a, b, mode, dur_min, dist_m, details}]
    const ids = Object.keys(nodes);
    // walking edges
    for (let i = 0; i < ids.length; i++) {
      for (let j = i + 1; j < ids.length; j++) {
        const a = nodes[ids[i]], b = nodes[ids[j]];
        const d = haversine(a, b);
        if (d <= 250) {
          const dur = d / 1000 / 4.5 * 60;
          edges.push({ a: a.id, b: b.id, mode: "walk", dur_min: dur, dist_m: d,
                       details: `${Math.round(d)} m walk` });
          edges.push({ a: b.id, b: a.id, mode: "walk", dur_min: dur, dist_m: d,
                       details: `${Math.round(d)} m walk` });
        }
      }
    }
    // bus edges (consecutive stops on same line)
    Object.entries(state.busLines).forEach(([key, fc]) => {
      const coords = [];
      fc.features.forEach(f => {
        if (f.geometry.type === "LineString") {
          f.geometry.coordinates.forEach(c => coords.push(c));
        }
      });
      // Walk through features in order, find the matching bus stop at each vertex
      const stops = state.busStops.filter(s => {
        const p = s.properties;
        return (p.routes || []).includes(key);
      });
      // sort by station_id
      stops.sort((a, b) => (a.properties.station_id || 0) - (b.properties.station_id || 0));
      for (let i = 0; i < stops.length - 1; i++) {
        const a = stops[i].properties.facility_id;
        const b = stops[i + 1].properties.facility_id;
        const an = nodes[a], bn = nodes[b];
        if (!an || !bn) continue;
        const d = haversine(an, bn);
        const dur = d / 1000 * 2.5;  // ~2.5 min/km
        edges.push({ a, b, mode: "bus", dur_min: dur + 5, dist_m: d,
                     details: `${key}: ${meta[a].name} → ${meta[b].name}` });
        edges.push({ a: b, b: a, mode: "bus", dur_min: dur + 5, dist_m: d,
                     details: `${key}: ${meta[b].name} → ${meta[a].name}` });
      }
    });
    return { nodes, edges, meta };
  }

  function dijkstra(graph, src, dst, mode) {
    const dist = {}, prev = {};
    Object.keys(graph.nodes).forEach(id => {
      dist[id] = Infinity; prev[id] = null;
    });
    dist[src] = 0;
    // Binary heap would be cleaner, but for ~100 nodes Array.sort is fine.
    const pq = [[0, src]];
    while (pq.length) {
      pq.sort((a, b) => a[0] - b[0]);
      const [d, u] = pq.shift();
      if (d > dist[u]) continue;
      if (u === dst) break;
      graph.edges.forEach(e => {
        if (e.a !== u) return;
        if (mode === "walk" && e.mode !== "walk") return;
        if (mode === "bus" && e.mode !== "bus") return;
        const nd = d + e.dur_min;
        if (nd < dist[e.b]) {
          dist[e.b] = nd;
          prev[e.b] = e;
          pq.push([nd, e.b]);
        }
      });
    }
    if (dist[dst] === Infinity) return null;
    // Reconstruct path edges from dst back to src
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
      resultDiv.innerHTML = `<div class="empty">Already at the destination.</div>`;
      return;
    }

    const graph = buildClientGraph();
    const path = dijkstra(graph, fromId, toId, mode);
    if (!path) {
      resultDiv.innerHTML = `<div class="error">No route found (mode=${mode}). Try mode=transit or larger walk radius.</div>`;
      return;
    }

    // Render polyline
    layers.route.clearLayers();
    const latlngs = [graph.nodes[fromId], ...path.edges.map(e => graph.nodes[e.b])];
    const line = L.polyline(latlngs.map(n => [n.lat, n.lng]), {
      color: "#0066cc", weight: 5, opacity: 0.7, dashArray: "10, 8",
    }).addTo(layers.route);
    map.fitBounds(line.getBounds(), { padding: [40, 40] });

    // Render steps
    let html = `<div class="summary">${path.total_min.toFixed(1)} min · ${path.edges.length} steps</div>`;
    path.edges.forEach(e => {
      const fromName = graph.meta[e.a].name;
      const toName = graph.meta[e.b].name;
      const icon = e.mode === "walk" ? "🚶" : "🚌";
      html += `<div class="step mode-${e.mode}">
        <strong>${icon} ${fromName} → ${toName}</strong>
        <div class="meta">${e.dur_min.toFixed(1)} min · ${Math.round(e.dist_m)} m · ${esc(e.details)}</div>
      </div>`;
    });
    resultDiv.innerHTML = html;
  }

  function resolveFacilityId(text) {
    if (!text) return null;
    // exact id match
    if (state.facilitiesById[text]) return text;
    // case-insensitive name
    const t = text.toLowerCase();
    for (const f of [...state.facilities, ...state.busStops]) {
      const p = f.properties;
      if ((p.name || "").toLowerCase() === t) return p.facility_id;
      if ((p.name_en || "").toLowerCase() === t) return p.facility_id;
    }
    // substring
    for (const f of [...state.facilities, ...state.busStops]) {
      const p = f.properties;
      if ((p.name || "").toLowerCase().includes(t)) return p.facility_id;
      if ((p.name_en || "").toLowerCase().includes(t)) return p.facility_id;
    }
    return null;
  }

  // ── Utilities ────────────────────────────────────────────────────────────
  function esc(s) { return String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
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

  // ── Wiring ──────────────────────────────────────────────────────────────
  attachSuggestion("from-input", "from-suggestions", (id) => {
    document.getElementById("from-input").value = state.facilitiesById[id]?.properties.name || id;
  });
  attachSuggestion("to-input", "to-suggestions", (id) => {
    document.getElementById("to-input").value = state.facilitiesById[id]?.properties.name || id;
  });
  document.getElementById("route-btn").addEventListener("click", findRoute);
  document.getElementById("refresh-btn").addEventListener("click", loadAll);

  document.querySelectorAll(".day-toggle button").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".day-toggle button").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      state.day = btn.dataset.day;
      renderSchedule();
    });
  });

  loadAll();
  // Auto-refresh live data every 30s
  setInterval(async () => {
    try {
      const live = await loadJSON("/data/live_buses.geojson");
      state.liveBuses = live.features || [];
      renderLiveBuses();
      renderLiveList();
      setLastUpdate(new Date().toLocaleTimeString());
    } catch (_) {}
  }, 30000);
})();