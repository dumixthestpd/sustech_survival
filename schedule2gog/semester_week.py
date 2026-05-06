#!/usr/bin/env python3
"""
SUSTech Semester Week Calculator

Calculates which teaching week a date falls in for SUSTech semesters.
Reads from `~/.openclaw/workspace/sustech/semester.json`.

Can be used as a module or a CLI script:

    # CLI
    python3 semester_week.py
    python3 semester_week.py 2026-04-20
    python3 semester_week.py next monday

    # Module
    from semester_week import get_week
    info = get_week("2026-04-20")
    print(info["week"], info["parity"])  # 8, "even"
"""

import datetime
import json
import os
import re
import sys
from typing import Optional, Union

# ─── Constants ────────────────────────────────────────────────────────────────

CONFIG_PATH = "/Users/dumix/.openclaw/workspace/sustech/2026-spring.json"

WEEKDAY_NAME_EN = [
    "Monday", "Tuesday", "Wednesday", "Thursday",
    "Friday", "Saturday", "Sunday"
]
WEEKDAY_NAME_CN = [
    "周一", "周二", "周三", "周四",
    "周五", "周六", "周日"
]
WEEKDAY_INDEX = {name.lower(): i for i, name in enumerate(WEEKDAY_NAME_EN)}

# Default MWF / TTh schedule (can be overridden in _notes)
DEFAULT_ODD_DAYS = [0, 2, 4]   # Mon, Wed, Fri
DEFAULT_EVEN_DAYS = [1, 3]     # Tue, Thu

# ─── Config ───────────────────────────────────────────────────────────────────

def load_config(config_path: Optional[str] = None) -> dict:
    path = config_path or CONFIG_PATH
    if not os.path.exists(path):
        print(f"❌ Config not found: {path}", file=sys.stderr)
        print(f"   Update: sk2gog calendar --update && sk2gog calendar --parse", file=sys.stderr)
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def semester_end(config: dict) -> datetime.date:
    """Derive semester end date from week_1_monday + total_weeks."""
    monday = datetime.date.fromisoformat(config["week_1_monday"])
    return monday + datetime.timedelta(weeks=config["total_weeks"])


def get_schedule_days(config: dict) -> tuple[list[int], list[int]]:
    """
    Returns (odd_week_days, even_week_days) as lists of weekday indices.
    Falls back to _notes overrides if present, else defaults.
    """
    notes = config.get("_notes", {})
    if "odd_week_days" in notes or "even_week_days" in notes:
        odd = notes.get("odd_week_days", DEFAULT_ODD_DAYS)
        even = notes.get("even_week_days", DEFAULT_EVEN_DAYS)
    else:
        odd, even = DEFAULT_ODD_DAYS, DEFAULT_EVEN_DAYS
    return odd, even


def holiday_ranges(config: dict) -> list[tuple[datetime.date, datetime.date]]:
    """Returns [(from, to), ...] for all holidays."""
    return [
        (datetime.date.fromisoformat(h["from"]), datetime.date.fromisoformat(h["to"]))
        for h in config.get("holidays", [])
    ]


def is_holiday(target: datetime.date, ranges: list[tuple[datetime.date, datetime.date]]) -> bool:
    return any(from_d <= target <= to_d for from_d, to_d in ranges)


def compensate_map(config: dict) -> dict[str, dict]:
    """Returns {date_str: {expected_weekday, expected_week}}."""
    return {
        c["date"]: {"expected_weekday": c["expected_weekday"], "expected_week": c["expected_week"]}
        for c in config.get("compensates", [])
    }


# ─── Core Logic ───────────────────────────────────────────────────────────────

def week_number(target: datetime.date, week1_monday: datetime.date) -> int:
    return (target - week1_monday).days // 7 + 1


def week_parity(wn: int) -> str:
    return "odd" if wn % 2 == 1 else "even"


def is_class_day(
    target: datetime.date,
    wn: int,
    odd_days: list[int],
    even_days: list[int],
    comp_map: dict,
) -> bool:
    scheduled = odd_days if wn % 2 == 1 else even_days
    if target.weekday() in scheduled:
        return True
    if target.isoformat() in comp_map:
        return True
    return False


def get_week(target: Union[datetime.date, str], config: Optional[dict] = None) -> dict:
    """
    Returns {
        "date", "week", "parity",
        "week_monday", "week_sunday",
        "is_class_day", "is_holiday", "is_compensatory",
        "holiday_range", "compensatory_info",
        "is_first_class_day", "semester_meta",
    }
    """
    if config is None:
        config = load_config()

    meta = {k: config[k] for k in ("week_1_monday", "first_class_day", "total_weeks") if k in config}
    week1_monday = datetime.date.fromisoformat(config["week_1_monday"])
    first_class = datetime.date.fromisoformat(config["first_class_day"])
    sem_end = semester_end(config)
    odd_days, even_days = get_schedule_days(config)
    holidays = holiday_ranges(config)
    comp_map = compensate_map(config)

    # Resolve target
    if isinstance(target, str):
        target = datetime.date.fromisoformat(target)

    result = {
        "date": target,
        "week": None,
        "parity": None,
        "week_monday": None,
        "week_sunday": None,
        "is_class_day": False,
        "is_holiday": False,
        "holiday_range": None,
        "is_compensatory": False,
        "compensatory_info": None,
        "is_first_class_day": False,
        "semester_meta": meta,
    }

    # Pre-semester
    if target < week1_monday:
        result["_pre_semester_days"] = (week1_monday - target).days
        return result

    # Post-semester
    if target > sem_end:
        result["_post_semester"] = True
        return result

    # Within semester
    wn = week_number(target, week1_monday)
    monday = target - datetime.timedelta(days=target.weekday())
    sunday = monday + datetime.timedelta(days=6)

    result.update({
        "week": wn,
        "parity": week_parity(wn),
        "week_monday": monday,
        "week_sunday": sunday,
    })

    # Holiday check
    for from_d, to_d in holidays:
        if from_d <= target <= to_d:
            result["is_holiday"] = True
            result["holiday_range"] = (from_d.isoformat(), to_d.isoformat())
            return result

    # Compensatory
    if target.isoformat() in comp_map:
        result["is_compensatory"] = True
        result["compensatory_info"] = comp_map[target.isoformat()]

    # First class day
    if target == first_class:
        result["is_first_class_day"] = True

    # Class day
    result["is_class_day"] = is_class_day(target, wn, odd_days, even_days, comp_map)

    return result


# ─── Formatting ───────────────────────────────────────────────────────────────

def format_week_range(monday: datetime.date, sunday: datetime.date) -> str:
    def fmt(d):
        return d.strftime("%b %d").replace(" 0", " ").replace("  ", " ")
    return f"{fmt(monday)} — {fmt(sunday)}"


def format_result(info: dict) -> str:
    target = info["date"]
    meta = info["semester_meta"]

    lines = []
    lines.append("")
    lines.append(f"  ╔══════════════════════════════════════════════════════╗")
    lines.append(f"  ║       SUSTech  Semester Week Calculator              ║")
    lines.append(f"  ╚══════════════════════════════════════════════════════╝")
    lines.append("")
    lines.append(f"  📅 Date:   {target.isoformat()} ({WEEKDAY_NAME_EN[target.weekday()]})")
    lines.append(f"  📅 Config: {CONFIG_PATH}")
    lines.append(f"  ─────────────────────────────────────────────────────────")

    # Pre/post semester
    if info.get("_pre_semester_days") is not None:
        days = info["_pre_semester_days"]
        lines.append(f"\n  ⏳ Pre-semester — {days} day{'s' if days != 1 else ''} until Week 1")
        lines.append("")
        return "\n".join(lines)

    if info.get("_post_semester"):
        lines.append(f"\n  🏖️ Post-semester — classes have ended")
        lines.append("")
        return "\n".join(lines)

    # Holiday
    if info.get("is_holiday"):
        f_str, t_str = info["holiday_range"]
        lines.append(f"\n  🎉 Holiday: {f_str} → {t_str}")
        lines.append(f"     No classes!")
        lines.append("")
        return "\n".join(lines)

    # Regular week
    wn = info["week"]
    parity = info["parity"].upper()
    mon, sun = info["week_monday"], info["week_sunday"]

    lines.append(f"\n  📚 Week {wn} ({parity} week)")
    lines.append(f"     Range:  {format_week_range(mon, sun)}")

    if info.get("is_first_class_day"):
        lines.append(f"     🌟 First day of classes!")

    if info.get("is_compensatory"):
        ci = info["compensatory_info"]
        lines.append(f"     🔄 Compensatory: {ci['expected_weekday']} schedule (was {ci['expected_week']} week)")

    days_left = (sun - target).days
    suffix = "today" if days_left == 0 else (f"{days_left} day{'s' if days_left != 1 else ''} left" if days_left > 0 else "done")
    lines.append(f"     📌 {suffix}")

    odd_days, even_days = DEFAULT_ODD_DAYS, DEFAULT_EVEN_DAYS
    if info["parity"] == "odd":
        schedule = [WEEKDAY_NAME_CN[d] for d in sorted(odd_days)]
        lines.append(f"     → Odd week:  {', '.join(schedule)}")
    else:
        schedule = [WEEKDAY_NAME_CN[d] for d in sorted(even_days)]
        lines.append(f"     → Even week: {', '.join(schedule)}")

    lines.append("")
    lines.append(f"  ─────────────────────────────────────────────────────────")
    lines.append(f"  Usage: python3 semester_week.py [date]")
    lines.append(f"         python3 semester_week.py 2026-05-01")
    lines.append(f"         python3 semester_week.py next monday")
    lines.append("")

    return "\n".join(lines)


# ─── CLI ──────────────────────────────────────────────────────────────────────

def parse_date_arg(arg: str) -> datetime.date:
    arg = arg.strip().lower()
    if arg in ("today", "") or arg == datetime.date.today().isoformat():
        return datetime.date.today()
    if arg == "tomorrow":
        return datetime.date.today() + datetime.timedelta(days=1)

    if arg in WEEKDAY_INDEX:
        return _next_weekday(WEEKDAY_INDEX[arg])
    if arg.startswith("next "):
        day_name = arg[5:].strip()
        if day_name in WEEKDAY_INDEX:
            return _next_weekday(WEEKDAY_INDEX[day_name], weeks_ahead=1)
        raise ValueError(f"Unknown day: {arg!r}")
    if arg.startswith("this "):
        day_name = arg[5:].strip()
        if day_name in WEEKDAY_INDEX:
            return _this_weekday(WEEKDAY_INDEX[day_name])
        raise ValueError(f"Unknown day: {arg!r}")

    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.datetime.strptime(arg, fmt).date()
        except ValueError:
            pass

    m = re.match(r"^(\d{1,2})[-/](\d{1,2})$", arg)
    if m:
        return datetime.date(datetime.date.today().year, int(m.group(1)), int(m.group(2)))

    raise ValueError(f"Cannot parse date: {arg!r}")


def _next_weekday(target_weekday: int, weeks_ahead: int = 0) -> datetime.date:
    today = datetime.date.today()
    days_ahead = target_weekday - today.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return today + datetime.timedelta(days=days_ahead + weeks_ahead * 7)


def _this_weekday(target_weekday: int) -> datetime.date:
    today = datetime.date.today()
    days_ahead = target_weekday - today.weekday()
    if days_ahead < 0:
        days_ahead += 7
    return today + datetime.timedelta(days=days_ahead)


def main():
    config = load_config()
    target = parse_date_arg(" ".join(sys.argv[1:])) if len(sys.argv) > 1 else datetime.date.today()
    info = get_week(target, config)
    print(format_result(info))


if __name__ == "__main__":
    main()
