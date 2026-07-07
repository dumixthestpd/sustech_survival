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
var COLLEGE_MAP = {};       // college-name → college-code (for p_kkyx on TIS personal search)
var LANGUAGE_MAP = {'中文': '1', '英文': '2', '双语': '3'}; // language-name → TIS code
var MODE = 'personal';      // 'personal' (我要选课, default) or 'campus' (全校课表, browse-only)

var PERIODS = 12;
var BLOCKED = {};          // { 'day:period' -> true }   day=1-7, period=1-12

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
    // Colleges: d.colleges is [(code, name), ...] — store name as option text,
    // but stash the code→name map on the select so loadCourses() can look up
    // the code for personal-mode requests (TIS p_kkyx requires the code).
    COLLEGE_MAP = {};
    var collegeItems = d.colleges.map(function(p) {
      COLLEGE_MAP[p[1]] = p[0];
      return p[1];
    });
    populateSelect(F_COL, collegeItems);
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
  // Campus mode does a substring match on c.college (the display name).
  // Personal mode hits TIS's p_kkyx which REQUIRES the code, not the name —
  // sending the name yields 0 results. Look up the code from COLLEGE_MAP.
  if (MODE === 'personal' && F_COL.value && COLLEGE_MAP[F_COL.value]) {
    qs += '&college=' + encodeURIComponent(COLLEGE_MAP[F_COL.value]);
  } else {
    qs += '&college=' + encodeURIComponent(F_COL.value);
  }
  qs += '&task_type=' + encodeURIComponent(F_TASK.value);
  qs += '&category=' + encodeURIComponent(F_CAT.value);
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
      // NCES compare — jumps to the public NCES search page for this code
      // so the user can browse all sections + reviews without our cache.
      (c.code ? '<a class="ghost nces-link" target="_blank" rel="noopener" href="https://ncesnext.com/search?q=' + encodeURIComponent(c.code) + '" title="Compare all sections of this course on NCES" style="color:var(--accent);font-size:.7rem;padding:.1rem .35rem;text-decoration:none">↗ NCES</a>' : '') +
    '</div>';

  card.addEventListener('click', function(e) {
    if (e.target.closest('.pick-btn')) return;
    if (e.target.closest('.nces-link')) return;  // let the <a> open its href
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
  var cards = RESULTS.querySelectorAll('.c-card');
  for (var i = 0; i < cards.length; i++) {
    cards[i].classList.toggle('active', cards[i].dataset.rwh === rwh);
  }
  var course = null;
  for (var j = 0; j < CAT.length; j++) {
    if (CAT[j].rwh === rwh) { course = CAT[j]; break; }
  }
  if (!course) return;
  switchTab('eval');
  // Try to find the matching NCES id and open the full detail; fall back
  // to the brief shape (rating + 3 review excerpts) if we can't pin it.
  fetchEval(course.code, course.teachers && course.teachers.join(','));
}

// fetchEval: called when a TIS card is clicked. Prefer the full detail
// (which has all reviews) by looking up the NCES id first via the brief
// endpoint; if that succeeds, we have an nces_id and switch to detail.
function fetchEval(code, teacher) {
  code = String(code || '').trim();
  if (!code) return;
  if (EVAL_CACHE[code]) {
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
      EVAL_CACHE[code] = d;
      routeEvalResponse(d);
    })['catch'](function(e) {
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
    if (!items.length) {
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
  EVAL_OUT.innerHTML = '<div class="ncn" style="padding:1rem">Loading course detail…</div>';
  getJSON('/api/nces/course/' + nces_id).then(function(d) {
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
  // Drag-to-reorder support. The picked list doubles as the priority
  // list for the solver, so reordering items = reprioritising courses
  // (like SUSTech_AutoScheduler). The drag handle is the whole item,
  // but right-click is reserved for the un-pick badge.
  div.draggable = true;

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
              'title="' + escapeHtml(b.code + ' ' + (b.course.class_group || '') + ' ' + dayName(b.day) + ' ' + b.periodStart + '-' + b.periodEnd + (b.conflict ? ' ⚠ CONFLICT' : '')) + '" ' +
              'data-rwh="' + b.rwh + '">' +
              '<span class="t">' + escapeHtml(b.code) + '</span>' +
              '<span style="font-size:.6rem;opacity:.8;display:block">' + escapeHtml(b.course.name || '') + '</span>' +
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
  // Re-apply blocked cells on top of course blocks (so they show even when
  // the cell already has a course drawn)
  applyBlockedVisual(GRID_ODD);
  applyBlockedVisual(GRID_EVEN);

  // Wire click + drag for blocking. Done here (not in renderGridBlocks)
  // because the cell DOM is rewritten each time and event delegation keeps
  // the listener attached to a stable parent.
  attachGridBlockingHandlers(GRID_ODD);
  attachGridBlockingHandlers(GRID_EVEN);
  // Right-click on a blocked cell cycles week-detail mode (all/odd/even)
  attachGridContextMenu(GRID_ODD);
  attachGridContextMenu(GRID_EVEN);
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

// Right-click on a cell in a blocked tbody: cycle week-detail mode
// (all → odd → even → all) and refresh visuals.
function attachGridContextMenu(tbody) {
  if (!tbody || tbody.dataset.ctxWired === '1') return;
  tbody.dataset.ctxWired = '1';
  tbody.addEventListener('contextmenu', function(e) {
    var td = e.target.closest('td[data-day][data-period]');
    if (!td) return;
    e.preventDefault();
    var key = td.getAttribute('data-day') + ':' + td.getAttribute('data-period');
    // Only meaningful for already-blocked cells
    if (!BLOCKED[key]) return;
    var next = _blockMode(key) === 'all' ? 'odd'
             : _blockMode(key) === 'odd' ? 'even'
             : 'all';
    _setBlockMode(key, next);
    applyBlockedVisual(GRID_ODD);
    applyBlockedVisual(GRID_EVEN);
    syncBlockedInput();
  });
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
    var idx = 0;            // index into the FLAT solutions list (for nav)
    var flat = solutions;
    var total = flat.length;

    function renderSolveItem() {
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

      // Build section rows + total credits
      var secHtml = '';
      var totalCredits = 0;
      for (var si = 0; si < sol.sections.length; si++) {
        var sec = sol.sections[si];
        var schedStr = sec.schedule || formatSchedule(sec.slots);
        totalCredits += parseFloat(sec.credits) || 0;
        // Annotate sections that had intra-code siblings
        var intraNote = '';
        if (intraDrops[sec.code]) {
          var others = intraDrops[sec.code].map(function(r) {
            var p = userPickedByCode[sec.code].filter(function(x) { return x === r; })[0] && PICKED[r];
            if (!p) return r;
            return 'class ' + (p.class_group || '?') + (p.teachers && p.teachers[0] ? ' (' + p.teachers[0] + ')' : '');
          }).join(', ');
          intraNote = ' <span class="sc-note">← kept this; ' + others + ' dropped (one code one class rule)</span>';
        }
        secHtml += '<div class="sc-sec">' +
          '<span class="solve-sec-code">' + escapeHtml(sec.code) + '</span>' +
          (sec.class_group ? ' <span style="color:var(--mut)">' + escapeHtml(sec.class_group) + '</span>' : '') +
          ' · ' + escapeHtml(sec.name || '') +
          (sec.teachers && sec.teachers[0] ? ' · ' + escapeHtml(sec.teachers.join(', ')) : '') +
          (sec.credits ? ' · <b>' + sec.credits + '</b> cr' : '') +
          (schedStr ? ' · <span style="color:var(--mut);font-size:.72rem">' + escapeHtml(schedStr) + '</span>' : '') +
          intraNote +
        '</div>';
      }

      // Build dropped annotation lines: "MSE410: dropped ↔ conflict with CH105"
      var dropHtml = '';
      if (droppedCodes.length) {
        dropHtml = '<div class="sc-drops">';
        droppedCodes.forEach(function(code) {
          var name = (PICKED[Object.keys(PICKED).filter(function(r) { return PICKED[r].code === code; })[0]] || {}).name || code;
          var reason = conflictReasons[code];
          var reasonText = reason && reason[0]
            ? '↔ conflict with <b>' + escapeHtml(reason[0].code) + '</b>'
            : '↔ no non-conflicting section exists';
          dropHtml += '<div class="sc-drop-row">' +
            '<span class="solve-sec-code">' + escapeHtml(code) + '</span> ' +
            escapeHtml(name) + ': <span style="color:var(--bad)">dropped</span>. ' +
            reasonText +
          '</div>';
        });
        dropHtml += '</div>';
      }

      var coverage = sol.covered;
      var droppedStr = (sol.dropped && sol.dropped.length)
        ? ' <span class="dropped">Dropped: ' + escapeHtml(sol.dropped.join(', ')) + '</span>'
        : '';

      // Build the group header: click to jump to first solution in that group.
      // Each group = same "dropped" set = a category of combinations.
      var groupHtml = '<div class="solve-groups">';
      for (var gk = 0; gk < groupOrder.length; gk++) {
        var gkey = groupOrder[gk];
        var gsols = groups[gkey];
        var gFirst = flat.indexOf(gsols[0]);
        var isActive = (gFirst === idx);
        var label = gkey === '__all__'
          ? 'No courses dropped'
          : 'Dropped ' + escapeHtml(gsols[0].dropped.join(', '));
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
          dropHtml +
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
  if (name === 'bids') renderBidPanel();
  // Lazy-load the NCES browse on first eval-tab open
  if (name === 'eval' && !EVAL_OUT.innerHTML.trim()) {
    renderEvalBrowse();
  }
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
  BID_EDIT.inputEl.removeEventListener('input', onBidEditInput);
  BID_EDIT.inputEl.removeEventListener('blur', onBidEditBlur);
  var box = BID_EDIT.inputEl.parentNode;
  box.classList.remove('editing');
  BID_EDIT.inputEl.value = String(BID_EDIT.originalBid);
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
  // cold load AND on every mode toggle.
  function loadForMode() {
    ALL_CAT = []; CAT = [];
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
  // Blocked-time text input: keep BLOCKED state in sync with manual edits
  // (the grid is the primary editor; the input is a fallback for power users)
  var blockedEl = document.getElementById('blocked-input');
  if (blockedEl) {
    loadBlockedFromInput();  // initial population
    blockedEl.addEventListener('change', function() {
      loadBlockedFromInput();
      renderGrid();
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


});
})();
