#!/usr/bin/env python3
"""
SUSTech Course Grid — Flask backend
Fetches + caches all TIS sections, runs the schedule solver.
Serves Vue 3 SPA at http://localhost:8765
"""

import os, re, json, time, threading
from pathlib import Path
from flask import Flask, send_file, request, jsonify
import requests

app = Flask(__name__, static_folder=".")
DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
CACHE_FILE = DATA_DIR / "courses.json"

SEMESTER = "2025-2026-2"
TIS_BASE = "https://tis.sustech.edu.cn"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "X-Requested-With": "XMLHttpRequest",
}

# ── Playwright fetch (uses existing browser session) ──────────────────────────
_pw_browser = None
_pw_lock = threading.Lock()

def get_playwright():
    global _pw_browser
    with _pw_lock:
        if _pw_browser is None:
            from playwright.sync_api import sync_playwright
            _pw_browser = sync_playwright().start().chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"]
            )
        return _pw_browser

def pw_fetch(url, method="POST", data=None, headers=None, timeout=30):
    """
    Make an HTTP request via a Playwright-controlled browser.
    Uses the browser's existing TIS session (already logged in).
    Returns (status_code, text).
    """
    headers = headers or {}
    headers["X-Requested-With"] = "XMLHttpRequest"
    headers["User-Agent"] = HEADERS["User-Agent"]

    body = None
    if data and method == "POST":
        from urllib.parse import urlencode
        body = urlencode(data)
        headers["Content-Type"] = "application/x-www-form-urlencoded"

    script = f"""
    async () => {{
        const opts = {{
            method: '{method}',
            headers: {json.dumps(dict(headers))},
        }};
        if ({json.dumps(body is not None)}) {{
            opts.body = {json.dumps(body)};
        }}
        const resp = await fetch({json.dumps(url)}, opts);
        const text = await resp.text();
        return {{ status: resp.status, body: text }};
    }}
    """

    browser = get_playwright()
    ctx = browser.new_context()
    page = ctx.new_page()
    try:
        result = page.evaluate(script, timeout=timeout * 1000)
        ctx.close()
        return result["status"], result["body"]
    except Exception as e:
        ctx.close()
        raise RuntimeError(f"pw_fetch failed: {e}")

def tis_post(endpoint, data, cookies=None, use_pw=True):
    """POST to TIS API. Falls back to requests.Session if Playwright unavailable."""
    url = f"{TIS_BASE}{endpoint}"
    if use_pw:
        try:
            status, text = pw_fetch(url, "POST", data, cookies)
            return type('R', (), {'status_code': status, 'text': text})()
        except Exception as e:
            print(f"[WARN] Playwright fetch failed, trying requests: {e}")

    # Fallback: use requests session
    s = requests.Session()
    if cookies:
        s.cookies.update(cookies)
    r = s.post(url, data=data, headers=HEADERS, timeout=20)
    return r

# ── TIS Login ────────────────────────────────────────────────────────────────
def loadsession():
    """Check existing session; re-login only if expired."""
    creds_file = Path(__file__).resolve().parent.parent.parent.parent / "credentials.txt"
    if not creds_file.exists():
        return None
    # Try existing session first (may still be valid)
    for cookie_file in ["tis/session.json", Path.home() / ".hermes" / "tis_session.json"]:
        p = Path(cookie_file)
        if p.exists():
            import json as _json
            try:
                cookies = _json.loads(p.read_text())
                r = requests.get(f"{TIS_BASE}/user/me", cookies=cookies, timeout=10)
                if r.status_code == 200:
                    return cookies
            except Exception:
                pass

    # Re-login via CAS
    creds = creds_file.read_text().strip().split(":")
    if len(creds) != 2:
        return None
    username, password = creds

    s = requests.Session()
    r = s.get(f"{TIS_BASE}/cas/login?service={TIS_BASE}", headers=HEADERS)
    m = re.search(r'name="execution" value="([^"]+)"', r.text)
    if not m:
        # Already authenticated — use session cookies from this request
        return dict(s.cookies)
    exec_val = m.group(1)
    rv = s.post(
        f"{TIS_BASE}/cas/login",
        data={"username": username, "password": password,
              "execution": exec_val, "_eventId": "submit", "geaptcha": ""},
        headers=HEADERS, allow_redirects=False
    )
    if rv.status_code in (302, 303):
        return dict(s.cookies)
    return None

def tis_post(endpoint, data, cookies):
    url = f"{TIS_BASE}{endpoint}"
    r = requests.post(url, data=data, headers=HEADERS, cookies=cookies, timeout=20)
    return r

# ── Fetch all sections ───────────────────────────────────────────────────────
def fetch_all_sections(cookies):
    """Fetch ALL course sections via paginated /Xsxktz/queryRwxxcxList."""
    all_sections = []
    seen_ids = set()
    page_size = 500
    page_num = 1

    # Search by all departments to catch everything
    depts = [
        "MSE","MA","PHY","CH","CS","HUM","SS","CLE","GE","BIO",
        "IPE","EME","MSEK","ART","MUS","PHYI","MSE"
    ]

    for dept in depts:
        p = 1
        while True:
            data = {
                "p_xn": SEMESTER[:9], "p_xq": SEMESTER[-1],
                "p_xnxq": SEMESTER.replace("-", ""),
                "p_xiaoqu": "1", "p_chaxunpylx": "1",
                "p_gjz": dept,
                "pageNum": str(p), "pageSize": str(page_size),
            }
            r = tis_post("/Xsxktz/queryRwxxcxList", data, cookies, use_pw=True)
            if r.status_code != 200:
                break
            try:
                j = json.loads(r.text)
            except Exception:
                break
            rw_list = j.get("rwList", {})
            items = rw_list.get("list", []) or rw_list.get("data", [])
            if not items:
                break
            for item in items:
                rwh = item.get("rwh", "")
                if rwh in seen_ids:
                    continue
                seen_ids.add(rwh)
                all_sections.append(item)
            total = rw_list.get("total", 0)
            if p * page_size >= total:
                break
            p += 1

    return all_sections

def parse_sections(raw_sections):
    """Parse raw TIS section list into {id, code, name, teacher, slots, credits, dept}."""
    courses = []
    weekday_map = {"一":0,"二":1,"三":2,"四":3,"五":4,"六":5,"日":6}
    DAY_LABELS = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]

    slot_re = re.compile(
        r"(?P<weeks>[\d,\-单双]+)\s*Week[,，]?\s*"
        r"(?P<day>Mon|Tue|Wed|Thu|Fri|Sat|Sun)\.?\s*"
        r"(?P<periods>\d+-\d+|\d+)\s*(?P<room>.+)?",
        re.IGNORECASE
    )

    for item in raw_sections:
        kcdm = item.get("kcdm", "")        # course code e.g. MSE306
        kcmc = item.get("kcmc", "")        # course name
        rwh  = item.get("rwh", "")         # section id
        dgjsmc = item.get("dgjsmc", "")    # teacher
        xf    = item.get("xf", "0")        # credits
        kkyxmc = item.get("kkyxmc", "")    # department

        # Parse English HTML (cleaner than Chinese)
        html_en = item.get("pkjgmx_en", "") or item.get("pkjgmx", "")
        if not html_en:
            continue

        # Find all "1-15单Week,Mon. 5-6 一教321、" patterns
        slots = []
        for m in slot_re.finditer(html_en):
            weeks_str = m.group("weeks")
            day_str   = m.group("day").title()[:3]
            periods_str = m.group("periods")
            room      = (m.group("room") or "").strip(" ，、.")

            day_idx = DAY_LABELS.index(day_str) if day_str in DAY_LABELS else -1
            if day_idx == -1:
                continue

            # Parse weeks: "1-15单" → (1,15,"odd"), "1-15" → (1,15,"all")
            weeks_match = re.match(r"(\d+)-(\d+)(单|双)?", weeks_str)
            if weeks_match:
                w_start, w_end, w_flag = weeks_match.groups()
                w_start, w_end = int(w_start), int(w_end)
            else:
                w_start, w_end, w_flag = 1, 15, None

            # Parse periods: "5-6" → [5,6], "5" → [5]
            if "-" in periods_str:
                p_start, p_end = periods_str.split("-")
                periods = list(range(int(p_start), int(p_end)+1))
            else:
                periods = [int(periods_str)]

            week_type = "odd" if w_flag == "单" else "even" if w_flag == "双" else "all"

            slots.append({
                "day": day_idx,
                "periods": periods,
                "weeks_start": w_start,
                "weeks_end": w_end,
                "week_type": week_type,
                "room": room,
            })

        if not slots:
            continue

        courses.append({
            "id": rwh,
            "code": kcdm,
            "name": kcmc,
            "teacher": dgjsmc,
            "credits": float(xf) if xf else 0,
            "dept": kkyxmc,
            "slots": slots,
        })

    return courses

# ── Solver ──────────────────────────────────────────────────────────────────
def section_conflicts(a_slots, b_slots):
    for sa in a_slots:
        for sb in b_slots:
            if sa["day"] != sb["day"]:
                continue
            sa_odd = sa["week_type"] == "all" or sa["week_type"] == "odd"
            sb_odd = sb["week_type"] == "all" or sb["week_type"] == "odd"
            if sa["week_type"] != "all" and sb["week_type"] != "all":
                if sa["week_type"] != sb["week_type"]:
                    continue
            sets_a = set(sa["periods"])
            sets_b = set(sb["periods"])
            if sets_a & sets_b:
                return True
    return False

def solve(sections_by_code, selected_codes, blocked_slots, max_results=20):
    """
    Backtracking: find all non-conflicting section combinations.
    sections_by_code: {code: [section, ...]}
    selected_codes: codes the user has picked
    blocked_slots: [(day, {periods}), ...]
    Returns: list of {courses: [{section}]} solutions
    """
    codes = list(selected_codes)
    results = []

    def conflicts_with_blocked(slots):
        for bs_day, bs_periods in blocked_slots:
            for s in slots:
                if s["day"] == bs_day and set(s["periods"]) & bs_periods:
                    return True
        return False

    def backtrack(i, current):
        if len(results) >= max_results:
            return
        if i == len(codes):
            results.append(list(current))
            return
        code = codes[i]
        sections = sections_by_code.get(code, [])
        if not sections:
            backtrack(i+1, current)
            return
        for sec in sections:
            if conflicts_with_blocked(sec["slots"]):
                continue
            if any(section_conflicts(sec["slots"], c["slots"]) for c in current):
                continue
            current.append(sec)
            backtrack(i+1, current)
            current.pop()

    backtrack(0, [])
    return results

# ── Routes ───────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_file("grid_app.html")

@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    cookies = loadsession()
    if not cookies:
        return jsonify({"error": "login failed"}), 401
    sections = fetch_all_sections(cookies)
    parsed = parse_sections(sections)
    CACHE_FILE.write_text(json.dumps(parsed, ensure_ascii=False, indent=2))
    return jsonify({"count": len(parsed)})

@app.route("/api/courses")
def api_courses():
    if CACHE_FILE.exists():
        age = time.time() - CACHE_FILE.stat().st_mtime
        if age > 3600:
            return jsonify({"status": "stale", "count": 0})
        data = json.loads(CACHE_FILE.read_text())
        return jsonify({"status": "ok", "courses": data, "count": len(data)})
    return jsonify({"status": "no_data", "count": 0})

@app.route("/api/solve", methods=["POST"])
def api_solve():
    body = request.json or {}
    selected = body.get("selected", [])   # [code, ...]
    blocked  = body.get("blocked", [])     # [[day, [periods]], ...]
    max_res  = body.get("max", 20)

    if not selected:
        return jsonify({"error": "no courses selected"}), 400

    # Load cached courses and group by code
    if not CACHE_FILE.exists():
        return jsonify({"error": "no data — POST /api/refresh first"}), 400
    courses = json.loads(CACHE_FILE.read_text())

    by_code = {}
    for c in courses:
        code = c["code"]
        if code not in by_code:
            by_code[code] = []
        by_code[code].append(c)

    # Filter selected to only codes we have
    available = [code for code in selected if code in by_code]
    blocked_slots = [(b[0], set(b[1])) for b in blocked]

    results = solve(by_code, available, blocked_slots, max_res)
    return jsonify({
        "solutions": results,
        "count": len(results),
        "requested": available,
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8765, debug=True)
