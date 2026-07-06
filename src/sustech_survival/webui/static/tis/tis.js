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
var PICKED_BIDS = {};        // { rwh: bid_int }      parallel to PICKED
var PICKED_CONFLICTS = {};    // { rwh: bool }        true if this rwh conflicts with another picked rwh
var ROUND_INFO = { jffs: 0, ksrq: '', jsrq: '', lcmc: '', xkfsdm: '', xkms: '', ok: false, message: '' };
var BID_DRAG = null;         // { sourceRwh, sourceBox, arrowEl, targetRwh, lastX, lastY }
var BID_EDIT = null;         // { rwh, originalBid, inputEl }


// ── State ─────────────────────────────────────────────────────────────────
var CAT = [];               // full course list from latest server fetch
var ALL_CAT = [];           // cached full catalog for client-side filtering
var PICKED = {};            // { rwh: courseDict }
var ACTIVE_RWH = null;      // last clicked card rwh (for eval)
var EVAL_CACHE = {};        // { code: evalResponse }
var ENROLLED_RWH = new Set(); // rwhs currently enrolled
var COLORS_CACHE = {};      // { code: color }
var SEMESTER_INFO = null;   // cached /api/tis/info response
var MODE = 'personal';      // 'personal' (我要选课, default) or 'campus' (全校课表, browse-only)

var PERIODS = 12;

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
    // Colleges: d.colleges is [(code, name), ...] — show name, store name
    populateSelect(F_COL, d.colleges.map(function(p) { return p[1]; }));
    populateSelect(F_TASK, d.task_types);
    populateSelect(F_CAT, d.categories);
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
  // Auto-select first type if no selection
  if (!val && sel.options.length > 1) {
    sel.selectedIndex = 1;
  } else if (val) {
    sel.value = val;
  }
}

function loadCourses(isInitialLoad) {
  var qs = sem();
  qs += '&mode=' + MODE;
  qs += '&keyword=' + encodeURIComponent(KW.value);
  qs += '&college=' + encodeURIComponent(F_COL.value);
  qs += '&task_type=' + encodeURIComponent(F_TASK.value);
  qs += '&category=' + encodeURIComponent(F_CAT.value);
  qs += '&campus=' + encodeURIComponent(F_CAM.value);
  qs += '&language=' + encodeURIComponent(F_LANG.value);
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

function renderResults(courses) {
  RESULTS.innerHTML = '';
  for (var i = 0; i < courses.length; i++) {
    RESULTS.appendChild(renderCard(courses[i]));
  }
}

function escapeHtml(s) {
  if (typeof s !== 'string') s = String(s);
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\"/g,'&quot;');
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
      '<span class="code">' + escapeHtml(c.code) + '</span>' +
      '<span class="nm">' + escapeHtml(c.name || c.name_en || '') + '</span>' +
      (c.class_group ? '<span class="grp">' + escapeHtml(c.class_group) + '</span>' : '') +
      (PICKED[c.rwh] ? '<span style="color:var(--accent);font-size:.7rem;margin-left:auto;cursor:pointer" class="unpick-badge" data-rwh="' + c.rwh + '">✕ picked</span>' : '') +
    '</div>' +
    (c.section_name && c.section_name !== c.name
      ? '<div class="sect">' + escapeHtml(c.section_name) + (c.section_name_en ? ' <span class="sect-en">' + escapeHtml(c.section_name_en) + '</span>' : '') + '</div>'
      : '') +
    '<div class="meta">' +
      (hasRealTeacher ? '<b>Teacher</b> ' + escapeHtml(teachers) : '<span style="color:var(--mut)"><b>Teacher</b> TBD</span>') +
      (c.credits ? ' · <b>Credits</b> ' + c.credits : '') +
      (c.capacity ? ' · <b>Capacity</b> ' + c.capacity : '') +
    '</div>' +
    (schedHTML ? '<div class="sched"><span class="sched-lbl">Schedule</span>' + schedHTML + '</div>' : '') +
    '<div class="actions">' +
      (PICKED[c.rwh]
        ? ''
        : '<button class="ghost pick-btn" data-action="add" style="color:var(--accent);font-size:.7rem;padding:.1rem .35rem">+ Pick</button>') +
    '</div>';

  card.addEventListener('click', function(e) {
    if (e.target.closest('.pick-btn')) return;
    if (e.target.closest('.unpick-badge')) {
      removePicked(c.rwh);
      return;
    }
    if (PICKED[c.rwh]) {
      removePicked(c.rwh);
      return;
    }
    selectCourse(c.rwh);
  });

  var pickBtn = card.querySelector('.pick-btn');
  if (pickBtn) {
    pickBtn.addEventListener('click', function(e) {
      e.stopPropagation();
      if (pickBtn.dataset.action === 'add') {
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
  // Display priority: name (top, large) > teacher+class > code (small, muted)
  var cls = d.code && d.code.match(/^\D+\d+\D?$/);  // not really used yet
  var html = '<div class="bc-head">' +
    '<div class="bc-name">' + escapeHtml(d.name) + '</div>' +
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
  html += '</div>' +
  '<div class="bc-foot">' +
    '<span class="bc-hint">community-sourced · ' + escapeHtml(d.code) + '</span>' +
    '<a href="' + escapeHtml(d.detail_url) + '" target="_blank" rel="noopener">Full NCES page ↗</a>' +
  '</div>';
  return html;
}

function briefFetch(code, evt) {
  // Cancel any in-flight request
  if (BRIEF_INFLIGHT && BRIEF_INFLIGHT.abort) BRIEF_INFLIGHT.abort();
  var ctrl = (typeof AbortController !== 'undefined') ? new AbortController() : null;
  if (ctrl) BRIEF_INFLIGHT = ctrl;
  var url = '/api/nces/code/' + encodeURIComponent(code) +
            '?xn=' + encodeURIComponent(currentXn()) +
            '&xq=' + encodeURIComponent(currentXq());
  fetch(url, ctrl ? { signal: ctrl.signal } : {})
    .then(function(r) { return r.json(); })
    .then(function(d) {
      BRIEF_CACHE[code] = d;
      if (BRIEF_ACTIVE_CODE === code) {
        BRIEF_CARD.innerHTML = briefRender(d);
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
      top = window.pageYOffset + window.innerHeight - cardH - 8;
    }
    if (top < window.pageYOffset + 8) top = window.pageYOffset + 8;
    BRIEF_CARD.style.left = left + 'px';
    BRIEF_CARD.style.top = top + 'px';
    BRIEF_CARD.classList.add('show');
    // Render cached result if any, else fetch
    if (BRIEF_CACHE[c.code]) {
      BRIEF_CARD.innerHTML = briefRender(BRIEF_CACHE[c.code]);
    } else {
      BRIEF_CARD.innerHTML = '<div class="bc-loading">Loading NCES</div>';
      briefFetch(c.code, evt);
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

// ── Course selection (for eval) ───────────────────────────────────────────

function selectCourse(rwh) {
  ACTIVE_RWH = rwh;
  var cards = RESULTS.querySelectorAll('.c-card');
  for (var i = 0; i < cards.length; i++) {
    cards[i].classList.toggle('active', cards[i].dataset.rwh === rwh);
  }
  var course = null;
  for (var j = 0; j < CAT.length; j++) {
    if (CAT[j].rwh === rwh) { course = CAT[j]; break; }
  }
  if (!course) {
    EVAL_OUT.innerHTML = '<div class="ncn">Course not found in current results.</div>';
    return;
  }
  // Auto-switch to the eval tab so the user can see the result
  switchTab('eval');
  fetchEval(course.code);
}

function fetchEval(code) {
  if (EVAL_CACHE[code]) {
    renderEval(EVAL_CACHE[code]);
    return;
  }
  EVAL_OUT.innerHTML = '<div class="ncn">Loading NCES evaluation…</div>';
  getJSON('/api/nces/code/' + encodeURIComponent(code) + '?xn=' + encodeURIComponent(currentXn()) + '&xq=' + encodeURIComponent(currentXq())).then(function(d) {
    EVAL_CACHE[code] = d;
    renderEval(d);
  })['catch'](function(e) {
    EVAL_OUT.innerHTML = '<div class="flash err">Error: ' + escapeHtml(e.message) + '</div>';
  });
}

function renderEval(d) {
  if (!d.available) {
    EVAL_OUT.innerHTML = '<div class="ncn">' + escapeHtml(d.reason || 'NCES evaluation not available for this course.') + '</div>' +
      (d.search_url ? '<div style="margin-top:.6rem"><a href="' + escapeHtml(d.search_url) + '" target="_blank" rel="noopener">Search NCES ↗</a></div>' : '');
    return;
  }
  var html = '<div class="bc-head">' +
    '<div class="bc-name">' + escapeHtml(d.name) + '</div>' +
    '<div class="bc-meta">' +
      '<span>' + escapeHtml(d.teacher) + '</span>' +
      (d.semester ? '<span class="bc-sem"> · ' + escapeHtml(d.semester) + '</span>' : '') +
      '<span class="bc-code">' + escapeHtml(d.code) + '</span>' +
    '</div>' +
  '</div>' +
  '<div class="bc-rating">' +
    '<span class="bc-score">' + (d.rating || 0).toFixed(1) + '</span>' +
    '<span class="bc-out">/ 10</span>' +
    '<span class="bc-rev">' + (d.review_count || 0) + ' reviews</span>' +
  '</div>' +
  '<div class="bc-dims" style="margin-bottom:.8rem">';
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
  html += '</div>';

  // Review excerpts
  var excerpts = d.review_excerpts || [];
  if (excerpts.length) {
    html += '<div style="font-size:.82rem;font-weight:600;margin-bottom:.4rem;color:var(--fg)">Top Reviews</div>';
    for (var i = 0; i < excerpts.length; i++) {
      var r = excerpts[i];
      html += '<div class="eval-item">' +
        '<div class="ei-t">' + escapeHtml(r.username || 'Anonymous') +
          (r.semester ? ' · ' + escapeHtml(r.semester) : '') +
          (r.likes ? ' · 👍' + r.likes : '') +
        '</div>' +
        (r.excerpt ? '<div class="ei-m">' + escapeHtml(r.excerpt) + (r.excerpt.length >= 200 ? '…' : '') + '</div>' : '') +
      '</div>';
    }
  } else {
    html += '<div class="ncn">No written reviews for this course.</div>';
  }

  html += '<div style="margin-top:.8rem"><a href="' + escapeHtml(d.detail_url) + '" target="_blank" rel="noopener">Full NCES page ↗</a></div>';

  EVAL_OUT.innerHTML = html;
}

// ── Picked sections ───────────────────────────────────────────────────────

function addPicked(course) {
  PICKED[course.rwh] = JSON.parse(JSON.stringify(course));
  if (!(course.rwh in PICKED_BIDS)) PICKED_BIDS[course.rwh] = 1;
  // Re-render search results so cards reflect the new pick state
  renderResults(CAT);
  renderPicked();
  renderGrid();
  renderBidPanel();
}

function removePicked(rwh) {
  delete PICKED[rwh];
  delete PICKED_BIDS[rwh];
  delete PICKED_CONFLICTS[rwh];
  // Re-render search results so cards reflect the unpicked state
  renderResults(CAT);
  if (ACTIVE_RWH === rwh) {
    ACTIVE_RWH = null;
  }
  renderPicked();
  renderGrid();
  renderBidPanel();
}

function renderPicked() {
  var keys = Object.keys(PICKED);
  var totalCredits = 0;
  for (var i = 0; i < keys.length; i++) {
    totalCredits += parseFloat(PICKED[keys[i]].credits) || 0;
  }
  PICK_STAT.textContent = keys.length + ' sections · ' + totalCredits.toFixed(1) + ' Credits';

  if (!keys.length) {
    PICK_LIST.innerHTML = '<div class="loading">No sections picked.</div>';
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

  var enrolled = ENROLLED_RWH.has(c.rwh);
  var schedHTML = c.slots && c.slots.length ? formatScheduleHTML(c.slots) : '';
  var teachers = c.teachers && c.teachers.length ? escapeHtml(c.teachers.join(', ')) : '<span style="color:var(--mut)">TBD</span>';

  // Check if this picked course conflicts with any other picked course
  var conflictMsg = '';
  var keys = Object.keys(PICKED);
  var slotsA = c.slots || [];
  for (var pi = 0; pi < keys.length; pi++) {
    if (PICKED[keys[pi]].rwh === c.rwh) continue;
    var slotsB = PICKED[keys[pi]].slots || [];
    if (sectionsConflict(slotsA, slotsB)) {
      conflictMsg = ' ⚠ conflicts with ' + escapeHtml(PICKED[keys[pi]].code);
      break;
    }
  }

  div.innerHTML =
    '<div class="pn">' + escapeHtml(c.name || c.name_en || '') +
      (enrolled ? '<span class="pick-enrolled">enrolled</span>' : '') +
      (conflictMsg ? '<span style="float:right;color:var(--bad);font-size:.65rem">⚠ conflicted</span>' : '') +
    '</div>' +
    (c.section_name && c.section_name !== c.name
      ? '<div class="pm" style="margin-top:.15rem">' + escapeHtml(c.section_name) + '</div>'
      : '') +
    '<div class="pm">' +
      '<b>Teacher</b> ' + teachers +
      (c.class_group ? ' · ' + escapeHtml(c.class_group) : '') +
      ' · <b>' + escapeHtml(c.code) + '</b>' +
      (schedHTML ? ' · ' + schedHTML : '') +
      (conflictMsg ? '<br><span style="color:var(--bad);font-size:.68rem">' + conflictMsg + '</span>' : '') +
    '</div>' +
    '<div class="acts">' +
      '<button class="ghost act-remove" style="color:var(--bad)" title="Remove from selection">✕ Remove</button>' +
    '</div>';

  div.querySelector('.act-remove').addEventListener('click', function() {
    removePicked(c.rwh);
  });

  return div;
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

function sectionsToBlocks(sections) {
  var allBlocks = [];
  for (var pi = 0; pi < sections.length; pi++) {
    var c = sections[pi];
    var slots = c.slots || [];
    var color = colorFor(c.code);
    for (var si = 0; si < slots.length; si++) {
      var s = slots[si];
      var weeks = s.weeks || [];
      if (typeof weeks === 'string') {
        weeks = weeks.split(',').map(function(x) { return parseInt(x, 10); });
      }
      allBlocks.push({
        day: s.day, periodStart: s.period_start, periodEnd: s.period_end,
        weeks: weeks, course: c, rwh: c.rwh, code: c.code, color: color
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
      if (entries && entries.length) {
        var hasStart = entries.some(function(e) { return e.isStart; });
        if (hasStart) {
          h += '<td class="cell" style="padding:0;position:relative;height:' + ROW_HEIGHT + 'px">' +
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
              'title="' + escapeHtml(b.code + ' ' + (b.course.class_group || '') + ' ' + dayName(b.day) + ' ' + b.periodStart + '-' + b.periodEnd + (b.conflict ? ' ⚠ CONFLICT' : '')) + '" ' +
              'data-rwh="' + b.rwh + '">' +
              '<span class="t">' + escapeHtml(b.code) + '</span>' +
              '<span style="font-size:.6rem;opacity:.8;display:block">' + escapeHtml(b.course.name || '') + '</span>' +
            '</div>';
          });
          h += '</div></td>';
        } else {
          h += '<td class="cell" style="padding:0;position:relative;height:' + ROW_HEIGHT + 'px">' +
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
        h += '<td class="cell" style="padding:0;position:relative;height:' + ROW_HEIGHT + 'px">' +
             '<div class="cell-inner"></div></td>';
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
    for (var li = 0; li < allBlocks.length; li++) {
      var code = allBlocks[li].code;
      if (seenCodes[code]) continue;
      seenCodes[code] = true;
      var sw = document.createElement('span');
      sw.className = 'sw';
      sw.style.background = allBlocks[li].color;
      var sl = document.createElement('span');
      sl.className = 'sl';
      sl.textContent = code;
      legendTarget.appendChild(sw);
      legendTarget.appendChild(sl);
    }
  }

  renderGridTable(targetOdd, buildPackedItems(allBlocks, true));
  renderGridTable(targetEven, buildPackedItems(allBlocks, false));
}

function renderGrid() {
  var keys = Object.keys(PICKED);
  if (!keys.length) {
    GRID_ODD.innerHTML = '<tr><td colspan="8" class="empty" style="padding:2rem 0">No picked sections.</td></tr>';
    GRID_EVEN.innerHTML = '<tr><td colspan="8" class="empty" style="padding:2rem 0">No picked sections.</td></tr>';
    return;
  }

  var pickedArr = [];
  for (var ki = 0; ki < keys.length; ki++) {
    pickedArr.push(PICKED[keys[ki]]);
  }
  var allBlocks = sectionsToBlocks(pickedArr);
  renderGridBlocks(allBlocks, GRID_ODD, GRID_EVEN, GRID_LEGEND);

  // Update conflict count on the solve button
  var conflictCount = allBlocks.filter(function(b) { return b.conflict; }).length;
  var conflictCodes = {};
  allBlocks.forEach(function(b) { if (b.conflict) conflictCodes[b.code] = true; });
  var btn = document.getElementById('grid-solve');
  if (conflictCount > 0) {
    btn.textContent = '⚠ ' + Object.keys(conflictCodes).length + ' courses conflict — Solve';
    btn.style.color = 'var(--bad)';
  } else {
    btn.textContent = '✅ No conflicts — Solve combinations';
    btn.style.color = '';
  }
}

// ── Enrolled ──────────────────────────────────────────────────────────────

function loadEnrolled() {
  ENROLLED_OUT.innerHTML = '<div class="ncn">Loading…</div>';
  getJSON('/api/tis/enrolled' + sem()).then(function(d) {
    ENROLLED_RWH = new Set();
    if (d.error) {
      ENROLLED_OUT.innerHTML = '<div class="flash err">' + escapeHtml(d.error) + '</div>';
      return;
    }
    var list = d.enrolled || [];
    if (!list.length) {
      ENROLLED_OUT.innerHTML = '<div class="ncn">No enrolled courses found.</div>';
      return;
    }
    var html = '';
    for (var i = 0; i < list.length; i++) {
      var item = list[i];
      var rwh = item.rwh || '';
      ENROLLED_RWH.add(rwh);
      var isPicked = !!PICKED[rwh];
      html += '<div class="ncn' + (isPicked ? ' ok' : '') + '">' +
        escapeHtml(item.code || item.name || '') +
        (item.class_group ? ' ' + escapeHtml(item.class_group) : '') +
        (isPicked ? ' ✓ in picked' : '') +
      '</div>';
    }
    ENROLLED_OUT.innerHTML = html;
    renderPicked();
  })['catch'](function(e) {
    ENROLLED_OUT.innerHTML = '<div class="flash err">' + escapeHtml(e.message) + '</div>';
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

  var blockedInput = document.getElementById('blocked-input').value;
  var blocked = parseBlockedInput(blockedInput);

  SOLVE_OUT.innerHTML = '<div class="ncn">Solving — trying all combinations…</div>';

  postJSON('/api/tis/solve' + sem(), {
    codes: codeOrder,
    priority: codeOrder,
    rwhs: Object.keys(PICKED),
    blocked: blocked,
    max: 30
  }).then(function(d) {
    var solutions = d.solutions || [];

    if (!solutions.length) {
      SOLVE_OUT.innerHTML = '<div class="ncn">No valid non-conflicting combinations found. ' +
        'Try removing some courses or adjusting blocked slots.</div>';
      return;
    }

    // Flatten: all solutions in order (already sorted by coverage then priority)
    var flat = solutions;
    var total = flat.length;
    var idx = 0;
    var totalCodes = codeOrder.length;

    function renderSolveItem() {
      var sol = flat[idx];
      // Build section rows + total credits
      var secHtml = '';
      var totalCredits = 0;
      for (var si = 0; si < sol.sections.length; si++) {
        var sec = sol.sections[si];
        var schedStr = sec.schedule || formatSchedule(sec.slots);
        totalCredits += parseFloat(sec.credits) || 0;
        secHtml += '<div class="sc-sec">' +
          '<span class="solve-sec-code">' + escapeHtml(sec.code) + '</span>' +
          (sec.class_group ? ' <span style="color:var(--mut)">' + escapeHtml(sec.class_group) + '</span>' : '') +
          ' · ' + escapeHtml(sec.name || '') +
          (sec.teachers && sec.teachers[0] ? ' · ' + escapeHtml(sec.teachers.join(', ')) : '') +
          (sec.credits ? ' · <b>' + sec.credits + '</b> cr' : '') +
          (schedStr ? ' · <span style="color:var(--mut);font-size:.72rem">' + escapeHtml(schedStr) + '</span>' : '') +
        '</div>';
      }

      var coverage = sol.covered;
      var droppedStr = (sol.dropped && sol.dropped.length)
        ? ' <span class="dropped">Dropped: ' + escapeHtml(sol.dropped.join(', ')) + '</span>'
        : '';

      var h =
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
          '<div class="sc-apply" style="margin-top:.5rem">' +
            '<button class="primary" id="solve-apply" style="width:100%;padding:.4rem">Apply This Schedule</button>' +
          '</div>' +
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
}

function switchTab(name) {
  var tabs = document.querySelectorAll('.tabs button');
  for (var i = 0; i < tabs.length; i++) {
    tabs[i].classList.toggle('active', tabs[i].dataset.tab === name);
  }
  document.getElementById('tab-grid').style.display = name === 'grid' ? '' : 'none';
  document.getElementById('tab-solve').style.display = name === 'solve' ? '' : 'none';
  document.getElementById('tab-eval').style.display = name === 'eval' ? '' : 'none';
  document.getElementById('tab-bids').style.display = name === 'bids' ? '' : 'none';
  // Re-render bid panel when switching to bids tab
  if (name === 'bids') renderBidPanel();
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
    return;
  }
  computePickedConflicts();
  var hasConflict = Object.keys(PICKED_CONFLICTS).length > 0;
  var keys = Object.keys(PICKED);

  if (hasConflict) {
    BID_BAR.innerHTML = '';
    BID_BOXES.innerHTML =
      '<div style="color:var(--warn);font-size:.84rem;padding:.5rem 0">⚠ Resolve schedule conflicts first to set bids.</div>';
    BID_META.textContent = '';
    BID_JFFS.textContent = 'conflicts pending';
    BID_JFFS.className = 'bp-jffs over';
    BID_STAT.style.display = 'block';
    BID_STAT_TEXT.innerHTML = '⚠ Conflicts — resolve to bid';
    return;
  }

  BID_STAT.style.display = 'block';
  var jffs = ROUND_INFO.jffs;
  var total = bidTotal();
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
  input.addEventListener('blur', onBidEditBlur);
}

function onBidEditKey(evt) {
  if (!BID_EDIT) return;
  if (evt.key === 'Escape') {
    cancelBidEdit();
    evt.preventDefault();
  } else if (evt.key === 'Enter') {
    var v = parseInt(BID_EDIT.inputEl.value, 10);
    if (!isNaN(v) && v >= 1) {
      PICKED_BIDS[BID_EDIT.rwh] = v;
      var rwh = BID_EDIT.rwh;
      cancelBidEdit();
      renderBidPanel();
    } else {
      cancelBidEdit();
    }
    evt.preventDefault();
  }
}

function onBidEditBlur() {
  if (BID_EDIT) cancelBidEdit();
}

function cancelBidEdit() {
  if (!BID_EDIT) return;
  BID_EDIT.inputEl.removeEventListener('keydown', onBidEditKey);
  BID_EDIT.inputEl.removeEventListener('blur', onBidEditBlur);
  var box = BID_EDIT.inputEl.parentNode;
  box.classList.remove('editing');
  BID_EDIT.inputEl.value = String(BID_EDIT.originalBid);
  BID_EDIT = null;
}

// ── Transfer overlay (drag-and-release confirmation) ──────────────────
function showTransferOverlay(srcRwh, dstRwh) {
  var src = PICKED[srcRwh];
  var dst = PICKED[dstRwh];
  var srcBid = Number(PICKED_BIDS[srcRwh]) || 0;
  var dstBid = Number(PICKED_BIDS[dstRwh]) || 0;
  var srcName = (src.code || srcRwh) + ' (' + (src.class_group || '?') + ')';
  var dstName = (dst.code || dstRwh) + ' (' + (dst.class_group || '?') + ')';

  var overlay = document.createElement('div');
  overlay.className = 'bid-overlay';
  overlay.id = 'bid-transfer-overlay';
  overlay.innerHTML =
    '<div class="bo-box">' +
      '<div class="bo-h">Transfer credits</div>' +
      '<div class="bo-row"><span class="bo-from">' + escapeHtml(srcName) + ' · ' + srcBid + ' pts</span></div>' +
      '<div class="bo-row"><span class="bo-to">' + escapeHtml(dstName) + ' · ' + dstBid + ' pts</span></div>' +
      '<div class="bo-hint">How many to move from source?</div>' +
      '<input class="bo-in" type="number" min="1" max="' + (srcBid - 1) + '" step="1" value="1"/>' +
      '<div class="bo-hint">Enter to confirm · Esc / click-outside to cancel</div>' +
    '</div>';
  document.body.appendChild(overlay);

  var input = overlay.querySelector('.bo-in');
  input.focus();
  input.select();

  function cleanup() {
    if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
    input.removeEventListener('keydown', onKey);
    overlay.removeEventListener('click', onClickOut);
  }
  function onKey(e) {
    if (e.key === 'Escape') { cleanup(); e.preventDefault(); return; }
    if (e.key === 'Enter') {
      var amt = parseInt(input.value, 10);
      if (isNaN(amt) || amt < 1 || amt >= srcBid) {
        // invalid — flash
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
  overlay.addEventListener('click', onClickOut);
}

// ── Submit to TIS ───────────────────────────────────────────────────────
BID_SUBMIT.addEventListener('click', function() {
  submitBids();
});

function submitBids() {
  var picks = {};
  for (var k in PICKED_BIDS) {
    if (PICKED_BIDS.hasOwnProperty(k) && PICKED[k]) {
      picks[k] = PICKED_BIDS[k];
    }
  }
  if (!Object.keys(picks).length) {
    BID_MSG.textContent = 'No picks to bid on.';
    BID_MSG.className = 'bp-msg err';
    return;
  }
  if (!confirm('Sync ' + Object.keys(picks).length + ' bid(s) to TIS? This is a real action.')) return;
  BID_MSG.textContent = 'Submitting: syncing ' + Object.keys(picks).length + ' bid(s)…';
  BID_MSG.className = 'bp-msg';
  BID_SUBMIT.disabled = true;
  postJSON('/api/tis/bids' + sem(), {
    picks: picks,
    xkfsdm: ROUND_INFO.xkfsdm || '',
    where: 'cart',
    jffs_limit: ROUND_INFO.jffs || null,
    dry_run: false,
  }).then(function(res) {
    BID_SUBMIT.disabled = false;
    if (res.over_limit) {
      BID_MSG.textContent = 'Over budget: ' + res.sum + ' > ' + res.jffs_limit + ' pts. Adjust bids first.';
      BID_MSG.className = 'bp-msg err';
      return;
    }
    if (res.error) {
      BID_MSG.textContent = 'Error: ' + res.error;
      BID_MSG.className = 'bp-msg err';
      return;
    }
    var okCount = (res.results || []).filter(function(r){return r.ok;}).length;
    var total = (res.results || []).length;
    BID_MSG.textContent = 'Committed: ' + okCount + '/' + total + ' bid(s) sent' +
      (res.sum ? ' · total ' + res.sum + ' pts' : '');
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

  // Tab buttons
  var tabBtns = document.querySelectorAll('.tabs button');
  for (var i = 0; i < tabBtns.length; i++) {
    tabBtns[i].addEventListener('click', function() {
      switchTab(this.dataset.tab);
    });
  }

  // Load info (this also triggers auto-load of all courses)
  document.getElementById('btn-info').addEventListener('click', loadInfo);

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

  // Mode switch
  document.querySelectorAll('.mode-btn').forEach(function(btn) {
    btn.addEventListener('click', function() {
      var newMode = btn.dataset.mode;
      if (newMode === MODE) return;
      MODE = newMode;
      document.querySelectorAll('.mode-btn').forEach(function(b) {
        b.classList.toggle('active', b.dataset.mode === MODE);
        if (b.dataset.mode === MODE) {
          b.style.border = '1px solid var(--accent)';
          b.style.background = 'rgba(91,157,255,.1)';
        } else {
          b.style.border = 'none';
          b.style.background = 'transparent';
        }
      });
      // Show/hide personal-only filters
      document.querySelectorAll('.personal-only').forEach(function(el) {
        el.style.display = MODE === 'personal' ? 'block' : 'none';
      });
      // Update h2 to reflect the current mode
      var h2 = document.getElementById('mode-h2');
      if (h2) h2.textContent = MODE === 'personal' ? 'Selection' : 'Catalog';
      // Show/hide task_type and scheduled (campus-only)
      var taskRow = document.getElementById('f-tasktype').closest('.row');
      var schedRow = document.getElementById('f-sched').closest('.row');
      if (taskRow) taskRow.style.display = MODE === 'campus' ? 'flex' : 'none';
      if (schedRow) schedRow.style.display = MODE === 'campus' ? 'flex' : 'none';
      // Reload
      ALL_CAT = []; CAT = [];
      if (MODE === 'personal') {
        var self = this;
        getJSON('/api/tis/course-types' + sem()).then(function(d) {
          if (d.course_types && d.course_types.length) populateCourseTypes(d.course_types);
          loadInfo();
        })['catch'](function() { loadInfo(); });
      } else {
        loadInfo();
        loadCourses();   // re-populate ALL_CAT so client-side filter works
      }
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

  // Refresh catalog
  document.getElementById('btn-refresh').addEventListener('click', function() {
    postJSON('/api/tis/refresh' + sem(), {}).then(function(d) {
      if (d.ok) {
        STAT.textContent = 'Refreshed: ' + d.count + ' courses.';
        loadInfo();
      } else {
        STAT.textContent = 'Refresh failed: ' + (d.error || 'unknown');
      }
    })['catch'](function(e) {
      STAT.textContent = 'Refresh error: ' + e.message;
    });
  });

  // Enter key on search input — fire immediately, cancel any debounce
  KW.addEventListener('keydown', function(e) {
    if (e.key === 'Enter') onFilterChangeImmediate();
  });

  // Enrolled
  document.getElementById('btn-enrolled').addEventListener('click', loadEnrolled);

  // Solve
  document.getElementById('btn-solve').addEventListener('click', solve);
  // Grid solve button — switches to solver tab and runs it
  document.getElementById('grid-solve').addEventListener('click', function() {
    switchTab('solve');
    setTimeout(solve, 100);
  });

  // On page load, the personal-mode filter rows (.personal-only) start
  // hidden. The mode-toggle handler shows them — but on initial load
  // (when Selection is the default mode and no toggle happens), the
  // handler never runs. Show them here so the xkfsdm dropdown and
  // ignore-conflicts checkbox are usable immediately.
  if (MODE === 'personal') {
    document.querySelectorAll('.personal-only').forEach(function(el) {
      el.style.display = 'block';
    });
  }

  // Auto-load: on page load, if we're in personal mode, fetch the
  // xkfsdm type list FIRST so the dropdown is populated before the
  // first search fires. Without this, the initial personal search goes
  // out with xkfsdm="" and TIS returns "not yet open" (the round is
  // technically open, but the empty xkfsdm makes TIS reject the
  // queryform). Catalog mode does not need this step.
  function initialLoad() {
    if (MODE === 'personal') {
      getJSON('/api/tis/course-types' + sem()).then(function(d) {
        if (d.course_types && d.course_types.length) populateCourseTypes(d.course_types);
        loadInfo();
      })['catch'](function() { loadInfo(); });
    } else {
      loadInfo();
      loadCourses();
    }
  }
  initialLoad();


});
})();
