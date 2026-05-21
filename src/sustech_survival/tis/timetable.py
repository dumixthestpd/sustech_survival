"""
Standalone timetable conflict solver for SUSTech TIS.

Usage:
    python3 src/sustech_survival/tis/timetable.py MSE306 "SS143" CH106
    python3 src/sustech_survival/tis/timetable.py MSE306 --exclude SS143
    python3 src/sustech_survival/tis/timetable.py MSE306 --codes-file courses.txt

Flags:
    --exclude CODE    Remove this course from the search
    --codes-file F    Read course codes from file (one per line)
    --semester Y-Q    Academic year and quarter (default: 2025-2026-2)
    --max N           Max schedules to show (default: 100)
    --json            Output as JSON
"""

import sys, re, json, argparse
from pathlib import Path
from html import parser as html_parser

_ROOT = Path(__file__).resolve().parent.parent.parent.parent

# ── Login ─────────────────────────────────────────────────────────────────────
def _login():
    import requests

    creds_file = _ROOT / "credentials.txt"
    with open(creds_file) as f:
        username, password = f.read().strip().split(":", 1)

    service_url = "https://tis.sustech.edu.cn/cas"
    encoded = service_url.replace(":", "%3A").replace("/", "%2F")
    login_url = f"https://cas.sustech.edu.cn/cas/login?service={encoded}"
    h = {"User-Agent": "Mozilla/5.0", "X-Requested-With": "XMLHttpRequest"}

    req = requests.get(login_url, headers=h, timeout=15)
    exec_token = re.search(r'name="execution" value="([^"]+)"', req.text).group(1)

    req2 = requests.post(
        login_url,
        data={"username": username, "password": password,
              "execution": exec_token, "_eventId": "submit"},
        allow_redirects=False, headers=h, timeout=15
    )
    ticket_url = req2.headers.get("Location", "")
    req3 = requests.get(ticket_url, allow_redirects=False, headers=h, timeout=15)
    sc = req3.headers.get("Set-Cookie", "")
    route_m = re.search(r"route=([^;]+)", sc)
    jsess_m = re.search(r"JSESSIONID=([^;]+)", sc)
    if not route_m or not jsess_m:
        return None
    return {"route": route_m.group(1), "JSESSIONID": jsess_m.group(1)}


# ── Slot parser (uses pkjgmx_en — English HTML, much cleaner) ─────────────────
_EN_DAY_MAP = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}


class _SlotParser(html_parser.HTMLParser):
    """Extract plain-text content from <p> tags."""
    def __init__(self):
        super().__init__()
        self.slots = []
        self._in_p = False
        self._buf = ""

    def handle_starttag(self, tag, attrs):
        if tag == "p":
            self._in_p = True
            self._buf = ""

    def handle_endtag(self, tag):
        if tag == "p" and self._in_p:
            self._in_p = False
            text = self._buf.strip()
            if text:
                self.slots.append(text)

    def handle_data(self, data):
        if self._in_p:
            self._buf += data


# English slot format: "1-15单Week,Mon. 5-6 一教321" or "1-9,11,13-15Week,Wed. 5-6"
_EN_SLOT_RE = re.compile(
    r"^(?P<weeks>[\d,-]+)(?P<note>单|双)?Week,"
    r"(?P<day>Mon|Tue|Wed|Thu|Fri|Sat|Sun)\.?[ ]*"
    r"(?P<periods>\d+-\d+|\d+)"
    r"[ ]*(?P<room>.+)?$"
)


def _parse_week_list(s: str) -> tuple[set[int], str]:
    """Parse '1-15' or '1-9,11,13-15' into a set of week numbers."""
    weeks: set[int] = set()
    week_type = "all"
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = part.split("-", 1)
            weeks.update(range(int(start), int(end) + 1))
        else:
            weeks.add(int(part))
    return weeks, week_type


def parse_slots(html: str) -> list[dict]:
    """Parse English pkjgmx_en HTML into slot dicts."""
    p = _SlotParser()
    p.feed(html)
    slots = []

    for raw in p.slots:
        m = _EN_SLOT_RE.match(raw)
        if not m:
            continue

        weeks_raw = m.group("weeks")   # "1-15" or "1-9,11,13-15"
        note = m.group("note") or ""   # 单 or 双 (embedded in weeks_raw)
        day_str = m.group("day")        # Mon, Tue, etc.
        periods_raw = m.group("periods")  # "5-6" or "5"
        room = m.group("room") or ""   # "一教321"

        weeks, week_type = _parse_week_list(weeks_raw)

        if note == "单":
            weeks = {w for w in weeks if w % 2 == 1}
            week_type = "odd"
        elif note == "双":
            weeks = {w for w in weeks if w % 2 == 0}
            week_type = "even"

        if "-" in periods_raw:
            p1, p2 = periods_raw.split("-")
            periods = list(range(int(p1), int(p2) + 1))
        else:
            periods = [int(periods_raw)]

        day = _EN_DAY_MAP.get(day_str, -1)

        slots.append({
            "raw": raw,
            "weeks": weeks,
            "week_type": week_type,
            "day": day,
            "periods": periods,
            "room": room,
        })

    return slots


# ── Conflict detection ─────────────────────────────────────────────────────────
def slots_conflict(a: dict, b: dict) -> bool:
    """True if two slots overlap (same day + shared week + shared period)."""
    if a["day"] != b["day"]:
        return False
    if not (a["weeks"] & b["weeks"]):
        return False
    return bool(set(a["periods"]) & set(b["periods"]))


def section_conflict(s1: dict, s2: dict) -> bool:
    """True if any slot in s1 conflicts with any slot in s2."""
    for a in s1.get("slots", []):
        for b in s2.get("slots", []):
            if slots_conflict(a, b):
                return True
    return False


# ── Fetch sections from TIS ───────────────────────────────────────────────────
def fetch_sections(codes: list[str], cookies: dict, xn: str, xq: str) -> dict[str, list[dict]]:
    import requests

    h = {
        "User-Agent": "Mozilla/5.0",
        "X-Requested-With": "XMLHttpRequest",
        "Cookie": f"route={cookies['route']}; JSESSIONID={cookies['JSESSIONID']}",
    }

    result = {}
    for code in codes:
        r = requests.post(
            "https://tis.sustech.edu.cn/Xsxktz/queryRwxxcxList",
            data={
                "p_xn": xn, "p_xq": xq,
                "p_chaxunpylx": "1",
                "p_gjz": code,
                "pageNum": 1, "pageSize": 500,
            },
            headers=h, timeout=15
        )
        # Use pkjgmx_en (English) for clean parsing
        raw_list = r.json().get("rwList", {}).get("list", [])
        parsed = []
        for item in raw_list:
            slots = parse_slots(item.get("pkjgmx_en", "") or item.get("pkjgmx", ""))
            if not slots:
                continue
            parsed.append({
                "code": code,
                "name": item.get("kcmc", ""),
                "section": item.get("kxh", ""),
                "instructor": item.get("dgjsmc", ""),
                "slots": slots,
            })
        result[code] = parsed
    return result


def parse_block(block_str: str) -> tuple[int, set[int]]:
    """Parse 'FRI:9-10' or 'FRI:9' → (day_int 0-6, {periods})."""
    day_str, periods_str = block_str.upper().split(":", 1)
    DAY_MAP = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6}
    day = DAY_MAP.get(day_str.strip())
    if day is None:
        raise ValueError(f"Unknown day: {day_str}. Use MON/TUE/WED/THU/FRI/SAT/SUN")
    periods = set()
    for part in periods_str.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            periods.update(range(int(start), int(end) + 1))
        else:
            periods.add(int(part))
    return day, periods


def section_blocks_blocked(sec: dict, blocked: list[tuple[int, set[int]]]) -> bool:
    """True if sec has any slot that overlaps a blocked day+period."""
    for slot in sec.get("slots", []):
        slot_periods = set(slot["periods"])
        for blocked_day, blocked_periods in blocked:
            if slot["day"] == blocked_day and slot_periods & blocked_periods:
                return True
    return False


# ── Solver ─────────────────────────────────────────────────────────────────────
def solve(sections: dict[str, list[dict]], max_results: int = 100,
          blocked: list[tuple[int, set[int]]] = None) -> list[list[dict]]:
    codes = list(sections.keys())
    results: list[list[dict]] = []

    blocked = blocked or []
    def backtrack(i: int, current: list[dict]):
        if i == len(codes):
            results.append(list(current))
            return
        if len(results) >= max_results:
            return
        code = codes[i]
        for sec in sections[code]:
            if section_blocks_blocked(sec, blocked):
                continue
            conflict = any(
                section_conflict(sec, sel)
                for sel in current
            )
            if not conflict:
                current.append(sec)
                backtrack(i + 1, current)
                current.pop()

    backtrack(0, [])
    return results


# ── Rendering ─────────────────────────────────────────────────────────────────
DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
PERIODS = list(range(1, 13))


def render_grid(schedule: list[dict]) -> str:
    """ASCII grid: rows=days, cols=periods."""
    grid = [[" " for _ in PERIODS] for _ in DAY_LABELS]

    for sec in schedule:
        label = f"{sec['code']}/{sec['section']}"
        for slot in sec["slots"]:
            for p in slot["periods"]:
                if 0 <= slot["day"] <= 6 and 1 <= p <= 12:
                    grid[slot["day"]][p - 1] = label

    pw = 13
    lines = [" " * 9 + "".join(f"{p:^{pw}}" for p in PERIODS)]
    lines.append("─" * len(lines[0]))
    for i, day in enumerate(DAY_LABELS):
        row = f"{day:>8} "
        for p in PERIODS:
            row += f"{grid[i][p-1]:^{pw}}"
        lines.append(row)
    return "\n".join(lines)


def describe_section(sec: dict) -> str:
    parts = []
    for s in sec["slots"]:
        w = f"{min(s['weeks'])}-{max(s['weeks'])}w"
        if s["week_type"] != "all":
            w += s["week_type"][0].upper()
        d = DAY_LABELS[s["day"]]
        pp = f"{s['periods'][0]}" if len(s["periods"]) == 1 else f"{s['periods'][0]}-{s['periods'][-1]}"
        parts.append(f"{w} {d} p{pp} @{s['room']}")
    return " | ".join(parts)


# ── CLI ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="SUSTech timetable solver")
    parser.add_argument("courses", nargs="*", help="Course codes (e.g. MSE306 SS143)")
    parser.add_argument("--exclude", "-e", action="append", default=[],
                        help="Exclude course code from search")
    parser.add_argument("--codes-file",
                        help="File with one course code per line")
    parser.add_argument("--semester", default="2025-2026-2",
                        help="Format: YYYY-YYYY-Q (default: 2025-2026-2)")
    parser.add_argument("--max", type=int, default=100)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--block", "-b", action="append", default=[],
                        help="Block a time slot: DAY:PERIODS (e.g. FRI:9-10, MON:5,6)")
    args = parser.parse_args()

    # Load codes
    codes: list[str] = list(args.courses)
    if args.codes_file:
        with open(args.codes_file) as f:
            codes += [l.strip() for l in f if l.strip()]
    codes = [c for c in codes if c not in args.exclude]
    if not codes:
        print("❌ No courses specified", file=sys.stderr)
        sys.exit(1)

    # Parse blocked slots
    blocked: list[tuple[int, set[int]]] = []
    for b in args.block:
        try:
            blocked.append(parse_block(b))
        except ValueError as e:
            print(f"❌ {e}", file=sys.stderr)
            sys.exit(1)

    parts = args.semester.rsplit("-", 1)
    xn, xq = parts[0], parts[1]

    print(f"🔑 Login...", file=sys.stderr)
    cookies = _login()
    if not cookies:
        print("❌ Login failed", file=sys.stderr)
        sys.exit(1)

    print(f"📡 Fetching sections ({xn}-{xq})...", file=sys.stderr)
    for code in codes:
        print(f"  {code}: ", file=sys.stderr, end="", flush=True)

    sections = fetch_sections(codes, cookies, xn, xq)

    for code in codes:
        n = len(sections.get(code, []))
        print(f"{n} sections", file=sys.stderr, flush=True)

    all_empty = all(len(sections.get(c, [])) == 0 for c in codes)
    if all_empty:
        print(f"⚠️  No sections found: {', '.join(codes)}", file=sys.stderr)
        print("❌ Nothing to schedule.", file=sys.stderr)
        sys.exit(1)

    blocked_desc = ", ".join(f"{DAY_LABELS[d]}:{','.join(str(p) for p in sorted(ps))}"
                              for d, ps in blocked)
    if blocked:
        print(f"🚫 Blocked: {blocked_desc}", file=sys.stderr)
    results = solve(sections, max_results=args.max, blocked=blocked)

    if args.json:
        out = [{"schedule": r, "total_credits": sum(3 for _ in r)} for r in results]
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return

    print(f"\n✅ Found {len(results)} conflict-free schedule(s)\n", file=sys.stderr)
    for i, sched in enumerate(results):
        print(f"═══ Schedule {i + 1} ═══")
        print(render_grid(sched))
        print()
        for sec in sched:
            print(f"  {sec['code']}/{sec['section']} | {sec['name']}")
            print(f"    {describe_section(sec)}")
        print()


if __name__ == "__main__":
    main()
