/* ───────────────────────────────────────────────────────────────────────────
 * TIS page SPA — 4171 lines, single IIFE, no build step.
 *
 * Files in this module:
 *   templates/tis.html  page markup, inline CSS, button labels
 *   static/tis/tis.js   this file — state, render, cascade, persistence
 *   blueprints/tis.py   HTTP routes (13 endpoints)
 *
 * Sections in this file (the `// ──` headers are the index):
 *   DOM refs · State · Loading bar · HTTP helpers · Semester helpers ·
 *   Color/time helpers · Catalog loaders · Results render · NCES brief ·
 *   NCES eval page · Picked list + mutators · ICS export · Flash/utils ·
 *   Drag-to-reorder picked · Solve tab · Weekly grid · Tabs · Bid panel ·
 *   DOMContentLoaded
 *
 * Cascade contract — PICKED is the single source of truth. The mutators
 * addPicked (L1678), removePicked (L1698), applyPicksFromData (used by
 * file Load + drag-drop) MUST all call this full set in order:
 *
 *     renderPicked()           ← #pick-list + Sync/Drop/Save/Load/ICS buttons
 *     updateResultsHeader()    ← select-all + count in search results
 *     renderGrid()             ← step-1 weekly grid (clear #grid-legend if empty)
 *     renderGrid3()            ← step-3 weekly grid (picked + TIS-enrolled)
 *     renderBidPanel()         ← bid boxes + bar + totals
 *     updateBidStat()          ← right-column "Bids: X/150 pts" summary
 *     updateSolveCodes()       ← solver "Codes to solve:" chip
 *
 * NO localStorage auto-save — picks live in memory only. The user
 * explicitly loads (button or drag-drop) and saves (button). See the
 * "File-based save/load" section below.
 *
 * HTTP transport (getJSON L118, postJSON L126): no timeout. TIS over VPN
 * is slow; a timeout aborts requests the user expects as slow. Callers
 * own error handling via .catch(); errors surface via flash(msg, kind).
 *
 * Module doc: docs/en/webui-architecture.md — facts about this module
 * only. Workflow, procedure, and "how to use" are NOT in module docs.
 * ─────────────────────────────────────────────────────────────────────────── */

(function() {
'use strict';

// ── DOM refs ──────────────────────────────────────────────────────────────
var SEM_SEL = document.getElementById('sem-select');
var KW = document.getElementById('kw');
var F_COL = document.getElementById('f-college');
var F_TASK = document.getElementById('f-tasktype');
var F_CAT = document.getElementById('f-cat');
var F_CAM = document.getElementById('f-campus');
var F_LANG = document.getElementById('f-lang');
var F_CULT = document.getElementById('f-cult');
var F_SCH = document.getElementById('f-sched');
var F_TEACHER = document.getElementById('f-teacher');
var STAT = document.getElementById('stat');
var RESULTS = document.getElementById('results');
var GRID_ODD = document.getElementById('grid-body-odd');
var GRID_EVEN = document.getElementById('grid-body-even');
// Step 3 grid — same layout (odd/even side-by-side) but shows picked
// + TIS-enrolled together. Separate DOM IDs so renderGrid (step 1) and
// renderGrid3 (step 3) don't trample each other when the user toggles
// between steps.
var GRID_ODD_3 = document.getElementById('grid-body-odd-3');
var GRID_EVEN_3 = document.getElementById('grid-body-even-3');
var GRID_LEGEND_3 = document.getElementById('grid-legend-3');
var BLOCK_BODY = document.getElementById('block-body');
var PICK_STAT = document.getElementById('pick-stat');
var PICK_LIST = document.getElementById('pick-list');
var ENROLLED_OUT = document.getElementById('enrolled-out');
var CRUMB = document.getElementById('crumb');
var SOLVE_OUT = document.getElementById('solve-out');
var SOLVE_CODES = document.getElementById('solve-codes');
var EVAL_OUT = document.getElementById('eval-out');
var BRIEF_CARD = document.createElement('div');
BRIEF_CARD.className = 'brief-card';
BRIEF_CARD.id = 'brief-card';
BRIEF_CARD.innerHTML = '<div class="bc-loading" id="bc-body">Loading NCES</div>';
document.body.appendChild(BRIEF_CARD);
var BRIEF_BODY = document.getElementById('bc-body');
var BRIEF_OPEN = null;  // set when populated
var BRIEF_HINT = null;
var BRIEF_ACTIVE_CODE = null;
var BRIEF_CACHE = {};   // code → response (avoid re-fetching on rapid hover)
var BRIEF_INFLIGHT = null;  // current fetch XHR
var BRIEF_HOVER_TIMER = null;
var GRID_LEGEND = document.getElementById('grid-legend');

// ── Bid panel refs + state (积分选课) ─────────────────────────────────────
var BID_BAR = document.getElementById('bid-bar');
var BID_BOXES = document.getElementById('bid-boxes');
var BID_META = document.getElementById('bp-meta');
var BID_JFFS = document.getElementById('bp-jffs');
var BID_MSG = document.getElementById('bp-msg');
var BID_SUBMIT = document.getElementById('bp-submit');
var BID_STAT = document.getElementById('bid-stat');
var BID_STAT_TEXT = document.getElementById('bid-stat-text');
var BID_OVER_BANNER = document.getElementById('bp-over-banner');
var BID_PANEL = document.querySelector('.bid-panel');
var BID_CONFLICT_BANNER = document.getElementById('bp-conflict-banner');
var PICKED_BIDS = {};        // { rwh: bid_int }      parallel to PICKED
var SAVED_SCHEDULES = [];    // [{label, sections, dropped, ts, totalCredits}] persisted to localStorage
var FOCUSED_SAVED_IDX = -1;  // -1 = no saved schedule focused (←/→ cycles solver idx instead)
var SOLVER_FLAT = null;      // last solver result (used by Save + ←/→)
var SOLVER_IDX = 0;          // current solver index
var SOLVER_TOTAL_CODES = 0;  // for the "X / Y" coverage line in the Compare pane
var SOLVER_codeToName = {};  // mirrored from the last solve() — for the Compare pane rendering
var SOLVER_groups = null;    // groupKey → [sol,...]
var SOLVER_groupOrder = [];  // order of first appearance in groups
var SOLVER_codeOrder = [];   // the priority list of codes used by the last solve() (for saved-schedule round-trip)
var PICKED_CONFLICTS = {};    // { rwh: bool }        true if this rwh conflicts with another picked rwh
var PICKED_CHECKED = {};      // { rwh: true }        UI-only: which right-panel checkboxes are ticked for bulk-remove. Not persisted.
var CURRENT_FILE = null;      // { kind: 'saved'|'loaded', name: 'tis-picks-...json' } — shown in the right panel for reference.
var ROUND_INFO = { jffs: 0, ksrq: '', jsrq: '', lcmc: '', xkfsdm: '', xkms: '', ok: false, message: '' };
var BID_DRAG = null;         // { sourceRwh, sourceBox, arrowEl, targetRwh, lastX, lastY }
var BID_EDIT = null;         // { rwh, originalBid, inputEl }
var EXISTING_BIDS = {};      // { rwh: bid_int } — bids already set on TIS for enrolled/cart items
                              // (read from d.enrolled[]/d.cart[] in search_personal response)


// ── State ─────────────────────────────────────────────────────────────────
var CAT = [];               // full course list from latest server fetch
var ALL_CAT = [];           // cached full catalog for client-side filtering
var PICKED = {};            // { rwh: courseDict }
var ACTIVE_RWH = null;      // last clicked card rwh (for eval)
var EVAL_CACHE = {};        // { code: evalResponse }
var ENROLLED_RWH = new Set(); // rwhs currently enrolled on TIS
// Full enrolled-item data keyed by rwh. Populated by loadEnrolled() so
// renderGrid3() can pull each enrolled course's slots/name/section for
// the step-3 weekly grid (which shows picked + enrolled together).
var ENROLLED_DATA = {};
var IGNORE_TIS_ENROLLED = true;  // when TRUE (default): module treats TIS-enrolled as informational;
                                 // user can drop / re-bid / etc. When FALSE: TIS-enrolled is
                                 // "unquestionable" — pinned picks that win every conflict, can't
                                 // be dropped, and the solver keeps them even at the cost of
                                 // dropping other picked courses. The 🗑 Drop-all-enrolled button
                                 // hides when this is FALSE.
var COLORS_CACHE = {};      // { code: color }
var SEMESTER_INFO = null;   // cached /api/tis/info response
var COLLEGE_MAP = {};       // college-name → college-code (for p_kkyx on TIS personal search)
var LANGUAGE_MAP = {'中文': '1', '英文': '2', '双语': '3'}; // language-name → TIS code
var CATEGORY_MAP = {};      // category-name → kclbdm code (e.g. 美育类→0907).
                            // Populated from /api/tis/info.category_codes on first load.
var LOAD_BY_RWH = {};       // { rwh: enrolled_int } — live "currently selected" count
                            // from TIS. Populated on demand by the "Refresh load"
                            // button; cached in localStorage 10 min so cards keep
                            // showing the count across search/filter/page changes.
var LOAD_FETCHED_AT = 0;    // Date.now() of the last successful refresh-load.
var MODE = 'personal';      // 'personal' (我要选课, default) or 'campus' (全校课表, browse-only)
var CURRENT_STEP = 1;        // active step in the 4-step workflow (1..4)
var GRID_VISIBLE = true;     // whether the weekly grid is shown (toggle in stepper header)

var PERIODS = 12;
var BLOCKED = {};          // { 'day:period' -> true }   day=1-7, period=1-12
var _modeLoadId = 0;       // monotonic token — incremented on every loadForMode call.
var _evalLoadId = 0;       // monotonic token — incremented on every selectCourse call.
                           // loadCourses() captures it at call time and discards the
                           // response if the token changed (guards against fast toggles).

// ── Loading bar (bar only — never touches results or stat) ──────────────
var LB = document.getElementById('loading-bar');
var LB_FILL = LB.querySelector('.lb-fill');
var LB_REQ_ID = 0;          // monotonically increasing request id
var LB_TIMER = null;
function loadingStart() {
  var id = ++LB_REQ_ID;
  LB.classList.add('active');
  LB_FILL._tick = 20;
  LB_FILL.style.width = '20%';
  if (LB_TIMER) clearInterval(LB_TIMER);
  LB_TIMER = setInterval(function() {
    if (LB_FILL._tick < 85) {
      LB_FILL._tick += Math.random() * 8;
      if (LB_FILL._tick > 85) LB_FILL._tick = 85;
      LB_FILL.style.width = LB_FILL._tick + '%';
    }
  }, 600);
  return id;
}
function loadingEnd(id) {
  // Only the most recent request can hide the bar — older responses are stale
  if (id !== LB_REQ_ID) return;
  if (LB_TIMER) { clearInterval(LB_TIMER); LB_TIMER = null; }
  LB_FILL.style.width = '100%';
  setTimeout(function() { LB_FILL.style.width = '0'; }, 200);
  setTimeout(function() { LB.classList.remove('active'); }, 400);
}

// ── HTTP helpers (transport only — UI updates are caller's job) ──────────
// No timeout: TIS is frequently slow over VPN, and a hard timeout would
// abort requests the user knows to expect as slow. The caller owns error
// handling via its .catch() — there, network errors surface as flash
// messages the user can act on (refresh, switch network, etc.).
function getJSON(url) {
  var id = loadingStart();
  return fetch(url).then(function(r) {
    loadingEnd(id);
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return r.json();
  }, function(e) { loadingEnd(id); throw e; });
}
function postJSON(url, body) {
  var id = loadingStart();
  return fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  }).then(function(r) {
    loadingEnd(id);
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return r.json();
  }, function(e) { loadingEnd(id); throw e; });
}
var DAYS = 7;
var DAY_NAMES = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
var ROW_HEIGHT = 38;

// ── Semester helpers ─────────────────────────────────────────────────────

function semesterLabel(xn, xq) {
  var season = xq === '1' ? 'Fall' : xq === '2' ? 'Spring' : 'Summer';
  // Fall uses the end_year (first half of xn), Spring/Summer use the cohort_year (second half)
  var yr = xq === '1' ? xn.substring(0,4) : xn.substring(5,9);
  return season + ' ' + yr + ' (' + xn + ' Semester ' + xq + ')';
}

function buildSemesterOptions() {
  // Generate 5 semesters: current + 2 back + 2 ahead
  // Current: Fall 2026 (xn=2025-2026, xq=1) for course-selecting season
  var baseYear = 2025; // 2025-2026
  var semesters = [];
  // Fall 2024 (Sem 1) -> 2024-2025, xq=1
  // Spring 2025 (Sem 2) -> 2024-2025, xq=2
  // Summer 2025 (Sem 3) -> 2024-2025, xq=3
  // Fall 2025 (Sem 1) -> 2025-2026, xq=1
  // Spring 2026 (Sem 2) -> 2025-2026, xq=2
  // Summer 2026 (Sem 3) -> 2025-2026, xq=3
  // Fall 2026 (Sem 1) -> 2026-2027, xq=1
  // pattern: each academic year YYYY-YYYY+1 has xq 1,2,3

  // Start from 2024-2025 (Fall 2024) through 2026-2027 (Summer 2027)
  // That gives us 3 academic years * 3 semesters = 9 semesters, but we want 5.
  // Let's do: from 2024-2025 Semester 3 (Summer 2025) to 2026-2027 Semester 1 (Fall 2026)
  // That covers 5 semesters centered around Fall 2026
  
  // Actually, simpler: position Fall 2026 as index 2 (0-based), then go 2 back, 2 ahead
  // Semester order: SEASON_CYCLE = [Fall, Spring, Summer] per academic year
  // Fall 2025 = (2025-2026, 1) index 0
  // Spring 2026 = (2025-2026, 2) index 1
  // Summer 2026 = (2025-2026, 3) index 2
  // Fall 2026 = (2026-2027, 1) index 3
  // Spring 2027 = (2026-2027, 2) index 4

  var all = [];
  var acYear = 2024;
  for (var ay = 0; ay < 6; ay++) {
    var xn = acYear + '-' + (acYear + 1);
    all.push({ xn: xn, xq: '1' }); // Fall
    all.push({ xn: xn, xq: '2' }); // Spring
    all.push({ xn: xn, xq: '3' }); // Summer
    acYear++;
  }
  // Find index of Fall 2026 (2026-2027, 1)
  var centerIdx = -1;
  for (var i = 0; i < all.length; i++) {
    if (all[i].xn === '2026-2027' && all[i].xq === '1') {
      centerIdx = i;
      break;
    }
  }
  // Take 5 centered around centerIdx
  var startIdx = Math.max(0, centerIdx - 2);
  var endIdx = Math.min(all.length, centerIdx + 3);
  for (var j = startIdx; j < endIdx; j++) {
    semesters.push(all[j]);
  }

  SEM_SEL.innerHTML = '';
  for (var k = 0; k < semesters.length; k++) {
    var opt = document.createElement('option');
    opt.value = semesters[k].xn + '|' + semesters[k].xq;
    opt.textContent = semesterLabel(semesters[k].xn, semesters[k].xq);
    SEM_SEL.appendChild(opt);
  }

  // URL params take priority, fallback to Fall 2026
  var m = location.search.match(/[?&]xn=([^&]+)/);
  var qm = location.search.match(/[?&]xq=([^&]+)/);
  var urlXn = m ? m[1] : '{{ xn }}';
  var urlXq = qm ? qm[1] : '{{ xq }}';

  // Try to find a match
  var found = false;
  for (var l = 0; l < SEM_SEL.options.length; l++) {
    var parts = SEM_SEL.options[l].value.split('|');
    if (parts[0] === urlXn && parts[1] === urlXq) {
      SEM_SEL.selectedIndex = l;
      found = true;
      break;
    }
  }
  if (!found) {
    // Default to Fall 2026 (index where xn=2026-2027, xq=1)
    for (var p = 0; p < SEM_SEL.options.length; p++) {
      var p2 = SEM_SEL.options[p].value.split('|');
      if (p2[0] === '2026-2027' && p2[1] === '1') {
        SEM_SEL.selectedIndex = p;
        break;
      }
    }
  }
}

function sem() {
  var parts = SEM_SEL.value.split('|');
  return '?xn=' + encodeURIComponent(parts[0]) + '&xq=' + encodeURIComponent(parts[1]);
}

function currentXn() { return SEM_SEL.value.split('|')[0]; }
function currentXq() { return SEM_SEL.value.split('|')[1]; }

// ── Helpers ───────────────────────────────────────────────────────────────

var PALETTE = ['#3a7ade','#3fb950','#d29922','#a371f7','#f07178','#2cb89e','#e3b341','#6cc6ff','#ff7b72','#56d364','#bc8cff','#ffa657'];

function colorFor(code) {
  if (COLORS_CACHE[code]) return COLORS_CACHE[code];
  var h = 0;
  for (var i = 0; i < code.length; i++) {
    h = ((h << 5) - h) + code.charCodeAt(i);
    h = h & h;
  }
  var idx = Math.abs(h) % PALETTE.length;
  COLORS_CACHE[code] = PALETTE[idx];
  return PALETTE[idx];
}

function dayName(d) {
  return DAY_NAMES[d - 1] || '?';
}

function slotsOverlap(a, b) {
  if (a.day !== b.day) return false;
  var aStart = a.period_start, aEnd = a.period_end;
  var bStart = b.period_start, bEnd = b.period_end;
  if (aEnd < bStart || bEnd < aStart) return false;
  var aw = a.weeks || [];
  var bw = b.weeks || [];
  if (aw.length && bw.length) {
    var ws = {};
    for (var wi = 0; wi < aw.length; wi++) ws[aw[wi]] = true;
    var intersect = false;
    for (var wj = 0; wj < bw.length; wj++) {
      if (ws[bw[wj]]) { intersect = true; break; }
    }
    if (!intersect) return false;
  }
  return true;
}

function sectionsConflict(slotsA, slotsB) {
  for (var i = 0; i < slotsA.length; i++) {
    for (var j = 0; j < slotsB.length; j++) {
      if (slotsOverlap(slotsA[i], slotsB[j])) return true;
    }
  }
  return false;
}

function formatWeeks(weeks) {
  if (!weeks || !weeks.length) return '';
  var suffix = '';
  if (weeks.length > 1) {
    // Only label parity when it's actually informative (more than one week)
    if (weeks.every(function(w) { return w % 2 === 1; })) suffix = '单周';
    else if (weeks.every(function(w) { return w % 2 === 0; })) suffix = '双周';
  }
  var w;
  if (weeks.length <= 6) w = weeks.join(',');
  else w = weeks[0] + '-' + weeks[weeks.length - 1];
  return ' ' + w + suffix;
}

function formatSchedule(slots) {
  if (!slots || !slots.length) return '';
  return slots.map(function(s) {
    var d = dayName(s.day);
    var r = s.room ? ' ' + s.room : '';
    var w = formatWeeks(s.weeks);
    return d + ' ' + s.period_start + '-' + s.period_end + r + w;
  }).join('; ');
}

function formatScheduleHTML(slots) {
  if (!slots || !slots.length) return '';
  var parts = [];
  for (var i = 0; i < slots.length; i++) {
    var s = slots[i];
    var d = dayName(s.day);
    var r = s.room ? ' ' + escapeHtml(s.room) : '';
    var w = formatWeeks(s.weeks);
    parts.push('<span class="slot-tag">' + escapeHtml(d + ' ' + s.period_start + '-' + s.period_end) + r + w + '</span>');
  }
  return parts.join('');
}

function parseBlockedInput(str) {
  if (!str.trim()) return [];
  var parts = str.split('/');
  var result = [];
  for (var pi = 0; pi < parts.length; pi++) {
    var p = parts[pi].trim();
    if (!p) continue;
    var commaIdx = p.indexOf(',');
    if (commaIdx < 0) continue;
    var dayStr = p.substring(0, commaIdx).trim();
    var periodsStr = p.substring(commaIdx + 1).trim();
    var day = parseInt(dayStr, 10);
    if (isNaN(day) || day < 1 || day > 7) continue;
    var periods = [];
    var rangeParts = periodsStr.split('-');
    if (rangeParts.length === 2) {
      var ps = parseInt(rangeParts[0], 10);
      var pe = parseInt(rangeParts[1], 10);
      if (!isNaN(ps) && !isNaN(pe)) {
        for (var pp = ps; pp <= pe; pp++) periods.push(pp);
      }
    } else {
      var pn = parseInt(periodsStr, 10);
      if (!isNaN(pn)) periods.push(pn);
    }
    if (periods.length) result.push([day, periods]);
  }
  return result;
}

// ── Semester dropdown init ────────────────────────────────────────────────
buildSemesterOptions();

// ── API callers ───────────────────────────────────────────────────────────

function loadInfo() {
  var qs = sem();
  CRUMB.textContent = 'loading…';
  return getJSON('/api/tis/info' + qs).then(function(d) {
    if (d.error) {
      CRUMB.textContent = 'Error: ' + d.error;
      return;
    }
    SEMESTER_INFO = d;
    var xn = currentXn();
    var xq = currentXq();
    CRUMB.textContent = d.count + ' courses · ' + semesterLabel(xn, xq);
    // Colleges: d.colleges is [(code, name), ...] — store name as option text,
    // but stash the code→name map on the select so loadCourses() can look up
    // the code for personal-mode requests (TIS p_kkyx requires the code).
    COLLEGE_MAP = {};
    var collegeItems = d.colleges.map(function(p) {
      COLLEGE_MAP[p[1]] = p[0];
      return p[1];
    });
    // CATEGORY_MAP: kclbmc → kclbdm (e.g. 美育类 → 0907). Backend also
    // translates, but we need the map here to (a) annotate the dropdown
    // and (b) send the right value when personal mode is active.
    CATEGORY_MAP = d.category_codes || {};
    // Language map: prefer server-provided, fall back to the hardcoded
    // defaults if the server didn't include one (back-compat).
    if (d.language_codes) LANGUAGE_MAP = d.language_codes;
    populateSelect(F_COL, collegeItems);
    populateSelect(F_TASK, d.task_types);
    // Category dropdown: value = bare name, text = "name (code)".
    // This way sel.value is clean for server lookup, and the user sees
    // the code annotation.
    {
      var catVal = F_CAT.value;
      var html = '<option value="">All</option>';
      d.categories.forEach(function(n) {
        var code = CATEGORY_MAP[n];
        var label = code ? n + ' (' + code + ')' : n;
        var ev = n.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
        var el = label.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
        html += '<option value="' + ev + '">' + el + '</option>';
      });
      F_CAT.innerHTML = html;
      F_CAT.value = catVal;
    }
    populateSelect(F_CAM, d.campuses);
    populateSelect(F_LANG, d.languages);
    STAT.textContent = d.count + ' courses available.';
    // Auto-load all courses after loading info
    return loadCourses(true);
  })['catch'](function(e) {
    CRUMB.textContent = 'Network error';
    STAT.textContent = 'Error loading info: ' + e.message;
  });
}

function populateSelect(sel, items) {
  var val = sel.value;
  var html = '<option value="">All</option>';
  for (var i = 0; i < items.length; i++) {
    var v = items[i];
    var e = v.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
    html += '<option value="' + e + '">' + e + '</option>';
  }
  sel.innerHTML = html;
  sel.value = val;
}

function populateCourseTypes(types, currentType) {
  // types is [{xkfsdm, xkfsmc, lcmc, ...}]
  var sel = document.getElementById('f-xkfsdm');
  var val = sel.value;
  // Keep the "Type" option at index 0, remove the rest
  while (sel.options.length > 1) sel.remove(1);
  for (var i = 0; i < types.length; i++) {
    var r = types[i];
    if (r.xkfsdm === 'yixuan' || r.xkfsdm === 'gouwuche') continue; // skip built-in tabs
    var o = document.createElement('option');
    o.value = r.xkfsdm;
    o.textContent = (r.xkfsmc || r.lcmc || r.xkfsdm);
    sel.appendChild(o);
  }
  // Default to kzyxk (培养方案内课程 — your plan courses). Most students
  // care about their plan courses first; bxxk (通识必修) is rarely the
  // search target for course codes like MSE307. If kzyxk isn't in the
  // round config (summer/etc.), fall back to the first available type.
  if (!val) {
    if (sel.querySelector('option[value="kzyxk"]')) {
      sel.value = 'kzyxk';
    } else if (sel.options.length > 1) {
      sel.selectedIndex = 1;
    }
  } else {
    sel.value = val;
  }
}

function loadCourses(isInitialLoad) {
  var loadId = ++_modeLoadId;
  var qs = sem();
  qs += '&mode=' + MODE;
  qs += '&keyword=' + encodeURIComponent(KW.value);
  // Campus mode does a substring match on c.college (the display name).
  // Personal mode hits TIS's p_kkyx which REQUIRES the code, not the name —
  // sending the name yields 0 results. Look up the code from COLLEGE_MAP.
  if (MODE === 'personal' && F_COL.value && COLLEGE_MAP[F_COL.value]) {
    qs += '&college=' + encodeURIComponent(COLLEGE_MAP[F_COL.value]);
  } else {
    qs += '&college=' + encodeURIComponent(F_COL.value);
  }
  qs += '&task_type=' + encodeURIComponent(F_TASK.value);
  // Personal mode: TIS p_kclb requires a kclbdm code (e.g. 0907 for 美育类),
  // not the display name — sending the name silently returns 0 results.
  // The CATEGORY_MAP (populated from /api/tis/info.category_codes) maps
  // bare names → codes. The dropdown value is the bare name (e.g. "美育类"),
  // and the option text is annotated "美育类 (0907)" for the user.
  var catVal = F_CAT.value;
  if (catVal) {
    if (MODE === 'personal' && CATEGORY_MAP[catVal]) {
      qs += '&category=' + encodeURIComponent(CATEGORY_MAP[catVal]);
    } else {
      qs += '&category=' + encodeURIComponent(catVal);
    }
  } else {
    qs += '&category=';
  }
  qs += '&campus=' + encodeURIComponent(F_CAM.value);
  // Personal mode: TIS p_skyy requires a code (1=中文, 2=英文, 3=双语),
  // not the display name.
  if (MODE === 'personal' && F_LANG.value && LANGUAGE_MAP[F_LANG.value]) {
    qs += '&language=' + encodeURIComponent(LANGUAGE_MAP[F_LANG.value]);
  } else {
    qs += '&language=' + encodeURIComponent(F_LANG.value);
  }
  qs += '&cultivation=' + encodeURIComponent(F_CULT.value);
  qs += '&teacher=' + encodeURIComponent(F_TEACHER.value);
  qs += '&scheduled=' + (F_SCH.checked ? '1' : '0');
  if (MODE === 'personal') {
    qs += '&xkfsdm=' + encodeURIComponent(document.getElementById('f-xkfsdm').value);
    qs += '&ignore_conflicts=' + (document.getElementById('f-ign-conf').checked ? '1' : '');
    qs += '&ignore_zero_capacity=' + (document.getElementById('f-ign-zero').checked ? '1' : '');
    qs += '&weekday=' + encodeURIComponent(document.getElementById('f-wday').value);
    qs += '&period_start=' + encodeURIComponent(document.getElementById('f-ps').value);
    qs += '&period_end=' + encodeURIComponent(document.getElementById('f-pe').value);
  }

  if (!isInitialLoad) {
    RESULTS.innerHTML = '<div class="loading">Searching…</div>';
  }

  return getJSON('/api/tis/courses' + qs).then(function(d) {
    if (loadId !== _modeLoadId) return;  // stale — a newer loadForMode call
    if (d.error) {
      RESULTS.innerHTML = '<div class="flash err">' + escapeHtml(d.error) + '</div><div class="empty">Check TIS credentials or try refreshing the catalog.</div>';
      CAT = [];
      return;
    }
    if (d.mode === 'personal') {
      CAT = d.courses || [];
      ALL_CAT = CAT.slice();
      // Populate type dropdown from API response if course_types available
      if (d.course_types && d.course_types.length) {
        populateCourseTypes(d.course_types, d.current_type);
      }
      // Round info for the bid panel — embedded in the same response,
      // so we do not need a second TIS call.
      if (d.round && d.round.xkfsdm) {
        ROUND_INFO = {
          ok: !!d.ok,
          jffs: Number(d.round.jffs) || 0,
          ksrq: d.round.ksrq || '',
          jsrq: d.round.jsrq || '',
          lcmc: d.round.lcmc || '',
          xkfsdm: d.round.xkfsdm || '',
          xkms: d.round.xkms || '',
          message: d.message || '',
        };
      }
      // Existing bids from TIS (so addPicked() can default to them for
      // already-enrolled/cart picks instead of starting from 1). TIS puts
      // the bid on the `xkxs` field of each yxkcList/xkgwcList item.
      EXISTING_BIDS = {};
      var _ingestBidItems = function(items) {
        for (var i = 0; i < items.length; i++) {
          if (items[i] && items[i].rwh && items[i].xkxs != null) {
            EXISTING_BIDS[items[i].rwh] = Number(items[i].xkxs) || 1;
          }
        }
      };
      _ingestBidItems(d.enrolled || []);
      _ingestBidItems(d.cart || []);
      var msg = d.message || '';
      if (!d.ok) {
        STAT.textContent = 'Selection: ' + (msg || 'unavailable');
        RESULTS.innerHTML = '<div class="empty">' + escapeHtml(msg || 'Course selection system not available (period may be closed).') + '</div>';
        renderBidPanel();
        return;
      }
      STAT.textContent = 'Selection: ' + d.total + ' course(s) available' + (msg ? ' · ' + msg : '');
      renderBidPanel();
    } else {
      CAT = d.courses || [];
      ALL_CAT = CAT.slice();
      STAT.textContent = 'Catalog: ' + (d.count || CAT.length) + ' course(s)';
    }
    if (!CAT.length) {
      RESULTS.innerHTML = '<div class="empty">No courses found matching the filters.</div>';
      return;
    }
    renderResults(CAT);
    renderFilterPills();
  })['catch'](function(e) {
    if (loadId !== _modeLoadId) return;  // stale
    RESULTS.innerHTML = '<div class="flash err">Network error: ' + escapeHtml(e.message) + '</div>';
    CAT = [];
  });
}

function filterResultsClientSide() {
  var kw = KW.value.trim().toLowerCase();
  var college = F_COL.value;
  var taskType = F_TASK.value;
  var category = F_CAT.value;
  var campus = F_CAM.value;
  var language = F_LANG.value;
  var cult = F_CULT.value;
  var teacher = F_TEACHER.value.trim().toLowerCase();
  var onlySched = F_SCH.checked;

  var filtered = ALL_CAT.filter(function(c) {
    if (college && c.college !== college) return false;
    if (taskType && c.task_type !== taskType) return false;
    if (category && c.category !== category) return false;
    if (campus && c.campus !== campus) return false;
    if (language && c.language !== language) return false;
    if (cult && c.cultivation !== cult) return false;
    if (onlySched && (!c.slots || !c.slots.length)) return false;
    if (teacher) {
      var t = (c.teachers || []).join(' ').toLowerCase();
      if (t.indexOf(teacher) === -1) return false;
    }
    if (kw) {
      var name = (c.name || '').toLowerCase();
      var code = (c.code || '').toLowerCase();
      var teachers = (c.teachers || []).join(' ').toLowerCase();
      if (name.indexOf(kw) === -1 && code.indexOf(kw) === -1 && teachers.indexOf(kw) === -1) {
        return false;
      }
    }
    return true;
  });

  CAT = filtered;
  STAT.textContent = 'Catalog: ' + ALL_CAT.length + ' course(s)' + (filtered.length < ALL_CAT.length ? ' (showing ' + filtered.length + ')' : '');
  if (!CAT.length) {
    RESULTS.innerHTML = '<div class="empty">No courses match the current filters.</div>';
    return;
  }
  renderResults(CAT);
}

// Hydrate every "View course page" link on the page with the nces_id
// from BRIEF_CACHE if a matching (code, teacher) entry exists. Called
// after renderResults() so users see upgraded URLs even before hovering
// (the BRIEF_CACHE survives within a session — it persists across
// filter changes, picked toggles, and any other re-render).
function hydrateViewCourseLinks() {
  document.querySelectorAll('.view-course-link').forEach(function(a) {
    if (a.dataset.viewCode === undefined) return;
    var teacher = a.dataset.viewTeacher || '';
    var cacheKey = a.dataset.viewCode + '::' + teacher;
    var cached = BRIEF_CACHE[cacheKey];
    if (cached && cached.available && cached.nces_id) {
      a.href = 'https://ncesnext.com/course/' + cached.nces_id + '/';
      a.title = 'Open NCES page for ' + a.dataset.viewCode + ' (id ' + cached.nces_id + ')';
    }
  });
}

// Hydrate every mini-card's NCES rating from BRIEF_CACHE. Same rationale
// as hydrateViewCourseLinks — re-renders (filter, pick toggle, etc.)
// should restore the rating immediately if the user already hovered over
// that card in this session. Load is already live (renderLoadBadge reads
// LOAD_BY_RWH every render), so we only need to fill the rating here.
function hydrateMiniCards() {
  document.querySelectorAll('.mini-card').forEach(function(m) {
    if (m.dataset.miniCode === undefined) return;
    var teacher = m.dataset.miniTeacher || '';
    var cacheKey = m.dataset.miniCode + '::' + teacher;
    var cached = BRIEF_CACHE[cacheKey];
    if (cached && cached.available && (cached.rating || cached.rating === 0)) {
      var valEl = m.querySelector('.mc-rating .mc-val');
      if (valEl) {
        valEl.textContent = cached.rating.toFixed(1) + '/10';
        var reviews = cached.review_count || 0;
        m.querySelector('.mc-rating').title =
          'NCES rating: ' + cached.rating.toFixed(1) + '/10 · ' + reviews + ' review' + (reviews === 1 ? '' : 's');
      }
    }
  });
}

function renderResults(courses) {
  RESULTS.innerHTML = '';
  // Sticky results header — shows "Select all" + count, plus a small
  // "N / M picked" indicator so the user knows what's selected without
  // scrolling to the right panel.
  var header = document.getElementById('results-header');
  var countEl = document.getElementById('results-count');
  if (header) {
    header.style.display = courses.length ? 'flex' : 'none';
  }
  if (countEl) {
    var pickedHere = 0;
    for (var pi = 0; pi < courses.length; pi++) {
      if (PICKED[courses[pi].rwh]) pickedHere++;
    }
    countEl.textContent = pickedHere + ' / ' + courses.length + ' picked';
  }
  for (var i = 0; i < courses.length; i++) {
    RESULTS.appendChild(renderCard(courses[i]));
  }
  // After every render: upgrade any "View course page" links whose
  // (code, teacher) match the BRIEF_CACHE. Cheap DOM walk; gives the
  // user the direct /course/<nces_id>/ URL immediately on page reload
  // if they had hovered over those cards in this session.
  hydrateViewCourseLinks();
  // Same idea for the inline NCES rating badge on each card's mini-card —
  // fill the placeholder dash with the cached rating if available.
  hydrateMiniCards();
  // Wire up the "Select all" header checkbox. Wire-once, since the
  // header element survives re-renders of the results list.
  var sel = document.getElementById('select-all-check');
  if (sel && !sel.dataset.wired) {
    sel.dataset.wired = '1';
    sel.addEventListener('change', function() {
      // Iterate the current CAT (already-filtered results). Tick or untick
      // each visible course in place. Per-card checkbox state updates via
      // renderResults at the end.
      var want = sel.checked;
      for (var i = 0; i < CAT.length; i++) {
        var c = CAT[i];
        var isPicked = !!PICKED[c.rwh];
        if (want && !isPicked) addPicked(c);
        else if (!want && isPicked) removePicked(c.rwh);
      }
    });
  }
  // Re-sync the Select-all checkbox to reflect current PICKED state.
  // Three states: all checked / some checked (indeterminate) / none checked.
  if (sel && courses.length) {
    var allPicked = true;
    var somePicked = false;
    for (var ri = 0; ri < courses.length; ri++) {
      if (PICKED[courses[ri].rwh]) somePicked = true;
      else allPicked = false;
    }
    sel.checked = allPicked;
    sel.indeterminate = !allPicked && somePicked;
  } else if (sel) {
    sel.checked = false;
    sel.indeterminate = false;
  }
}

function escapeHtml(s) {
  if (s == null) return '';
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\"/g,'&quot;');
}

// rerenderAllWithLoad: re-render every surface that shows a load badge
// after LOAD_BY_RWH changes (button click, cache hydrate, etc.). We
// touch only the surfaces that carry course data — search results,
// picked list, compare pane — so other UI is undisturbed.
function rerenderAllWithLoad() {
  // Search results (step 1) — CAT is module-scoped; renderResults(CAT)
  // is the canonical pattern used after every search (see lines 631,
  // 1749, 2952).
  if (typeof renderResults === 'function' && typeof CAT !== 'undefined') {
    try { renderResults(CAT); } catch (e) { /* CAT may be empty during init */ }
  }
  // Picked list (right column)
  if (typeof renderPicked === 'function') {
    try { renderPicked(); } catch (e) {}
  }
  // Compare pane (step 4) — cards show load on each section
  if (typeof renderComparePane === 'function') {
    try { renderComparePane(); } catch (e) {}
  }
}

// renderLoadBadge: build the "[N] / [M]" load badge for a course card.
//   c = course dict (must have rwh; capacity is optional)
//   N (current load) is looked up from LOAD_BY_RWH (set by Refresh load button)
//   M (capacity) is shown in darker theme color when known, muted otherwise.
// Returns "" if neither N nor M is available (old-style cards stay clean).
// Style: N in accent blue (#5b9dff), M in a slightly darker variant (#3a7ad9).
function renderLoadBadge(c) {
  var cap = c.capacity;
  var n = LOAD_BY_RWH[c.rwh];
  // Use the API-provided enrolled count as a baseline so the badge
  // shows something the moment a search response arrives (before the
  // user clicks Refresh load). User-provided counts always win.
  if (n == null && typeof c.enrolled === 'number') n = c.enrolled;
  var hasN = (n != null);
  var hasM = (cap != null && cap > 0);
  if (!hasN && !hasM) return '';
  var nHtml = hasN
    ? '<b style="color:var(--accent);font-weight:600">' + n + '</b>'
    : '<span style="color:var(--mut)" title="Click 🔄 Refresh load to fetch live count">?</span>';
  var mHtml = hasM
    ? '<b style="color:#3a7ad9;font-weight:600">' + cap + '</b>'
    : '<span style="color:var(--mut)">?</span>';
  return '<span class="load-badge" title="Selected / Capacity (live)">' +
    nHtml + ' / ' + mHtml +
    '</span>';
}

function renderCard(c) {
  var card = document.createElement('div');
  card.className = 'c-card';
  card.dataset.rwh = c.rwh;
  if (c.rwh === ACTIVE_RWH) card.classList.add('active');

  var schedStr = c.schedule || formatSchedule(c.slots);
  var schedHTML = c.slots && c.slots.length ? formatScheduleHTML(c.slots) : '';
  var teachers = c.teachers && c.teachers.length ? c.teachers.join(', ') : 'TBD';
  var hasRealTeacher = c.teachers && c.teachers.length > 0;

  card.innerHTML =
    '<div class="top">' +
      // Per-card checkbox — the user ticks the boxes they want, then hits
      // "Select all" in the results header to flip every visible card.
      // Larger hit-target than the old "+ Pick" ghost button.
      '<label class="pick-check-label" title="Add/remove from your selection">' +
        '<input type="checkbox" class="pick-check" data-rwh="' + escapeHtml(c.rwh) + '"' +
        (PICKED[c.rwh] ? ' checked' : '') + ' />' +
      '</label>' +
      '<span class="code">' + escapeHtml(c.code) + '</span>' +
      '<span class="nm">' + escapeHtml(c.name || c.name_en || '') + '</span>' +
      (c.class_group ? '<span class="grp">' + escapeHtml(c.class_group) + '</span>' : '') +
      // Small mini-card pinned to the right of the title row. Shows:
      //   - NCES rating (⭐ X.X/10) — placeholder dash before briefFetch
      //     populates BRIEF_CACHE; hydrated from cache on re-render.
      //   - TIS load ([N]/[M]) — current/capacity, always live.
      // Kept compact so it doesn't push the schedule/meta down on long
      // course lists. data-nces-code + data-nces-teacher let briefFetch
      // and the hydrate pass target just this card.
      '<span class="mini-card" data-mini-code="' + escapeHtml(c.code) + '" ' +
        'data-mini-teacher="' + escapeHtml((c.teachers || []).join(',')) + '">' +
        '<span class="mc-rating" title="NCES rating (hover to load)">⭐<span class="mc-val">—</span></span>' +
        '<span class="mc-load" title="TIS enrollment — current / capacity">' +
          (renderLoadBadge(c) || '<span class="mc-val mc-muted">Load?</span>') +
        '</span>' +
      '</span>' +
    '</div>' +
    (c.section_name && c.section_name !== c.name
      ? '<div class="sect">' + escapeHtml(c.section_name) + (c.section_name_en ? ' <span class="sect-en">' + escapeHtml(c.section_name_en) + '</span>' : '') + '</div>'
      : '') +
    '<div class="meta">' +
      (hasRealTeacher ? '<b>Teacher</b> ' + escapeHtml(teachers) : '<span style="color:var(--mut)"><b>Teacher</b> TBD</span>') +
      (c.credits ? ' · <b>Credits</b> ' + c.credits : '') +
      // TIS load is now in the title-row mini-card (.mc-load) so it sits
      // next to the NCES rating where the user can scan both at once.
    '</div>' +
    (schedHTML ? '<div class="sched"><span class="sched-lbl">Schedule</span>' + schedHTML + '</div>' : '') +
    (c.code ? '<div class="nces-link">' +
      '<a href="https://ncesnext.com/search?q=' + encodeURIComponent(c.code) + '" target="_blank" rel="noopener">Compare in NCES ↗</a>' +
      // Direct course page (e.g. /course/123/) — opens the specific section
      // the card represents, not the multi-section search. Falls back to
      // the search URL until the brief cache hydrates with the nces_id.
      // briefFetch() updates the href on every matching card once the
      // nces_id is known. data-code + data-teacher uniquely identify the
      // (code, teacher) pair that briefFetch keyed the lookup by.
      '<a class="view-course-link" data-view-code="' + escapeHtml(c.code) + '" ' +
        'data-view-teacher="' + escapeHtml((c.teachers || []).join(',')) + '" ' +
        'href="https://ncesnext.com/search?q=' + encodeURIComponent(c.code) + '" ' +
        'target="_blank" rel="noopener" title="Open the NCES detail page for this section">View course page ↗</a>' +
    '</div>' : '');

  card.addEventListener('click', function(e) {
    if (e.target.closest('a')) return;  // NCES link
    if (e.target.closest('.pick-check')) return;  // checkbox handles itself
    // Bare-card click → open the NCES detail modal for this course.
    // Unpick via the checkbox on the card.
    openCourseNcesModal(c.rwh);
  });

  var check = card.querySelector('.pick-check');
  if (check) {
    check.addEventListener('change', function(e) {
      e.stopPropagation();
      if (check.checked) {
        addPicked(c);
      } else {
        removePicked(c.rwh);
      }
    });
  }

  // Hover preview — NCES ratings + dimensions + reviews
  var nm = card.querySelector('.nm');
  if (nm) {
    nm.addEventListener('mouseenter', function(e) { briefShow(c, e); });
    nm.addEventListener('mouseleave', function() { briefHide(); });
  }

  return card;
}

// ── Filter pills ──────────────────────────────────────────────────────────
function renderFilterPills() {
  var pills = [];
  var clearAll = false;

  function addPill(label, value) {
    if (!value) return;
    clearAll = true;
    pills.push('<span class="filter-pill" data-filter="' + escapeHtml(label) + '">' +
               escapeHtml(value) + '<span class="fp-x">✕</span></span>');
  }

  addPill('keyword', KW.value.trim());
  var fNames = {
    'f-college': 'College',
    'f-tasktype': 'Type',
    'f-cat': 'Category',
    'f-campus': 'Campus',
    'f-lang': 'Language',
    'f-cult': 'Level',
    'f-teacher': 'Teacher',
    'f-xkfsdm': 'Course Type',
  };
  for (var id in fNames) {
    var el = document.getElementById(id);
    if (el && el.value && el.value !== '') {
      pills.push('<span class="filter-pill" data-filter="' + fNames[id] + '">' +
                 escapeHtml(fNames[id]) + ': ' + escapeHtml(el.value) +
                 '<span class="fp-x">✕</span></span>');
    }
  }
  // Checkboxes
  if (document.getElementById('f-sched') && document.getElementById('f-sched').checked) {
    pills.push('<span class="filter-pill" data-filter="scheduled">Only with schedule<span class="fp-x">✕</span></span>');
  }
  if (MODE === 'personal') {
    var ignConf = document.getElementById('f-ign-conf');
    if (ignConf && ignConf.checked) pills.push('<span class="filter-pill" data-filter="ign-conf">Ignore conflicts<span class="fp-x">✕</span></span>');
    var ignZero = document.getElementById('f-ign-zero');
    if (ignZero && ignZero.checked) pills.push('<span class="filter-pill" data-filter="ign-zero">Ignore zero cap<span class="fp-x">✕</span></span>');
    var wday = document.getElementById('f-wday');
    if (wday && wday.value) pills.push('<span class="filter-pill" data-filter="wday">Day: ' + escapeHtml(wday.value) + '<span class="fp-x">✕</span></span>');
  }

  var container = document.getElementById('filter-pills');
  if (!container) return;
  if (!clearAll) {
    container.innerHTML = '';
    return;
  }
  container.innerHTML = pills.join('') +
    '<span class="filter-pill fp-empty" style="visibility:hidden"></span>';

  // Click handler: clicking ✕ clears that filter and re-searches
  container.querySelectorAll('.filter-pill').forEach(function(pill) {
    pill.addEventListener('click', function(e) {
      if (e.target.closest('.fp-x')) {
        var filter = pill.dataset.filter;
        // Clear the corresponding input
        if (filter === 'keyword') { KW.value = ''; }
        else if (filter === 'College') { F_COL.value = ''; }
        else if (filter === 'Type') { F_TASK.value = ''; }
        else if (filter === 'Category') { F_CAT.value = ''; }
        else if (filter === 'Campus') { F_CAM.value = ''; }
        else if (filter === 'Language') { F_LANG.value = ''; }
        else if (filter === 'Level') { F_CULT.value = ''; }
        else if (filter === 'Teacher') { F_TEACHER.value = ''; }
        else if (filter === 'Course Type') { var ctEl = document.getElementById('f-xkfsdm'); if (ctEl) ctEl.value = ''; }
        else if (filter === 'scheduled') { F_SCH.checked = false; }
        else if (filter === 'ign-conf') { var ie = document.getElementById('f-ign-conf'); if (ie) ie.checked = false; }
        else if (filter === 'ign-zero') { var iz = document.getElementById('f-ign-zero'); if (iz) iz.checked = false; }
        else if (filter && filter.startsWith('Day:')) { var wd = document.getElementById('f-wday'); if (wd) wd.value = ''; }
        loadCourses();
      }
    });
  });
}

// ── Hover brief card (NCES structured) ─────────────────────────────────────
function briefRender(d) {
  if (!d.available) {
    var reason = escapeHtml(d.reason || 'not in NCES index');
    var searchUrl = d.search_url || ('https://ncesnext.com/search?q=' +
                                     encodeURIComponent(d.code || ''));
    return '<div class="bc-empty">' +
             '<div>No NCES data yet</div>' +
             '<div class="bce-detail">' + reason + '</div>' +
             '<div class="bce-detail" style="margin-top:.6rem">' +
               '<a href="' + escapeHtml(searchUrl) + '" target="_blank" rel="noopener" ' +
                  'style="color:var(--accent);text-decoration:none">Search NCES ↗</a>' +
             '</div>' +
           '</div>';
  }
  // Show a teacher-mismatch / no-eval warning right under the name, so
  // the user knows the rating below belongs to a different section
  // (or that the section has no reviews yet) BEFORE they click.
  var warnHtml = '';
  if (d.teacher_mismatch && d.tis_teacher) {
    warnHtml = '<div class="bc-warn">' +
      '⚠ Different teacher — ' + escapeHtml(d.tis_teacher) +
      ' not in NCES; showing ' + escapeHtml(d.teacher || '?') +
      ' (best available)' +
    '</div>';
  } else if ((d.review_count || 0) === 0) {
    warnHtml = '<div class="bc-warn">' +
      '⚠ No evaluations yet — NCES has no reviews for ' +
      escapeHtml(d.code) + (d.teacher ? ' by ' + escapeHtml(d.teacher) : '') +
    '</div>';
  }
  // Display priority: name (top, large) > teacher+class > code (small, muted)
  var html = '<div class="bc-head">' +
    '<div class="bc-name">' + escapeHtml(d.name) + '</div>' +
    warnHtml +
    '<div class="bc-meta">' +
      '<span>' + escapeHtml(d.teacher) + '</span>' +
      (d.semester ? '<span class="bc-sem">· ' + escapeHtml(d.semester) + '</span>' : '') +
      '<span class="bc-code">' + escapeHtml(d.code) + '</span>' +
    '</div>' +
  '</div>' +
  '<div class="bc-rating">' +
    '<span class="bc-score">' + (d.rating || 0).toFixed(1) + '</span>' +
    '<span class="bc-out">/ 10</span>' +
    '<span class="bc-rev">' + (d.review_count || 0) + ' reviews</span>' +
  '</div>' +
  '<div class="bc-dims">';
  var dims = [
    ['Difficulty', d.dimensions.difficulty],
    ['Workload',   d.dimensions.workload],
    ['Grading',    d.dimensions.grading],
    ['Takeaways',  d.dimensions.takeaways],
  ];
  for (var i = 0; i < dims.length; i++) {
    var dim = dims[i][1] || {label: '—', pct: 0};
    var pct = Math.round(dim.pct || 0);
    var isLow = pct < 50;
    html += '<div class="bc-dim-row">' +
      '<span class="bc-dim-name">' + dims[i][0] + '</span>' +
      '<div class="bc-bar"><div class="bc-bar-fill' + (isLow ? ' low' : '') +
        '" style="width:' + pct + '%"></div></div>' +
      '<span class="bc-dim-val">' +
        '<span class="lbl">' + escapeHtml(dim.label || '—') + '</span>' +
        pct + '%' +
      '</span>' +
    '</div>';
  }
  // List teacher's other courses as small chips when there's a mismatch
  // or no eval, so the user knows what reviews ARE available.
  var otherHtml = '';
  if ((d.teacher_mismatch || (d.review_count || 0) === 0) &&
      d.teacher_other && d.teacher_other.length) {
    otherHtml = '<div class="bc-other-h">' + escapeHtml(d.tis_teacher || d.teacher) +
                ' teaches elsewhere:</div>' +
      '<div class="bc-other">' +
        d.teacher_other.map(function(c) {
          return '<div class="bc-other-chip">' +
            '<b>' + escapeHtml(c.code || '') + '</b>' +
            '<span>' + (c.review_count || 0) + ' rev</span>' +
          '</div>';
        }).join('') +
      '</div>';
  }
  html += '</div>' + otherHtml +
    '<div class="bc-foot">' +
    '<span class="bc-hint">community-sourced · ' + escapeHtml(d.code) + '</span>' +
    '<a href="' + escapeHtml(d.detail_url) + '" target="_blank" rel="noopener">Full NCES page ↗</a>' +
  '</div>';
  return html;
}

function briefFetch(code, teacher, evt) {
  // Cancel any in-flight request
  if (BRIEF_INFLIGHT && BRIEF_INFLIGHT.abort) BRIEF_INFLIGHT.abort();
  var ctrl = (typeof AbortController !== 'undefined') ? new AbortController() : null;
  if (ctrl) BRIEF_INFLIGHT = ctrl;
  var url = '/api/nces/code/' + encodeURIComponent(code) +
            '?xn=' + encodeURIComponent(currentXn()) +
            '&xq=' + encodeURIComponent(currentXq());
  if (teacher) url += '&teacher=' + encodeURIComponent(teacher);
  fetch(url, ctrl ? { signal: ctrl.signal } : {})
    .then(function(r) { return r.json(); })
    .then(function(d) {
      BRIEF_CACHE[code + '::' + (teacher || '')] = d;
      if (BRIEF_ACTIVE_CODE === code) {
        BRIEF_CARD.innerHTML = briefRender(d);
      }
      // If the brief resolved to a specific NCES section (nces_id
      // present), upgrade every card's "View course page" link for this
      // (code, teacher) pair so it opens /course/<nces_id>/ instead of
      // the generic /search?q=<code>/ fallback. Done via DOM walk on
      // data-view-code / data-view-teacher rather than re-rendering the
      // entire results list — keeps the cost of one hover negligible.
      if (d && d.available && d.nces_id) {
        document.querySelectorAll('.view-course-link').forEach(function(a) {
          if (a.dataset.viewCode !== code) return;
          if ((a.dataset.viewTeacher || '') !== (teacher || '')) return;
          a.href = 'https://ncesnext.com/course/' + d.nces_id + '/';
          a.title = 'Open NCES page for ' + code + ' (id ' + d.nces_id + ')';
        });
      }
      // Fill in the inline NCES rating badge on every matching mini-card.
      // The rating is the headline number the user wants at-a-glance; it
      // was a "—" placeholder until hover triggered this fetch. The
      // review_count gives context ("how reliable is this number?").
      if (d && d.available && (d.rating || d.rating === 0)) {
        var rating = d.rating;
        var reviews = d.review_count || 0;
        document.querySelectorAll('.mini-card').forEach(function(m) {
          if (m.dataset.miniCode !== code) return;
          if ((m.dataset.miniTeacher || '') !== (teacher || '')) return;
          var valEl = m.querySelector('.mc-rating .mc-val');
          if (valEl) {
            valEl.textContent = rating.toFixed(1) + '/10';
            m.querySelector('.mc-rating').title =
              'NCES rating: ' + rating.toFixed(1) + '/10 · ' + reviews + ' review' + (reviews === 1 ? '' : 's');
          }
        });
      }
    })
    .catch(function(e) {
      if (e.name === 'AbortError') return;
      if (BRIEF_ACTIVE_CODE === code) {
        BRIEF_CARD.innerHTML =
          '<div class="bc-empty">NCES unavailable<div class="bce-detail">' +
            escapeHtml(e.message || 'request failed') +
          '</div></div>';
      }
    });
}

function briefShow(c, evt) {
  if (!c.code) return;
  clearTimeout(BRIEF_HOVER_TIMER);
  BRIEF_HOVER_TIMER = setTimeout(function() {
    BRIEF_ACTIVE_CODE = c.code;
    // Position the card relative to viewport
    var rect = (evt.currentTarget || evt.target).getBoundingClientRect();
    var cardW = 380, cardH = 360;
    var left = rect.right + 8 + window.pageXOffset;
    var top = rect.top + window.pageYOffset;
    // Flip to left if would overflow right edge
    if (left + cardW > window.pageXOffset + window.innerWidth - 8) {
      left = rect.left + window.pageXOffset - cardW - 8;
    }
    // Clamp to viewport bottom + top
    if (top + cardH > window.pageYOffset + window.innerHeight - 8) {
      top = window.pageYOffset + window.innerHeight - cardH;
    }
    if (top < window.pageYOffset + 8) top = window.pageYOffset + 8;
    BRIEF_CARD.style.left = left + 'px';
    BRIEF_CARD.style.top = top + 'px';
    BRIEF_CARD.classList.add('show');
    // Render cached result if any, else fetch. Key the cache by
    // (code, teacher) so the same course under different teachers
    // doesn't share a stale response.
    var teacherStr = (c.teachers || []).join(',');
    var cacheKey = c.code + '::' + teacherStr;
    if (BRIEF_CACHE[cacheKey]) {
      BRIEF_CARD.innerHTML = briefRender(BRIEF_CACHE[cacheKey]);
    } else {
      BRIEF_CARD.innerHTML = '<div class="bc-loading">Loading NCES</div>';
      briefFetch(c.code, teacherStr, evt);
    }
  }, 280);
}

function briefHide() {
  clearTimeout(BRIEF_HOVER_TIMER);
  BRIEF_HOVER_TIMER = setTimeout(function() {
    BRIEF_CARD.classList.remove('show');
    // Don't blank the iframe — keep it loaded so re-hover is instant
  }, 140);
}

// Keep card open when mouse enters it (give user time to scroll iframe)
BRIEF_CARD.addEventListener('mouseenter', function() {
  clearTimeout(BRIEF_HOVER_TIMER);
});
BRIEF_CARD.addEventListener('mouseleave', function() { briefHide(); });

// ── NCES Course Eval tab ─────────────────────────────────────────────────
//
// Three render modes share the same #eval-out div:
//   - browse: paginated course list (default), fetched from /api/nces/browse
//   - detail: one course with full reviews, fetched from /api/nces/course/<id>
//   - brief:  compact view when a TIS card is clicked (3 top reviews only)
//
// State:
var EVAL_PAGE = 1;
var EVAL_PER_PAGE = 30;
var EVAL_SORT = 'rating';        // 'rating' | 'reviews' | 'name'
var EVAL_SEARCH = '';            // current search query
var EVAL_TOTAL_PAGES = 1;
var EVAL_TOTAL = 0;
var EVAL_MODE = 'browse';        // 'browse' | 'detail' | 'brief'
var EVAL_BROWSE_LOADING = null;  // AbortController for in-flight browse request

// DOM refs (resolved at init time — see end of file)
var EVAL_SEARCH_EL, EVAL_SORT_EL, EVAL_PREV_EL, EVAL_NEXT_EL, EVAL_PAGE_INFO_EL;

function selectCourse(rwh) {
  ACTIVE_RWH = rwh;
  var loadId = ++_evalLoadId;
  var cards = RESULTS.querySelectorAll('.c-card');
  for (var i = 0; i < cards.length; i++) {
    cards[i].classList.toggle('active', cards[i].dataset.rwh === rwh);
  }
  var course = null;
  for (var j = 0; j < CAT.length; j++) {
    if (CAT[j].rwh === rwh) { course = CAT[j]; break; }
  }
  if (!course) return;
  EVAL_OUT.innerHTML = '<div class="ncn">Loading NCES evaluation…</div>';
  switchTab('eval');
  fetchEval(course.code, course.teachers && course.teachers.join(','), loadId);
}

// fetchEval: called when a TIS card is clicked. Prefer the full detail
// (which has all reviews) by looking up the NCES id first via the brief
// endpoint; if that succeeds, we have an nces_id and switch to detail.
function fetchEval(code, teacher, loadId) {
  code = String(code || '').trim();
  if (!code) return;
  if (EVAL_CACHE[code]) {
    if (loadId !== undefined && loadId !== _evalLoadId) return;  // stale
    var d = EVAL_CACHE[code];
    routeEvalResponse(d);
    return;
  }
  EVAL_OUT.innerHTML = '<div class="ncn">Loading NCES evaluation…</div>';
  getJSON('/api/nces/code/' + encodeURIComponent(code) +
          '?xn=' + encodeURIComponent(currentXn()) +
          '&xq=' + encodeURIComponent(currentXq()) +
          (teacher ? '&teacher=' + encodeURIComponent(teacher) : ''))
    .then(function(d) {
      if (loadId !== undefined && loadId !== _evalLoadId) return;  // stale
      EVAL_CACHE[code] = d;
      routeEvalResponse(d);
    })['catch'](function(e) {
      if (loadId !== undefined && loadId !== _evalLoadId) return;  // stale
      EVAL_OUT.innerHTML = '<div class="flash err">Error: ' + escapeHtml(e.message) + '</div>';
    });
}

// Decide what to show when a TIS card is clicked:
//   - exact match with reviews  → full detail page
//   - mismatch / no-eval / no data → pick screen (let user choose)
function routeEvalResponse(d) {
  if (!d.available) { renderEvalNotFound(d); return; }
  if (d.teacher_mismatch) { renderEvalPick(d, 'mismatch'); return; }
  if ((d.review_count || 0) === 0 && d.tis_teacher) {
    renderEvalPick(d, 'no-eval'); return;
  }
  if (d.nces_id) { renderEvalDetail(d.nces_id); return; }
  renderEvalNotFound(d);
}

function renderEvalNotFound(d) {
  EVAL_OUT.dataset.mode = 'notfound';
  EVAL_OUT.innerHTML = '<div class="empty" style="padding:1.5rem">' +
    escapeHtml(d.reason || 'NCES evaluation not available for this course.') + '</div>' +
    (d.search_url ? '<div style="margin:.6rem 1.5rem"><a href="' + escapeHtml(d.search_url) +
      '" target="_blank" rel="noopener">Search NCES ↗</a></div>' : '');
}

// ── Browse list (default view) ───────────────────────────────────────────
function renderEvalBrowse() {
  EVAL_MODE = 'browse';
  if (EVAL_OUT.dataset.mode === 'browse' && !EVAL_OUT.innerHTML) {
    // first load
  }
  EVAL_OUT.dataset.mode = 'browse';
  // Cancel any in-flight request
  if (EVAL_BROWSE_LOADING && EVAL_BROWSE_LOADING.abort) EVAL_BROWSE_LOADING.abort();
  EVAL_BROWSE_LOADING = (typeof AbortController !== 'undefined') ? new AbortController() : null;

  EVAL_OUT.innerHTML = '<div class="ncn" style="padding:1rem">Loading NCES courses…</div>';
  var url;
  if (EVAL_SEARCH) {
    url = '/api/nces/search?q=' + encodeURIComponent(EVAL_SEARCH);
  } else {
    url = '/api/nces/browse?page=' + EVAL_PAGE + '&per_page=' + EVAL_PER_PAGE + '&sort=' + EVAL_SORT;
  }
  var fetchOpts = EVAL_BROWSE_LOADING ? { signal: EVAL_BROWSE_LOADING.signal } : {};
  fetch(url, fetchOpts).then(function(r) {
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return r.json();
  }).then(function(d) {
    EVAL_TOTAL = d.total || 0;
    EVAL_TOTAL_PAGES = d.pages || Math.ceil(d.total / EVAL_PER_PAGE) || 1;
    var items = d.items || [];
    if (EVAL_SEARCH) {
      // search returns no pages info; recompute
      EVAL_TOTAL_PAGES = 1; EVAL_PAGE = 1;
    }
    var html = '<div class="eval-list">';
    if (d.error) {
      // Upstream NCES API is down (e.g. consolidated /api/v1/courses → 404).
      // Surface a plain-English message + the per-card "Compare in NCES"
      // fallback so the user knows what's wrong and what still works.
      // The raw backend error string is kept as a tooltip for debugging.
      html += '<div class="empty" style="padding:1.5rem;text-align:center;color:var(--warn)">' +
        '<div style="font-size:.9rem;margin-bottom:.4rem">⚠ NCES browse is temporarily unavailable.</div>' +
        '<div style="font-size:.74rem;color:var(--mut)">The community eval database is not responding right now. ' +
        'Course search and picking still work — to read reviews for a specific course, ' +
        'click the "Compare in NCES ↗" link on any course card, or open the course detail ' +
        'in a new tab.</div>' +
        '<div style="font-size:.65rem;color:var(--mut);margin-top:.5rem" title="' + escapeHtml(d.error) + '">Backend: ' + escapeHtml(d.error) + '</div>' +
        '</div>';
    } else if (!items.length) {
      html += '<div class="empty" style="padding:1.5rem;text-align:center">No courses found.</div>';
    } else {
      for (var i = 0; i < items.length; i++) {
        html += renderEvalBrowseCard(items[i]);
      }
    }
    html += '</div>';
    EVAL_OUT.innerHTML = html;
    updateEvalPager();
    // wire up card clicks
    var cards = EVAL_OUT.querySelectorAll('.eval-browse-card');
    for (var k = 0; k < cards.length; k++) {
      cards[k].addEventListener('click', function(e) {
        var id = parseInt(this.dataset.ncesId, 10);
        if (id) renderEvalDetail(id);
      });
    }
  })['catch'](function(e) {
    if (e.name === 'AbortError') return;
    EVAL_OUT.innerHTML = '<div class="flash err">Error: ' + escapeHtml(e.message) + '</div>';
  });
}

function renderEvalBrowseCard(c) {
  var rating = (c.rate_average != null) ? Number(c.rate_average).toFixed(2) : '—';
  var reviews = c.review_count || 0;
  var teachers = c.teacher_names || '';
  var terms = (c.term_ids || []).map(_termIdToDisplay).join(', ');
  return '<div class="eval-browse-card" data-nces-id="' + (c.id || '') + '">' +
    '<div class="ev-top">' +
      '<span class="ev-code">' + escapeHtml(c.course_code || '') + '</span>' +
      '<span class="ev-name">' + escapeHtml(c.name || '') + '</span>' +
      '<span class="ev-rating">' + rating + '<span class="ev-out">/10</span></span>' +
      '<span class="ev-reviews">' + reviews + ' reviews</span>' +
    '</div>' +
    (teachers ? '<div class="ev-meta"><b>Teacher</b> ' + escapeHtml(teachers) + '</div>' : '') +
    (terms ? '<div class="ev-meta"><b>Terms</b> ' + escapeHtml(terms) + '</div>' : '<div class="ev-empty">no term data</div>') +
  '</div>';
}

function updateEvalPager() {
  if (!EVAL_PAGE_INFO_EL) return;
  var total = EVAL_TOTAL.toLocaleString();
  var info = EVAL_SEARCH
    ? total + ' results'
    : 'Page ' + EVAL_PAGE + ' / ' + EVAL_TOTAL_PAGES + ' (' + total + ' courses)';
  EVAL_PAGE_INFO_EL.textContent = info;
  if (EVAL_PREV_EL) EVAL_PREV_EL.disabled = EVAL_PAGE <= 1;
  if (EVAL_NEXT_EL) EVAL_NEXT_EL.disabled = EVAL_PAGE >= EVAL_TOTAL_PAGES;
}

function _termIdToDisplay(term_id) {
  // Reuse the scraper-side logic — kept inline so we don't depend on the
  // module for tiny display strings. Format: "20252" → "2025春"
  if (!term_id || term_id.length < 5) return term_id || '';
  var season = {'1': '秋', '2': '春', '3': '夏'}[term_id[4]] || '';
  return term_id.slice(0, 4) + season;
}

// ── Detail view (one course, full reviews) ───────────────────────────────
function renderEvalDetail(nces_id) {
  EVAL_MODE = 'detail';
  EVAL_OUT.dataset.mode = 'detail';
  var loadId = _evalLoadId;
  EVAL_OUT.innerHTML = '<div class="ncn" style="padding:1rem">Loading course detail…</div>';
  getJSON('/api/nces/course/' + nces_id).then(function(d) {
    if (loadId !== _evalLoadId) return;  // stale — user already clicked another course
    if (!d.available) {
      EVAL_OUT.innerHTML = '<div class="empty" style="padding:1.5rem">' +
        escapeHtml(d.reason || 'Course not found in NCES') + '</div>';
      return;
    }
    EVAL_OUT.innerHTML = renderEvalDetailCard(d);
    var back = document.getElementById('eval-back');
    if (back) back.addEventListener('click', renderEvalBrowse);
  })['catch'](function(e) {
    EVAL_OUT.innerHTML = '<div class="flash err">Error: ' + escapeHtml(e.message) + '</div>';
  });
}

function renderEvalDetailCard(d) {
  var rating = (d.rating || 0).toFixed(2);
  var semesters = (d.semesters || []).join(', ') || '—';
  var dims = d.dimensions || {};
  var dimNames = [['Difficulty', 'difficulty'], ['Workload', 'workload'],
                  ['Grading', 'grading'], ['Takeaways', 'takeaways']];
  var dimHtml = '<div class="eval-dims">';
  for (var i = 0; i < dimNames.length; i++) {
    var key = dimNames[i][1];
    var dim = dims[key] || {label: '—', pct: 0};
    var pct = Math.round(dim.pct || 0);
    var isLow = pct < 50;
    dimHtml += '<div class="eval-dim-row">' +
      '<span class="ed-name-lbl">' + dimNames[i][0] + '</span>' +
      '<div class="ed-bar"><div class="ed-bar-fill' + (isLow ? ' low' : '') +
        '" style="width:' + pct + '%"></div></div>' +
      '<span class="ed-val">' +
        '<span class="lbl">' + escapeHtml(dim.label || '—') + '</span>' +
        pct + '%' +
      '</span>' +
    '</div>';
  }
  dimHtml += '</div>';

  var reviews = d.reviews || [];
  var reviewsHtml = '';
  if (reviews.length) {
    reviewsHtml = '<div class="eval-reviews-h">All Reviews (' + reviews.length + ')</div>';
    for (var j = 0; j < reviews.length; j++) {
      var r = reviews[j];
      var d_html = '';
      var dimKeys = [['difficulty', 'difficulty'], ['workload', 'workload'],
                     ['grading', 'grading'], ['takeaways', 'takeaways']];
      for (var di = 0; di < dimKeys.length; di++) {
        var v = (r.dimensions || {})[dimKeys[di][0]];
        if (v && v !== '—') {
          d_html += '<span><b>' + dimKeys[di][1] + '</b> ' + escapeHtml(v) + '</span>';
        }
      }
      var rate = (typeof r.rate === 'number') ? r.rate : 0;
      var rateHtml = '<span class="ei-rate" title="Individual rating">' +
        rate.toFixed(1) + '<span class="ei-rate-out">/10</span></span>';
      reviewsHtml += '<div class="eval-item">' +
        '<div class="ei-t">' + rateHtml +
          '<span class="ei-author">' + escapeHtml(r.username || 'Anonymous') + '</span>' +
          (r.semester ? ' · <span class="ei-sem">' + escapeHtml(r.semester) + '</span>' : '') +
          (r.likes ? ' · 👍' + r.likes : '') +
        '</div>' +
        (r.text ? '<div class="ei-m">' + escapeHtml(r.text) + '</div>' : '') +
        (d_html ? '<div class="ei-dims">' + d_html + '</div>' : '') +
      '</div>';
    }
  } else {
    // No reviews at all — surface it as a warning so the user knows this
    // section exists in NCES but the community hasn't reviewed it.
    reviewsHtml = '<div class="eval-reviews-h reviews-mismatch-hdr">' +
      '⚠ Exact course match found, but no evaluations yet — ' +
      escapeHtml(d.name || d.code) +
      (d.teacher ? ' by ' + escapeHtml(d.teacher) : '') + ':' +
    '</div>' +
    '<div class="ncn">No written reviews for this course.</div>';
  }

  return '<div class="eval-detail">' +
    '<button class="ghost ed-back" id="eval-back">← Back to browse</button>' +
    '<div class="ed-head">' +
      '<span class="ed-name">' + escapeHtml(d.name || '') + '</span>' +
      '<span class="ed-rating">' + rating + '<span class="ed-out">/10</span></span>' +
      '<span class="ed-reviews">' + (d.review_count || 0) + ' reviews</span>' +
    '</div>' +
    '<div class="ed-meta">' +
      '<span><b>Code</b> ' + escapeHtml(d.code || '') + '</span>' +
      (d.teacher ? '<span><b>Teacher</b> ' + escapeHtml(d.teacher) + '</span>' : '') +
      (d.department ? '<span><b>Dept</b> ' + escapeHtml(d.department) + '</span>' : '') +
      '<span><b>Terms</b> ' + escapeHtml(semesters) + '</span>' +
    '</div>' +
    dimHtml +
    reviewsHtml +
    '<div style="margin-top:1rem"><a href="' + escapeHtml(d.detail_url) +
      '" target="_blank" rel="noopener">Full NCES page ↗</a></div>' +
  '</div>';
}

// ── Pick screen — shown when the TIS section has no exact match in NCES,
// or the matched section has no reviews yet. Asks the user to pick which
// NCES course they want to inspect. Courses are grouped into two
// categories so the user can choose based on what they care about:
//   - "Same teacher on different course" — gauge the teacher via their
//     other taught courses (more useful for course selection)
//   - "Different teacher on same course" — gauge the course via other
//     teachers' sections (more useful for course identity)
function renderEvalPick(d, reason) {
  EVAL_MODE = 'pick';
  EVAL_OUT.dataset.mode = 'pick';

  var sameTeacher = d.teacher_other || [];
  var sameCourse  = d.alternatives || [];

  var hasAny = sameTeacher.length > 0 || sameCourse.length > 0;

  var headerTitle = reason === 'mismatch'
    ? '⚠ No exact course match in NCES'
    : '⚠ No evaluations yet for this section';
  var headerBody = reason === 'mismatch'
    ? 'NCES has no reviews for your teacher <b>' + escapeHtml(d.tis_teacher) +
      '</b> in <b>' + escapeHtml(d.code) + '</b>. Pick which course you want to see:'
    : 'NCES has no reviews for <b>' + escapeHtml(d.code) +
      '</b> by <b>' + escapeHtml(d.tis_teacher) +
      '</b> yet. Pick which course you want to see:';

  // Empty state: nothing to pick. Just show a search-NCES link.
  if (!hasAny) {
    EVAL_OUT.innerHTML = '<div class="eval-detail">' +
      '<button class="ghost ed-back" id="eval-back">← Back to browse</button>' +
      '<div class="eval-detail-body" style="padding:1.2rem">' +
        '<div class="ed-head"><span class="ed-name">No NCES data</span></div>' +
        '<div class="ncn" style="margin-top:.6rem">' +
          'NCES has no reviews for your teacher in this course, and no ' +
          'other courses by your teacher have been reviewed either. ' +
          'You can try searching NCES manually.' +
        '</div>' +
        '<div style="margin-top:1rem"><a href="' +
          escapeHtml(d.search_url || 'https://ncesnext.com/search?q=' +
            encodeURIComponent(d.code || '')) +
          '" target="_blank" rel="noopener" class="ghost">Search NCES ↗</a></div>' +
      '</div>' +
    '</div>';
    var back = document.getElementById('eval-back');
    if (back) back.addEventListener('click', renderEvalBrowse);
    return;
  }

  // Helper: read dimension as [label, pct] pair from either a Course dict
  // (uses .difficulty = ['Easy', 100]) or an alternatives dict (uses
  // .dimensions.difficulty = {label, pct}). Returns ['—', 0] on miss.
  function dimPair(obj, dim) {
    if (!obj) return ['—', 0];
    if (obj[dim]) return obj[dim];                // Course dict shape
    var d = obj.dimensions && obj.dimensions[dim];  // alternatives shape
    if (d) return [d.label || '—', d.pct || 0];
    return ['—', 0];
  }

  // Helper to render a course card button (same shape for both panels).
  function cardHtml(c) {
    var d1 = dimPair(c, 'difficulty');
    var w1 = dimPair(c, 'workload');
    var g1 = dimPair(c, 'grading');
    var t1 = dimPair(c, 'takeaways');
    return '<button class="pick-card" data-nces-id="' + (c.nces_id || '') + '">' +
      '<div class="pc-head">' +
        '<b>' + escapeHtml(c.code || '') + '</b>' +
        '<span>' + escapeHtml(c.name || '') + '</span>' +
      '</div>' +
      '<div class="pc-meta">' +
        '<span class="pc-teacher">' + escapeHtml(c.teacher || '') + '</span>' +
      '</div>' +
      '<div class="pc-rating">' +
        '<span class="pc-score">' + (c.rating || 0).toFixed(1) + '</span>' +
        '<span class="pc-out">/ 10</span>' +
        '<span class="pc-rev">' + (c.review_count || 0) + ' reviews</span>' +
      '</div>' +
      '<div class="pc-dims">' +
        '<span>Difficulty ' + Math.round(d1[1] || 0) + '%</span>' +
        '<span>Workload ' + Math.round(w1[1] || 0) + '%</span>' +
        '<span>Grading ' + Math.round(g1[1] || 0) + '%</span>' +
        '<span>Gain ' + Math.round(t1[1] || 0) + '%</span>' +
      '</div>' +
    '</button>';
  }

  var sameTeacherHtml = sameTeacher.length
    ? '<div class="pick-section">' +
        '<div class="pick-section-h">Same teacher on different course ' +
          '<span class="pick-section-meta">' + sameTeacher.length + ' option' +
          (sameTeacher.length === 1 ? '' : 's') + '</span></div>' +
        '<div class="pick-section-b">' +
          'Useful for gauging what <b>' + escapeHtml(d.tis_teacher) +
          '</b> is like as a teacher based on their other courses.' +
        '</div>' +
        '<div class="pick-grid">' + sameTeacher.map(cardHtml).join('') + '</div>' +
      '</div>'
    : '';

  var sameCourseHtml = sameCourse.length
    ? '<div class="pick-section">' +
        '<div class="pick-section-h">Different teacher on same course ' +
          '<span class="pick-section-meta">' + sameCourse.length + ' option' +
          (sameCourse.length === 1 ? '' : 's') + '</span></div>' +
        '<div class="pick-section-b">' +
          'Useful for gauging <b>' + escapeHtml(d.code) + '</b> as a course ' +
          'by looking at how other teachers teach it.' +
        '</div>' +
        '<div class="pick-grid">' + sameCourse.map(function(a) {
          return cardHtml({
            code: d.code, name: d.name,
            teacher: a.teacher,
            nces_id: a.nces_id,
            rating: a.rating,
            review_count: a.review_count,
            // alternatives now include dimensions (scraper provides them)
            difficulty: dimPair(a, 'difficulty'),
            workload:   dimPair(a, 'workload'),
            grading:    dimPair(a, 'grading'),
            takeaways:  dimPair(a, 'takeaways'),
          });
        }).join('') + '</div>' +
      '</div>'
    : '';

  EVAL_OUT.innerHTML = '<div class="eval-detail">' +
    '<button class="ghost ed-back" id="eval-back">← Back to browse</button>' +
    '<div class="pick-head">' +
      '<div class="pick-head-h">' + headerTitle + '</div>' +
      '<div class="pick-head-b">' + headerBody + '</div>' +
    '</div>' +
    sameTeacherHtml + sameCourseHtml +
  '</div>';

  // Wire up: clicking a card opens that NCES section's full detail.
  var back = document.getElementById('eval-back');
  if (back) back.addEventListener('click', renderEvalBrowse);
  var cards = EVAL_OUT.querySelectorAll('.pick-card');
  for (var i = 0; i < cards.length; i++) {
    cards[i].addEventListener('click', function() {
      var id = parseInt(this.dataset.ncesId, 10);
      if (id) renderEvalDetail(id);
    });
  }
}
function renderEvalBrief(d) {
  EVAL_MODE = 'brief';
  EVAL_OUT.dataset.mode = 'brief';
  if (!d.available) {
    EVAL_OUT.innerHTML = '<div class="empty" style="padding:1.5rem">' +
      escapeHtml(d.reason || 'NCES evaluation not available for this course.') + '</div>' +
      (d.search_url ? '<div style="margin:.6rem 1.5rem"><a href="' + escapeHtml(d.search_url) +
        '" target="_blank" rel="noopener">Search NCES ↗</a></div>' : '');
    return;
  }
  var rating = (d.rating || 0).toFixed(1);
  var dims = d.dimensions || {};
  var dimNames = [['Difficulty', 'difficulty'], ['Workload', 'workload'],
                  ['Grading', 'grading'], ['Takeaways', 'takeaways']];
  var dimHtml = '';
  for (var i = 0; i < dimNames.length; i++) {
    var dim = dims[dimNames[i][1]] || {label: '—', pct: 0};
    var pct = Math.round(dim.pct || 0);
    var isLow = pct < 50;
    dimHtml += '<div class="eval-dim-row">' +
      '<span class="ed-name-lbl">' + dimNames[i][0] + '</span>' +
      '<div class="ed-bar"><div class="ed-bar-fill' + (isLow ? ' low' : '') +
        '" style="width:' + pct + '%"></div></div>' +
      '<span class="ed-val">' +
        '<span class="lbl">' + escapeHtml(dim.label || '—') + '</span>' +
        pct + '%' +
      '</span>' +
    '</div>';
  }
  var excerpts = d.review_excerpts || [];
  // Build a review-area header that tells the user the data below is for
  // a different teacher's section (mismatch) or has no reviews at all
  // (exact match but 0 reviews). Without this, the review list below
  // would be silently misattributed to the user's TIS teacher.
  var reviewsHdr = '';
  if (d.teacher_mismatch && d.tis_teacher) {
    reviewsHdr = '<div class="eval-reviews-h reviews-mismatch-hdr">' +
      '⚠ Valid exact course match not found in NCES — ' +
      escapeHtml(d.name || d.code) +
      ' by other teacher (' + escapeHtml(d.teacher || '?') + '):' +
    '</div>';
  } else if ((d.review_count || 0) === 0 && d.available) {
    reviewsHdr = '<div class="eval-reviews-h reviews-mismatch-hdr">' +
      '⚠ Exact course match found, but no evaluations yet — ' +
      escapeHtml(d.name || d.code) +
      (d.teacher ? ' by ' + escapeHtml(d.teacher) : '') + ':' +
    '</div>';
  }
  var exHtml = excerpts.length
    ? reviewsHdr + excerpts.map(function(r) {
        var rate = (typeof r.rate === 'number') ? r.rate : 0;
        var rateHtml = '<span class="ei-rate" title="Individual rating">' +
          rate.toFixed(1) + '<span class="ei-rate-out">/10</span></span>';
        return '<div class="eval-item">' +
          '<div class="ei-t">' + rateHtml +
            '<span class="ei-author">' + escapeHtml(r.username || 'Anonymous') + '</span>' +
            (r.semester ? ' · <span class="ei-sem">' + escapeHtml(r.semester) + '</span>' : '') +
            (r.likes ? ' · 👍' + r.likes : '') +
          '</div>' +
          (r.excerpt ? '<div class="ei-m">' + escapeHtml(r.excerpt) +
            (r.excerpt.length >= 200 ? '…' : '') + '</div>' : '') +
        '</div>';
      }).join('')
    : reviewsHdr + '<div class="ncn">No written reviews for this course.</div>';

  // Teacher-mismatch banner: when the user clicked a TIS card whose
  // teacher isn't represented in NCES, surface that clearly. Without
  // this, the data below would be silently misattributed to the user's
  // teacher. Also fires when the section exists in NCES but has no
  // reviews yet — show the teacher's other courses so the user can
  // gauge them from somewhere.
  var showFallback = (d.teacher_mismatch && d.tis_teacher) ||
                     ((d.review_count || 0) === 0 && d.available && d.tis_teacher);
  var mismatchHtml = '';
  if (showFallback) {
    // Priority: same teacher on different course (more useful for
    // gauging the teacher) over different teacher on same course.
    var other = d.teacher_other || [];
    var otherHtml = other.length
      ? '<div class="tm-section">' +
          '<div class="tm-section-h">What ' + escapeHtml(d.tis_teacher) +
            ' teaches elsewhere</div>' +
          '<div class="tm-other">' +
            other.map(function(c) {
              var d1 = dimPair(c, 'difficulty');
              var w1 = dimPair(c, 'workload');
              var g1 = dimPair(c, 'grading');
              var t1 = dimPair(c, 'takeaways');
              return '<button class="tm-other-card" data-nces-id="' + (c.nces_id || '') + '">' +
                '<div class="to-head">' +
                  '<b>' + escapeHtml(c.code || '') + '</b>' +
                  '<span>' + escapeHtml(c.name || '') + '</span>' +
                '</div>' +
                '<div class="to-meta">' +
                  '<span class="to-rating">' + (c.rating || 0).toFixed(1) + '/10</span>' +
                  '<span class="to-reviews">' + (c.review_count || 0) + ' reviews</span>' +
                '</div>' +
                '<div class="to-dims">' +
                  '<span>Difficulty ' + Math.round(d1[1] || 0) + '%</span>' +
                  '<span>Workload ' + Math.round(w1[1] || 0) + '%</span>' +
                  '<span>Grading ' + Math.round(g1[1] || 0) + '%</span>' +
                  '<span>Gain ' + Math.round(t1[1] || 0) + '%</span>' +
                '</div>' +
              '</button>';
            }).join('') +
          '</div>' +
        '</div>'
      : '';

    var alts = d.alternatives || [];
    var altHtml = alts.length
      ? '<div class="tm-section">' +
          '<div class="tm-section-h">Other sections of ' + escapeHtml(d.code) + '</div>' +
          '<div class="tm-alts">' +
            alts.map(function(a) {
              return '<button class="tm-alt" data-nces-id="' + (a.nces_id || '') + '">' +
                '<b>' + escapeHtml(a.teacher || '?') + '</b>' +
                (a.rating ? ' · ' + a.rating.toFixed(2) + '/10' : '') +
                (a.review_count ? ' · ' + a.review_count + ' reviews' : '') +
              '</button>';
            }).join('') +
          '</div>' +
        '</div>'
      : '';

    // Title above the alternatives/teacher-other panel differs depending
    // on whether the teacher is wrong or the section has 0 reviews.
    var bannerTitle = d.teacher_mismatch
      ? '⚠ Different teacher'
      : '⚠ No evaluations for this section';
    var bannerBody = d.teacher_mismatch
      ? 'NCES has no reviews for your teacher <b>' + escapeHtml(d.tis_teacher) +
        '</b> in <b>' + escapeHtml(d.code) + '</b>. Showing the highest-rated section instead.'
      : 'NCES has no reviews for <b>' + escapeHtml(d.code) +
        '</b> by <b>' + escapeHtml(d.tis_teacher) +
        '</b> yet. See what they teach elsewhere:';

    mismatchHtml =
      '<div class="teacher-mismatch">' +
        '<div class="tm-h">' + bannerTitle + '</div>' +
        '<div class="tm-b">' + bannerBody + '</div>' +
        otherHtml + altHtml +
      '</div>';
  }

  EVAL_OUT.innerHTML = '<div class="eval-detail">' +
    '<button class="ghost ed-back" id="eval-back">← Back to browse</button>' +
    mismatchHtml +
    '<div class="ed-head">' +
      '<span class="ed-name">' + escapeHtml(d.name || '') + '</span>' +
      '<span class="ed-rating">' + rating + '<span class="ed-out">/10</span></span>' +
      '<span class="ed-reviews">' + (d.review_count || 0) + ' reviews</span>' +
    '</div>' +
    '<div class="ed-meta">' +
      '<span><b>Code</b> ' + escapeHtml(d.code || '') + '</span>' +
      (d.teacher ? '<span><b>Teacher</b> ' + escapeHtml(d.teacher) + '</span>' : '') +
      (d.semester ? '<span><b>Term</b> ' + escapeHtml(d.semester) + '</span>' : '') +
    '</div>' +
    '<div class="eval-dims">' + dimHtml + '</div>' +
    exHtml +
    '<div style="margin-top:1rem"><a href="' + escapeHtml(d.detail_url) +
      '" target="_blank" rel="noopener">Full NCES page ↗</a></div>' +
  '</div>';
  var back = document.getElementById('eval-back');
  if (back) back.addEventListener('click', renderEvalBrowse);
  // Alternatives in the teacher-mismatch banner: clicking one jumps to that
  // NCES section's full detail (it has its own reviews).
  var altBtns = EVAL_OUT.querySelectorAll('.tm-alt');
  for (var ai = 0; ai < altBtns.length; ai++) {
    altBtns[ai].addEventListener('click', function() {
      var id = parseInt(this.dataset.ncesId, 10);
      if (id) renderEvalDetail(id);
    });
  }
  // Teacher's other courses: clicking jumps to that course's detail
  // (useful when the TIS teacher's section has no reviews, but their
  // OTHER courses do — gives the user real review data to look at).
  var otherBtns = EVAL_OUT.querySelectorAll('.tm-other-card');
  for (var oi = 0; oi < otherBtns.length; oi++) {
    otherBtns[oi].addEventListener('click', function() {
      var id = parseInt(this.dataset.ncesId, 10);
      if (id) renderEvalDetail(id);
    });
  }
}

// ── Picked sections ───────────────────────────────────────────────────────

function addPicked(course) {
  PICKED[course.rwh] = JSON.parse(JSON.stringify(course));
  if (!(course.rwh in PICKED_BIDS)) {
    // Default to 0 for new picks (user may be "showing interest"
    // without actually bidding on the section). For picks that
    // already have a bid on TIS (enrolled/cart), keep that value
    // so we don't zero out something the user already paid for.
    PICKED_BIDS[course.rwh] = EXISTING_BIDS[course.rwh] != null
      ? EXISTING_BIDS[course.rwh]
      : 0;
  }
  // Re-render search results so cards reflect the new pick state
  renderResults(CAT);
  renderPicked();
  renderGrid();
  renderGrid3();  // step-3 grid shows picked + enrolled together
  renderBidPanel();
  updateBidStat();
  updateSolveCodes();
  updateExportIcsButton();
  // No localStorage auto-save — picks live in memory until the user
  // explicitly saves/loads a file. See the "Data model" note at the
  // top of the file (DOMContentLoaded section).
}

function removePicked(rwh) {
  delete PICKED[rwh];
  delete PICKED_BIDS[rwh];
  delete PICKED_CONFLICTS[rwh];
  delete PICKED_CHECKED[rwh];  // any tick for bulk-remove is moot now
  // Re-render search results so cards reflect the unpicked state
  renderResults(CAT);
  if (ACTIVE_RWH === rwh) {
    ACTIVE_RWH = null;
  }
  renderPicked();
  renderGrid();
  renderGrid3();  // step-3 grid shows picked + enrolled together
  renderBidPanel();
  updateBidStat();
  updateSolveCodes();
  updateExportIcsButton();
}

function flash(msg, kind) {
  // Brief inline status — non-blocking.
  var el = document.getElementById('flash-zone');
  if (!el) return;
  var div = document.createElement('div');
  div.className = 'flash ' + (kind || 'info');
  div.textContent = msg;
  el.appendChild(div);
  setTimeout(function () { if (div.parentNode) div.parentNode.removeChild(div); }, 2400);
}

function renderPicked() {
  // Display rule: count by UNIQUE course code, sum credits per unique
  // code. Picked sections of the same code (e.g. MA101 taught by three
  // teachers) count as one course for credit purposes — the user is
  // enrolling in MA101 once, not three times.
  var keys = Object.keys(PICKED);
  var codeCredits = {};   // { code: credits_int }
  var totalCredits = 0;
  for (var i = 0; i < keys.length; i++) {
    var c = PICKED[keys[i]];
    var code = c.code;
    if (!(code in codeCredits)) {
      codeCredits[code] = parseFloat(c.credits) || 0;
      totalCredits += codeCredits[code];
    }
  }
  PICK_STAT.textContent = keys.length + ' sections · ' +
    Object.keys(codeCredits).length + ' courses · ' +
    totalCredits.toFixed(1) + ' Credits';
  // The action buttons (Save, Load, Drop-all, Remove-selected, Select-all)
  // are built once by initPickedActions() in DOMContentLoaded. Per-render
  // updates: the Save button label + the Select-all header count need to
  // stay in sync with the current PICKED size.
  updatePickedActionsState();

  if (!keys.length) {
    // Page is blank until the user loads a file. Make the empty state
    // useful — show a hint pointing at the Load button + drag-drop.
    PICK_LIST.innerHTML = '<div class="loading" style="padding:1rem .7rem;line-height:1.5">' +
      '<div style="font-size:.85rem;color:var(--txt);margin-bottom:.3rem">No picks loaded</div>' +
      '<div style="font-size:.72rem;color:var(--mut)">Click <b>📂 Load file</b> above, or drag a <code>.json</code> onto the page.</div>' +
      '</div>';
    return;
  }

  PICK_LIST.innerHTML = '';
  for (var j = 0; j < keys.length; j++) {
    PICK_LIST.appendChild(renderPickItem(PICKED[keys[j]]));
  }
  updateSolveCodes();
}

function renderPickItem(c) {
  var div = document.createElement('div');
  div.className = 'pick';
  div.dataset.rwh = c.rwh;
  // Drag-to-reorder support. The picked list doubles as the priority
  // list for the solver, so reordering items = reprioritising courses
  // (like SUSTech_AutoScheduler). The drag handle is the whole item,
  // but right-click is reserved for the un-pick badge.
  div.draggable = true;

  var enrolled = ENROLLED_RWH.has(c.rwh);
  var schedHTML = c.slots && c.slots.length ? formatScheduleHTML(c.slots) : '';
  var teachers = c.teachers && c.teachers.length ? escapeHtml(c.teachers.join(', ')) : '<span style="color:var(--mut)">TBD</span>';

  // Check if this picked course conflicts with any other picked course.
  // When TIS-enrolled is "unquestionable" (IGNORE_TIS_ENROLLED off), an
  // enrolled rwh doesn't get the "conflicts with X" badge — it wins,
  // so the warning would be confusing.
  var conflictMsg = '';
  var keys = Object.keys(PICKED);
  var slotsA = c.slots || [];
  for (var pi = 0; pi < keys.length; pi++) {
    if (PICKED[keys[pi]].rwh === c.rwh) continue;
    if (!IGNORE_TIS_ENROLLED && enrolled) break;  // enrolled wins, skip
    if (!IGNORE_TIS_ENROLLED && ENROLLED_RWH.has(keys[pi])) continue;  // the other side is enrolled — we still conflict, not it
    var slotsB = PICKED[keys[pi]].slots || [];
    if (sectionsConflict(slotsA, slotsB)) {
      conflictMsg = ' ⚠ conflicts with ' + escapeHtml(PICKED[keys[pi]].code);
      break;
    }
  }

  div.innerHTML =
    '<label class="picked-check-wrap" title="Tick to mark for bulk remove">' +
      '<input type="checkbox" class="picked-check" data-rwh="' + escapeHtml(c.rwh) + '"' +
        (PICKED_CHECKED[c.rwh] ? ' checked' : '') + '>' +
    '</label>' +
    '<div class="pick-body">' +
      '<div class="pn">' + escapeHtml(c.name || c.name_en || '') +
        (enrolled ? '<span class="pick-enrolled">enrolled</span>' : '') +
        (conflictMsg ? '<span style="float:right;color:var(--bad);font-size:.65rem">⚠ conflicted</span>' : '') +
      '</div>' +
      (c.section_name && c.section_name !== c.name
        ? '<div class="pm" style="margin-top:.15rem">' + escapeHtml(c.section_name) + '</div>'
        : '') +
      '<div class="pm">' +
        '<b>Teacher</b> ' + teachers +
        ' · <b>' + escapeHtml(c.code) + '</b>' +
        (c.class_group ? ' · ' + escapeHtml(c.class_group) : '') +
        (schedHTML ? ' · ' + schedHTML : '') +
        (renderLoadBadge(c) ? ' · ' + renderLoadBadge(c) : '') +
        (conflictMsg ? '<br><span style="color:var(--bad);font-size:.68rem">' + conflictMsg + '</span>' : '') +
      '</div>' +
    '</div>';

  // Per-card checkbox — toggles the PICKED_CHECKED set. The label wrapper
  // captures the click; the checkbox state itself drives the visual.
  var cb = div.querySelector('.picked-check');
  cb.addEventListener('change', function() {
    if (cb.checked) PICKED_CHECKED[c.rwh] = true;
    else delete PICKED_CHECKED[c.rwh];
    updatePickedActionsState();
  });
  // Prevent checkbox clicks from starting a drag (drag-to-reorder is on
  // the whole card; the checkbox must not initiate it).
  cb.addEventListener('mousedown', function(e) { e.stopPropagation(); });
  cb.addEventListener('dragstart', function(e) { e.preventDefault(); });

  return div;
}

// ── Drag-to-reorder picked list (priority for the solver) ───────────────
// PICKED is { rwh: course }. JS object key order is preserved since ES2015
// (insertion order for string keys, integer-like keys first). So moving
// rwh X to position N = remove X from PICKED, re-insert at the right
// iteration, re-render. Same approach as c.x-d.fun's priority drag.

function attachPickedDragHandlers() {
  if (PICK_LIST._dragWired === '1') return;
  PICK_LIST._dragWired = '1';

  PICK_LIST.addEventListener('dragstart', function(e) {
    var item = e.target.closest('.pick');
    if (!item) return;
    PICK_LIST._draggingRwh = item.dataset.rwh;
    item.classList.add('dragging');
    e.dataTransfer.effectAllowed = 'move';
    // dataTransfer must have data for Firefox to allow the drag
    e.dataTransfer.setData('text/plain', item.dataset.rwh);
  });
  PICK_LIST.addEventListener('dragend', function() {
    PICK_LIST._draggingRwh = null;
    var dragging = PICK_LIST.querySelector('.dragging');
    if (dragging) dragging.classList.remove('dragging');
    // Clear any leftover over indicators
    var overs = PICK_LIST.querySelectorAll('.drag-over');
    overs.forEach(function(el) { el.classList.remove('drag-over'); });
  });
  PICK_LIST.addEventListener('dragover', function(e) {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    var item = e.target.closest('.pick');
    if (!item || item.dataset.rwh === PICK_LIST._draggingRwh) return;
    // Mark where the drop will land (above or below the hovered item)
    var rect = item.getBoundingClientRect();
    var above = (e.clientY - rect.top) < rect.height / 2;
    item.classList.toggle('drag-over-above', above);
    item.classList.toggle('drag-over-below', !above);
  });
  PICK_LIST.addEventListener('dragleave', function(e) {
    var item = e.target.closest('.pick');
    if (item) {
      item.classList.remove('drag-over-above');
      item.classList.remove('drag-over-below');
    }
  });
  PICK_LIST.addEventListener('drop', function(e) {
    e.preventDefault();
    var srcRwh = PICK_LIST._draggingRwh || e.dataTransfer.getData('text/plain');
    if (!srcRwh || !PICKED[srcRwh]) return;
    var target = e.target.closest('.pick');
    if (!target || target.dataset.rwh === srcRwh) return;
    var rect = target.getBoundingClientRect();
    var above = (e.clientY - rect.top) < rect.height / 2;

    // Rebuild PICKED in the new order. JS objects preserve insertion
    // order for string keys (ES2015+), so this is the priority list.
    var order = Object.keys(PICKED);
    order.splice(order.indexOf(srcRwh), 1);
    var targetIdx = order.indexOf(target.dataset.rwh);
    order.splice(above ? targetIdx : targetIdx + 1, 0, srcRwh);
    var reordered = {};
    order.forEach(function(r) { reordered[r] = PICKED[r]; });
    PICKED = reordered;
    renderPicked();
    renderGrid();
  });
}


function dryRunAction(url, rwh, div) {
  var existing = div.querySelector('.wire');
  if (existing) existing.remove();
  postJSON(url, { rwh: rwh, dry_run: true }).then(function(d) {
    var pre = document.createElement('pre');
    pre.className = 'wire';
    pre.textContent = JSON.stringify(d, null, 2);
    div.appendChild(pre);
  })['catch'](function(e) {
    var pre = document.createElement('pre');
    pre.className = 'wire';
    pre.textContent = 'Error: ' + e.message;
    div.appendChild(pre);
  });
}

function updateSolveCodes() {
  var codes = {};
  var keys = Object.keys(PICKED);
  for (var i = 0; i < keys.length; i++) {
    codes[PICKED[keys[i]].code] = true;
  }
  var codeList = Object.keys(codes);
  SOLVE_CODES.textContent = codeList.length ? codeList.join(', ') : 'none';
}

// ── Weekly Grid (merged multi-period blocks, per-cell column packing) ──

// ── Weekly Grid (reusable: sections → blocks → tables) ─────────────────

// Lightweight overlap check between two sections (any shared day+period+week).
// Mirrors the backend _slots_overlap() but client-side so the solver
// annotations can compute "dropped because it conflicts with X" without
// a round-trip.
function _sectionsOverlapLite(a, b) {
  var sa = a.slots || a.slots_raw || [];
  var sb = b.slots || b.slots_raw || [];
  for (var i = 0; i < sa.length; i++) {
    for (var j = 0; j < sb.length; j++) {
      if (sa[i].day !== sb[j].day) continue;
      var ap = sa[i].period_end != null
        ? { start: sa[i].period_start, end: sa[i].period_end }
        : { start: sa[i].ksjc || sa[i].period_start, end: sa[i].jsjc || sa[i].period_end };
      var bp = sb[j].period_end != null
        ? { start: sb[j].period_start, end: sb[j].period_end }
        : { start: sb[j].ksjc || sb[j].period_start, end: sb[j].jsjc || sb[j].period_end };
      if (ap.start <= bp.end && bp.start <= ap.end) {
        // weeks overlap?
        var aw = sa[i].weeks || [];
        var bw = sb[j].weeks || [];
        if (aw.length && bw.length) {
          for (var k = 0; k < aw.length; k++) {
            if (bw.indexOf(aw[k]) >= 0) return true;
          }
        } else {
          return true;
        }
      }
    }
  }
  return false;
}

function sectionsToBlocks(sections) {
  var allBlocks = [];
  for (var pi = 0; pi < sections.length; pi++) {
    var c = sections[pi];
    var color = colorFor(c.code);
    // Two accepted shapes per section:
    //   SOLVER format:  { slots: [{day, period_start, period_end, weeks}, ...] }
    //   FLAT picks-file format: { day, period_start, period_end, weeks_odd/even/all }
    // We treat both uniformly below.
    var slots = c.slots;
    if (!slots || !slots.length) {
      // Synthesize a single slot from top-level fields. weeks_all means
      // it appears in both odd and even weeks; weeks_odd/even narrow it.
      if (c.day && c.period_start && c.period_end) {
        var wArr = [];
        if (c.weeks_all) { wArr.push(0, 1); }
        else {
          if (c.weeks_odd)  wArr.push(0);
          if (c.weeks_even) wArr.push(1);
        }
        slots = [{
          day: c.day,
          period_start: c.period_start,
          period_end: c.period_end,
          weeks: wArr.length ? wArr : [0, 1]  // default to all if unspecified
        }];
      } else {
        slots = [];
      }
    }
    for (var si = 0; si < slots.length; si++) {
      var s = slots[si];
      var weeks = s.weeks || [];
      if (typeof weeks === 'string') {
        weeks = weeks.split(',').map(function(x) { return parseInt(x, 10); });
      }
      // enrolled flag flows through from the section shape so renderGridBlocks
      // can color the legend swatch differently (and pass it down to
      // _tagEnrolled for the block-level lock styling).
      allBlocks.push({
        day: s.day, periodStart: s.period_start, periodEnd: s.period_end,
        weeks: weeks, course: c, rwh: c.rwh, code: c.code, color: color,
        enrolled: c.__enrolled || false,
      });
    }
  }
  return allBlocks;
}

function detectConflicts(allBlocks) {
  for (var bi = 0; bi < allBlocks.length; bi++) {
    allBlocks[bi].conflict = false;
    for (var bj = bi + 1; bj < allBlocks.length; bj++) {
      if (allBlocks[bi].rwh === allBlocks[bj].rwh) continue;
      if (slotsOverlap(
        { day: allBlocks[bi].day, period_start: allBlocks[bi].periodStart, period_end: allBlocks[bi].periodEnd, weeks: allBlocks[bi].weeks },
        { day: allBlocks[bj].day, period_start: allBlocks[bj].periodStart, period_end: allBlocks[bj].periodEnd, weeks: allBlocks[bj].weeks }
      )) {
        allBlocks[bi].conflict = true;
        allBlocks[bj].conflict = true;
      }
    }
  }
}

function buildPackedItems(blocks, isOdd) {
  var parity = [];
  for (var i = 0; i < blocks.length; i++) {
    var b = blocks[i];
    if (b.weeks && b.weeks.length && b.weeks.some(function(w) { return (w % 2 === 1) === isOdd; })) {
      parity.push(b);
    }
  }
  if (!parity.length) return null;

  var dayGroups = {};
  parity.forEach(function(b) {
    if (!dayGroups[b.day]) dayGroups[b.day] = [];
    dayGroups[b.day].push(b);
  });

  var result = [];
  for (var d = 1; d <= 7; d++) {
    var blks = dayGroups[d];
    if (!blks || !blks.length) continue;
    blks.sort(function(a, b) { return a.periodStart - b.periodStart; });

    var cols = [];
    var colFor = {};
    blks.forEach(function(b) {
      var pds = [];
      for (var p = b.periodStart; p <= b.periodEnd; p++) pds.push(p);
      var placed = false;
      for (var ci = 0; ci < cols.length; ci++) {
        if (!pds.some(function(p) { return cols[ci][p]; })) {
          pds.forEach(function(p) { cols[ci][p] = true; });
          colFor[b.rwh] = ci;
          placed = true;
          break;
        }
      }
      if (!placed) {
        var nc = {};
        pds.forEach(function(p) { nc[p] = true; });
        cols.push(nc);
        colFor[b.rwh] = cols.length - 1;
      }
    });

    var total = cols.length || 1;
    blks.forEach(function(b) {
      result.push({ block: b, col: colFor[b.rwh], total: total });
    });
  }
  return result;
}

function renderGridTable(tbody, items) {
  if (!items || !items.length) {
    tbody.innerHTML = '<tr><td colspan="8" class="empty" style="padding:2rem 0">No courses in this week group.</td></tr>';
    return;
  }

  var cellMap = {};
  items.forEach(function(item) {
    var b = item.block;
    var span = b.periodEnd - b.periodStart + 1;
    for (var p = b.periodStart; p <= b.periodEnd; p++) {
      var key = b.day + ':' + p;
      if (!cellMap[key]) cellMap[key] = [];
      var dup = cellMap[key].some(function(e) { return e.rwh === b.rwh; });
      if (!dup) {
        cellMap[key].push({
          block: b, col: item.col, total: item.total,
          span: span, isStart: (p === b.periodStart), rwh: b.rwh
        });
      }
    }
  });

  var h = '';
  for (var row = 1; row <= PERIODS; row++) {
    h += '<tr><th>' + row + '</th>';
    for (var day = 1; day <= DAYS; day++) {
      var key = day + ':' + row;
      var entries = cellMap[key];
      var isBlocked = !!BLOCKED[day + ':' + row];
      var classes = 'cell' + (isBlocked ? ' blocked' : '');
      if (entries && entries.length) {
        var hasStart = entries.some(function(e) { return e.isStart; });
        if (hasStart) {
          h += '<td class="' + classes + '" data-day="' + day + '" data-period="' + row + '" style="padding:0;position:relative;height:' + ROW_HEIGHT + 'px">' +
               '<div class="cell-inner" style="position:absolute;left:0;top:0;right:0;bottom:0">';
          entries.forEach(function(e) {
            if (!e.isStart) return;
            var b = e.block;
            var w = 100 / e.total;
            var l = e.col * w;
            var z = 10 - e.col;
            var spanH = e.span * ROW_HEIGHT;
            h += '<div class="blk' + (b.conflict ? ' conf' : '') + '" style="' +
              'background:' + b.color + ';' +
              'width:' + w + '%;left:' + l + '%;' +
              'height:' + spanH + 'px;top:0;' +
              'z-index:' + z + ';' +
              '" ' +
              'title="' + escapeHtml(b.code + ' ' + (b.course.class_group || '') + (b.course.teachers && b.course.teachers[0] ? ' · ' + b.course.teachers.join(', ') : '') + ' · ' + dayName(b.day) + ' ' + b.periodStart + '-' + b.periodEnd + (b.conflict ? ' ⚠ CONFLICT' : '')) + '" ' +
              'data-rwh="' + b.rwh + '">' +
              '<span class="t">' + escapeHtml(b.code) + '</span>' +
              '<span style="font-size:.6rem;opacity:.8;display:block">' + escapeHtml(b.course.name || '') + (b.course.class_group ? ' <span style="opacity:.7">·' + escapeHtml(b.course.class_group) + '</span>' : '') + '</span>' +
              (b.course.teachers && b.course.teachers[0]
                ? '<span style="font-size:.58rem;opacity:.65;display:block;font-style:italic">' + escapeHtml(b.course.teachers.join(', ')) + '</span>'
                : '') +
            '</div>';
          });
          h += '</div></td>';
        } else {
          var c2 = 'cell' + (isBlocked ? ' blocked' : '');
          h += '<td class="' + c2 + '" data-day="' + day + '" data-period="' + row + '" style="padding:0;position:relative;height:' + ROW_HEIGHT + 'px">' +
               '<div class="cell-inner" style="position:absolute;left:0;top:0;right:0;bottom:0">';
          entries.forEach(function(e) {
            if (e.isStart) return;
            var b = e.block;
            if (b.conflict) {
              var w = 100 / e.total;
              h += '<div class="blk conf" style="' +
                'top:0;left:' + (e.col * w) + '%;width:' + w + '%;height:100%;z-index:1;' +
                'background:transparent;border:none;outline:none;' +
                'border-left:3px solid var(--bad);opacity:.5"></div>';
            }
          });
          h += '</div></td>';
        }
      } else {
        var c3 = 'cell empty-cell' + (isBlocked ? ' blocked' : '');
        h += '<td class="' + c3 + '" data-day="' + day + '" data-period="' + row + '" style="position:relative;height:' + ROW_HEIGHT + 'px"></td>';
      }
    }
    h += '</tr>';
  }
  tbody.innerHTML = h;
}

function renderGridBlocks(allBlocks, targetOdd, targetEven, legendTarget) {
  targetOdd.innerHTML = '';
  targetEven.innerHTML = '';
  if (legendTarget) legendTarget.innerHTML = '';

  if (!allBlocks.length) {
    targetOdd.innerHTML = '<tr><td colspan="8" class="empty" style="padding:2rem 0">No schedule data.</td></tr>';
    targetEven.innerHTML = '<tr><td colspan="8" class="empty" style="padding:2rem 0">No schedule data.</td></tr>';
    return;
  }

  detectConflicts(allBlocks);

  // Legend
  if (legendTarget) {
    var seenCodes = {};
    var lockedMode = (typeof IGNORE_TIS_ENROLLED !== 'undefined') && !IGNORE_TIS_ENROLLED;
    for (var li = 0; li < allBlocks.length; li++) {
      var lb = allBlocks[li];
      var code = lb.code;
      if (seenCodes[code]) continue;
      seenCodes[code] = true;
      // When in locked mode, give enrolled entries a distinct legend swatch
      // (accent blue) and a 🔒 suffix so the user can scan the legend and
      // know "these are TIS-enrolled, unquestionable" without looking at
      // the grid.
      var isEnrolled = !!lb.enrolled;
      var sw = document.createElement('span');
      sw.className = 'sw' + (isEnrolled && lockedMode ? ' sw-enrolled-locked' : '');
      sw.style.background = (isEnrolled && lockedMode) ? 'var(--accent)' : lb.color;
      var sl = document.createElement('span');
      sl.className = 'sl' + (isEnrolled && lockedMode ? ' sl-locked' : '');
      sl.textContent = code + (isEnrolled && lockedMode ? ' 🔒' : '');
      legendTarget.appendChild(sw);
      legendTarget.appendChild(sl);
    }
  }

  renderGridTable(targetOdd, buildPackedItems(allBlocks, true));
  renderGridTable(targetEven, buildPackedItems(allBlocks, false));
}

// Single empty grid for the scheduler's block-time UI. No course blocks —
// just cells the user can click to mark BLOCKED.
function renderBlockGrid() {
  if (!BLOCK_BODY) return;
  var h = '';
  for (var row = 1; row <= PERIODS; row++) {
    h += '<tr><th>' + row + '</th>';
    for (var day = 1; day <= DAYS; day++) {
      h += '<td class="cell" data-day="' + day + '" data-period="' + row +
        '" style="position:relative;height:' + ROW_HEIGHT + 'px"></td>';
    }
    h += '</tr>';
  }
  BLOCK_BODY.innerHTML = h;
  applyBlockedVisual(BLOCK_BODY);
  attachGridBlockingHandlers(BLOCK_BODY);
  attachGridContextMenu(BLOCK_BODY);
}

function renderGrid() {
  var keys = Object.keys(PICKED);
  if (!keys.length) {
    GRID_ODD.innerHTML = '<tr><td colspan="8" class="empty" style="padding:2rem 0">No picked sections.</td></tr>';
    GRID_EVEN.innerHTML = '<tr><td colspan="8" class="empty" style="padding:2rem 0">No picked sections.</td></tr>';
    // Clear the color legend too — without this, the legend swatches from
    // a previous (now-empty) picked set stay visible, making the user
    // think the courses are still picked.
    if (GRID_LEGEND) GRID_LEGEND.innerHTML = '';
    return;
  }

  var pickedArr = [];
  for (var ki = 0; ki < keys.length; ki++) {
    pickedArr.push(PICKED[keys[ki]]);
  }
  var allBlocks = sectionsToBlocks(pickedArr);
  renderGridBlocks(allBlocks, GRID_ODD, GRID_EVEN, GRID_LEGEND);
  // Re-apply blocked cells on top of course blocks (so they show even when
  // the cell already has a course drawn). Blocking is now edited in the
  // scheduler tab's single grid, but we still mirror the state here so the
  // user can SEE which slots are off-limits.
  applyBlockedVisual(GRID_ODD);
  applyBlockedVisual(GRID_EVEN);
}

// Step 3 weekly grid — combines picked + TIS-enrolled into one view so
// the user can see what their final schedule looks like (including the
// classes they're not actively managing). Uses the same odd/even
// side-by-side layout as step 1 (.persistent-grid, inherited). Enrolled
// sections render with a 🔒 lock badge so they're visually distinct from
// the user's own picks. No clicking — this grid is read-only (the user
// picks from step 1, blocks from step 2; step 3 is solver-driven).
function renderGrid3() {
  if (!GRID_ODD_3 || !GRID_EVEN_3) return;

  // Build the combined section list: picked + enrolled. Enrolled entries
  // get a `__enrolled: true` marker that sectionsToBlocks / the legend
  // can use to differentiate them. The `enrolled` flag in the section
  // shape mirrors what /api/tis/enrolled now returns, so if the user has
  // run a personal search and an enrolled rwh is also in PICKED, we
  // dedupe by rwh (PICKED wins — user-owned state overrides TIS view).
  var sections = [];
  var seenRwh = {};
  Object.keys(PICKED).forEach(function(rwh) {
    sections.push(Object.assign({}, PICKED[rwh], { __enrolled: false }));
    seenRwh[rwh] = true;
  });
  ENROLLED_RWH.forEach(function(rwh) {
    if (seenRwh[rwh]) return;
    var enrolled = ENROLLED_DATA[rwh];  // full {slots, code, name, ...}
    if (!enrolled || !enrolled.slots || !enrolled.slots.length) return;
    sections.push({
      rwh: rwh,
      code: enrolled.code,
      name: enrolled.name,
      section_name: enrolled.section,
      slots: enrolled.slots,
      has_schedule: true,
      __enrolled: true,
    });
  });

  if (!sections.length) {
    GRID_ODD_3.innerHTML = '<tr><td colspan="8" class="empty" style="padding:2rem 0">No picked or enrolled sections.</td></tr>';
    GRID_EVEN_3.innerHTML = '<tr><td colspan="8" class="empty" style="padding:2rem 0">No picked or enrolled sections.</td></tr>';
    if (GRID_LEGEND_3) GRID_LEGEND_3.innerHTML = '';
    return;
  }
  var allBlocks = sectionsToBlocks(sections);
  renderGridBlocks(allBlocks, GRID_ODD_3, GRID_EVEN_3, GRID_LEGEND_3);
  // Tag enrolled blocks with a 🔒 so the user can tell them apart from
  // picks at a glance. Match by rwh (more precise than code — same
  // course can have multiple picked rwhs, only the enrolled one should
  // get the lock). Done by walking the rendered DOM after
  // renderGridBlocks has set the colors.
  //
  // Two styling modes:
  //   - lockedMode=false (default, IGNORE_TIS_ENROLLED is true): use
  //     .blk-enrolled — subtle dashed border + small 🔒. Tells the user
  //     "this is TIS-enrolled" without screaming "LOCKED" since it's
  //     still a soft pick they can drop.
  //   - lockedMode=true (IGNORE_TIS_ENROLLED is false): use
  //     .blk-enrolled-locked — accent-blue gradient + solid border +
  //     larger 🔒. The user explicitly flipped "Ignore TIS enrolled" off
  //     meaning "treat enrolled as unquestionable", so the visual should
  //     scream that distinction.
  var enrolledRwhs = {};
  ENROLLED_RWH.forEach(function(r) { enrolledRwhs[r] = true; });
  var lockedMode = !IGNORE_TIS_ENROLLED;
  function _tagEnrolled(tbody) {
    tbody.querySelectorAll('.blk').forEach(function(b) {
      var rwh = b.dataset.rwh || '';
      if (!enrolledRwhs[rwh]) return;
      // PICKED wins over ENROLLED — if the user also has this rwh
      // picked, don't override their view of it as their own pick.
      if (PICKED[rwh]) return;
      b.classList.add(lockedMode ? 'blk-enrolled-locked' : 'blk-enrolled');
      if (!b.querySelector('.blk-lock')) {
        var lock = document.createElement('span');
        lock.className = 'blk-lock';
        lock.textContent = '🔒';
        b.insertBefore(lock, b.firstChild);
      }
    });
  }
  _tagEnrolled(GRID_ODD_3);
  _tagEnrolled(GRID_EVEN_3);
  applyBlockedVisual(GRID_ODD_3);
  applyBlockedVisual(GRID_EVEN_3);
}

// Week-detail mode for a blocked cell:
function _setBlockMode(key, mode) {
  if (mode === 'all' || !mode) {
    BLOCKED[key] = true;
  } else {
    BLOCKED[key] = { weeks: mode };
  }
}
function _blockMode(key) {
  if (!BLOCKED[key]) return null;
  if (BLOCKED[key] === true) return 'all';
  return BLOCKED[key].weeks || 'all';
}

// Right-click on a cell opens a mode-selector panel. The user picks:
//   - All weeks   (soft radial gradient — "leaves room to breathe")
//   - Odd weeks   (upper-left triangle)
//   - Even weeks  (lower-right triangle)
//   - Unblock     (only shown if cell is already blocked)
// The current mode is highlighted with ✓. Click-outside or Escape closes
// the panel without applying changes.
function attachGridContextMenu(tbody) {
  if (!tbody || tbody.dataset.ctxWired === '1') return;
  tbody.dataset.ctxWired = '1';
  tbody.addEventListener('contextmenu', function(e) {
    var td = e.target.closest('td[data-day][data-period]');
    if (!td) return;
    e.preventDefault();
    var day = parseInt(td.getAttribute('data-day'), 10);
    var period = parseInt(td.getAttribute('data-period'), 10);
    var key = day + ':' + period;
    showBlockPanel(key, day, period, e.clientX, e.clientY);
  });
}

// Show the mode-selector panel at (clientX, clientY). Builds the panel
// DOM on demand, positions it near the cursor, and wires the option
// buttons to mutate BLOCKED. Click outside / Escape closes it.
function showBlockPanel(key, day, period, clientX, clientY) {
  hideBlockPanel();
  var currentMode = _blockMode(key);  // 'all' / 'odd' / 'even' / null

  var panel = document.createElement('div');
  panel.id = 'block-panel';
  panel.className = 'block-panel';

  var dnames = ['', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  var header = dnames[day] + ' · Period ' + period;
  if (currentMode) header += ' · currently <b>' + currentMode + '</b>';

  var opts = [
    { mode: 'all',  label: 'All weeks',  desc: 'block every week' },
    { mode: 'odd',  label: 'Odd weeks',  desc: 'block odd-numbered weeks' },
    { mode: 'even', label: 'Even weeks', desc: 'block even-numbered weeks' },
  ];
  if (currentMode) {
    opts.push({ mode: 'unblock', label: 'Unblock', desc: 'remove this block' });
  }

  var html = '<div class="bp-header">' + header + '</div>';
  for (var i = 0; i < opts.length; i++) {
    var o = opts[i];
    var isCurrent = (o.mode === currentMode);
    var swatchCls = o.mode === 'unblock' ? 'bp-swatch-none' : ('bp-swatch-' + o.mode);
    html += '<button class="bp-opt' + (isCurrent ? ' bp-current' : '') +
      '" data-mode="' + o.mode + '">' +
      '<span class="bp-swatch ' + swatchCls + '"></span>' +
      '<span class="bp-label"><b>' + o.label + '</b><br>' +
      '<span style="font-size:.65rem;color:var(--mut)">' + o.desc + '</span></span>' +
      (isCurrent ? '<span class="bp-check">✓</span>' : '') +
      '</button>';
  }
  panel.innerHTML = html;
  document.body.appendChild(panel);

  // Position near cursor; clamp to viewport so it doesn't go off-screen
  var rect = panel.getBoundingClientRect();
  var pad = 8;
  var x = clientX + 4;
  var y = clientY + 4;
  if (x + rect.width > window.innerWidth - pad)  x = window.innerWidth - rect.width - pad;
  if (y + rect.height > window.innerHeight - pad) y = window.innerHeight - rect.height - pad;
  if (x < pad) x = pad;
  if (y < pad) y = pad;
  panel.style.left = x + 'px';
  panel.style.top = y + 'px';

  // Apply the chosen mode
  panel.querySelectorAll('.bp-opt').forEach(function(btn) {
    btn.addEventListener('click', function(ev) {
      ev.stopPropagation();
      var m = btn.dataset.mode;
      if (m === 'unblock') {
        delete BLOCKED[key];
      } else {
        _setBlockMode(key, m);
      }
      hideBlockPanel();
      // Refresh all visuals + text input
      applyBlockedVisual(GRID_ODD);
      applyBlockedVisual(GRID_EVEN);
      if (BLOCK_BODY) applyBlockedVisual(BLOCK_BODY);
      syncBlockedInput();
    });
  });

  // Close on outside click or Escape
  setTimeout(function() {
    function onOutside(ev) {
      if (panel && !panel.contains(ev.target)) hideBlockPanel();
      document.removeEventListener('click', onOutside, true);
      document.removeEventListener('contextmenu', onOutside, true);
    }
    function onEsc(ev) {
      if (ev.key === 'Escape') {
        hideBlockPanel();
        document.removeEventListener('keydown', onEsc);
        document.removeEventListener('click', onOutside, true);
        document.removeEventListener('contextmenu', onOutside, true);
      }
    }
    document.addEventListener('click', onOutside, true);
    document.addEventListener('contextmenu', onOutside, true);
    document.addEventListener('keydown', onEsc);
  }, 0);
}

function hideBlockPanel() {
  var p = document.getElementById('block-panel');
  if (p && p.parentNode) p.parentNode.removeChild(p);
}

// Apply .blocked class + data-mode attribute to cells matching BLOCKED state.
// Used after renderGridBlocks() (which overwrites innerHTML).
function applyBlockedVisual(tbody) {
  if (!tbody) return;
  var cells = tbody.querySelectorAll('td[data-day][data-period]');
  cells.forEach(function(td) {
    var key = td.getAttribute('data-day') + ':' + td.getAttribute('data-period');
    if (BLOCKED[key]) {
      td.classList.add('blocked');
      var mode = _blockMode(key);
      td.setAttribute('data-mode', mode);
    } else {
      td.classList.remove('blocked');
      td.removeAttribute('data-mode');
    }
  });
}

// Click + drag on grid cells to toggle BLOCKED. Single click flips the
// cell; drag selects a range (toggles all cells from start to current
// to the same state as the start cell, so drag-then-release gives a
// continuous "add" or "remove" gesture).
function attachGridBlockingHandlers(tbody) {
  if (!tbody || tbody.dataset.blockingWired === '1') return;
  tbody.dataset.blockingWired = '1';

  var startCell = null;  // { day, period }
  var startState = null;  // boolean, BLOCKED state at mousedown

  function cellFromEvent(e) {
    var td = e.target.closest('td[data-day][data-period]');
    if (!td) return null;
    return {
      day: parseInt(td.getAttribute('data-day'), 10),
      period: parseInt(td.getAttribute('data-period'), 10),
      el: td
    };
  }
  function setRangeBlocked(from, to, blocked) {
    var d1 = Math.min(from.day, to.day), d2 = Math.max(from.day, to.day);
    var p1 = Math.min(from.period, to.period), p2 = Math.max(from.period, to.period);
    for (var d = d1; d <= d2; d++) {
      for (var p = p1; p <= p2; p++) {
        var key = d + ':' + p;
        if (blocked) BLOCKED[key] = true;
        else delete BLOCKED[key];
      }
    }
  }
  function refresh() {
    applyBlockedVisual(GRID_ODD);
    applyBlockedVisual(GRID_EVEN);
    if (BLOCK_BODY) applyBlockedVisual(BLOCK_BODY);
    syncBlockedInput();
  }

  tbody.addEventListener('mousedown', function(e) {
    if (e.button !== 0) return;  // left-click only; right-click reserved for week-detail
    var c = cellFromEvent(e);
    if (!c) return;
    e.preventDefault();
    startCell = c;
    var key = c.day + ':' + c.period;
    startState = !BLOCKED[key];  // what to set on release
    setRangeBlocked(c, c, startState);
    refresh();
  });
  tbody.addEventListener('mouseover', function(e) {
    if (!startCell) return;
    var c = cellFromEvent(e);
    if (!c) return;
    setRangeBlocked(startCell, c, startState);
    refresh();
  });
  // Finalize on mouseup anywhere (not just tbody — user may drag off the
  // grid and release)
  function onUp() {
    if (!startCell) return;
    startCell = null;
    startState = null;
  }
  document.addEventListener('mouseup', onUp);
  // Context menu on a cell: right-click opens the week-detail prompt
  // (UI affordance for odd/even blocking). Skipped here for brevity — the
  // simple click/drag is enough for most use cases; week-detail is
  // a future iteration.
}

// Convert BLOCKED to the text input format ("1,3-5/2,1-2" style).
// Groups consecutive periods in the same day so the input stays compact.
function blockedToInput() {
  var out = [];
  for (var d = 1; d <= 7; d++) {
    var periods = [];
    for (var p = 1; p <= 12; p++) {
      if (BLOCKED[d + ':' + p]) periods.push(p);
    }
    if (!periods.length) continue;
    // Group consecutive into ranges
    var ranges = [];
    var start = periods[0], end = periods[0];
    for (var i = 1; i < periods.length; i++) {
      if (periods[i] === end + 1) { end = periods[i]; continue; }
      ranges.push(start === end ? '' + start : start + '-' + end);
      start = end = periods[i];
    }
    ranges.push(start === end ? '' + start : start + '-' + end);
    out.push(d + ',' + ranges.join(','));
  }
  return out.join('/');
}

function syncBlockedInput() {
  var el = document.getElementById('blocked-input');
  if (el) el.value = blockedToInput();
}

// Hook up: keep BLOCKED in sync with the text input (so users can still
// type by hand). Initial population parses whatever is already in the box.
function loadBlockedFromInput() {
  var el = document.getElementById('blocked-input');
  if (!el) return;
  var parsed = parseBlockedInput(el.value);
  BLOCKED = {};
  parsed.forEach(function(pair) {
    var day = pair[0], periods = pair[1];
    periods.forEach(function(p) { BLOCKED[day + ':' + p] = true; });
  });
}

// ── Enrolled ──────────────────────────────────────────────────────────────

function loadEnrolled() {
  // User removed the dedicated "Enrollment status" right-panel display,
  // so loadEnrolled() no longer writes any visible content into
  // #enrolled-out. It still:
  //   - fetches /api/tis/enrolled and populates ENROLLED_RWH +
  //     ENROLLED_DATA (used by step-3 weekly grid + pick-list 🔒 badges)
  //   - re-renders pick list + step-3 grid so newly-locked courses
  //     get their visual treatment
  // The lock banner that used to live in #enrolled-out is also gone —
  // the toggle's title text + 🔒 badges in the pick list + locked-mode
  // blue blocks in step 3 grid are the remaining indicators.
  getJSON('/api/tis/enrolled' + sem()).then(function(d) {
    ENROLLED_RWH = new Set();
    ENROLLED_DATA = {};
    if (d.error) {
      console.warn('enrolled load failed:', d.error);
      return;
    }
    var list = d.enrolled || [];
    for (var i = 0; i < list.length; i++) {
      var item = list[i];
      var rwh = item.rwh || '';
      ENROLLED_RWH.add(rwh);
      ENROLLED_DATA[rwh] = item;  // cache full data for renderGrid3()
    }
    renderPicked();           // 🔒 badges on already-loaded picks
    renderGrid3();            // step-3 weekly grid re-renders with locks
  })['catch'](function(e) {
    console.warn('enrolled load error:', e.message);
  });
}

// ── Solver (priority-based course dropping) ──────────────────────────────

function solve() {
  var codes = {};
  var codeOrder = [];
  var keys = Object.keys(PICKED);
  for (var i = 0; i < keys.length; i++) {
    var c = PICKED[keys[i]].code;
    if (!codes[c]) {
      codes[c] = true;
      codeOrder.push(c);
    }
  }
  if (!codeOrder.length) {
    SOLVE_OUT.innerHTML = '<div class="flash err">No courses picked to solve for.</div>';
    return;
  }

  // BLOCKED (in-memory) is the source of truth. Round-trip through the
  // compact input string so the API receives the same shape the old
  // #blocked-input path produced ([[day, [periods]]] list).
  var blocked = parseBlockedInput(blockedToInput());

  SOLVE_OUT.innerHTML = '<div class="ncn">Solving — trying all combinations…</div>';

  postJSON('/api/tis/solve' + sem(), {
    codes: codeOrder,
    priority: codeOrder,
    rwhs: Object.keys(PICKED),
    blocked: blocked,
    // When TIS-enrolled is "unquestionable", the solver must keep
    // those rwhs in every solution (drop other picked courses first).
    // When the flag is on (default), the solver is free to drop them.
    locked_rwhs: IGNORE_TIS_ENROLLED ? [] : Array.from(ENROLLED_RWH),
    max: 30
  }).then(function(d) {
    var solutions = d.solutions || [];

    if (!solutions.length) {
      SOLVE_OUT.innerHTML = '<div class="ncn">No valid non-conflicting combinations found. ' +
        'Try removing some courses or adjusting blocked slots.</div>';
      return;
    }

    // Group solutions by the "dropped" set (same dropped = same group).
    // Within a group, solutions differ only by which class was chosen
    // for codes the user picked multiple sections of. Key the group
    // by the sorted "dropped" list, since order doesn't matter.
    var groups = {};   // groupKey → [sol, sol, ...]
    var groupOrder = [];  // preserve order of first appearance
    for (var gi = 0; gi < solutions.length; gi++) {
      var s = solutions[gi];
      var key = (s.dropped || []).slice().sort().join('|') || '__all__';
      if (!groups[key]) {
        groups[key] = [];
        groupOrder.push(key);
      }
      groups[key].push(s);
    }

    var totalCodes = codeOrder.length;
    // Publish to module scope so Save / ←/→ / Compare can reach them
    SOLVER_IDX = 0;
    SOLVER_FLAT = solutions;
    SOLVER_TOTAL_CODES = totalCodes;
    SOLVER_codeOrder = codeOrder.slice();  // round-trip: saved schedules keep priority
    var flat = solutions;
    var idx = SOLVER_IDX;
    var total = flat.length;

    // ── code → name lookup (PICKED first, CAT fallback) ─────────────
    // The name is the user-facing primary identifier. Code is shown only
    // as a parenthetical for disambiguation (e.g. "生物学原理 (BIO103)").
    var codeToName = {};
    Object.keys(PICKED).forEach(function(rwh) {
      var p = PICKED[rwh];
      if (p.code && p.name && !codeToName[p.code]) codeToName[p.code] = p.name;
    });
    CAT.forEach(function(c) {
      if (c.code && c.name && !codeToName[c.code]) codeToName[c.code] = c.name;
    });
    // Lift helpers to module scope (used by Save + Compare)
    SOLVER_codeToName = codeToName;
    SOLVER_groups = groups;
    SOLVER_groupOrder = groupOrder;
    function cname(code) { return codeToName[code] || code; }
    // codeAndName(code): returns 'CODE NAME' format with code in blue
    // (class .sc-code) and the name following. The code goes FIRST so
    // users can scan by code when comparing multiple courses.
    function codeAndName(code) {
      var n = codeToName[code];
      var codeHtml = '<span class="sc-code">' + escapeHtml(code) + '</span>';
      if (n && n !== code) return codeHtml + ' ' + escapeHtml(n);
      return codeHtml;
    }
    function joinCodeNames(codes) {
      return codes.map(function(c) { return codeAndName(c); }).join(', ');
    }
    // Keep the inner renderSolveItem working with closure `flat/idx` — the
    // hoisted version (renderSolverItem) below reads module-scope state
    // and is what ←/→ actually calls.
    function renderSolveItem() {
      SOLVER_IDX = idx;  // keep module scope in sync for hoisted ←/→
      var sol = flat[idx];

      // ── Per-solution annotations ───────────────────────────────────
      // (a) "One code one class rule" — codes the user picked multiple
      //     sections of. The solution keeps ONE; the others are not in
      //     `sol.dropped` (which is keyed by code) so we compute them here.
      var userPickedByCode = {};  // code → [rwh,...]
      Object.keys(PICKED).forEach(function(rwh) {
        var c = PICKED[rwh].code;
        if (!userPickedByCode[c]) userPickedByCode[c] = [];
        userPickedByCode[c].push(rwh);
      });
      var solutionRwhs = sol.sections.map(function(s) { return s.rwh; });
      var intraDrops = {};  // code → [rwh,...] dropped by "one code" rule
      Object.keys(userPickedByCode).forEach(function(code) {
        var rwhs = userPickedByCode[code];
        if (rwhs.length <= 1) return;
        var kept = rwhs.filter(function(r) { return solutionRwhs.indexOf(r) >= 0; });
        var dropped = rwhs.filter(function(r) { return solutionRwhs.indexOf(r) < 0; });
        if (kept.length && dropped.length) {
          intraDrops[code] = dropped;
        }
      });

      // (b) For each fully-dropped code, find a kept section whose slots
      //     overlap with any of the dropped code's sections → "conflict with"
      var droppedCodes = sol.dropped || [];
      var conflictReasons = {};  // code → [keptSection, ...] (first overlap wins)
      var allCourses = CAT.concat(sol.sections);  // all sections we have data for
      var catByCode = {};  // code → [courses]
      allCourses.forEach(function(c) {
        if (!catByCode[c.code]) catByCode[c.code] = [];
        catByCode[c.code].push(c);
      });
      droppedCodes.forEach(function(code) {
        var droppedSecs = catByCode[code] || [];
        var keptSecs = sol.sections.filter(function(s) { return s.code !== code; });
        droppedSecs.forEach(function(ds) {
          for (var ki = 0; ki < keptSecs.length; ki++) {
            if (_sectionsOverlapLite(ds, keptSecs[ki])) {
              if (!conflictReasons[code]) conflictReasons[code] = [];
              conflictReasons[code].push(keptSecs[ki]);
              break;
            }
          }
        });
      });

      // Build section rows + total credits (selected courses — no annotations
      // for one-code drops, those are surfaced in their own block below).
      // Format: "CODE NAME cls 001 · 教师 · 3 cr · schedule"
      // Code first, in blue (.sc-code), no parens. "class" abbreviated to "cls".
      var secHtml = '';
      var totalCredits = 0;
      for (var si = 0; si < sol.sections.length; si++) {
        var sec = sol.sections[si];
        var schedStr = sec.schedule || formatSchedule(sec.slots);
        totalCredits += parseFloat(sec.credits) || 0;
        secHtml += '<div class="sc-sec">' +
          codeAndName(sec.code) +
          (sec.class_group ? ' <span style="color:var(--mut)">cls ' + escapeHtml(sec.class_group) + '</span>' : '') +
          (sec.teachers && sec.teachers[0] ? ' · ' + escapeHtml(sec.teachers.join(', ')) : '') +
          (sec.credits ? ' · <b>' + sec.credits + '</b> cr' : '') +
          (schedStr ? ' · <span style="color:var(--mut);font-size:.72rem">' + escapeHtml(schedStr) + '</span>' : '') +
        '</div>';
      }

      // Build dropped annotation lines:
      //   "生物学原理 (BIO103): dropped ↔ conflict with 大学化学 (CH105)"
      // Build dropped annotation lines: "CODE NAME: dropped ↔ conflict with CODE NAME"
      // (Code first, in blue, no parens. Name follows.)
      var dropHtml = '';
      if (droppedCodes.length) {
        dropHtml = '<div class="sc-drops">';
        droppedCodes.forEach(function(code) {
          var reason = conflictReasons[code];
          var reasonText = reason && reason[0]
            ? '↔ conflict with <b>' + codeAndName(reason[0].code) + '</b>'
            : '↔ no non-conflicting section exists';
          dropHtml += '<div class="sc-drop-row">' +
            codeAndName(code) + ': <span style="color:var(--bad)">dropped</span>. ' +
            reasonText +
          '</div>';
        });
        dropHtml += '</div>';
      }

      // One-code-one-class drops: courses where the user picked multiple
      // sections of the SAME course code and the solver kept one. The
      // dropped siblings are not in sol.dropped (which is keyed by code),
      // so we surface them here. The header line explains the situation
      // in plain English; per-row annotations are kept minimal.
      //
      // Multi-teacher rendering: always show ALL teachers of both the
      // kept and dropped classes. The earlier "compare first teacher"
      // logic was wrong — two classes that share a first teacher are
      // still different sections with different full rosters.
      function teacherList(t) {
        return (t && t.length) ? t.join(', ') : '—';
      }
      var oneCodeHtml = '';
      var oneCodeKeys = Object.keys(intraDrops);
      if (oneCodeKeys.length) {
        oneCodeHtml = '<div class="sc-onecode">' +
          '<div class="sc-onecode-h">Same course picked across multiple teaching classes — solution kept one</div>';
        oneCodeKeys.forEach(function(code) {
          var droppedRwhs = intraDrops[code];
          // Find the kept section (in sol.sections with this code)
          var kept = sol.sections.filter(function(s) { return s.code === code; })[0];
          var keptClass = kept && kept.class_group ? kept.class_group : '?';
          oneCodeHtml += '<div class="sc-onecode-row">' +
            codeAndName(code) + ': <b>kept cls ' + escapeHtml(keptClass) + '</b>' +
            ' <span class="sc-teacher">— ' + escapeHtml(teacherList(kept && kept.teachers)) + '</span>';
          // Each dropped class on its own indented sub-line
          oneCodeHtml += '<div class="sc-onecode-drops">';
          droppedRwhs.forEach(function(r) {
            var p = PICKED[r];
            if (!p) return;
            var cls = p.class_group || '?';
            oneCodeHtml += '<div class="sc-onecode-drop">· dropped cls ' +
              escapeHtml(cls) +
              ' <span class="sc-teacher">— ' + escapeHtml(teacherList(p.teachers)) + '</span>' +
            '</div>';
          });
          oneCodeHtml += '</div></div>';
        });
        oneCodeHtml += '</div>';
      }

      var coverage = sol.covered;
      var droppedStr = (sol.dropped && sol.dropped.length)
        ? ' <span class="dropped">Dropped: ' + joinCodeNames(sol.dropped) + '</span>'
        : '';

      // ── Categorized drop-group list (top of solve output) ───────────
      // One section per group. The header is the dropped-set (using
      // course NAMES, code in parens). The count badge shows how many
      // combinations fall in this group. Clicking jumps to the first
      // solution in the group; the currently-active group is highlighted
      // even when the user is on a later solution in that group
      // (so arrow navigation does NOT lose the highlight).
      var currentSol = flat[idx];
      var currentGroupKey = (currentSol.dropped || []).slice().sort().join('|') || '__all__';
      var groupHtml = '<div class="solve-groups">';
      for (var gk = 0; gk < groupOrder.length; gk++) {
        var gkey = groupOrder[gk];
        var gsols = groups[gkey];
        var gFirst = flat.indexOf(gsols[0]);
        // Highlight if the CURRENT solution belongs to this group, not
        // only if it is the first solution in the group.
        var isActive = (gkey === currentGroupKey);
        var label = gkey === '__all__'
          ? 'No courses dropped'
          : 'Dropped ' + (gsols[0].dropped.length
              ? gsols[0].dropped.map(codeAndName).join(', ')
              : '');
        groupHtml += '<button class="sg-chip' + (isActive ? ' sg-active' : '') +
          '" data-gfirst="' + gFirst + '" title="Jump to first combination in this group">' +
          label + ' <span class="sg-cnt">' + gsols.length + '</span></button>';
      }
      groupHtml += '</div>';

      var h =
        groupHtml +
        '<div class="solve-nav">' +
          '<button class="nav-btn" id="solve-prev"' + (idx === 0 ? ' disabled' : '') + '>◀</button>' +
          '<span class="nav-pos">Solution <b>' + (idx + 1) + '</b>/' + total + '</span>' +
          '<button class="nav-btn" id="solve-next"' + (idx >= total - 1 ? ' disabled' : '') + '>▶</button>' +
        '</div>' +
        '<div class="solve-coverage">' +
          '<b>' + coverage + '/' + totalCodes + '</b> courses · ' +
          '<b>' + totalCredits.toFixed(1) + '</b> credits' +
          droppedStr +
        '</div>' +
        '<div class="solve-card" style="border:none;background:transparent;padding:0;margin-bottom:.3rem">' +
          secHtml +
          oneCodeHtml +
          dropHtml +
          '<div class="sc-apply" style="margin-top:.5rem;display:flex;gap:.5rem">' +
            '<button class="primary" id="solve-apply" style="flex:1;padding:.4rem">Apply This Schedule</button>' +
            '<button class="ghost" id="solve-add" style="flex:1;padding:.4rem" title="Add this solution to the candidates list in step 4 (Compare) without touching your current picks">➕ Add to candidates</button>' +
            '<button class="ghost" id="solve-export" style="flex:1;padding:.4rem" title="Download this solution as a .json file (one schedule per file)">💾 Export as JSON</button>' +
          '</div>' +
          (SAVED_SCHEDULES.length
            ? '<div class="sc-compare-link" style="margin-top:.4rem;font-size:.72rem;color:var(--accent);text-align:center">' +
              '📂 ' + SAVED_SCHEDULES.length + ' candidate' + (SAVED_SCHEDULES.length === 1 ? '' : 's') + ' — <a href="#" onclick="event.preventDefault();switchStep(4);return false;" style="color:var(--accent);text-decoration:underline;cursor:pointer">open Compare (step 4)</a>' +
              '</div>'
            : '') +
        '</div>' +
        '<div class="grid-wrap" style="border-top:1px solid var(--border);margin-top:.6rem;padding-top:.6rem;font-size:.68rem">' +
          '<div style="margin-bottom:8px">' +
            '<div style="font-size:.7rem;color:var(--accent);font-weight:500;margin-bottom:2px">Odd Weeks</div>' +
            '<table class="grid" style="font-size:.65rem"><thead><tr><th>Pd</th><th>Mon</th><th>Tue</th><th>Wed</th><th>Thu</th><th>Fri</th><th>Sat</th><th>Sun</th></tr></thead>' +
              '<tbody id="solve-grid-odd"></tbody></table>' +
          '</div>' +
          '<div>' +
            '<div style="font-size:.7rem;color:var(--accent);font-weight:500;margin-bottom:2px">Even Weeks</div>' +
            '<table class="grid" style="font-size:.65rem"><thead><tr><th>Pd</th><th>Mon</th><th>Tue</th><th>Wed</th><th>Thu</th><th>Fri</th><th>Sat</th><th>Sun</th></tr></thead>' +
              '<tbody id="solve-grid-even"></tbody></table>' +
          '</div>' +
        '</div>';

      SOLVE_OUT.innerHTML = h;

      // Render the schedule grid for this solution
      var solveBlocks = sectionsToBlocks(sol.sections);
      renderGridBlocks(
        solveBlocks,
        document.getElementById('solve-grid-odd'),
        document.getElementById('solve-grid-even'),
        null  // no legend in solver grid
      );

      // Wire nav buttons
      var prev = document.getElementById('solve-prev');
      var next = document.getElementById('solve-next');
      if (prev) prev.addEventListener('click', function() { if (idx > 0) { idx--; renderSolveItem(); } });
      if (next) next.addEventListener('click', function() { if (idx < total - 1) { idx++; renderSolveItem(); } });
      document.getElementById('solve-apply').addEventListener('click', function() { applySolution(flat[idx]); });
      var addBtn = document.getElementById('solve-add');
      if (addBtn) addBtn.addEventListener('click', function() { saveCurrentSolverSchedule(flat[idx]); });
      var exportBtn = document.getElementById('solve-export');
      if (exportBtn) exportBtn.addEventListener('click', function() { exportSolverScheduleAsJson(flat[idx]); });
      // Wire group chips: click → jump to first combination in that group
      var groupChips = SOLVE_OUT.querySelectorAll('.sg-chip');
      for (var ci = 0; ci < groupChips.length; ci++) {
        groupChips[ci].addEventListener('click', function() {
          var target = parseInt(this.dataset.gfirst, 10);
          if (!isNaN(target) && target >= 0 && target < total) {
            idx = target;
            renderSolveItem();
          }
        });
      }
    }

    renderSolveItem();
  })['catch'](function(e) {
    SOLVE_OUT.innerHTML = '<div class="flash err">Error: ' + escapeHtml(e.message) + '</div>';
  });
}

function applySolution(sol) {
  PICKED = {};
  for (var i = 0; i < sol.sections.length; i++) {
    var sec = sol.sections[i];
    PICKED[sec.rwh] = JSON.parse(JSON.stringify(sec));
  }
  renderResults(CAT);
  renderPicked();
  renderGrid();
  SOLVE_OUT.innerHTML = '<div class="ncn" style="color:var(--ok)">Solution applied — ' +
    sol.sections.length + ' sections picked.' +
    (sol.dropped && sol.dropped.length ? ' <span style="color:var(--bad)">Dropped: ' + escapeHtml(sol.dropped.join(', ')) + '</span>' : '') +
    '</div>';
  // Applying changes PICKED; the saved schedules in localStorage still
  // describe the OLD set (correct — they're a historical record). But
  // unfocus any currently-focused saved card so ←/→ no longer cycles it
  // (the user is now on the freshly-applied schedule, not a saved one).
  FOCUSED_SAVED_IDX = -1;
}

// ── Save / Compare / Focus ───────────────────────────────────────────────
// Save a solver solution to localStorage. Does NOT touch PICKED — that's
// what "Apply" is for. The saved schedule is a snapshot you can browse
// later without changing your current picks.
function saveCurrentSolverSchedule(sol) {
  if (!sol || !sol.sections || !sol.sections.length) return;
  // Compute total credits the same way renderSolveItem does
  var totalCredits = 0;
  for (var i = 0; i < sol.sections.length; i++) {
    totalCredits += parseFloat(sol.sections[i].credits) || 0;
  }
  var idx = SAVED_SCHEDULES.length + 1;
  var label = '#' + idx;
  // Disambiguate by dropped set if there are multiple groups
  if (sol.dropped && sol.dropped.length) {
    label += ' · drop ' + sol.dropped.join(',');
  }
  // Also save the blocked time zones + priority so a saved schedule
  // can recreate the solver input. blocked is the compact input string
  // (e.g. "1,2-3/3,5-6") parsed by parseBlockedInput; null/empty if
  // the user hadn't blocked any slots when they saved.
  var blockedStr = blockedToInput();
  var blockedCount = blockedStr ? blockedToInput().split('/').filter(function(s) { return s.trim(); }).length : 0;
  var entry = {
    label: label,
    sections: JSON.parse(JSON.stringify(sol.sections)),
    dropped: sol.dropped || [],
    ts: Date.now(),
    totalCredits: totalCredits,
    // New: blocked + priority snapshot for round-trip reproducibility
    blocked: blockedStr || null,
    priority: SOLVER_codeOrder ? SOLVER_codeOrder.slice() : null,
  };
  SAVED_SCHEDULES.push(entry);
  try { localStorage.setItem('tis-saved-schedules', JSON.stringify(SAVED_SCHEDULES)); } catch (e) {}
  renderComparePane();
  var blockedTag = blockedCount ? ' · ' + blockedCount + ' blocked slot' + (blockedCount === 1 ? '' : 's') : '';
  flash('➕ Added candidate ' + label + ' — ' + sol.sections.length + ' sections · ' + totalCredits.toFixed(1) + ' cr' + blockedTag + ' · go to step 4 to review', 'ok');
}

// exportSolverScheduleAsJson: download a single solver solution as a
// standalone .json file. The format is the same as a saved-schedule
// entry (so the file can be re-loaded into the Compare step later),
// wrapped in a tiny envelope with version + ts.
function exportSolverScheduleAsJson(sol) {
  if (!sol || !sol.sections || !sol.sections.length) return;
  var totalCredits = 0;
  for (var i = 0; i < sol.sections.length; i++) {
    totalCredits += parseFloat(sol.sections[i].credits) || 0;
  }
  var idx = SOLVER_IDX + 1;
  var blockedStr = blockedToInput() || null;
  var envelope = {
    version: 2,
    type: 'tis-candidate',
    ts: Date.now(),
    schedule: {
      label: 'solution-' + idx,
      sections: sol.sections,
      dropped: sol.dropped || [],
      totalCredits: totalCredits,
      blocked: blockedStr,
      priority: SOLVER_codeOrder ? SOLVER_codeOrder.slice() : null,
    }
  };
  var filename = 'tis-solution-' + idx + '.json';
  var blob = new Blob([JSON.stringify(envelope, null, 2)], { type: 'application/json' });
  triggerDownload(blob, filename);
  flash('💾 Exported ' + filename + ' — ' + sol.sections.length + ' sections', 'ok');
}

// triggerDownload: helper to download a Blob as a file (used by JSON
// and ZIP export). Click-anchored; works without server support.
function triggerDownload(blob, filename) {
  var url = URL.createObjectURL(blob);
  var a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.style.display = 'none';
  document.body.appendChild(a);
  a.click();
  setTimeout(function() {
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, 0);
}

function deleteSavedSchedule(i) {
  if (i < 0 || i >= SAVED_SCHEDULES.length) return;
  var removed = SAVED_SCHEDULES.splice(i, 1)[0];
  try { localStorage.setItem('tis-saved-schedules', JSON.stringify(SAVED_SCHEDULES)); } catch (e) {}
  if (FOCUSED_SAVED_IDX === i) FOCUSED_SAVED_IDX = -1;
  else if (FOCUSED_SAVED_IDX > i) FOCUSED_SAVED_IDX--;
  renderComparePane();
  if (removed) flash('🗑 Deleted ' + removed.label, 'ok');
}

function applySavedSchedule(i) {
  if (i < 0 || i >= SAVED_SCHEDULES.length) return;
  var saved = SAVED_SCHEDULES[i];
  // Wrap as a "solution" object so applySolution can consume it
  var sol = {
    sections: saved.sections,
    dropped: saved.dropped,
  };
  applySolution(sol);
  // Also restore the saved blocked time zones (if any). This is a
  // snapshot — the user explicitly chose to apply THIS schedule, so
  // their current BLOCKED is replaced (not merged). Show a status
  // message so they know it happened.
  if (saved.blocked) {
    // Clear current BLOCKED, then re-apply from the saved compact string.
    for (var k in BLOCKED) if (BLOCKED.hasOwnProperty(k)) delete BLOCKED[k];
    var parsed = parseBlockedInput(saved.blocked);
    for (var pi = 0; pi < parsed.length; pi++) {
      var day = parsed[pi][0];
      var periods = parsed[pi][1];
      for (var pj = 0; pj < periods.length; pj++) {
        BLOCKED[day + ':' + periods[pj]] = true;
      }
    }
    // Sync the text input + re-render the scheduler grid so the user
    // sees the restored blocked cells.
    syncBlockedInput();
    renderBlockGrid();
    renderGrid();  // also reflect the blocked state in the main grid
    flash('Restored ' + parsed.length + ' blocked slot' + (parsed.length === 1 ? '' : 's') + ' from ' + saved.label, 'ok');
  }
  // Jump to the Bid & sync step (was step 4; now step 5 in the 5-step
  // flow) so the user can review the applied schedule and assign bids.
  switchStep(5);
}

// clearAllCandidates: empty the in-memory + localStorage candidate list.
// Confirmation prompt since this is destructive. The user is also given
// a hint that re-loading the same JSONs later will re-populate.
function clearAllCandidates() {
  if (!SAVED_SCHEDULES.length) {
    flash('No candidates to clear', 'warn');
    return;
  }
  if (!confirm('Remove all ' + SAVED_SCHEDULES.length + ' candidate(s)?\n\nThis clears the in-memory + localStorage copy. JSON files you exported are not deleted.')) return;
  SAVED_SCHEDULES = [];
  FOCUSED_SAVED_IDX = -1;
  try { localStorage.removeItem('tis-saved-schedules'); } catch (e) {}
  renderComparePane();
  flash('🗑 Cleared all candidates', 'ok');
}

// exportAllCandidatesAsZip: bundle every candidate as its own JSON
// file inside a single .zip (one file per schedule, named after the
// candidate label). Uses an inline minimal STORE-method zip writer —
// no external library needed.
//
// ZIP format reference: APPNOTE.TXT (PKWARE). Layout:
//   [Local file header + file data] * N
//   [Central directory header]     * N
//   [End of central directory record] (1)
function exportAllCandidatesAsZip() {
  if (!SAVED_SCHEDULES.length) {
    flash('No candidates to export', 'warn');
    return;
  }
  var files = [];
  for (var i = 0; i < SAVED_SCHEDULES.length; i++) {
    var s = SAVED_SCHEDULES[i];
    var name = sanitizeFilename(s.label || ('candidate-' + (i + 1))) + '.json';
    var envelope = {
      version: 2,
      type: 'tis-candidate',
      ts: s.ts || Date.now(),
      schedule: {
        label: s.label,
        sections: s.sections,
        dropped: s.dropped || [],
        totalCredits: s.totalCredits || 0,
        blocked: s.blocked || null,
        priority: s.priority || null,
      }
    };
    var data = new TextEncoder().encode(JSON.stringify(envelope, null, 2));
    files.push({ name: name, data: data });
  }
  var zipBlob = buildZip(files);
  var ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
  triggerDownload(zipBlob, 'tis-candidates-' + ts + '.zip');
  flash('📦 Exported ' + files.length + ' candidate(s) as zip', 'ok');
}

// buildZip: minimal ZIP writer (STORE method, no compression).
// Returns a Blob. ~80 lines, no external deps.
function buildZip(files) {
  // Precomputed CRC-32 table (IEEE 802.3 polynomial 0xEDB88320).
  var crcTable = (function() {
    var t = new Uint32Array(256);
    for (var n = 0; n < 256; n++) {
      var c = n;
      for (var k = 0; k < 8; k++) c = (c & 1) ? (0xEDB88320 ^ (c >>> 1)) : (c >>> 1);
      t[n] = c >>> 0;
    }
    return t;
  })();
  function crc32(bytes) {
    var c = 0xFFFFFFFF;
    for (var i = 0; i < bytes.length; i++) c = crcTable[(c ^ bytes[i]) & 0xFF] ^ (c >>> 8);
    return (c ^ 0xFFFFFFFF) >>> 0;
  }
  // Dos-time/date for the local headers — set to 2020-01-01 00:00:00
  // (a fixed recent timestamp). We don't track real mod-times per file.
  var dosTime = 0;       // 00:00:00
  var dosDate = (1 << 5) | 1;  // 1980-01-01  (will be set to 2020 below)
  // 2020-01-01 → dosDate = ((2020 - 1980) << 9) | (1 << 5) | 1
  dosDate = ((2020 - 1980) << 9) | (1 << 5) | 1;
  var enc = new TextEncoder();
  var parts = [];
  var central = [];
  var offset = 0;
  for (var i = 0; i < files.length; i++) {
    var f = files[i];
    var nameBytes = enc.encode(f.name);
    var data = f.data;
    var crc = crc32(data);
    // Local file header (30 bytes + name)
    var lfh = new Uint8Array(30 + nameBytes.length);
    var lv = new DataView(lfh.buffer);
    lv.setUint32(0, 0x04034b50, true);            // signature
    lv.setUint16(4, 20, true);                    // version needed (2.0)
    lv.setUint16(6, 0, true);                     // flags
    lv.setUint16(8, 0, true);                     // compression: store
    lv.setUint16(10, dosTime, true);              // mod time
    lv.setUint16(12, dosDate, true);              // mod date
    lv.setUint32(14, crc, true);                  // CRC-32
    lv.setUint32(18, data.length, true);          // compressed size
    lv.setUint32(22, data.length, true);          // uncompressed size
    lv.setUint16(26, nameBytes.length, true);     // file name length
    lv.setUint16(28, 0, true);                    // extra field length
    lfh.set(nameBytes, 30);
    parts.push(lfh, data);
    // Central directory header (46 bytes + name)
    var cdh = new Uint8Array(46 + nameBytes.length);
    var cv = new DataView(cdh.buffer);
    cv.setUint32(0, 0x02014b50, true);            // signature
    cv.setUint16(4, 20, true);                    // version made by
    cv.setUint16(6, 20, true);                    // version needed
    cv.setUint16(8, 0, true);                     // flags
    cv.setUint16(10, 0, true);                    // compression
    cv.setUint16(12, dosTime, true);              // mod time
    cv.setUint16(14, dosDate, true);              // mod date
    cv.setUint32(16, crc, true);                  // CRC-32
    cv.setUint32(20, data.length, true);          // compressed size
    cv.setUint32(24, data.length, true);          // uncompressed size
    cv.setUint16(28, nameBytes.length, true);     // file name length
    cv.setUint16(30, 0, true);                    // extra field
    cv.setUint16(32, 0, true);                    // comment length
    cv.setUint16(34, 0, true);                    // disk number
    cv.setUint16(36, 0, true);                    // internal attrs
    cv.setUint32(38, 0, true);                    // external attrs
    cv.setUint32(42, offset, true);               // local header offset
    cdh.set(nameBytes, 46);
    central.push(cdh);
    offset += lfh.length + data.length;
  }
  var cdSize = central.reduce(function(a, b) { return a + b.length; }, 0);
  var cdOffset = offset;
  // End of central directory record (22 bytes)
  var eocd = new Uint8Array(22);
  var ev = new DataView(eocd.buffer);
  ev.setUint32(0, 0x06054b50, true);              // signature
  ev.setUint16(4, 0, true);                       // disk number
  ev.setUint16(6, 0, true);                       // disk w/ cd start
  ev.setUint16(8, files.length, true);            // entries on this disk
  ev.setUint16(10, files.length, true);           // total entries
  ev.setUint32(12, cdSize, true);                 // cd size
  ev.setUint32(16, cdOffset, true);               // cd offset
  ev.setUint16(20, 0, true);                      // comment length
  return new Blob([].concat(parts, central, [eocd]), { type: 'application/zip' });
}

// sanitizeFilename: turn a label into something safe for filesystems
// (no /, no \x00, max 64 chars). Used for zip entry names.
function sanitizeFilename(name) {
  return String(name)
    .replace(/[\\/:*?"<>|\x00-\x1f]/g, '_')
    .replace(/\s+/g, '_')
    .slice(0, 64) || 'candidate';
}

// loadCandidatesFromFiles: read one or more JSON files selected by
// the user. Each file is normalized to a schedule object and pushed
// onto SAVED_SCHEDULES. Two on-disk formats are supported:
//
//   1. Single-schedule envelope:  { "type": "tis-candidate", "schedule": { ... } }
//   2. Multi-schedule array:     { "version": 2, "schedules": [ {...}, {...} ] }
//
// Files matching either shape are accepted; unknown shapes are
// reported in a single toast so the user knows which file failed.
function loadCandidatesFromFiles(fileList) {
  var files = Array.prototype.slice.call(fileList || []);
  if (!files.length) return;
  var pending = files.length;
  var added = 0;
  var failed = 0;
  var errs = [];
  function onAllDone() {
    if (added) {
      try { localStorage.setItem('tis-saved-schedules', JSON.stringify(SAVED_SCHEDULES)); } catch (e) {}
      renderComparePane();
      flash('📂 Loaded ' + added + ' candidate' + (added === 1 ? '' : 's') +
        (failed ? ' · ' + failed + ' failed' : ''), added && !failed ? 'ok' : 'warn');
    } else if (failed) {
      flash('✗ Failed to load ' + failed + ' file' + (failed === 1 ? '' : 's') + ' — see toast', 'bad');
    }
    if (errs.length) console.warn('Candidate load errors:', errs);
  }
  function ingestFile(file) {
    var reader = new FileReader();
    reader.onload = function() {
      try {
        var data = JSON.parse(reader.result);
        var items = normalizeCandidateFile(data, file.name);
        for (var i = 0; i < items.length; i++) {
          // Re-label to avoid clobbering with existing #N names
          items[i].label = (items[i].label || ('loaded-' + (SAVED_SCHEDULES.length + 1)));
          // If a label collides, suffix with a counter
          var base = items[i].label;
          var n = 1;
          while (SAVED_SCHEDULES.some(function(e) { return e.label === items[i].label; })) {
            items[i].label = base + ' (' + (++n) + ')';
          }
          SAVED_SCHEDULES.push(items[i]);
          added++;
        }
      } catch (e) {
        failed++;
        errs.push(file.name + ': ' + e.message);
      }
      if (--pending === 0) onAllDone();
    };
    reader.onerror = function() {
      failed++;
      errs.push(file.name + ': read error');
      if (--pending === 0) onAllDone();
    };
    reader.readAsText(file);
  }
  for (var i = 0; i < files.length; i++) ingestFile(files[i]);
}

// normalizeCandidateFile: turn a parsed JSON object into an array of
// schedule entries (candidates). Returns [] on any shape mismatch.
function normalizeCandidateFile(data, fileName) {
  if (!data || typeof data !== 'object') throw new Error('not an object');
  // Multi-schedule: {version, schedules: [...]}
  if (Array.isArray(data.schedules)) {
    var out = [];
    for (var i = 0; i < data.schedules.length; i++) {
      out.push(scheduleEntryFromObject(data.schedules[i], fileName + '#' + (i + 1)));
    }
    return out;
  }
  // Single-schedule envelope: {type:'tis-candidate', schedule: {...}}
  if (data.type === 'tis-candidate' && data.schedule) {
    return [scheduleEntryFromObject(data.schedule, fileName)];
  }
  // Legacy raw schedule: {sections, dropped, ...} at the top level
  if (Array.isArray(data.sections)) {
    return [scheduleEntryFromObject(data, fileName)];
  }
  // Picks-file format: {picks: [...], version: 1}
  if (Array.isArray(data.picks)) {
    return [picksToCandidateEntry(data, fileName)];
  }
  throw new Error('unrecognized format');
}

// scheduleEntryFromObject: coerce a single schedule object into the
// SAVED_SCHEDULES entry shape. Missing fields are filled with safe
// defaults so the renderer doesn't blow up.
function scheduleEntryFromObject(obj, fileName) {
  if (!obj || !Array.isArray(obj.sections)) throw new Error('no sections array');
  var credSum = 0;
  for (var i = 0; i < obj.sections.length; i++) credSum += parseFloat(obj.sections[i].credits) || 0;
  return {
    label: obj.label || fileName,
    sections: JSON.parse(JSON.stringify(obj.sections)),
    dropped: Array.isArray(obj.dropped) ? obj.dropped.slice() : [],
    ts: obj.ts || Date.now(),
    totalCredits: obj.totalCredits || credSum,
    blocked: obj.blocked || null,
    priority: Array.isArray(obj.priority) ? obj.priority.slice() : null,
  };
}

// picksToCandidateEntry: convert the legacy picks-file shape
// ({version, picks: [...]}) into a candidate entry. Each pick is a
// flat section object with snake_case fields; we just pass them
// through as sections.
function picksToCandidateEntry(data, fileName) {
  var credSum = 0;
  for (var i = 0; i < data.picks.length; i++) credSum += parseFloat(data.picks[i].credits) || 0;
  return {
    label: fileName,
    sections: JSON.parse(JSON.stringify(data.picks)),
    dropped: [],
    ts: data.ts || Date.now(),
    totalCredits: credSum,
    blocked: null,
    priority: null,
  };
}

function loadSavedSchedules() {
  try {
    var raw = localStorage.getItem('tis-saved-schedules');
    if (raw) {
      var arr = JSON.parse(raw);
      if (Array.isArray(arr)) {
        // Validate each entry has sections
        SAVED_SCHEDULES = arr.filter(function(e) { return e && Array.isArray(e.sections); });
      }
    }
  } catch (e) {
    SAVED_SCHEDULES = [];
  }
}

// Focus a saved schedule card (toggles visual emphasis; no scroll).
// The focused card is the one ←/→ cycles between.
function focusSavedCard(i) {
  if (i < 0 || i >= SAVED_SCHEDULES.length) return;
  FOCUSED_SAVED_IDX = (FOCUSED_SAVED_IDX === i) ? -1 : i;  // re-click unfocuses
  var cards = document.querySelectorAll('#solve-compare .cmp-card');
  for (var k = 0; k < cards.length; k++) {
    cards[k].classList.toggle('cmp-focused', k === FOCUSED_SAVED_IDX);
  }
  updateSolverFocusHint();
}

// When a saved card is focused, hint to the user that ←/→ now cycles
// between saved schedules (instead of solver solutions).
function updateSolverFocusHint() {
  // Update the saved-count link at the top to reflect the new state
  var link = document.querySelector('.sc-compare-link');
  if (!link) return;
  if (FOCUSED_SAVED_IDX >= 0) {
    link.innerHTML = '📂 ' + SAVED_SCHEDULES.length + ' candidate' + (SAVED_SCHEDULES.length === 1 ? '' : 's') + ' — <b>←/→</b> cycles focused card, click anywhere else to switch back';
  } else {
    link.innerHTML = '📂 ' + SAVED_SCHEDULES.length + ' candidate' + (SAVED_SCHEDULES.length === 1 ? '' : 's') + ' — <a href="#" onclick="event.preventDefault();switchStep(4);return false;" style="color:var(--accent);text-decoration:underline;cursor:pointer">open Compare (step 4)</a>';
  }
}

function cycleFocusedSavedSchedule(dir) {
  if (!SAVED_SCHEDULES.length) return false;
  // If nothing focused, focus the first; otherwise cycle
  if (FOCUSED_SAVED_IDX < 0) {
    FOCUSED_SAVED_IDX = 0;
  } else {
    FOCUSED_SAVED_IDX = (FOCUSED_SAVED_IDX + dir + SAVED_SCHEDULES.length) % SAVED_SCHEDULES.length;
  }
  // Update focus class on cards WITHOUT re-rendering (preserves page scroll)
  var cards = document.querySelectorAll('#solve-compare .cmp-card');
  for (var k = 0; k < cards.length; k++) {
    cards[k].classList.toggle('cmp-focused', k === FOCUSED_SAVED_IDX);
  }
  updateSolverFocusHint();
  return true;  // event was consumed
}

function cycleSolverSolution(dir) {
  if (!SOLVER_FLAT || !SOLVER_FLAT.length) return false;
  var newIdx = SOLVER_IDX + dir;
  if (newIdx < 0 || newIdx >= SOLVER_FLAT.length) return false;
  // Click the prev/next button so the existing event handler + render
  // path runs (preserves the group-chip highlight, etc.)
  var btn = document.getElementById(dir < 0 ? 'solve-prev' : 'solve-next');
  if (btn && !btn.disabled) btn.click();
  return true;
}

// Render the Compare pane inside #solve-compare (a static div in
// step 4). Shows each candidate as a full card with sections, dropped
// list, and a mini odd/even grid. Page position is preserved across
// re-renders: this only replaces innerHTML, so the user can stay
// scrolled to whichever card they're looking at.
function renderComparePane() {
  var pane = document.getElementById('solve-compare');
  if (!pane) return;  // step 4 not in the DOM yet (e.g. before init)
  if (!SAVED_SCHEDULES.length) {
    pane.innerHTML = '<div class="cmp-empty" style="text-align:center;padding:2.5rem 1rem;color:var(--mut);font-size:.85rem;line-height:1.6">' +
      '<div style="font-size:1.6rem;margin-bottom:.3rem;opacity:.4">📂</div>' +
      '<div>No candidates yet.</div>' +
      '<div style="margin-top:.5rem;font-size:.75rem">Go to step 3 (Schedule) and click <b>➕ Add to candidates</b> on a solution you like, or click <b>📂 Load JSONs</b> above to bring in a file you exported earlier.</div>' +
      '</div>';
    return;
  }

  var h = '<div class="sc-compare-h" style="font-size:.85rem;font-weight:600;color:var(--accent);margin-bottom:.5rem;display:flex;align-items:center;gap:.6rem">' +
    '📂 Candidates <span class="sg-cnt" style="font-size:.7rem">' + SAVED_SCHEDULES.length + '</span>' +
    '<span style="font-size:.65rem;color:var(--mut);font-weight:400;margin-left:auto">Click a card to focus · ←/→ to cycle · click again to unfocus</span>' +
    '</div>';

  for (var i = 0; i < SAVED_SCHEDULES.length; i++) {
    var s = SAVED_SCHEDULES[i];
    var secList = '';
    var credSum = 0;
    for (var si = 0; si < s.sections.length; si++) {
      var sec = s.sections[si];
      credSum += parseFloat(sec.credits) || 0;
      var codeText = escapeHtml(sec.code || '');
      var clsText = sec.class_group ? ' <span style="color:var(--mut)">cls ' + escapeHtml(sec.class_group) + '</span>' : '';
      var tchText = sec.teachers && sec.teachers[0] ? ' · ' + escapeHtml(sec.teachers.join(', ')) : '';
      var schText = sec.schedule || formatSchedule(sec.slots);
      secList += '<div class="sc-sec" style="font-size:.72rem">' + codeText + clsText + tchText +
        (sec.credits ? ' · <b>' + sec.credits + '</b> cr' : '') +
        (renderLoadBadge(sec) ? ' · ' + renderLoadBadge(sec) : '') +
        (schText ? ' · <span style="color:var(--mut)">' + escapeHtml(schText) + '</span>' : '') +
        '</div>';
    }
    var droppedHtml = '';
    if (s.dropped && s.dropped.length) {
      droppedHtml = '<div class="sc-drops" style="margin-top:.3rem;font-size:.7rem">' +
        '<b style="color:var(--bad)">Dropped:</b> ' +
        s.dropped.map(function(c) {
          var n = SOLVER_codeToName[c];
          return n && n !== c
            ? '<span class="sc-code">' + escapeHtml(c) + '</span> ' + escapeHtml(n)
            : '<span class="sc-code">' + escapeHtml(c) + '</span>';
        }).join(', ') +
        '</div>';
    }

    h += '<div class="cmp-card' + (i === FOCUSED_SAVED_IDX ? ' cmp-focused' : '') + '" data-idx="' + i + '" ' +
      'style="background:var(--panel);border:1px solid var(--border);border-radius:6px;padding:.7rem;margin-bottom:.6rem;cursor:pointer;transition:border-color .12s,box-shadow .12s">' +
      '<div class="cmp-h" style="display:flex;align-items:center;gap:.5rem;margin-bottom:.4rem;flex-wrap:wrap">' +
        '<span class="cmp-label" style="font-size:.85rem;font-weight:600;color:var(--accent)">' + escapeHtml(s.label) + '</span>' +
        '<span class="sg-cnt" style="font-size:.7rem">' + s.sections.length + ' sections · ' + credSum.toFixed(1) + ' cr</span>' +
        (s.blocked
          ? '<span class="sg-cnt" style="font-size:.7rem;background:rgba(231,76,60,.18);color:#ff8a73" title="This schedule was saved with these blocked time zones. Click Apply to restore them.">🚫 ' + s.blocked.split('/').filter(function(x) { return x.trim(); }).length + ' blocked</span>'
          : '') +
        '<span style="margin-left:auto;display:flex;gap:.3rem">' +
          '<button class="ghost cmp-apply" data-i="' + i + '" style="font-size:.7rem;padding:.2rem .5rem">Apply</button>' +
          '<button class="ghost cmp-del"  data-i="' + i + '" style="font-size:.7rem;padding:.2rem .5rem;color:var(--bad)">🗑</button>' +
        '</span>' +
      '</div>' +
      '<div class="cmp-body">' + secList + droppedHtml + '</div>' +
      '<div class="cmp-grid" style="display:grid;grid-template-columns:1fr 1fr;gap:.5rem;margin-top:.5rem;font-size:.6rem">' +
        '<div>' +
          '<div style="font-size:.6rem;color:var(--accent);font-weight:500;margin-bottom:2px">Odd Weeks</div>' +
          '<table class="grid"><thead><tr><th>Pd</th><th>Mon</th><th>Tue</th><th>Wed</th><th>Thu</th><th>Fri</th><th>Sat</th><th>Sun</th></tr></thead>' +
            '<tbody class="cmp-grid-odd"></tbody></table>' +
        '</div>' +
        '<div>' +
          '<div style="font-size:.6rem;color:var(--accent);font-weight:500;margin-bottom:2px">Even Weeks</div>' +
          '<table class="grid"><thead><tr><th>Pd</th><th>Mon</th><th>Tue</th><th>Wed</th><th>Thu</th><th>Fri</th><th>Sat</th><th>Sun</th></tr></thead>' +
            '<tbody class="cmp-grid-even"></tbody></table>' +
        '</div>' +
      '</div>' +
      '</div>';
  }

  pane.innerHTML = h;

  // Wire card click → focus toggle; card buttons (Apply / Delete) → actions
  var cards = pane.querySelectorAll('.cmp-card');
  for (var k = 0; k < cards.length; k++) {
    cards[k].addEventListener('click', function(e) {
      // If the click was on a button, let that handler run instead
      if (e.target.closest('.cmp-apply, .cmp-del')) return;
      focusSavedCard(parseInt(this.dataset.idx, 10));
    });
  }
  var applyBtns = pane.querySelectorAll('.cmp-apply');
  for (var ai = 0; ai < applyBtns.length; ai++) {
    applyBtns[ai].addEventListener('click', function() {
      applySavedSchedule(parseInt(this.dataset.i, 10));
    });
  }
  var delBtns = pane.querySelectorAll('.cmp-del');
  for (var di = 0; di < delBtns.length; di++) {
    delBtns[di].addEventListener('click', function() {
      deleteSavedSchedule(parseInt(this.dataset.i, 10));
    });
  }

  // Render mini grids for each card
  for (var gi = 0; gi < SAVED_SCHEDULES.length; gi++) {
    var s2 = SAVED_SCHEDULES[gi];
    var blocks = sectionsToBlocks(s2.sections);
    var cardEl = pane.querySelector('.cmp-card[data-idx="' + gi + '"]');
    if (!cardEl) continue;
    renderGridBlocks(
      blocks,
      cardEl.querySelector('.cmp-grid-odd'),
      cardEl.querySelector('.cmp-grid-even'),
      null  // no legend in compare mini grid
    );
  }
}

function switchStep(n) {
  if (typeof n !== 'number' || n < 1 || n > 5) n = 1;
  CURRENT_STEP = n;

  // Update step chip styles
  var chips = document.querySelectorAll('.step-chip');
  for (var i = 0; i < chips.length; i++) {
    var stepNum = parseInt(chips[i].dataset.step, 10);
    chips[i].classList.toggle('active', stepNum === n);
    chips[i].classList.toggle('done', stepNum < n);
  }

  // Show the matching pane
  var panes = document.querySelectorAll('.step-pane');
  for (var j = 0; j < panes.length; j++) {
    var paneStep = parseInt(panes[j].dataset.stepPane, 10);
    panes[j].style.display = paneStep === n ? '' : 'none';
  }

  // Refresh per-step data
  if (n === 3) { updateSolveCodes(); }
  if (n === 4) { renderComparePane(); }
  if (n === 5) { renderBidPanel(); updateExportIcsButton(); }

  // Grid visibility: persistent in steps 1+2, hidden in 3+4+5 unless
  // the user toggled it on.
  GRID_VISIBLE = (n === 1 || n === 2);
  var gridToggle = document.getElementById('step-toggle-grid');
  if (gridToggle) {
    gridToggle.classList.toggle('off', !GRID_VISIBLE);
    var dot = document.getElementById('step-toggle-dot');
    if (dot) dot.textContent = GRID_VISIBLE ? '●' : '○';
  }
  applyGridVisibility();
}

// applyGridVisibility: show or hide the persistent grid in the current
// step pane. In steps 1+2, GRID_VISIBLE is true (default). In 3+4, the
// user controls via the "Grid" toggle in the stepper header.
function applyGridVisibility() {
  var stepContent = document.getElementById('step-content');
  if (!stepContent) return;
  // The persistent grid only exists in steps 1 and 2 (rendered in HTML).
  // In steps 3+4, this is a no-op since the pane doesn't contain a grid.
  var grid = stepContent.querySelector('.persistent-grid');
  if (grid) grid.style.display = GRID_VISIBLE ? '' : 'none';
}

// updateExportIcsButton: enable only when the schedule is conflict-free
// AND there is at least one pick. Sync to TIS is always enabled (with
// confirm dialog). The conflict check is the only real precondition for
// Export ICS — a conflicted schedule produces an invalid .ics file.
function updateExportIcsButton() {
  var btn = document.getElementById('btn-export-ics');
  if (!btn) return;
  var has = Object.keys(PICKED).length > 0;
  var noConflict = Object.keys(PICKED_CONFLICTS).length === 0;
  var ok = has && noConflict;
  btn.disabled = !ok;
  if (!ok) {
    btn.title = has
      ? 'Resolve schedule conflicts first — a conflicted schedule produces an invalid .ics file.'
      : 'Pick at least one section to export.';
  } else {
    btn.title = 'Download schedule as .ics';
  }
}

// Backward-compat: map old tab names to step numbers.
function switchTab(name) {
  if (name === 'grid') return switchStep(1);
  if (name === 'solve') return switchStep(3);
  if (name === 'bids') return switchStep(5);
  if (name === 'eval') {
    openNcesSheet();
    return;
  }
  switchStep(1);
}

// ── NCES detail sheet ──────────────────────────────────────────────────
// The old eval tab is gone — NCES is now a hover-brief on each card.
// Clicking a course card opens this near-fullscreen modal (the sheet).
// "View NCES detail" (from the brief) opens the same sheet.
function openCourseNcesModal(rwh) {
  // Look up the course by rwh, open the sheet, and fetch its brief.
  var course = null;
  if (rwh && PICKED[rwh]) course = PICKED[rwh];
  if (!course && rwh) {
    for (var j = 0; j < CAT.length; j++) {
      if (CAT[j].rwh === rwh) { course = CAT[j]; break; }
    }
  }
  if (!course) { openNcesSheet(); return; }
  ACTIVE_RWH = rwh;
  var sheet = document.getElementById('nces-sheet');
  var content = document.getElementById('nces-sheet-content');
  if (!sheet || !content) return;
  content.innerHTML = '<div class="ncn" style="padding:2rem;text-align:center">Loading NCES…</div>';
  sheet.classList.add('show');
  // Route the eval renderers into the sheet content, not the old eval-out.
  var oldEvalOut = EVAL_OUT;
  EVAL_OUT = content;
  sheet._restoreEvalOut = function() { EVAL_OUT = oldEvalOut; };
  fetchEval(course.code, course.teachers && course.teachers.join(','), ++_evalLoadId);
}

function openNcesSheet() {
  // If we have a focused card (ACTIVE_RWH), fetch + render it; otherwise
  // show the browse view as a fallback.
  var sheet = document.getElementById('nces-sheet');
  var content = document.getElementById('nces-sheet-content');
  if (!sheet || !content) return;
  content.innerHTML = '<div class="ncn" style="padding:2rem;text-align:center">Loading NCES…</div>';
  sheet.classList.add('show');
  if (ACTIVE_RWH) {
    var c = PICKED[ACTIVE_RWH] || (CAT || []).find(function(x) { return x.rwh === ACTIVE_RWH; });
    if (c) {
      // Route eval renderers into the sheet content (eval-out is gone).
      var oldEvalOut2 = EVAL_OUT;
      EVAL_OUT = content;
      sheet._restoreEvalOut = function() { EVAL_OUT = oldEvalOut2; };
      fetchEval(c.code, c.teachers && c.teachers[0], ++_evalLoadId);
      return;
    }
  }
  // Fallback: show browse
  content.innerHTML = '<div class="eval-toolbar">' +
    '<input type="text" id="sheet-eval-search" placeholder="Search by code…" style="flex:1;min-width:120px"/>' +
    '<select id="sheet-eval-sort"><option value="rating">Top rated</option><option value="reviews">Most reviewed</option><option value="name">A–Z</option></select>' +
    '</div><div id="sheet-eval-out"></div>';
  // Re-use the existing browse renderer, but in the sheet container
  var oldEvalOut = EVAL_OUT;
  EVAL_OUT = document.getElementById('sheet-eval-out');
  renderEvalBrowse();
  // Restore on close
  sheet._restoreEvalOut = function() { EVAL_OUT = oldEvalOut; };
}

function closeNcesSheet() {
  var sheet = document.getElementById('nces-sheet');
  if (!sheet) return;
  sheet.classList.remove('show');
  if (sheet._restoreEvalOut) { sheet._restoreEvalOut(); sheet._restoreEvalOut = null; }
}


// ── Event binding ─────────────────────────────────────────────────────────


// ── Bid panel (积分选课) ─────────────────────────────────────────────
// Visible only in personal mode + when at least one section is picked
// + no schedule conflicts. Refreshes the round info on every render.
function bidShouldShow() {
  if (MODE !== 'personal') return false;
  if (!Object.keys(PICKED).length) return false;
  return true;
}

function loadRound() {
  return getJSON('/api/tis/round' + sem())
    .then(function(d) {
      ROUND_INFO = {
        ok: !!d.ok,
        jffs: Number(d.jffs) || 0,
        ksrq: d.ksrq || '',
        jsrq: d.jsrq || '',
        lcmc: d.lcmc || '',
        xkfsdm: d.xkfsdm || '',
        xkms: d.xkms || '',
        message: d.message || '',
      };
      if (!d.ok && d.message) {
        // Round is closed — still allow the panel to render but show
        // the message so the user knows why bids won't sync.
        console.log('[bid] round not active:', d.message);
      }
    })['catch'](function(e) {
      console.warn('[bid] loadRound failed:', e);
    });
}

function computePickedConflicts() {
  PICKED_CONFLICTS = {};
  var keys = Object.keys(PICKED);
  for (var i = 0; i < keys.length; i++) {
    var a = PICKED[keys[i]];
    if (!a || !a.slots) continue;
    for (var j = 0; j < keys.length; j++) {
      if (i === j) continue;
      var b = PICKED[keys[j]];
      if (!b || !b.slots) continue;
      if (sectionsConflict(a.slots, b.slots)) {
        // When TIS-enrolled is "unquestionable" (IGNORE_TIS_ENROLLED off),
        // enrolled rwhs WIN conflicts — don't flag them as conflicted.
        // The non-enrolled rwh on the other side is still flagged.
        var aEnrolled = ENROLLED_RWH.has(keys[i]);
        var bEnrolled = ENROLLED_RWH.has(keys[j]);
        if (!IGNORE_TIS_ENROLLED && aEnrolled && bEnrolled) continue;
        if (!IGNORE_TIS_ENROLLED && aEnrolled) { PICKED_CONFLICTS[keys[j]] = true; continue; }
        if (!IGNORE_TIS_ENROLLED && bEnrolled) { PICKED_CONFLICTS[keys[i]] = true; continue; }
        PICKED_CONFLICTS[keys[i]] = true;
        PICKED_CONFLICTS[keys[j]] = true;
      }
    }
  }
}

function bidTotal() {
  var s = 0;
  for (var k in PICKED_BIDS) {
    if (PICKED_BIDS.hasOwnProperty(k)) s += Number(PICKED_BIDS[k]) || 0;
  }
  return s;
}

function renderBidPanel() {
  if (!bidShouldShow()) {
    BID_BAR.innerHTML = '';
    BID_BOXES.innerHTML = '';
    BID_STAT.style.display = 'none';
    if (BID_CONFLICT_BANNER) BID_CONFLICT_BANNER.textContent = '';
    if (BID_PANEL) BID_PANEL.classList.remove('has-conflicts');
    return;
  }
  computePickedConflicts();
  var hasConflict = Object.keys(PICKED_CONFLICTS).length > 0;
  var keys = Object.keys(PICKED);

  // Conflict warning — loud, non-blocking. The bid panel stays fully
  // interactive: the user can set bids on every picked rwh regardless of
  // conflicts. The submit button stays enabled too — TIS will accept the
  // bid updates (they're independent of enrollment), and the user's
  // enrollment attempt will fail separately due to the schedule overlap.
  if (BID_CONFLICT_BANNER) {
    if (hasConflict) {
      // Build a unique, priority-sorted list of conflicted course codes
      var seen = {};
      var codes = [];
      var ckeys = Object.keys(PICKED_CONFLICTS);
      for (var ci = 0; ci < ckeys.length; ci++) {
        var c = PICKED[ckeys[ci]];
        var cd = c && (c.code || c.kcdm) || '';
        if (cd && !seen[cd]) { seen[cd] = true; codes.push(cd); }
      }
      codes.sort();
      BID_CONFLICT_BANNER.textContent =
        '⚠ ' + codes.length + ' course(s) have schedule conflicts: ' +
        codes.join(', ') +
        '. Bids will sync to TIS, but enrollment will fail for conflicting sections until you resolve via Conflict-free Scheduler.';
    } else {
      BID_CONFLICT_BANNER.textContent = '';
    }
  }
  if (BID_PANEL) BID_PANEL.classList.toggle('has-conflicts', hasConflict);
  updateExportIcsButton();

  BID_STAT.style.display = 'block';
  var jffs = ROUND_INFO.jffs;
  var total = bidTotal();
  var overBudget = !!(jffs && total > jffs);

  // Over-budget banner — loud warning, but the submit button stays
  // enabled. TIS will reject the over-budget POST with a clear error,
  // and we'd rather the user see that exact response than hide the
  // failure mode behind a disabled button.
  if (BID_OVER_BANNER) {
    if (overBudget) {
      BID_OVER_BANNER.textContent = '⚠ Over budget: ' + total.toFixed(1) +
        ' / ' + jffs.toFixed(1) + ' pts — ' +
        (total - jffs).toFixed(1) + ' pts over. TIS will reject this — submit anyway to see the exact rejection, or lower bids first.';
    } else {
      BID_OVER_BANNER.textContent = '';
    }
  }
  if (BID_PANEL) BID_PANEL.classList.toggle('over-budget', overBudget);
  // Note: we deliberately do NOT disable the submit button here.
  // The user is a SUSTech student who knows their budget; hiding
  // the action would mask the real server-side response.

  if (jffs && total > jffs) {
    BID_STAT_TEXT.innerHTML = '🎯 ' + total + ' pts used · <span style="color:var(--bad)">⚠ over ' + (total - jffs).toFixed(1) + ' pts budget</span> — click to manage';
  } else if (total > 0) {
    BID_STAT_TEXT.innerHTML = '🎯 ' + total + ' pts used' + (jffs ? ' / ' + jffs.toFixed(1) + ' available' : '') + ' — click to manage';
  } else {
    BID_STAT.style.display = 'none';
  }
  // Header
  var phaseLabel = ROUND_INFO.lcmc || '积分选课';
  BID_META.textContent = phaseLabel +
    (ROUND_INFO.ksrq ? ' · ' + ROUND_INFO.ksrq.slice(5, 16) + ' → ' + ROUND_INFO.jsrq.slice(5, 16) : '');
  var jffs = ROUND_INFO.jffs;
  var total = bidTotal();
  BID_JFFS.textContent = (jffs ? jffs.toFixed(1) : '—') + ' pts available · using ' + total;
  if (jffs && total > jffs) {
    BID_JFFS.classList.add('over');
  } else {
    BID_JFFS.classList.remove('over');
  }

  // Bar
  if (!keys.length) {
    BID_BAR.innerHTML = '';
  } else {
    // Use max(jffs, total) for the scale so over-budget is still visible
    var scale = Math.max(jffs || 0, total, 1);
    var segs = '';
    for (var i = 0; i < keys.length; i++) {
      var rwh = keys[i];
      var bid = Number(PICKED_BIDS[rwh]) || 0;
      var pct = (bid / scale) * 100;
      var course = PICKED[rwh];
      segs += '<div class="bid-seg" data-ix="' + (i % 8) + '" data-rwh="' + escapeHtml(rwh) +
              '" style="width:' + pct.toFixed(2) + '%">' + bid + '</div>';
    }
    BID_BAR.innerHTML = segs;
  }

  // Boxes
  var boxes = '';
  for (var j = 0; j < keys.length; j++) {
    var rwh2 = keys[j];
    var c = PICKED[rwh2];
    var bid2 = Number(PICKED_BIDS[rwh2]) || 0;
    var displayName = c.name || c.name_en || c.section_name || '';
    boxes += '<div class="bid-box" data-rwh="' + escapeHtml(rwh2) + '">' +
      '<div class="bb-code">' + escapeHtml(c.code || '') +
        (c.class_group ? ' · ' + escapeHtml(c.class_group) : '') + '</div>' +
      '<div class="bb-bid">' + bid2 + '</div>' +
      '<div class="bb-name" title="' + escapeHtml(displayName) + '">' + escapeHtml(displayName) + '</div>' +
      '<input class="bb-edit" type="number" min="1" step="1" value="' + bid2 + '"/>' +
      '</div>';
  }
  BID_BOXES.innerHTML = boxes;
  attachBidBoxHandlers();
  BID_MSG.textContent = '';
  BID_MSG.className = 'bp-msg';
  updateAssignUnbiddedButton();
}

// ── Click / drag handlers on a bid box ─────────────────────────────────
function attachBidBoxHandlers() {
  var boxes = BID_BOXES.querySelectorAll('.bid-box');
  for (var i = 0; i < boxes.length; i++) {
    boxes[i].addEventListener('mousedown', onBidBoxMouseDown);
  }
}

var BID_CLICK_TIMER = null;
var BID_MOUSE_DOWN_AT = null;

function onBidBoxMouseDown(evt) {
  // Only primary button
  if (evt.button !== 0) return;
  var box = evt.currentTarget;
  var rwh = box.dataset.rwh;
  BID_MOUSE_DOWN_AT = { x: evt.clientX, y: evt.clientY, rwh: rwh, t: Date.now() };
  // Capture so we get mousemove even outside the box
  document.addEventListener('mousemove', onBidMouseMove);
  document.addEventListener('mouseup', onBidMouseUp);
}

function onBidMouseMove(evt) {
  if (!BID_MOUSE_DOWN_AT) return;
  var dx = Math.abs(evt.clientX - BID_MOUSE_DOWN_AT.x);
  var dy = Math.abs(evt.clientY - BID_MOUSE_DOWN_AT.y);
  if (dx + dy < 6) return;  // not a drag yet

  if (!BID_DRAG) {
    // Start a drag from the source box
    var srcBox = BID_BOXES.querySelector('[data-rwh="' + cssEsc(BID_MOUSE_DOWN_AT.rwh) + '"]');
    if (!srcBox) return;
    BID_DRAG = {
      sourceRwh: BID_MOUSE_DOWN_AT.rwh,
      sourceBox: srcBox,
      arrowEl: document.createElement('div'),
      targetRwh: null,
      lastX: evt.clientX,
      lastY: evt.clientY,
    };
    BID_DRAG.arrowEl.className = 'bid-arrow';
    document.body.appendChild(BID_DRAG.arrowEl);
    srcBox.classList.add('drag-source');
  }
  BID_DRAG.lastX = evt.clientX;
  BID_DRAG.lastY = evt.clientY;
  // Highlight nearest box
  var tgt = nearestBidBox(evt.clientX, evt.clientY, BID_DRAG.sourceRwh);
  BID_DRAG.targetRwh = tgt;
  // Update highlight
  var all = BID_BOXES.querySelectorAll('.bid-box');
  for (var i = 0; i < all.length; i++) {
    if (all[i].dataset.rwh === tgt) all[i].classList.add('drag-target');
    else all[i].classList.remove('drag-target');
  }
  drawArrow(BID_DRAG.sourceBox, evt.clientX, evt.clientY);
}

function onBidMouseUp(evt) {
  document.removeEventListener('mousemove', onBidMouseMove);
  document.removeEventListener('mouseup', onBidMouseUp);

  if (BID_DRAG) {
    // End of drag — show transfer overlay if there's a target
    var srcRwh = BID_DRAG.sourceRwh;
    var dstRwh = BID_DRAG.targetRwh;
    cleanupDrag();
    if (dstRwh && dstRwh !== srcRwh) {
      showTransferOverlay(srcRwh, dstRwh);
    }
  } else if (BID_MOUSE_DOWN_AT) {
    // Click (no drag) — enter edit mode
    var rwh = BID_MOUSE_DOWN_AT.rwh;
    var box = BID_BOXES.querySelector('[data-rwh="' + cssEsc(rwh) + '"]');
    if (box) startBidEdit(rwh, box);
  }
  BID_MOUSE_DOWN_AT = null;
}

function cleanupDrag() {
  if (!BID_DRAG) return;
  if (BID_DRAG.arrowEl && BID_DRAG.arrowEl.parentNode) {
    BID_DRAG.arrowEl.parentNode.removeChild(BID_DRAG.arrowEl);
  }
  var all = BID_BOXES.querySelectorAll('.bid-box');
  for (var i = 0; i < all.length; i++) {
    all[i].classList.remove('drag-source');
    all[i].classList.remove('drag-target');
  }
  BID_DRAG = null;
}

function nearestBidBox(x, y, excludeRwh) {
  var boxes = BID_BOXES.querySelectorAll('.bid-box');
  var best = null;
  var bestDist = 999999;
  for (var i = 0; i < boxes.length; i++) {
    if (boxes[i].dataset.rwh === excludeRwh) continue;
    var r = boxes[i].getBoundingClientRect();
    var cx = r.left + r.width / 2;
    var cy = r.top + r.height / 2;
    var d = Math.abs(x - cx) + Math.abs(y - cy);
    if (d < bestDist) { bestDist = d; best = boxes[i].dataset.rwh; }
  }
  return best;
}

function drawArrow(srcBox, x, y) {
  if (!BID_DRAG || !BID_DRAG.arrowEl) return;
  var r = srcBox.getBoundingClientRect();
  var sx = r.left + r.width / 2;
  var sy = r.top + r.height / 2;
  var svg = '<svg width="200" height="200" style="position:absolute;left:' + (x - 100) +
            'px;top:' + (y - 100) + 'px"><defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0 L10,5 L0,10 Z" fill="var(--accent)"/></marker></defs>' +
            '<line x1="' + (sx - (x - 100)) + '" y1="' + (sy - (y - 100)) + '" x2="100" y2="100" marker-end="url(#ah)"/></svg>';
  BID_DRAG.arrowEl.innerHTML = svg;
}

// ── Single-click edit ───────────────────────────────────────────────────
function startBidEdit(rwh, box) {
  if (BID_EDIT) cancelBidEdit();
  var original = Number(PICKED_BIDS[rwh]) || 0;
  var input = box.querySelector('.bb-edit');
  box.classList.add('editing');
  input.value = String(original);
  input.focus();
  input.select();
  BID_EDIT = { rwh: rwh, originalBid: original, inputEl: input };
  input.addEventListener('keydown', onBidEditKey);
  input.addEventListener('input', onBidEditInput);
  input.addEventListener('blur', onBidEditBlur);
}

// onBidEditInput: live-update the bid total + bar + compact summary as
// the user types. We don't touch the bb-bid div (it's hidden during edit).
function onBidEditInput() {
  if (!BID_EDIT) return;
  var v = parseInt(BID_EDIT.inputEl.value, 10);
  if (isNaN(v) || v < 1) return;        // keep last valid until user types a real number
  PICKED_BIDS[BID_EDIT.rwh] = v;
  updateBidTotals();
}

// updateBidTotals: refresh the live bits of the bid panel (header total,
// segment bar, compact right-column summary) without rebuilding the boxes
// (which would destroy the edit input).
function updateBidTotals() {
  var jffs = ROUND_INFO.jffs;
  var total = bidTotal();
  if (BID_JFFS) {
    BID_JFFS.textContent = (jffs ? jffs.toFixed(1) : '—') + ' pts available · using ' + total;
    if (jffs && total > jffs) BID_JFFS.classList.add('over');
    else BID_JFFS.classList.remove('over');
  }
  if (BID_BAR) {
    var keys = Object.keys(PICKED);
    var scale = Math.max(jffs || 0, total, 1);
    var segs = '';
    for (var i = 0; i < keys.length; i++) {
      var bid = Number(PICKED_BIDS[keys[i]]) || 0;
      var pct = (bid / scale) * 100;
      segs += '<div class="bid-seg" data-ix="' + (i % 8) + '" data-rwh="' +
        escapeHtml(keys[i]) + '" style="width:' + pct.toFixed(2) + '%">' + bid + '</div>';
    }
    BID_BAR.innerHTML = segs;
  }
  updateBidStat();
  updateAssignUnbiddedButton();
}

// Count how many picked rwhs currently have a 0 (or missing) bid
function countUnbiddedPicks() {
  var keys = Object.keys(PICKED);
  var n = 0;
  for (var i = 0; i < keys.length; i++) {
    var b = Number(PICKED_BIDS[keys[i]]) || 0;
    if (b <= 0) n++;
  }
  return n;
}

// Enable/disable the "Assign 1 to all unbidded" button based on whether
// any picks are currently zero-bid. Re-runs on every bid change so the
// button reflects live state.
function updateAssignUnbiddedButton() {
  var btn = document.getElementById('btn-bid-fill-unbidded');
  if (!btn) return;
  var n = countUnbiddedPicks();
  if (n <= 0) {
    btn.disabled = true;
    btn.style.opacity = '0.4';
    btn.style.cursor = 'not-allowed';
    btn.title = 'All picked rwhs already have a bid';
    // Reset label to the static form (no count) when nothing to do
    btn.textContent = '+1 to all unbidded';
  } else {
    btn.disabled = false;
    btn.style.opacity = '';
    btn.style.cursor = '';
    btn.title = 'Set bid = 1 on ' + n + ' unbidded rwh' + (n === 1 ? '' : 's');
    // Reflect the count in the button label so the user knows the impact
    btn.textContent = '+1 to all unbidded (' + n + ')';
  }
}

// "Assign 1 point to all unbidded" — set bid = 1 on every picked rwh
// that currently has 0 (or no bid). Re-renders the bid panel so the
// bar, totals, and box values update live.
function assignOneToUnbidded() {
  if (countUnbiddedPicks() <= 0) return;
  var keys = Object.keys(PICKED);
  var n = 0;
  for (var i = 0; i < keys.length; i++) {
    var b = Number(PICKED_BIDS[keys[i]]) || 0;
    if (b <= 0) {
      PICKED_BIDS[keys[i]] = 1;
      n++;
    }
  }
  if (n > 0) {
    flash('Assigned 1 pt to ' + n + ' unbidded pick' + (n === 1 ? '' : 's'), 'ok');
    // Re-render the panel; updateBidTotals updates totals + assigns the
    // new box values, but a full renderBidPanel is needed so the .bid-box
    // children reflect the new value (their <input> is rebuilt by JS).
    renderBidPanel();
  }
}

// updateBidStat: refresh just the compact "X pts used / Y available" summary
// in the right column. Called live from the bid-edit input listener.
function updateBidStat() {
  if (!BID_STAT || !BID_STAT_TEXT) return;
  var has = Object.keys(PICKED).length > 0;
  if (!has) { BID_STAT.style.display = 'none'; return; }
  var jffs = ROUND_INFO.jffs;
  var total = bidTotal();
  BID_STAT.style.display = 'block';
  if (jffs && total > jffs) {
    BID_STAT_TEXT.innerHTML = '🎯 ' + total + ' pts used · <span style="color:var(--bad)">⚠ over ' + (total - jffs).toFixed(1) + ' pts budget</span> — click to manage';
  } else {
    BID_STAT_TEXT.innerHTML = '🎯 ' + total + ' pts used' + (jffs ? ' / ' + jffs.toFixed(1) + ' available' : '') + ' — click to manage';
  }
}

function onBidEditKey(evt) {
  if (!BID_EDIT) return;
  if (evt.key === 'Escape') {
    // Revert: undo any in-flight PICKED_BIDS updates and refresh
    PICKED_BIDS[BID_EDIT.rwh] = BID_EDIT.originalBid;
    var rwhEsc = BID_EDIT.rwh;
    cancelBidEdit();
    renderBidPanel();
    updateBidTotals();
    evt.preventDefault();
  } else if (evt.key === 'Enter') {
    var v = parseInt(BID_EDIT.inputEl.value, 10);
    var valid = !isNaN(v) && v >= 1;
    var rwhEnter = BID_EDIT.rwh;
    if (valid) {
      PICKED_BIDS[rwhEnter] = v;
    } else {
      PICKED_BIDS[rwhEnter] = BID_EDIT.originalBid;
    }
    cancelBidEdit();
    renderBidPanel();
    updateBidTotals();
    evt.preventDefault();
  }
}

function onBidEditBlur() {
  // Same commit-or-revert semantics as Enter. Without this, PICKED_BIDS
  // was getting the new value from onBidEditInput (so the bar updated)
  // while the visible number reverted to originalBid on blur — leaving
  // the display out of sync with the bar.
  if (!BID_EDIT) return;
  var v = parseInt(BID_EDIT.inputEl.value, 10);
  var valid = !isNaN(v) && v >= 1;
  var rwh = BID_EDIT.rwh;
  if (valid) {
    PICKED_BIDS[rwh] = v;
  } else {
    // Invalid input (empty, zero, negative, NaN) — revert to original
    PICKED_BIDS[rwh] = BID_EDIT.originalBid;
  }
  cancelBidEdit();
  renderBidPanel();
  updateBidTotals();
}

function cancelBidEdit() {
  if (!BID_EDIT) return;
  BID_EDIT.inputEl.removeEventListener('keydown', onBidEditKey);
  BID_EDIT.inputEl.removeEventListener('input', onBidEditInput);
  BID_EDIT.inputEl.removeEventListener('blur', onBidEditBlur);
  var box = BID_EDIT.inputEl.parentNode;
  box.classList.remove('editing');
  // Don't restore input.value — the caller will renderBidPanel(), which
  // rebuilds the box HTML from the (now committed or reverted)
  // PICKED_BIDS[rwh]. Restoring the value here caused a desync where
  // the bar showed the new number but the visible bid reverted to the
  // old one.
  BID_EDIT = null;
}

// ── Transfer overlay (drag-and-release confirmation) ──────────────────
function _bidBoxName(c) {
  return c.name || c.name_en || c.section_name || c.code || '';
}

function showTransferOverlay(srcRwh, dstRwh) {
  var src = PICKED[srcRwh];
  var dst = PICKED[dstRwh];
  var srcBid = Number(PICKED_BIDS[srcRwh]) || 0;
  var dstBid = Number(PICKED_BIDS[dstRwh]) || 0;
  var srcName = _bidBoxName(src) + ' (' + (src.class_group || '?') + ')';
  var dstName = _bidBoxName(dst) + ' (' + (dst.class_group || '?') + ')';

  var overlay = document.createElement('div');
  overlay.className = 'bid-overlay';
  overlay.id = 'bid-transfer-overlay';
  overlay.innerHTML =
    '<div class="bo-box">' +
      '<div class="bo-h">Transfer credits</div>' +
      '<div class="bo-row"><span class="bo-from"></span></div>' +
      '<div class="bo-row"><span class="bo-to"></span></div>' +
      '<div class="bo-hint">How many to move from source?</div>' +
      '<input class="bo-in" type="number" min="1" max="' + (srcBid - 1) + '" step="1" value="1"/>' +
      '<div class="bo-hint">Enter to confirm · Esc / click-outside to cancel</div>' +
    '</div>';
  document.body.appendChild(overlay);

  var fromSpan = overlay.querySelector('.bo-from');
  var toSpan   = overlay.querySelector('.bo-to');
  var input    = overlay.querySelector('.bo-in');

  // paint(amt): re-renders the from/to rows with the projected values
  // after subtracting/adding `amt` points. Invalid amounts (NaN, <1)
  // fall back to showing the current state.
  function paint(amt) {
    if (isNaN(amt) || amt < 1) {
      fromSpan.textContent = 'from ' + srcName + ' · ' + srcBid + ' pts';
      toSpan.textContent   = 'to '   + dstName + ' · ' + dstBid + ' pts';
      return;
    }
    var newSrc = srcBid - amt;
    var newDst = dstBid + amt;
    fromSpan.textContent = 'from ' + srcName + ' · ' + srcBid + ' pts → ' + newSrc + ' pts';
    toSpan.textContent   = 'to '   + dstName + ' · ' + dstBid + ' pts → ' + newDst + ' pts';
  }
  paint(1);
  input.focus();
  input.select();

  function cleanup() {
    if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
    input.removeEventListener('keydown', onKey);
    input.removeEventListener('input', onInput);
    overlay.removeEventListener('click', onClickOut);
  }
  function onInput() {
    var amt = parseInt(input.value, 10);
    paint(amt);
  }
  function onKey(e) {
    if (e.key === 'Escape') { cleanup(); e.preventDefault(); return; }
    if (e.key === 'Enter') {
      var amt = parseInt(input.value, 10);
      if (isNaN(amt) || amt < 1 || amt >= srcBid) {
        input.style.borderColor = 'var(--bad)';
        return;
      }
      PICKED_BIDS[srcRwh] = srcBid - amt;
      PICKED_BIDS[dstRwh] = dstBid + amt;
      cleanup();
      renderBidPanel();
      e.preventDefault();
    }
  }
  function onClickOut(e) {
    if (e.target === overlay) cleanup();
  }
  input.addEventListener('keydown', onKey);
  input.addEventListener('input', onInput);
  overlay.addEventListener('click', onClickOut);
}

// ── Submit to TIS ───────────────────────────────────────────────────────
// BID_SUBMIT is the old bp-submit button (no longer in HTML — the new
// step-④ terminal action row has btn-sync-tis instead, wired in
// DOMContentLoaded). Guard the legacy handler in case the element comes
// back via a different template path.
if (BID_SUBMIT) BID_SUBMIT.addEventListener('click', function() {
  submitBids();
});

function submitBids() {
  // Group picks by endpoint. Enrolled courses go to updXkxsByyx; cart
  // courses go to upd_xkxsBygwc. The previous code hardcoded 'cart' for
  // everything, so bids on already-enrolled sections silently failed
  // (TIS rejected the request because the rwh wasn't in cart state).
  var picksByWhere = { cart: {}, enrolled: {} };
  for (var k in PICKED_BIDS) {
    if (PICKED_BIDS.hasOwnProperty(k) && PICKED[k]) {
      var w = ENROLLED_RWH.has(k) ? 'enrolled' : 'cart';
      picksByWhere[w][k] = PICKED_BIDS[k];
    }
  }
  var totalPicks = Object.keys(picksByWhere.cart).length +
                    Object.keys(picksByWhere.enrolled).length;
  if (!totalPicks) {
    BID_MSG.textContent = 'No picks to bid on.';
    BID_MSG.className = 'bp-msg err';
    return;
  }
  if (!confirm('Sync ' + totalPicks + ' bid(s) to TIS? This is a real action.')) return;
  BID_MSG.textContent = 'Submitting: syncing ' + totalPicks + ' bid(s)…';
  BID_MSG.className = 'bp-msg';
  BID_SUBMIT.disabled = true;

  function _sendBatch(where, picks) {
    return postJSON('/api/tis/bids' + sem(), {
      picks: picks,
      xkfsdm: ROUND_INFO.xkfsdm || '',
      where: where,
      jffs_limit: ROUND_INFO.jffs || null,
      dry_run: false,
    });
  }

  // Fire the batches sequentially would be safer for rate limiting, but
  // they're independent so we go in parallel and merge the results.
  var batches = [];
  if (Object.keys(picksByWhere.cart).length) {
    batches.push(_sendBatch('cart', picksByWhere.cart));
  }
  if (Object.keys(picksByWhere.enrolled).length) {
    batches.push(_sendBatch('enrolled', picksByWhere.enrolled));
  }

  Promise.all(batches).then(function(results) {
    BID_SUBMIT.disabled = false;
    var merged = { results: [], sum: 0, over_limit: false };
    for (var i = 0; i < results.length; i++) {
      var r = results[i] || {};
      if (r.over_limit) merged.over_limit = true;
      merged.sum += r.sum || 0;
      merged.results = merged.results.concat(r.results || []);
    }
    if (merged.over_limit) {
      BID_MSG.textContent = 'Over budget: ' + merged.sum + ' > ' + ROUND_INFO.jffs +
        ' pts. Adjust bids first.';
      BID_MSG.className = 'bp-msg err';
      return;
    }
    var okCount = 0;
    var failed = [];
    for (var fi = 0; fi < merged.results.length; fi++) {
      if (merged.results[fi].ok) okCount++;
      else failed.push(merged.results[fi]);
    }
    var total = merged.results.length;
    var failedSummary = '';
    if (failed.length) {
      var parts = [];
      for (var fj = 0; fj < failed.length; fj++) {
        var f = failed[fj];
        var code = (PICKED[f.rwh] && PICKED[f.rwh].code) || f.rwh;
        parts.push(code + ' (' + (f.message || 'no message') + ')');
      }
      failedSummary = ' · ' + failed.length + ' failed: ' + parts.join('; ');
    }
    BID_MSG.textContent = 'Committed: ' + okCount + '/' + total + ' bid(s) sent' +
      (merged.sum ? ' · total ' + merged.sum + ' pts' : '') + failedSummary;
    BID_MSG.className = 'bp-msg' + (okCount === total ? '' : ' err');
    loadRound().then(renderBidPanel);
  })['catch'](function(e) {
    BID_SUBMIT.disabled = false;
    BID_MSG.textContent = 'Network error: ' + e.message;
    BID_MSG.className = 'bp-msg err';
  });
}

// CSS escape for selector use
function cssEsc(s) { return String(s).replace(/["\\]/g, '\\$&'); }

// ROUND_INFO is now populated by loadCourses (single TIS call),
// so we no longer trigger a separate /api/tis/round fetch on mount.
// loadRound is kept as a manual refresh hook (post-submit, or if the
// user clicks Refresh) — it is NOT called on initial load.
renderBidPanel();

// Hook: after loadInfo → loadCourses completes, the round info is
// already embedded in the courses response, so just re-render the
// panel. (No second TIS call.)
var _origLoadInfo = loadInfo;
loadInfo = function() {
  return _origLoadInfo().then(function() {
    if (MODE === 'personal') renderBidPanel();
  });
};

document.addEventListener('DOMContentLoaded', function() {

  // Load any saved schedules from previous sessions (Compare pane source)
  loadSavedSchedules();

  // ── Stepper wiring (5-step workflow) ─────────────────────────────
  // The step chips are the new top-of-center tabs. Clicking a chip
  // jumps to that step. Current step is highlighted in accent; completed
  // steps turn OK green. The "Grid" toggle shows/hides the weekly grid
  // in steps 3-4-5 (it's persistent by default in 1-2).
  var stepChips = document.querySelectorAll('.step-chip');
  for (var sci = 0; sci < stepChips.length; sci++) {
    stepChips[sci].addEventListener('click', function() {
      switchStep(parseInt(this.dataset.step, 10));
    });
  }
  var gridToggle = document.getElementById('step-toggle-grid');
  if (gridToggle) {
    gridToggle.addEventListener('click', function() {
      GRID_VISIBLE = !GRID_VISIBLE;
      gridToggle.classList.toggle('off', !GRID_VISIBLE);
      var dot = document.getElementById('step-toggle-dot');
      if (dot) dot.textContent = GRID_VISIBLE ? '●' : '○';
      applyGridVisibility();
    });
  }

  // ── ←/→ keyboard nav in steps 3 + 4 ──────────────────────────────────
  // In step 3 (Schedule), ←/→ cycles solver solutions. In step 4
  // (Compare), ←/→ cycles between candidate cards (when one is
  // focused). Esc unfocuses. Page position is preserved (the solver
  // re-renders in place; the compare pane only toggles a CSS class).
  document.addEventListener('keydown', function(e) {
    if (CURRENT_STEP !== 3 && CURRENT_STEP !== 4) return;
    // Skip when typing in an input/textarea/contenteditable
    var t = e.target;
    if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
    if (e.key === 'ArrowLeft') {
      if (FOCUSED_SAVED_IDX >= 0) {
        if (cycleFocusedSavedSchedule(-1)) e.preventDefault();
      } else if (CURRENT_STEP === 3) {
        if (cycleSolverSolution(-1)) e.preventDefault();
      } else if (CURRENT_STEP === 4 && SAVED_SCHEDULES.length) {
        FOCUSED_SAVED_IDX = 0;  // focus first when nothing focused
        updateSolverFocusHint();
        var cards = document.querySelectorAll('#solve-compare .cmp-card');
        for (var k = 0; k < cards.length; k++) {
          cards[k].classList.toggle('cmp-focused', k === FOCUSED_SAVED_IDX);
        }
        e.preventDefault();
      }
    } else if (e.key === 'ArrowRight') {
      if (FOCUSED_SAVED_IDX >= 0) {
        if (cycleFocusedSavedSchedule(+1)) e.preventDefault();
      } else if (CURRENT_STEP === 3) {
        if (cycleSolverSolution(+1)) e.preventDefault();
      } else if (CURRENT_STEP === 4 && SAVED_SCHEDULES.length) {
        FOCUSED_SAVED_IDX = 0;
        updateSolverFocusHint();
        var cards2 = document.querySelectorAll('#solve-compare .cmp-card');
        for (var m = 0; m < cards2.length; m++) {
          cards2[m].classList.toggle('cmp-focused', m === FOCUSED_SAVED_IDX);
        }
        e.preventDefault();
      }
    } else if (e.key === 'Escape' && FOCUSED_SAVED_IDX >= 0) {
      FOCUSED_SAVED_IDX = -1;
      var cards3 = document.querySelectorAll('#solve-compare .cmp-card');
      for (var n = 0; n < cards3.length; n++) {
        cards3[n].classList.toggle('cmp-focused', false);
      }
      updateSolverFocusHint();
      e.preventDefault();
    } else if (e.key === 'Escape' && FOCUSED_SAVED_IDX >= 0) {
      // Esc unfocuses the saved card (back to solver arrow behavior)
      FOCUSED_SAVED_IDX = -1;
      var cards = document.querySelectorAll('#solve-compare .cmp-card');
      for (var k = 0; k < cards.length; k++) {
        cards[k].classList.remove('cmp-focused');
      }
      updateSolverFocusHint();
      e.preventDefault();
    }
  });

  // ── Step 4 terminal action wiring (Export ICS, Sync to TIS) ────────
  var btnExportIcs = document.getElementById('btn-export-ics');
  if (btnExportIcs) btnExportIcs.onclick = exportICS;
  var btnSyncTis = document.getElementById('btn-sync-tis');
  if (btnSyncTis) btnSyncTis.onclick = syncToTIS;
  // "Assign 1 to all unbidded" — fill in minimum bids on zero-bid picks
  var btnFillUnbidded = document.getElementById('btn-bid-fill-unbidded');
  if (btnFillUnbidded) btnFillUnbidded.onclick = assignOneToUnbidded;

  // ── NCES detail sheet wiring (replaces the eval tab) ──────────────
  var ncesSheet = document.getElementById('nces-sheet');
  var ncesSheetBackdrop = document.getElementById('nces-sheet-backdrop');
  var ncesSheetClose = document.getElementById('nces-sheet-close');
  if (ncesSheetClose) ncesSheetClose.addEventListener('click', closeNcesSheet);
  if (ncesSheetBackdrop) ncesSheetBackdrop.addEventListener('click', closeNcesSheet);
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape' && ncesSheet && ncesSheet.classList.contains('show')) {
      closeNcesSheet();
    }
  });

  // Load info (this also triggers auto-load of all courses)
  document.getElementById('btn-info').addEventListener('click', loadInfo);

  // ── NCES eval toolbar wiring ───────────────────────────────────────
  EVAL_SEARCH_EL  = document.getElementById('eval-search');
  EVAL_SORT_EL    = document.getElementById('eval-sort');
  EVAL_PREV_EL    = document.getElementById('eval-prev');
  EVAL_NEXT_EL    = document.getElementById('eval-next');
  EVAL_PAGE_INFO_EL = document.getElementById('eval-page-info');
  // Debounce search input (typing 5 chars should fire 1 NCES call, not 5)
  var _evalSearchTimer = null;
  if (EVAL_SEARCH_EL) {
    EVAL_SEARCH_EL.addEventListener('input', function() {
      if (_evalSearchTimer) clearTimeout(_evalSearchTimer);
      _evalSearchTimer = setTimeout(function() {
        _evalSearchTimer = null;
        EVAL_SEARCH = EVAL_SEARCH_EL.value.trim();
        EVAL_PAGE = 1;
        if (EVAL_MODE !== 'browse') {
          EVAL_MODE = 'browse';
          EVAL_OUT.innerHTML = '';
        }
        renderEvalBrowse();
      }, 400);
    });
    EVAL_SEARCH_EL.addEventListener('keydown', function(e) {
      if (e.key === 'Enter') {
        if (_evalSearchTimer) { clearTimeout(_evalSearchTimer); _evalSearchTimer = null; }
        EVAL_SEARCH = EVAL_SEARCH_EL.value.trim();
        EVAL_PAGE = 1;
        renderEvalBrowse();
      }
    });
  }
  if (EVAL_SORT_EL) {
    EVAL_SORT_EL.addEventListener('change', function() {
      EVAL_SORT = EVAL_SORT_EL.value;
      EVAL_PAGE = 1;
      renderEvalBrowse();
    });
  }
  if (EVAL_PREV_EL) {
    EVAL_PREV_EL.addEventListener('click', function() {
      if (EVAL_PAGE > 1) { EVAL_PAGE--; renderEvalBrowse(); }
    });
  }
  if (EVAL_NEXT_EL) {
    EVAL_NEXT_EL.addEventListener('click', function() {
      if (EVAL_PAGE < EVAL_TOTAL_PAGES) { EVAL_PAGE++; renderEvalBrowse(); }
    });
  }

  // Semester change — reload everything
  SEM_SEL.addEventListener('change', function() {
    ALL_CAT = [];
    CAT = [];
    loadInfo();
  });

  // Search button: in personal mode always hit the server (each xkfsdm
  // tab is its own paginated query against TIS, not a slice of a
  // client-side cache). In catalog mode, do client-side filter on the
  // full loaded 1503-course cache.
  document.getElementById('btn-search').addEventListener('click', onFilterChangeImmediate);

  // ── Mode-dependent DOM (Selection vs Catalog) ────────────────────────
  // Single source of truth for which rows show in which mode. Called
  // on cold load AND on every mode toggle so the two paths never drift.
  function applyModeVisibility() {
    // personal-only rows: shown in Selection, hidden in Catalog
    document.querySelectorAll('.personal-only').forEach(function(el) {
      el.style.display = MODE === 'personal' ? 'block' : 'none';
    });
    // task_type + scheduled rows: shown in Catalog, hidden in Selection
    var taskRow = document.getElementById('f-tasktype');
    var schedRow = document.getElementById('f-sched');
    if (taskRow) {
      var tr = taskRow.closest('.row');
      if (tr) tr.style.display = MODE === 'campus' ? 'flex' : 'none';
    }
    if (schedRow) {
      var sr = schedRow.closest('.row');
      if (sr) sr.style.display = MODE === 'campus' ? 'flex' : 'none';
    }
    // h2 heading text
    var h2 = document.getElementById('mode-h2');
    if (h2) h2.textContent = MODE === 'personal' ? 'Selection' : 'Catalog';
    // mode button active styling
    document.querySelectorAll('.mode-btn').forEach(function(b) {
      var active = b.dataset.mode === MODE;
      b.classList.toggle('active', active);
      b.style.border = active ? '1px solid var(--accent)' : 'none';
      b.style.background = active ? 'rgba(91,157,255,.1)' : 'transparent';
    });
  }

  // Fetch + load the right data set for the current mode. Called on
  // cold load AND on every mode toggle. Uses _modeLoadId to guard both
  // the course-types → loadInfo chain AND loadCourses responses against
  // stale results from fast toggling.
  function loadForMode() {
    var loadId = ++_modeLoadId;  // will be captured by loadCourses() inside loadInfo()
    ALL_CAT = []; CAT = [];
    if (MODE === 'personal') {
      getJSON('/api/tis/course-types' + sem()).then(function(d) {
        if (loadId !== _modeLoadId) return;  // stale — another toggle happened
        if (d.course_types && d.course_types.length) populateCourseTypes(d.course_types);
        if (loadId !== _modeLoadId) return;  // check again after populateCourseTypes
        loadInfo();
      })['catch'](function() { if (loadId === _modeLoadId) loadInfo(); });
    } else {
      loadInfo();
    }
  }

  // Mode switch
  document.querySelectorAll('.mode-btn').forEach(function(btn) {
    btn.addEventListener('click', function() {
      var newMode = btn.dataset.mode;
      if (newMode === MODE) return;
      MODE = newMode;
      applyModeVisibility();
      loadForMode();
    });
  });

  // Client-side filter when any filter changes. Catalog mode filters
  // the full 1503-course cache. Personal mode re-queries TIS because
  // each xkfsdm is a separate paginated query, not a slice.
  //
  // Debounce: typing in the keyword field would otherwise fire 1 TIS
  // call per keystroke (input + change events). TIS rate-limits at
  // ~1 call per 3-5s, so we wait 500ms after the last keystroke
  // before firing.
  var _searchDebounce = null;
  function onFilterChange() {
    if (_searchDebounce) clearTimeout(_searchDebounce);
    _searchDebounce = setTimeout(function() {
      _searchDebounce = null;
      if (MODE === 'campus' && ALL_CAT.length) filterResultsClientSide();
      else loadCourses();
    }, 500);
  }
  function onFilterChangeImmediate() {
    if (_searchDebounce) { clearTimeout(_searchDebounce); _searchDebounce = null; }
    if (MODE === 'campus' && ALL_CAT.length) filterResultsClientSide();
    else loadCourses();
  }
  var filterEls = [KW, F_COL, F_TASK, F_CAT, F_CAM, F_LANG, F_CULT, F_TEACHER, F_SCH];
  for (var fi = 0; fi < filterEls.length; fi++) {
    // Selects / checkboxes: fire on change only (no debounce needed)
    if (filterEls[fi] === KW) {
      // Keyword input: debounce so typing doesn't spam TIS
      filterEls[fi].addEventListener('input', onFilterChange);
    } else {
      filterEls[fi].addEventListener('change', onFilterChangeImmediate);
    }
  }

  // ── Refresh: catalog + load — single button now (formerly two
  //    buttons: "Refresh catalog" + "🔄 Refresh load"). User feedback
  //    that the info is "stable" and only needs refreshing on page
  //    entry / explicit manual action — no need for two separate
  //    triggers. Both happen sequentially: refresh catalog first
  //    (so the user's filter set has fresh course data), then refresh
  //    load (so the [N] / [M] badges fill in).
  function _doRefreshCatalog(after) {
    return postJSON('/api/tis/refresh' + sem(), {}).then(function(d) {
      if (d.ok) {
        STAT.textContent = 'Refreshed: ' + d.count + ' courses.';
        loadInfo();
        if (after) after(null, d);
      } else {
        STAT.textContent = 'Refresh failed: ' + (d.error || 'unknown');
        if (after) after(new Error(d.error || 'refresh failed'));
      }
    })['catch'](function(e) {
      STAT.textContent = 'Refresh error: ' + e.message;
      if (after) after(e);
    });
  }
  function _doRefreshLoad(btn, after) {
    if (btn.disabled) return Promise.resolve();
    btn.disabled = true;
    var prev = btn.textContent;
    btn.textContent = '⏳ Refreshing load…';
    var qs = sem() + '&mode=personal';
    qs += '&keyword=' + encodeURIComponent(KW.value);
    qs += '&teacher=' + encodeURIComponent(F_TEACHER.value);
    if (MODE === 'personal' && F_COL.value && COLLEGE_MAP[F_COL.value]) {
      qs += '&college=' + encodeURIComponent(COLLEGE_MAP[F_COL.value]);
    } else {
      qs += '&college=' + encodeURIComponent(F_COL.value);
    }
    qs += '&campus=' + encodeURIComponent(F_CAM.value);
    if (MODE === 'personal' && F_CAT.value && CATEGORY_MAP[F_CAT.value]) {
      qs += '&category=' + encodeURIComponent(CATEGORY_MAP[F_CAT.value]);
    } else {
      qs += '&category=' + encodeURIComponent(F_CAT.value);
    }
    if (MODE === 'personal' && F_LANG.value && LANGUAGE_MAP[F_LANG.value]) {
      qs += '&language=' + encodeURIComponent(LANGUAGE_MAP[F_LANG.value]);
    } else {
      qs += '&language=' + encodeURIComponent(F_LANG.value);
    }
    qs += '&cultivation=' + encodeURIComponent(F_CULT.value);
    qs += '&xkfsdm=' + encodeURIComponent((document.getElementById('f-xkfsdm') || {}).value || '');
    qs += '&ignore_conflicts=' + (document.getElementById('f-ign-conf') && document.getElementById('f-ign-conf').checked ? '1' : '');
    qs += '&ignore_zero_capacity=' + (document.getElementById('f-ign-zero') && document.getElementById('f-ign-zero').checked ? '1' : '');
    qs += '&weekday=' + encodeURIComponent((document.getElementById('f-wday') || {}).value || '');
    qs += '&period_start=' + encodeURIComponent((document.getElementById('f-ps') || {}).value || '');
    qs += '&period_end=' + encodeURIComponent((document.getElementById('f-pe') || {}).value || '');
    qs += '&page_size=500';

    return postJSON('/api/tis/refresh-load' + qs, {}).then(function(d) {
      btn.disabled = false;
      btn.textContent = prev;
      if (!d.ok) {
        STAT.textContent = '⚠ Load refresh unavailable: ' + (d.message || d.error || 'unknown');
        if (after) after(new Error(d.message || d.error || 'load failed'));
        return;
      }
      var n = d.with_count || 0;
      var fetched = d.fetched || 0;
      // Merge: only overwrite entries for rwhs that came back with a
      // count, so old cache survives for rwhs not in this search's
      // page (rare — the call is paginated, but defensive).
      var keys = Object.keys(d.loads || {});
      for (var i = 0; i < keys.length; i++) {
        LOAD_BY_RWH[keys[i]] = d.loads[keys[i]];
      }
      LOAD_FETCHED_AT = Date.now();
      try {
        localStorage.setItem('tis-load-cache', JSON.stringify({
          ts: LOAD_FETCHED_AT,
          loads: LOAD_BY_RWH,
        }));
      } catch (e) {}
      // Re-render every surface that shows a load badge.
      rerenderAllWithLoad();
      STAT.textContent = '✓ Catalog + load refreshed: ' + n + ' / ' + fetched + ' got live counts';
      if (after) after(null, d);
    })['catch'](function(e) {
      btn.disabled = false;
      btn.textContent = prev;
      STAT.textContent = '⚠ Load refresh failed: ' + e.message;
      if (after) after(e);
    });
  }

  // Single combined button — runs catalog refresh first, then load refresh.
  // User said the underlying data is stable, so one combined trigger
  // covers both without making them pick.
  document.getElementById('btn-refresh-all').addEventListener('click', function() {
    var btn = document.getElementById('btn-refresh-all');
    var prev = btn.textContent;
    btn.disabled = true;
    btn.textContent = '⏳ Refreshing…';
    _doRefreshCatalog(function(err) {
      if (err) {
        btn.disabled = false;
        btn.textContent = prev;
        return;
      }
      _doRefreshLoad(btn, function() {
        btn.disabled = false;
        btn.textContent = prev;
      });
    });
  });

  // Hydrate load cache from localStorage on init so a returning user
  // sees last-known counts while the TIS call is in flight.
  try {
    var raw = localStorage.getItem('tis-load-cache');
    if (raw) {
      var c = JSON.parse(raw);
      // TTL: 10 min — TIS numbers move in real time but re-hitting
      // every load is what triggers their rate limit. A fresh click
      // overwrites.
      if (c && c.ts && (Date.now() - c.ts) < 10 * 60 * 1000 && c.loads) {
        LOAD_BY_RWH = c.loads;
        LOAD_FETCHED_AT = c.ts;
        rerenderAllWithLoad();
      } else {
        localStorage.removeItem('tis-load-cache');
      }
    }
  } catch (e) {}

  // Enter key on search input — fire immediately, cancel any debounce
  KW.addEventListener('keydown', function(e) {
    if (e.key === 'Enter') onFilterChangeImmediate();
  });

  // Enrolled: no longer exposed via a button. The "Ignore TIS enrolled"
  // tickbox (further down) drives loadEnrolled() — flipping it triggers
  // the load automatically. User feedback that the explicit button was
  // redundant noise in the right panel.

  // Solve
  document.getElementById('btn-solve').addEventListener('click', solve);
  // grid-solve button was removed when the tab structure became the
  // stepper. The "🎯 Solve conflicts" button in the step-1 grid is now
  // just the Solve step itself; clicking the step-3 chip navigates
  // there. Guard in case a future template brings grid-solve back.
  var gridSolveBtn = document.getElementById('grid-solve');
  if (gridSolveBtn) gridSolveBtn.addEventListener('click', function() {
    switchTab('solve');
    setTimeout(solve, 100);
  });

  // ── Compare-step (step 4) toolbar wiring ────────────────────────
  // The compare step has three primary actions: load more JSONs into
  // the candidate list, clear the candidate list, and export the
  // whole list as a single .zip. We also support drag-drop of JSON
  // files anywhere on the page (handled in the file-loader section
  // below) — these bindings only cover the explicit toolbar buttons.
  var btnLoadCandidates = document.getElementById('btn-load-candidates');
  var candidatesFileInput = document.getElementById('candidates-file-input');
  if (btnLoadCandidates && candidatesFileInput) {
    btnLoadCandidates.addEventListener('click', function() { candidatesFileInput.click(); });
    candidatesFileInput.addEventListener('change', function(e) {
      loadCandidatesFromFiles(e.target.files);
      // Reset the input so the same file can be loaded twice in a row
      e.target.value = '';
    });
  }
  var btnClearCandidates = document.getElementById('btn-clear-candidates');
  if (btnClearCandidates) btnClearCandidates.addEventListener('click', clearAllCandidates);
  var btnExportZip = document.getElementById('btn-export-candidates-zip');
  if (btnExportZip) btnExportZip.addEventListener('click', exportAllCandidatesAsZip);
  // Block-time editor: BLOCKED is the single source of truth (in-memory).
  // The block grid (step 2) is the primary editor; the hidden #blocked-input
  // is a legacy fallback for power users typing the compact syntax directly.
  // We render the grid unconditionally — it doesn't depend on the input.
  renderBlockGrid();
  var blockedEl = document.getElementById('blocked-input');
  if (blockedEl) {
    loadBlockedFromInput();  // initial population from text (if any)
    blockedEl.addEventListener('change', function() {
      loadBlockedFromInput();
      renderGrid();
      if (BLOCK_BODY) applyBlockedVisual(BLOCK_BODY);
    });
  }
  // Drag-to-reorder picked list = reprioritise for the solver
  attachPickedDragHandlers();

  // On cold load, run the same setup the mode-toggle handler runs.
  // Without this, the page starts in the default mode (Selection) but
  // nothing in the DOM reflects it — the xkfsdm dropdown stays empty,
  // Task Type / Only with schedule stay visible, etc. Sharing the same
  // functions with the toggle handler means the two paths can't drift.
  applyModeVisibility();
  loadForMode();
  // Initialize the stepper. Step 1 is the default; switchStep sets the
  // chip active/done classes and shows the right pane.
  switchStep(1);

  // Data model: page starts BLANK. Picks live in memory only. To populate:
  //   1) click "📂 Load file" and pick a JSON file, OR
  //   2) drag a JSON file onto the page (anywhere).
  // There is no localStorage auto-restore — the previous "auto-save on
  // every change + auto-restore on load" design made the file path
  // unclear (the data existed in localStorage but no file was shown).
  // Now the user is always explicit about which file they're working with.
  initDragDropLoad();
  // ── Picked-panel action buttons (must exist in DOM before any user
  //     can interact with them, even on a fresh page with no picks). ──
  initPickedActions();

  // ── END DOMContentReady ──────────────────────────────────────────
});
// ── END outer IIFE ────────────────────────────────────────────────

// ── Picked-panel actions (right column) ──────────────────────────────────
// The right column is the "picks management" surface — local data (Save,
// Load) + the one server-side op on ENROLLED_RWH (Drop all). The terminal
// actions on the picks (Export ICS, Sync to TIS) live in step ④ of the
// stepper — see addStep4TerminalActions() in commit 2.
//
// Layout (top → bottom in the right column):
//   [pick-stat]   ← "14 sections · 10 courses · 25.0 Credits"
//   [bid-stat]    ← hidden when PICKED is empty
//   [HEADER]      ← ☐ Select-all · 0 / 14 selected · [✕ Remove selected]
//   [pick-list]   ← per-card checkboxes (mirrors the left-panel pattern)
//   [dataRow]     ← 💾 Save 14 picks · 📂 Load file
//   [divider]     ← "Server-side — affects TIS"
//                   [🗑 Drop all enrolled]
//   [enrolled]
function initPickedActions() {
  var pickedCol = document.getElementById('picked-col');
  if (!pickedCol) return;
  var pickList = document.getElementById('pick-list');
  if (!pickList) return;
  if (document.getElementById('picked-data-actions')) return;

  // HEADER: select-all + count + remove-selected. Above the pick-list.
  // Two-row layout to fit in the narrow right column without text wrap:
  //   row 1: ☑ All  (14 selected)            [✕ Remove N]
  //   row 2: [💾 Save N picks] [📂 Load file]    ← local file (under save/load)
  var header = document.createElement('div');
  header.id = 'picked-bulk-header';
  header.className = 'picked-bulk-header';
  header.innerHTML =
    '<div class="picked-bulk-row1">' +
      '<label class="picked-select-all-wrap" title="Tick all visible picks">' +
        '<input type="checkbox" id="picked-select-all">' +
        '<span>All</span>' +
      '</label>' +
      '<span class="picked-selected-count" id="picked-selected-count">0 / 0 selected</span>' +
      '<button class="picked-remove-selected-btn" id="btn-remove-selected" title="Remove all ticked picks (confirm for many)">✕ Remove</button>' +
    '</div>' +
    '<div class="picked-bulk-row2">' +
      '<button class="save-file-btn" id="btn-save-picks" title="Save your selection to a JSON file (works any time, even with conflicts)">💾 Save <span id="save-count">0 picks</span></button>' +
      '<button class="load-file-btn" id="btn-load-picks" title="Load picks from a JSON file (will replace your current selection)">📂 Load file</button>' +
    '</div>' +
    '<div class="picked-file-info" id="picked-file-info" title="Local file you last saved/loaded"></div>';

  // Drop all enrolled: server-side op on ENROLLED_RWH (different state
  // from PICKED). Different intent from "sync my picks" — kept here
  // because the right column is where enrollment state is shown. The
  // button name is the description; no "Server-side — affects TIS"
  // divider is needed since the title attribute + the confirm() call
  // already make the destructive intent unambiguous.
  //
  // Visibility is gated on IGNORE_TIS_ENROLLED: when the user has
  // marked TIS-enrolled as "unquestionable" (toggle = off), we hide
  // this button entirely — the entire point of the flag is "you can't
  // touch TIS-enrolled." Toggle is right next to it so the user sees
  // the relationship.
  var dropBtn = document.createElement('div');
  dropBtn.id = 'picked-drop-wrap';
  dropBtn.className = 'picked-drop-wrap';
  dropBtn.innerHTML =
    '<label class="ignore-tis-enrolled-wrap" title="When OFF, TIS-enrolled courses are unquestionable — solver keeps them, can\'t be dropped here, win every conflict">' +
      '<input type="checkbox" id="ignore-tis-enrolled" checked>' +
      '<span>Ignore TIS enrolled</span>' +
    '</label>' +
    '<button class="drop-all-tis-btn" id="btn-drop-all" title="Drop every currently-enrolled section on TIS (destructive — will prompt for confirmation)">🗑 Drop all enrolled courses in TIS</button>';

  // Wire the toggle. Three things flip when the user changes this:
//
//   1. The local IGNORE_TIS_ENROLLED state flag (read by the solver,
//      conflict banner, and conflict-badges code).
//   2. The 🗑 Drop-all-enrolled button visibility (hidden when locked
//      — "unquestionable" means we won't let the user mass-drop them).
//   3. The right-panel 🔒 lock badges + lock banner (re-rendered).
//
// And the toggle ALSO doubles as the trigger to load TIS-enrolled data.
// The user might never click "Load my enrolled" explicitly — flipping
// this checkbox to OFF is the more meaningful action (now that TIS-
// enrolled is locked, they need it visible). If ENROLLED_RWH is empty
// when the toggle fires, we call loadEnrolled() so the grid + right
// panel + solver all have the data they need. If we already loaded,
// we just re-render the affected views (no refetch).
  var ignoreChk = dropBtn.querySelector('#ignore-tis-enrolled');
  var dropBtnEl = dropBtn.querySelector('#btn-drop-all');
  function _syncIgnoreFlag() {
    IGNORE_TIS_ENROLLED = ignoreChk.checked;
    dropBtnEl.style.display = IGNORE_TIS_ENROLLED ? '' : 'none';
    if (ENROLLED_OUT) ENROLLED_OUT.dataset.ignoreFlag = IGNORE_TIS_ENROLLED ? '1' : '0';
  }
  function _onIgnoreFlagChange() {
    var prevIgnore = IGNORE_TIS_ENROLLED;
    IGNORE_TIS_ENROLLED = ignoreChk.checked;
    dropBtnEl.style.display = IGNORE_TIS_ENROLLED ? '' : 'none';
    if (ENROLLED_OUT) ENROLLED_OUT.dataset.ignoreFlag = IGNORE_TIS_ENROLLED ? '1' : '0';
    // Re-render the right-panel enrolled list (badge/banner state changed)
    // and the step-3 grid (solver-affecting change). We don't refetch if
    // the data is already loaded — flag flipping alone doesn't change the
    // underlying TIS state, only how the module treats it.
    if (ENROLLED_RWH.size === 0) {
      // Cold start — flip = "go fetch the data so I can see the locks"
      loadEnrolled();
      return;
    }
    // Hot reload — data is in memory, just re-render the views that read
    // the flag. renderPicked() picks up the 🔒 badge change on already-
    // loaded picks; renderGrid3() re-runs with the same data; the solver
    // re-runs only if its results are already on screen (step 3 was the
    // active pane when the user flipped).
    renderPicked();
    renderGrid3();
    // Refresh the right-panel enrollment list. The simplest path is to
    // call loadEnrolled() again — it's a single GET, idempotent, and
    // re-renders the panel from scratch with the correct flag-driven UI.
    loadEnrolled();
    // If the solver result is currently visible on step 3, re-run it so
    // the new locked_rwhs take effect on the suggested combinations.
    if (typeof SOLVE_OUT !== 'undefined' && SOLVE_OUT && SOLVE_OUT.innerHTML &&
        SOLVE_OUT.querySelector('.solved')) {
      // Triggered by user flipping the flag — don't show a separate
      // "solving…" status, the grid already updates.
      solve();
    }
  }
  ignoreChk.addEventListener('change', _onIgnoreFlagChange);
  _syncIgnoreFlag();

  pickList.parentNode.insertBefore(header, pickList);
  pickList.parentNode.insertBefore(dropBtn, pickList);

  // Wire the bulk header
  var selectAllCb = document.getElementById('picked-select-all');
  selectAllCb.addEventListener('change', function() {
    var want = selectAllCb.checked;
    var keys = Object.keys(PICKED);
    if (want) {
      for (var i = 0; i < keys.length; i++) PICKED_CHECKED[keys[i]] = true;
    } else {
      PICKED_CHECKED = {};
    }
    renderPicked();  // re-render so per-card checkboxes reflect the new state
  });

  document.getElementById('btn-remove-selected').onclick = removeSelectedPicks;
  document.getElementById('btn-save-picks').onclick = savePicksToFile;
  document.getElementById('btn-load-picks').onclick = loadPicksFromFile;
  document.getElementById('btn-drop-all').onclick = dropAllEnrolled;

  // Sync the new header/button labels to the CURRENT pick state. The
  // init order is: loadPicksFromStorage() → applyPicksFromData() (which
  // triggers renderPicked → updatePickedActionsState, but the elements
  // didn't exist yet) → initPickedActions (now). So we sync once more here.
  updatePickedActionsState();
}

// Refresh the bulk-header state + save-button label from current PICKED
// and PICKED_CHECKED. Called from renderPicked() (which is in the cascade).
function updatePickedActionsState() {
  var total = Object.keys(PICKED).length;
  var checked = Object.keys(PICKED_CHECKED).length;
  var countEl = document.getElementById('picked-selected-count');
  if (countEl) countEl.textContent = checked + ' / ' + total + ' selected';
  var selectAllCb = document.getElementById('picked-select-all');
  if (selectAllCb) {
    selectAllCb.checked = total > 0 && checked === total;
    selectAllCb.indeterminate = checked > 0 && checked < total;
  }
  var saveCount = document.getElementById('save-count');
  if (saveCount) saveCount.textContent = total + (total === 1 ? ' pick' : ' picks');
  var removeBtn = document.getElementById('btn-remove-selected');
  if (removeBtn) {
    removeBtn.disabled = checked === 0;
    removeBtn.textContent = checked > 0
      ? '✕ Remove ' + checked
      : '✕ Remove';
  }
  var loadBtn = document.getElementById('btn-load-picks');
  if (loadBtn) {
    loadBtn.title = 'Load picks from a JSON file (will replace your ' +
      total + ' current ' + (total === 1 ? 'pick' : 'picks') + ')';
  }
  // File-info line: shows the last-saved/loaded file so the user always
  // knows which file their in-memory picks are anchored to. There is no
  // localStorage cache — when nothing has been loaded or saved yet, this
  // line tells the user to use the Load button or drag a JSON file in.
  var fileInfo = document.getElementById('picked-file-info');
  if (fileInfo) {
    if (CURRENT_FILE) {
      fileInfo.innerHTML = '<span class="fi-label">' +
        (CURRENT_FILE.kind === 'saved' ? '📄 last saved → ' : '📄 loaded ← ') +
        '</span><span class="fi-name" title="' + escapeHtml(CURRENT_FILE.name) + '">' +
        escapeHtml(CURRENT_FILE.name) + '</span>';
    } else {
      fileInfo.innerHTML = '<span class="fi-label">📄 No file loaded — pick a file or drag a JSON onto the page</span>';
    }
  }
}

function removeSelectedPicks() {
  var rwhs = Object.keys(PICKED_CHECKED);
  if (!rwhs.length) return;
  var msg = rwhs.length === 1
    ? 'Remove 1 picked section?'
    : 'Remove ' + rwhs.length + ' picked sections?';
  if (!confirm(msg)) return;
  // Snapshot the keys before mutating (removePicked touches PICKED_CHECKED
  // and we don't want to mutate-while-iterating).
  var toRemove = rwhs.slice();
  for (var i = 0; i < toRemove.length; i++) {
    removePicked(toRemove[i]);
  }
  PICKED_CHECKED = {};
  updatePickedActionsState();
}

// ── File-based save/load (no localStorage) ──────────────────────────────
// Picks live in memory only. There is no localStorage auto-save/auto-restore
// — the user explicitly loads a file (via the button or by drag-drop) and
// explicitly saves to a new timestamped file when they're done.
//
// File shape (versioned so future format changes can detect old data and
// discard rather than crash):
//   {
//     version: 1,
//     picks: [ { ...courseObj... }, ... ],
//     savedAt: "ISO-8601 string"
//   }

function loadPicksFromFile() {
  var input = document.createElement('input');
  input.type = 'file'; input.accept = 'application/json,.json';
  input.onchange = function() {
    var file = input.files && input.files[0];
    if (!file) return;
    readPicksFile(file, 'replace');
  };
  input.click();
}

// Drag-and-drop: drop any *.json onto the page to load it. Shows a visual
// overlay while dragging so the user knows the drop zone is active.
function initDragDropLoad() {
  var overlay = document.createElement('div');
  overlay.id = 'drop-overlay';
  overlay.className = 'drop-overlay';
  overlay.innerHTML = '<div class="drop-overlay-inner">📂 Drop a JSON picks file to load</div>';
  document.body.appendChild(overlay);

  // dragenter/leave fire on every child — track depth so the overlay
  // stays visible while the cursor moves over nested elements.
  var dragDepth = 0;
  var hasFiles = function(e) {
    return e.dataTransfer && Array.from(e.dataTransfer.types || []).indexOf('Files') !== -1;
  };
  document.addEventListener('dragenter', function(e) {
    if (!hasFiles(e)) return;
    dragDepth++;
    overlay.classList.add('show');
  });
  document.addEventListener('dragleave', function() {
    dragDepth = Math.max(0, dragDepth - 1);
    if (dragDepth === 0) overlay.classList.remove('show');
  });
  document.addEventListener('dragover', function(e) {
    if (hasFiles(e)) { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; }
  });
  document.addEventListener('drop', function(e) {
    e.preventDefault();
    dragDepth = 0;
    overlay.classList.remove('show');
    var files = e.dataTransfer && e.dataTransfer.files;
    if (!files || !files.length) return;
    // Only the first .json file is loaded; the rest are ignored.
    var file = null;
    for (var i = 0; i < files.length; i++) {
      if (files[i].name && /\.json$/i.test(files[i].name)) { file = files[i]; break; }
    }
    if (!file) { flash('Drop a .json picks file to load.', 'err'); return; }
    readPicksFile(file, 'replace');
  });
}

// Shared by the Load button and drag-drop. Validates the JSON shape,
// then either replaces or merges with the current PICKED set.
// ── Picks file load with rwh verification ──────────────────────────────
// readPicksFile → verifyPicksBeforeLoad → (user confirms) → applyPicksFromData.
// Each rwh in the saved file is pinged against /api/tis/course/<rwh>;
// if TIS returns 404 the section has been removed/renamed since the
// file was saved. We surface that BEFORE applying (otherwise the user
// would see "I picked this, but Sync to TIS just rejects it" later).
function readPicksFile(file, mode) {
  mode = mode || 'replace';
  var reader = new FileReader();
  reader.onload = function() {
    try {
      var data = JSON.parse(reader.result);
      if (!data || data.version !== 1 || !Array.isArray(data.picks)) {
        flash('Not a valid picks file (missing version or picks).', 'err');
        return;
      }
      // No picks to load — nothing to verify, just apply (which is a no-op)
      if (!data.picks.length) {
        applyPicksFromData(data);
        return;
      }
      verifyPicksBeforeLoad(data, file, mode);
    } catch (e) { flash('Could not parse file: ' + e.message, 'err'); }
  };
  reader.readAsText(file);
}

// Ping /api/tis/course/<rwh> for every pick in parallel, then show a
// confirmation modal with the breakdown: N found, M gone, K errored.
// The user picks what to do next.
function verifyPicksBeforeLoad(data, file, mode) {
  // Reset PICKED_BIDS only if we're replacing (so partial apply doesn't
  // nuke the existing bids). The mutator does the full reset in
  // applyPicksFromData → but we need to do it NOW, before the user
  // confirms, so the empty/loading state is consistent.
  // We delay the reset until the user actually confirms.
  var picks = data.picks;
  var pending = picks.length;
  var verified = [];   // { rwh, status: 'ok'|'gone'|'error', pick, error? }
  var allDone = false;
  var xn = currentXn(), xq = currentXq();

  var showModal = function() {
    var found = verified.filter(function(v) { return v.status === 'ok'; });
    var gone = verified.filter(function(v) { return v.status === 'gone'; });
    var errs = verified.filter(function(v) { return v.status === 'error'; });
    showPicksVerifyModal({
      fileName: file.name,
      found: found, gone: gone, errors: errs,
      onCancel: function() {
        flash('Load cancelled — file left untouched.', 'warn');
      },
      onLoadFoundOnly: function() {
        var filtered = { version: 1, picks: found.map(function(v) { return v.pick; }) };
        finishLoad(filtered, file, mode);
      },
      onLoadAll: function() {
        finishLoad(data, file, mode);
      },
    });
  };

  var finishLoad = function(loadedData, loadedFile, loadedMode) {
    // Reset PICKED + dependents if we're replacing (the original
    // readPicksFile behavior). applyPicksFromData will re-render.
    if (loadedMode === 'replace') {
      PICKED = {};
      PICKED_BIDS = {};
      PICKED_CONFLICTS = {};
      PICKED_CHECKED = {};
      ACTIVE_RWH = null;
    }
    applyPicksFromData(loadedData);
    CURRENT_FILE = { kind: 'loaded', name: loadedFile.name };
    updatePickedActionsState();
    var loadedCount = loadedData.picks.length;
    var skipCount = picks.length - loadedCount;
    var skipMsg = skipCount ? ' (' + skipCount + ' skipped — no longer in catalog)' : '';
    flash((loadedMode === 'replace' ? 'Loaded ' : 'Merged ') +
      loadedCount + ' pick(s) from ' + loadedFile.name + skipMsg, 'ok');
  };

  // If verification is fast, don't flash the modal. If any are gone,
  // always show the modal (that's the point — let the user decide).
  // To keep UX responsive, we collect results as they arrive and only
  // show the modal when we know there's a non-trivial decision.
  var startTime = Date.now();
  var MIN_LATENCY_MS = 250;  // only show "loading" flash if it takes longer

  for (var i = 0; i < picks.length; i++) {
    (function(pick) {
      if (!pick || !pick.rwh) {
        verified.push({ rwh: '?', status: 'error', pick: pick, error: 'no rwh' });
        pending--;
        if (pending === 0) allDone = true;
        return;
      }
      var url = '/api/tis/course/' + encodeURIComponent(pick.rwh) + sem();
      fetch(url).then(function(resp) {
        if (resp.status === 200) verified.push({ rwh: pick.rwh, status: 'ok', pick: pick });
        else if (resp.status === 404) verified.push({ rwh: pick.rwh, status: 'gone', pick: pick });
        else verified.push({ rwh: pick.rwh, status: 'error', pick: pick, code: resp.status });
      }).catch(function(e) {
        verified.push({ rwh: pick.rwh, status: 'error', pick: pick, error: e.message });
      }).then(function() {
        pending--;
        if (pending === 0 && !allDone) {
          allDone = true;
          var foundCount = verified.filter(function(v) { return v.status === 'ok'; }).length;
          var goneCount = verified.filter(function(v) { return v.status === 'ok' ? 0 : 1; }).length;
          // If everything verified OK and no decision needed, skip the modal
          if (goneCount === 0) {
            finishLoad(data, file, mode);
          } else {
            showModal();
          }
        }
      });
    })(picks[i]);
  }

  // While verification is running, if it takes a while, flash a status
  setTimeout(function() {
    if (allDone) return;
    flash('Verifying ' + pending + ' section(s) against current catalog…', 'ok');
  }, MIN_LATENCY_MS);
}

// Build and show the verify-load modal. Returns when user clicks a
// button. The modal is dismissable via "Cancel" or Esc.
function showPicksVerifyModal(opts) {
  var overlay = document.createElement('div');
  overlay.className = 'pv-modal-overlay';
  overlay.innerHTML = '<div class="pv-modal" role="dialog" aria-labelledby="pv-title">' +
    '<div class="pv-modal-h">' +
      '<span class="pv-modal-t" id="pv-title">📂 Load "' + escapeHtml(opts.fileName) + '"</span>' +
      '<button class="pv-modal-x" aria-label="Close">×</button>' +
    '</div>' +
    '<div class="pv-modal-body"></div>' +
    '<div class="pv-modal-actions"></div>' +
  '</div>';
  document.body.appendChild(overlay);

  var body = overlay.querySelector('.pv-modal-body');
  var actions = overlay.querySelector('.pv-modal-actions');

  var renderRow = function(label, items, kindClass, emptyText) {
    if (!items.length) {
      return '<div class="pv-row pv-empty"><span class="pv-tag ' + kindClass + '">' + label + ' (0)</span><span class="pv-empty-text">' + emptyText + '</span></div>';
    }
    var lis = items.map(function(v) {
      var p = v.pick || {};
      var codeText = escapeHtml(p.code || '?');
      var clsText = p.class_group ? ' <span style="color:var(--mut)">cls ' + escapeHtml(p.class_group) + '</span>' : '';
      var t = p.teachers && p.teachers.length ? p.teachers.join(', ') : '';
      var tchText = t ? ' · ' + escapeHtml(t) : '';
      return '<li class="pv-li pv-' + kindClass + '" data-rwh="' + escapeHtml(v.rwh || '') + '">' +
        '<code class="pv-code">' + codeText + '</code>' +
        clsText + tchText +
        (kindClass === 'gone' ? ' <span class="pv-tag-mini">removed</span>' : '') +
        (kindClass === 'error' ? ' <span class="pv-tag-mini">error</span>' : '') +
      '</li>';
    }).join('');
    return '<div class="pv-row">' +
      '<span class="pv-tag ' + kindClass + '">' + label + ' (' + items.length + ')</span>' +
      '<ul class="pv-list">' + lis + '</ul>' +
    '</div>';
  };

  body.innerHTML =
    renderRow('✓ Found', opts.found, 'ok', 'None of the saved sections are still available.') +
    renderRow('✗ Removed from catalog', opts.gone, 'gone', 'Nothing was removed.') +
    renderRow('⚠ Verification errored', opts.errors, 'error', 'No errors.');

  var cancel = function() {
    document.removeEventListener('keydown', escHandler);
    if (overlay.parentNode) document.body.removeChild(overlay);
    opts.onCancel();
  };
  var loadFound = function() {
    document.removeEventListener('keydown', escHandler);
    if (overlay.parentNode) document.body.removeChild(overlay);
    if (!opts.found.length) { cancel(); return; }
    opts.onLoadFoundOnly();
  };
  var loadAll = function() {
    document.removeEventListener('keydown', escHandler);
    if (overlay.parentNode) document.body.removeChild(overlay);
    opts.onLoadAll();
  };

  // Action buttons — Cancel is on the LEFT (always available).
  // "Load only found" is the SAFE default and is visually primary
  // (it's what most users want). "Load all anyway" is the demoted,
  // danger option — it lets the user proceed but TIS will reject
  // missing rwhs at sync time.
  var html = '<button class="pv-btn pv-btn-cancel">Cancel</button>';
  if (opts.found.length) {
    html += '<button class="pv-btn pv-btn-primary">Load only found (' + opts.found.length + ')</button>';
  } else {
    html += '<button class="pv-btn" disabled>Nothing to load</button>';
  }
  if (opts.gone.length || opts.errors.length) {
    html += '<button class="pv-btn pv-btn-danger">Load all anyway (' + (opts.gone.length + opts.errors.length) + ' may fail)</button>';
  }
  actions.innerHTML = html;

  // Wire handlers
  overlay.querySelector('.pv-modal-x').addEventListener('click', cancel);
  var btns = actions.querySelectorAll('.pv-btn');
  btns[0].addEventListener('click', cancel);  // Cancel
  if (opts.found.length) btns[1].addEventListener('click', loadFound);
  if (opts.gone.length || opts.errors.length) {
    btns[btns.length - 1].addEventListener('click', loadAll);
  }
  // Esc cancels
  var escHandler = function(e) {
    if (e.key === 'Escape') { cancel(); }
  };
  document.addEventListener('keydown', escHandler);
  // Backdrop click also cancels
  overlay.addEventListener('click', function(e) {
    if (e.target === overlay) cancel();
  });
}

function applyPicksFromData(data) {
  if (!data || !data.picks) return;
  for (var i = 0; i < data.picks.length; i++) {
    var c = data.picks[i];
    if (c && c.rwh) PICKED[c.rwh] = c;
  }
  // Same cascade as the mutators — restoring is a mutation too.
  renderResults(CAT);
  renderPicked();
  renderGrid();
  renderGrid3();  // step-3 grid shows picked + enrolled together
  renderBidPanel();
  updateBidStat();
  updateSolveCodes();
  updateExportIcsButton();
}

function savePicksToFile() {
  var keys = Object.keys(PICKED);
  if (!keys.length) { flash('No sections picked — nothing to save.', 'warn'); return; }
  var picksArr = [];
  for (var i = 0; i < keys.length; i++) picksArr.push(PICKED[keys[i]]);
  var ts = new Date().toISOString().replace(/[:.]/g, '-').replace(/T/, '_').slice(0, 19);
  var filename = 'tis-picks-' + ts + '.json';
  var blob = new Blob([JSON.stringify({
    version: 1, picks: picksArr, savedAt: new Date().toISOString(),
  }, null, 2)], { type: 'application/json' });
  var url = URL.createObjectURL(blob);
  var a = document.createElement('a');
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click(); document.body.removeChild(a);
  URL.revokeObjectURL(url);
  // Track the last-saved filename so the right panel can show it. This
  // is the file the user *just* downloaded — useful as a reference, but
  // not authoritative (the user could rename/move it).
  CURRENT_FILE = { kind: 'saved', name: filename };
  updatePickedActionsState();
  flash('Saved ' + keys.length + ' pick(s) → ' + filename, 'ok');
}

// ── Real actions (talk to TIS) ────────────────────────────────────────────
// Both use confirm() with a verbose preview. No fake-safety disable — the
// user must read the preview and click OK to commit a real action. The
// server is the final gate, so any server-side rejection (auth, course
// closed, conflict, etc.) is surfaced verbatim by the .catch handlers.

function syncToTIS() {
  var keys = Object.keys(PICKED);
  if (!keys.length) { flash('No sections picked — nothing to sync.', 'warn'); return; }
  // Group by endpoint. Enrolled picks go to updXkxsByyx; cart picks go
  // to upd_xkxsBygwc. The previous code hardcoded 'cart' for everything,
  // so bids on already-enrolled sections silently failed.
  var picksByWhere = { cart: {}, enrolled: {} };
  for (var k in PICKED_BIDS) {
    if (PICKED_BIDS.hasOwnProperty(k) && PICKED[k]) {
      var w = ENROLLED_RWH.has(k) ? 'enrolled' : 'cart';
      picksByWhere[w][k] = PICKED_BIDS[k];
    }
  }
  var totalPicks = Object.keys(picksByWhere.cart).length + Object.keys(picksByWhere.enrolled).length;
  if (!totalPicks) { flash('No bids set on any picked section.', 'warn'); return; }

  // Verbose confirm: list every rwh + bid value the user is about to commit.
  var preview = '';
  var allKeys = Object.keys(picksByWhere.cart).concat(Object.keys(picksByWhere.enrolled));
  for (var i = 0; i < allKeys.length; i++) {
    var rwh = allKeys[i];
    var c = PICKED[rwh];
    var bid = PICKED_BIDS[rwh] || 0;
    preview += '\n  · ' + (c.code || rwh) + ' ' + (c.class_group || '') + ' — ' + bid + ' pts';
  }
  if (!confirm('Sync ' + totalPicks + ' bid(s) to TIS? This is a real action — it will overwrite any bids TIS already has.\n\n' + preview)) return;

  function _sendBatch(where, picks) {
    return postJSON('/api/tis/bids' + sem(), {
      picks: picks, round_code: ROUND_INFO.xkfsdm || '',
      where: where, jffs_limit: ROUND_INFO.jffs || null, dry_run: false,
    });
  }
  var batches = [];
  if (Object.keys(picksByWhere.cart).length) batches.push(_sendBatch('cart', picksByWhere.cart));
  if (Object.keys(picksByWhere.enrolled).length) batches.push(_sendBatch('enrolled', picksByWhere.enrolled));

  Promise.all(batches).then(function(results) {
    var merged = { results: [], sum: 0, over_limit: false };
    for (var i = 0; i < results.length; i++) {
      var r = results[i] || {};
      if (r.over_limit) merged.over_limit = true;
      merged.sum += r.sum || 0;
      merged.results = merged.results.concat(r.results || []);
    }
    if (merged.over_limit) {
      flash('Over budget: ' + merged.sum + ' > ' + ROUND_INFO.jffs + ' pts. Adjust bids first.', 'err');
      return;
    }
    var okCount = 0; var failed = [];
    for (var fi = 0; fi < merged.results.length; fi++) {
      if (merged.results[fi].ok) okCount++;
      else failed.push(merged.results[fi]);
    }
    var failedSummary = '';
    if (failed.length) {
      var parts = [];
      for (var fj = 0; fj < failed.length; fj++) {
        var f = failed[fj];
        var code = (PICKED[f.rwh] && PICKED[f.rwh].code) || f.rwh;
        parts.push(code + ' (' + (f.message || 'no message') + ')');
      }
      failedSummary = ' · ' + failed.length + ' failed: ' + parts.join('; ');
    }
    flash('Synced: ' + okCount + '/' + merged.results.length + ' bid(s)' +
      (merged.sum ? ' · total ' + merged.sum + ' pts' : '') + failedSummary,
      okCount === merged.results.length ? 'ok' : 'err');
  })['catch'](function(e) { flash('Network error: ' + e.message, 'err'); });
}

function dropAllEnrolled() {
  if (!ENROLLED_RWH.size) { flash('No enrolled sections to drop.', 'warn'); return; }
  // Verbose preview — every rwh the user is about to drop.
  var preview = '';
  ENROLLED_RWH.forEach(function(rwh) {
    var c = PICKED[rwh];
    preview += '\n  · ' + (c ? (c.code || rwh) + ' ' + (c.class_group || '') : rwh);
  });
  if (!confirm('Drop all ' + ENROLLED_RWH.size + ' enrolled section(s)? This is a real action — you can re-add them but the operation is not reversible on the server side.\n\n' + preview)) return;

  // Sequential POSTs so the user can see each result in order. TIS rate-
  // limits; going one at a time avoids bursting.
  var rwhs = [];
  ENROLLED_RWH.forEach(function(rwh) { rwhs.push(rwh); });
  var okCount = 0; var failed = [];
  function _next(i) {
    if (i >= rwhs.length) {
      flash('Dropped: ' + okCount + '/' + rwhs.length +
        (failed.length ? ' · ' + failed.length + ' failed' : ''),
        okCount === rwhs.length ? 'ok' : 'err');
      loadEnrolled();  // refresh the enrolled set so the next attempt is clean
      return;
    }
    postJSON('/api/tis/drop' + sem(), { rwh: rwhs[i], dry_run: false }).then(function(r) {
      if (r && r.ok) okCount++;
      else failed.push({ rwh: rwhs[i], message: (r && r.message) || 'unknown' });
      _next(i + 1);
    })['catch'](function(e) {
      failed.push({ rwh: rwhs[i], message: e.message });
      _next(i + 1);
    });
  }
  _next(0);
}

// ── ICS export (was exportICal / parseSlotsForIcal — renamed for consistency) ──
function exportICS() {
  var keys = Object.keys(PICKED);
  if (!keys.length) { flash('No sections picked — nothing to export.', 'warn'); return; }
  var picks = [];
  for (var i = 0; i < keys.length; i++) {
    var c = PICKED[keys[i]];
    var slots = parseSlotsForICS(c);
    for (var j = 0; j < slots.length; j++) picks.push(slots[j]);
  }
  if (!picks.length) { flash('Picked sections have no parseable schedule — cannot export.', 'warn'); return; }
  var semInfo = SEMESTER_INFO && SEMESTER_INFO.semester;
  var xn = semInfo ? semInfo.xn : '';
  var xq = semInfo ? semInfo.xq : '';
  if (!xn || !xq) { flash('No semester info loaded — cannot determine xn/xq.', 'warn'); return; }
  var url = '/api/tis/ical?xn=' + encodeURIComponent(xn) +
            '&xq=' + encodeURIComponent(xq) +
            '&picks=' + encodeURIComponent(JSON.stringify(picks));
  window.location = url;
}

function parseSlotsForICS(c) {
  var out = [];
  var slots = c.slots || [];
  for (var i = 0; i < slots.length; i++) {
    var s = slots[i];
    if (!s || !s.weeks || !s.weeks.length) continue;
    var weekdayMap = {'Mon': 0, 'Tue': 1, 'Wed': 2, 'Thu': 3,
                      'Fri': 4, 'Sat': 5, 'Sun': 6};
    var wd = s.weekday_int != null ? s.weekday_int
            : (s.weekday != null && weekdayMap[s.weekday] != null
               ? weekdayMap[s.weekday] : null);
    if (wd == null) continue;
    var periods = s.periods || (s.period_start ? [s.period_start] : []);
    if (!periods.length) continue;
    out.push({
      weeks: s.weeks,
      weekday: wd,
      periods: periods,
      title: (c.name || c.code || 'Class') + (c.class_group ? ' (' + c.class_group + ')' : ''),
      teacher: (c.teachers || []).join(', '),
      room: (c.rooms || []).join(', '),
    });
  }
  return out;
}
// ── END outer IIFE ────────────────────────────────────────────────
})();
