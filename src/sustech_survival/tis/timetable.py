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
from pathlib import Path as _Path
from html import parser as html_parser
from sustech_survival.sso import TISAuth

SKILL_ROOT = _Path(__file__).resolve().parent.parent.parent.parent

# -- Slot parser (uses pkjgmx_en — English HTML, much cleaner) -----------------
_EN_DAY_MAP = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}


class _SlotParser(html_parser.HTMLParser):
    """Extract plain-text content from <p> tags."""
    def __init__(self):
        super().__init__()
        self.slots = []
        self.in_p = False
        self.buf = ""

    def handle_starttag(self, tag, attrs):
        if tag == "p":
            self.in_p = True
            self.buf = ""

    def handle_endtag(self, tag):
        if tag == "p" and self.in_p:
            self.in_p = False
            text = self.buf.strip()
            if text:
                self.slots.append(text)

    def handle_data(self, data):
        if self.in_p:
            self.buf += data


# English slot format: "1-15单Week,Mon. 5-6 一教321" or "1-9,11,13-15Week,Wed. 5-6"
_EN_SLOT_RE = re.compile(
    r"^(?P<weeks>[\d,-]+)(?P<note>单|双)?Week,"
    r"(?P<day>Mon|Tue|Wed|Thu|Fri|Sat|Sun)\.?[ ]*"
    r"(?P<periods>\d+-\d+|\d+)"
    r"[ ]*(?P<room>.+)?$"
)


def parse_week_list(s: str) -> tuple[set[int], str]:
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

        weeks, week_type = parse_week_list(weeks_raw)

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


# -- Conflict detection ---------------------------------------------------------
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


# -- Fetch sections from TIS ---------------------------------------------------
def fetch_sections(codes: list[str], auth, xn: str, xq: str) -> dict[str, list[dict]]:
    result = {}
    for code in codes:
        r = auth.post(
            "/Xsxktz/queryRwxxcxList",
            data={
                "p_xn": xn, "p_xq": xq,
                "p_chaxunpylx": "1",
                "p_gjz": code,
                "pageNum": 1, "pageSize": 500,
            },
            timeout=15
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


# -- Solver ---------------------------------------------------------------------
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


# -- Rendering -----------------------------------------------------------------
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
    lines.append("-" * len(lines[0]))
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



# NOTE: the standalone argparse CLI was removed 2026-08-10 during the
# CLI unification. Use `sustech tis timetable`
# (defined inline in sustech_survival/tis/cli.py) — it wraps the
# same Python API exposed by this module.


# -- Schedule table renderer (TUI grid + markdown export) --------------


def render_table(schedule: list[dict]) -> str:
    """Render one solved schedule as a fixed-grid table (markdown).

    The grid is laid out as:
      - rows = 7 days (Mon..Sun)
      - columns = 12 periods (1..12)
      - cells = "code/section" if a class meets, "." otherwise
    Plus a legend below the grid showing each class with its room/teacher.

    Use case: `sustech tis timetable MSE306 SS143` prints this for the
    solver's output so users can read it in a chat / terminal without
    rendering HTML.

    Args:
        schedule: list of section dicts (the same shape `solve()` returns)

    Returns:
        a multi-line markdown table string
    """
    DAY_LABELS_LOCAL = DAY_LABELS  # ["Mon", ...]
    # 7 × 12 grid: grid[day_int][period_int] = "code/section" or "."
    grid: dict[int, dict[int, str]] = {d: {p: "." for p in range(1, 13)} for d in range(1, 8)}
    # Track each section's room/teacher for the legend below
    legend: dict[tuple[str, str], tuple[str, str]] = {}  # (code, section) → (room, teacher)

    for sec in schedule:
        key = (sec.get("code", ""), sec.get("section", ""))
        room = sec.get("room", "") or ""
        teacher = sec.get("teacher", "") or ""
        legend[key] = (room, teacher)
        for s in sec.get("slots", []):
            d = s.get("day")
            periods = s.get("periods", [])
            if not d or not periods:
                continue
            cell = f"{key[0]}/{key[1]}" if key[1] else key[0]
            for p in periods:
                if 1 <= d <= 7 and 1 <= p <= 12:
                    grid[d][p] = cell

    lines: list[str] = []
    # Header row
    header = "| Day     | " + " | ".join(f"p{p:>2}" for p in range(1, 13)) + " |"
    sep = "|" + "-" * 8 + "|" + "|".join("-" * 4 for _ in range(12)) + "|"
    lines.append(header)
    lines.append(sep)
    for d in range(1, 8):
        row = f"| {DAY_LABELS_LOCAL[d-1]:<6} | " + " | ".join(f"{grid[d][p]:<3}" for p in range(1, 13)) + " |"
        lines.append(row)
    lines.append(sep)
    lines.append("")
    lines.append("**Legend:**")
    if not legend:
        lines.append("  (empty)")
    for (code, sec), (room, teacher) in sorted(legend.items()):
        label = f"{code}/{sec}" if sec else code
        lines.append(f"  - {label}  —  {room or '(no room)'}  /  {teacher or '(no teacher)'}")

    # Add periods label row below grid
    lines.append("")
    lines.append("**Periods:** 1-4 = morning, 5-8 = afternoon, 9-12 = evening (SUSTech convention)")
    return "\n".join(lines)
