#!/usr/bin/env python3
"""
sk2gog — SUSTech Schedule to Google Calendar CLI

Usage:
    sk2gog calendar [--check]
    sk2gog calendar --update [--year YYYY] [--all]
    sk2gog date [YYYY-MM-DD]
    sk2gog week [YYYY-MM-DD]
    sk2gog help
"""

import argparse
import datetime
import json
import os
import re
import sys
from glob import glob
from typing import Optional

import requests
import subprocess

# HTML-based calendar parser (pdftohtml positional extraction)
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)
from html_parse import parse_calendar_html as _parse_calendar_html

# ─── Config ───────────────────────────────────────────────────────────────────

CALENDAR_URL = "https://www.sustech.edu.cn/zh/academic-calendar.html"
BASE_DIR = os.path.expanduser("~/.openclaw/workspace/sustech")
METADATA_FILE = os.path.join(BASE_DIR, "calendar_metadata.json")
SEMESTER_JSON = os.path.join(BASE_DIR, "semester.json")
COURSES_CSV = os.path.join(BASE_DIR, "26spring", "courses.csv")

os.makedirs(BASE_DIR, exist_ok=True)


# ─── Calendar Commands ───────────────────────────────────────────────────────

def cmd_calendar(args) -> int:
    """Fetch / check academic calendar."""
    html = _fetch_page(CALENDAR_URL)
    calendars = _find_links(html)
    if not calendars:
        print("No calendars found on page.")
        return 1

    print(f"Found {len(calendars)} calendar(s) on page:")
    for c in calendars:
        print(f"  {c['year']}: {c['text']}")
    print()

    page_years = {c["year"] for c in calendars}

    if args.check:
        updates = _check_updates(calendars)
        if updates:
            for c, reason in updates:
                print(f"[{reason}] {c['year']}: {c['text']}")
        else:
            print("All up to date.")
        return 0

    if args.update or not args.check:
        if args.all:
            targets = calendars
        elif args.year:
            targets = [c for c in calendars if c["year"] == str(args.year)]
            if not targets:
                print(f"Year {args.year} not found. Available: {', '.join(sorted(page_years))}")
                return 1
        else:
            default_year = max(page_years)
            targets = [c for c in calendars if c["year"] == default_year]
            print(f"Defaulting to {default_year}. Use --year or --all to change.")

        for c in targets:
            year = c["year"]
            pdf_path = os.path.join(BASE_DIR, f"academic-calendar-{year}.pdf")
            needs_download = (
                args.update
                or not os.path.exists(pdf_path)
                or _check_updates([c])
            )
            if needs_download:
                print(f"Downloading {year}...", end=" ")
                if _download_pdf(c["url"], pdf_path):
                    print("done.")
                else:
                    print("failed.")
            else:
                print(f"{year}: already cached.")

        _save_metadata(calendars)
    return 0


def cmd_parse(args) -> int:
    """
    Parse cached calendar PDF(s) into semester.json.

    Uses pdftohtml to convert PDF to HTML with positional data, then parses
    the HTML for accurate calendar extraction (no OCR column-mixing).
    """
    year = str(args.year) if args.year else None
    if year:
        years = [year]
    else:
        pdfs = glob(os.path.join(BASE_DIR, "academic-calendar-*.pdf"))
        years = sorted(re.findall(r"(\d{4})", " ".join(pdfs)), reverse=True)
        if not years:
            print("No cached PDFs. Run: sk2gog calendar --update")
            return 1
        year = years[0]
        years = [year]

    for yr in years:
        pdf_path = os.path.join(BASE_DIR, f"academic-calendar-{yr}.pdf")
        if not os.path.exists(pdf_path):
            print(f"No PDF for {yr}. Run: sk2gog calendar --update --year {yr}")
            continue

        # Step 1: Convert PDF to HTML with pdftohtml
        html_path = os.path.join(BASE_DIR, f"academic-calendar-{yr}.html")
        try:
            r = subprocess.run(
                ["pdftohtml", "-c", "-noframes", pdf_path,
                 os.path.join(BASE_DIR, f"academic-calendar-{yr}")],
                capture_output=True, text=True, timeout=60
            )
            if r.returncode != 0:
                print(f"pdftohtml failed for {yr}: {r.stderr}")
                # Fallback to pdftotext
                data = _parse_pdf(yr)
                if data:
                    _write_semester_json(data)
                    print(f"Parsed (fallback): {SEMESTER_JSON}")
                continue
        except FileNotFoundError:
            print("pdftohtml not found — falling back to pdftotext")
            data = _parse_pdf(yr)
            if data:
                _write_semester_json(data)
                print(f"Parsed: {SEMESTER_JSON}")
            continue
        except subprocess.TimeoutExpired:
            print(f"pdftohtml timed out for {yr} — falling back to pdftotext")
            data = _parse_pdf(yr)
            if data:
                _write_semester_json(data)
                print(f"Parsed: {SEMESTER_JSON}")
            continue

        # Step 2: Parse the HTML
        data = _parse_calendar_html(html_path, yr)
        if data:
            _write_semester_json(data)
            print(f"Parsed: {SEMESTER_JSON}")
    return 0


# ─── Date / Week Commands ───────────────────────────────────────────────────

def cmd_date(args) -> int:
    """Show date info: week, day, workday/break, classes."""
    if args.date:
        try:
            target = datetime.date.fromisoformat(args.date)
        except ValueError:
            print(f"Invalid date: {args.date}")
            return 1
    else:
        target = datetime.date.today()

    info = _get_date_info(target)
    _print_date_info(info, target)
    return 0


def cmd_week(args) -> int:
    """Show week number and type (odd/even)."""
    if args.date:
        try:
            target = datetime.date.fromisoformat(args.date)
        except ValueError:
            print(f"Invalid date: {args.date}")
            return 1
    else:
        target = datetime.date.today()

    info = _get_date_info(target)
    if info.get("is_holiday"):
        print(f"Holiday: {info['holiday_name']}")
    elif info.get("week") is None:
        print("Outside semester.")
    else:
        print(f"Week {info['week']} ({info['parity']})")
    return 0


# ─── Core Logic ─────────────────────────────────────────────────────────────

def _get_date_info(target: datetime.date) -> dict:
    if not os.path.exists(SEMESTER_JSON):
        return {"error": "semester.json not found. Run: sk2gog calendar --update && sk2gog calendar --parse"}

    with open(SEMESTER_JSON, "r", encoding="utf-8") as f:
        config = json.load(f)

    spring = config.get("spring", {})
    holidays_map = {h["date"]: h for h in spring.get("holidays", [])}
    comp_map = {c["date"]: c for c in spring.get("compensatory", [])}

    week1_monday = datetime.date.fromisoformat(spring["week_1_monday"])
    semester_end = datetime.date.fromisoformat(spring["semester_end"])
    first_class = datetime.date.fromisoformat(spring["first_class_day"])
    odd_days = config.get("_notes", {}).get("odd_week_days", [0, 2, 4])
    even_days = config.get("_notes", {}).get("even_week_days", [1, 3])

    target_str = target.isoformat()
    day_names_cn = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    day_names_en = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

    result = {
        "week": None,
        "parity": None,
        "is_holiday": False,
        "holiday_name": None,
        "is_class_day": False,
        "is_compensatory": False,
        "comp_note": None,
        "is_workday": False,
        "is_break": False,
        "classes": [],
        "weekday_cn": day_names_cn[target.weekday()],
        "weekday_en": day_names_en[target.weekday()],
        "week_monday": None,
        "week_sunday": None,
    }

    # Pre/post semester
    if target < week1_monday:
        result["is_break"] = True
        return result
    if target > semester_end:
        result["is_break"] = True
        return result

    # Week number (computed before holiday check so we can show week for holidays)
    week_num = (target - week1_monday).days // 7 + 1
    parity = "odd" if week_num % 2 == 1 else "even"
    result["week"] = week_num
    result["parity"] = parity

    # Week bounds
    days_since_mon = target.weekday()
    week_monday = target - datetime.timedelta(days=days_since_mon)
    week_sunday = week_monday + datetime.timedelta(days=6)
    result["week_monday"] = week_monday
    result["week_sunday"] = week_sunday

    # Holiday — cancels ALL classes for that day. Mutual exclusive with compensatory.
    if target_str in holidays_map:
        result["is_holiday"] = True
        result["holiday_name"] = holidays_map[target_str]["name"]
        # No compensatory on the same day, no classes on a holiday
        return result

    # Compensatory — NOT a holiday. Shows makeup classes for a cancelled weekday.
    is_comp = target_str in comp_map
    if is_comp:
        result["is_compensatory"] = True
        result["comp_note"] = comp_map[target_str].get("note", "")

    # Schedule days — based on odd/even week parity
    scheduled = odd_days if week_num % 2 == 1 else even_days
    weekday_idx = target.weekday()
    has_class = weekday_idx in scheduled

    if has_class or is_comp:
        result["is_class_day"] = True
        result["is_workday"] = True

    # Load classes from courses.csv if available
    if result["is_class_day"] and os.path.exists(COURSES_CSV):
        comp_targets = _comp_target_days(target_str, comp_map) if is_comp else None
        result["classes"] = _get_classes_on_day(target, week_num, parity, comp_targets)

    return result


def _comp_target_days(target_str: str, comp_map: dict) -> list:
    """
    Parse compensatory note to get the weekday indices being made up.

    Note formats:
      "上单周周二的课" -> [1]       (Tuesday)
      "上双周周五的课" -> [4]       (Friday)
    OCR-tolerant: handles 期→上, 周周→周, etc.
    """
    entry = comp_map.get(target_str)
    if not entry:
        return []
    note = entry.get("note", "")
    # Normalize OCR noise
    note = re.sub(r"期+", "上", note)  # 期 → 上
    note = re.sub(r"周周", "周", note)  # 周周 → 周

    day_map = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6}
    targets = []
    for m in re.finditer(r"周([一二三四五日])", note):
        char = m.group(1)
        if char in day_map:
            targets.append(day_map[char])
    return targets


def _format_comp_note(note: str) -> str:
    """
    Convert "周日补周二/周五的课" -> "补周二、周五的课"
    """
    if not note or "补" not in note:
        return note
    # Extract the "补X/Y/Z的课" part
    import re
    m = re.search(r"补(.+?)的?课", note)
    if m:
        days_raw = m.group(1)
        # Translate Chinese numbers
        day_map = {"一": "周一", "二": "周二", "三": "周三",
                   "四": "周四", "五": "周五", "六": "周六", "日": "周日"}
        for k, v in day_map.items():
            days_raw = days_raw.replace(k, v)
        return f"补{days_raw}的课"
    return note


def _get_classes_on_day(
    date_obj: datetime.date, week_num: int, parity: str,
    comp_target_days: list = None
) -> list:
    """
    Read courses.csv and find classes on this date.
    If comp_target_days is set (compensatory day), return classes for those target days
    instead of the actual day of week.
    """
    import csv
    classes = []
    weekday_map = {"星期一": 0, "星期二": 1, "星期三": 2, "星期四": 3, "星期五": 4, "星期六": 5, "星期日": 6}
    day_name = next((k for k, v in weekday_map.items() if v == date_obj.weekday()), None)

    # If compensatory, look up classes for the days being made up
    target_days = comp_target_days if comp_target_days else [date_obj.weekday()]

    try:
        with open(COURSES_CSV, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                schedule = row.get("Schedule", "")
                for seg in schedule.split(";"):
                    seg = seg.strip()
                    if not seg:
                        continue
                    # Check day — match if class day is in target_days
                    day_match = re.search(r"星期(.)", seg)
                    if not day_match:
                        continue
                    class_day_abbr = day_match.group(1)  # e.g. "一", "二"
                    day_map_abbr = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6}
                    class_day_idx = day_map_abbr.get(class_day_abbr)
                    if class_day_idx is None or class_day_idx not in target_days:
                        continue
                    # Check week
                    week_match = re.match(r"(\d+)-(\d+)(周|单周|双周)", seg)
                    if not week_match:
                        continue
                    w_start, w_end = int(week_match.group(1)), int(week_match.group(2))
                    w_type = week_match.group(3)
                    in_range = w_start <= week_num <= w_end
                    if w_type == "单周" and week_num % 2 == 0:
                        in_range = False
                    if w_type == "双周" and week_num % 2 == 1:
                        in_range = False
                    if in_range:
                        location = ""
                        loc_match = re.search(r"第\d+-\d+节\s*(.+)$", seg)
                        if loc_match:
                            location = loc_match.group(1).strip()
                        classes.append({
                            "course": row.get("Course Name", "").strip(),
                            "teacher": row.get("Teacher", "").strip(),
                            "periods": f"第{week_match.group(1)}-{week_match.group(2)}节",
                            "location": location,
                        })
    except Exception:
        pass

    return classes


def _print_date_info(info: dict, target: datetime.date) -> None:
    if "error" in info:
        print(info["error"])
        return

    # Week
    if info["week"] is not None:
        week_str = f"Week {info['week']} ({info['parity']})"
    elif info["is_break"]:
        week_str = "outside semester"
    else:
        week_str = ""

    # Status
    parts = []
    if info["is_holiday"]:
        parts.append(f"Holiday: {info['holiday_name']}")
    elif info["is_compensatory"]:
        parts.append(f"补课 ({_format_comp_note(info['comp_note'])})")
    elif info["is_class_day"]:
        parts.append("Workday")
    elif info["is_break"]:
        parts.append("Break")
    status = ", ".join(parts) if parts else "No class"

    print(f"{target.isoformat()} ({info['weekday_en']})")
    if week_str:
        print(f"  {week_str}")
    print(f"  {status}")

    if info["classes"]:
        print("  Classes:")
        for cls in info["classes"]:
            loc = f" @ {cls['location']}" if cls["location"] else ""
            print(f"    - {cls['course']} ({cls['teacher']}) {cls['periods']}{loc}")
    elif info["is_class_day"]:
        print("  Classes: (courses.csv not found)")


# ─── HTTP Helpers ────────────────────────────────────────────────────────────

def _fetch_page(url: str) -> str:
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    return resp.text


def _download_pdf(url: str, dest: str) -> bool:
    try:
        resp = requests.get(url, timeout=30, stream=True)
        resp.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(8192):
                f.write(chunk)
        return True
    except Exception:
        return False


def _find_links(html: str) -> list:
    base = "https://www.sustech.edu.cn"
    pattern = re.compile(r'href="(/uploads/files/[^"]+\.pdf)"[^>]*>([^<]+)</a>')
    results = []
    seen = set()
    for m in pattern.finditer(html):
        href, text = m.group(1), m.group(2).strip()
        url = base + href if href.startswith("/") else href
        if url in seen:
            continue
        seen.add(url)
        year_m = re.search(r"\uff08(\d{4})\uff09", text)
        year = year_m.group(1) if year_m else None
        if year:
            results.append({"year": year, "text": text, "url": url})
    return results


# ─── Metadata ───────────────────────────────────────────────────────────────

def _check_updates(calendars: list) -> list:
    import hashlib
    if not os.path.exists(METADATA_FILE):
        return [(c, "new") for c in calendars]
    with open(METADATA_FILE, "r", encoding="utf-8") as f:
        meta = json.load(f)
    updates = []
    for c in calendars:
        url_hash = hashlib.md5(c["url"].encode()).hexdigest()
        if c["year"] not in meta:
            updates.append((c, "new"))
        elif meta[c["year"]].get("url_hash") != url_hash:
            updates.append((c, "updated"))
    return updates


def _save_metadata(calendars: list) -> None:
    import hashlib
    meta = {}
    for c in calendars:
        meta[c["year"]] = {
            "url": c["url"],
            "url_hash": hashlib.md5(c["url"].encode()).hexdigest(),
            "text": c["text"],
        }
    with open(METADATA_FILE, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)


# ─── PDF Parsing ─────────────────────────────────────────────────────────────

def _parse_pdf(year: str) -> Optional[dict]:
    pdf_path = os.path.join(BASE_DIR, f"academic-calendar-{year}.pdf")
    if not os.path.exists(pdf_path):
        return None

    text = None
    try:
        import subprocess
        # Use -raw (physical lines) to avoid column-mixing artifacts
        r = subprocess.run(["pdftotext", "-raw", pdf_path, "-"],
                           capture_output=True, text=True, timeout=30)
        if r.returncode == 0 and r.stdout.strip():
            text = r.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    if not text:
        try:
            from pdfminer.high_level import extract_text
            text = extract_text(pdf_path)
        except ImportError:
            print("Need pdftotext (poppler) or pdfminer.six to parse PDF.")
            return None

    return _parse_calendar_text(text, year)


def _parse_calendar_text(text: str, year: str) -> dict:
    """
    Line-by-line parser using pdftotext -raw output.
    Each line is a physical PDF line, so date→name associations are trustworthy.

    Strategy:
    - Process each line independently
    - For each line, check if it contains a date AND a known holiday name
      (holidays: 春节, 清明节, 劳动节, 端午)
    - For compensatory days, match the specific "上单周/上双周" pattern on each line
    - For semester dates, look for lines with "本科生上课" and "本科生夏季"
    """
    import datetime

    spring = {
        "week_1_monday": None,
        "first_class_day": None,
        "semester_end": None,
        "teaching_weeks": 17,
        "holidays": [],
        "compensatory": [],
        "breaks": [],
    }

    lines = text.split("\n")
    y = int(year)

    # Known anchors
    holiday_names = ["春节", "清明节", "劳动节", "端午节"]

    # Regex: date pattern on a single line
    date_pat = re.compile(r"(\d{1,2})月(\d{1,2})日")
    # Compensatory: "上单周周X的课" or "上双周周X的课" (OCR-tolerant)
    # Pattern: DATE + stuff + [上期]+[单双]周 + 周X + [的的]?课
    comp_pat = re.compile(
        r"(\d{1,2})月(\d{1,2})日.*?"
        r"[上期]{1,2}([单双])周周([一二三四五六日]).*?课",
        re.DOTALL
    )

    seen_holidays = set()
    seen_comp = set()

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # ── Holiday detection ────────────────────────────────────────────────
        # If a line contains both a date and a known holiday name, associate them
        date_m = date_pat.search(line)
        if date_m:
            month, day = int(date_m.group(1)), int(date_m.group(2))
            ds = f"{year}-{month:02d}-{day:02d}"

            for hname in holiday_names:
                if hname in line:
                    # Skip if already recorded (avoid duplicates from multiple columns)
                    if ds not in seen_holidays:
                        seen_holidays.add(ds)
                        spring["holidays"].append({"date": ds, "name": f"{hname}"})

                        # Single-day public holidays: only add surrounding "假期" if the
                        # PDF line explicitly contains "假期" text (e.g. "清明节假期")
                        # Otherwise just add the holiday itself.
                        if hname in ["清明节", "端午节"]:
                            # Check if "假期" appears near the holiday in the same PDF line
                            line_lower = line.lower()
                            if "假期" in line:
                                base = datetime.date(y, month, day)
                                for off in (1, 2):
                                    alt = (base + datetime.timedelta(days=off)).isoformat()
                                    if alt not in seen_holidays:
                                        seen_holidays.add(alt)
                                        spring["holidays"].append({"date": alt, "name": f"{hname}假期"})
                    break  # don't associate the same date with multiple holiday names

        # ── Compensatory day detection ────────────────────────────────────────
        # Match: "5月9日...上单周周二的课" on the same physical line
        comp_m = comp_pat.search(line)
        if comp_m:
            month, day = int(comp_m.group(1)), int(comp_m.group(2))
            week_type = comp_m.group(3)   # 单 or 双
            weekday_char = comp_m.group(4)  # 一二三四五...
            ds = f"{year}-{month:02d}-{day:02d}"

            if ds not in seen_comp:
                seen_comp.add(ds)
                note = f"上{week_type}周周{weekday_char}的课"
                spring["compensatory"].append({"date": ds, "note": note})

        # ── First class day: "本科生上课" in the line ──────────────────────────
        if "本科生上课" in line:
            date_m = date_pat.search(line)
            if date_m and not spring.get("first_class_day"):
                month, day = int(date_m.group(1)), int(date_m.group(2))
                if 2 <= month <= 4:
                    spring["first_class_day"] = f"{year}-{month:02d}-{day:02d}"

        # ── Semester end: "本科生夏季" followed by a date ─────────────────────
        if "本科生夏季" in line or "本科生期末" in line:
            date_m = date_pat.search(line)
            if date_m and not spring.get("semester_end"):
                month, day = int(date_m.group(1)), int(date_m.group(2))
                if 6 <= month <= 7:
                    spring["semester_end"] = f"{year}-{month:02d}-{day:02d}"

    # ── Derive week_1_monday ─────────────────────────────────────────────────────
    if spring.get("first_class_day"):
        first = datetime.date.fromisoformat(spring["first_class_day"])
        week1 = first - datetime.timedelta(days=first.weekday())
        spring["week_1_monday"] = week1.isoformat()

    print(f"Parsed {year}: {spring.get('first_class_day')} -> {spring.get('semester_end')}")
    return {"year": year, "spring": spring}


def _write_semester_json(data: dict) -> None:
    """
    Deep-merge parsed data into existing semester.json.
    - Top-level keys (meta, _notes) are preserved from existing if not in data
    - spring fields: only overwrite if data has a non-None value
    - holidays/compensatory: APPEND new entries to existing lists (no duplicates by date)
    """
    existing = {}
    if os.path.exists(SEMESTER_JSON):
        with open(SEMESTER_JSON, "r", encoding="utf-8") as f:
            existing = json.load(f)

    sp_existing = existing.get("spring", {})
    sp_new = data.get("spring", {})

    # Deep merge spring — only update non-date fields from parsed data
    # semester_end is NOT taken from PDF (unreliable); preserve existing
    merged_spring = dict(sp_existing)
    for key in ["week_1_monday", "first_class_day",
                "teaching_weeks", "breaks"]:
        if sp_new.get(key):
            merged_spring[key] = sp_new[key]

    # Merge holidays: add new dates not already in existing list
    existing_hol_dates = {h["date"] for h in sp_existing.get("holidays", [])}
    for h in sp_new.get("holidays", []):
        if h["date"] not in existing_hol_dates:
            merged_spring.setdefault("holidays", list(sp_existing.get("holidays", []))).append(h)

    # Merge compensatory: add new dates within spring semester (Feb–Jul)
    # Filter out fall compensatory dates that appear in the same PDF
    existing_comp_dates = {c["date"] for c in sp_existing.get("compensatory", [])}
    for c in sp_new.get("compensatory", []):
        ds = c["date"]
        if ds in existing_comp_dates:
            continue
        # Only include dates within spring semester (Feb 1 – Jul 31)
        d = datetime.date.fromisoformat(ds)
        spring_start = datetime.date(int(data["year"]), 2, 1)
        spring_end = datetime.date(int(data["year"]), 7, 31)
        if spring_start <= d <= spring_end:
            merged_spring.setdefault("compensatory", list(sp_existing.get("compensatory", []))).append(c)

    # Put it together
    merged = {
        "meta": data.get("meta", existing.get("meta", {})),
        "spring": merged_spring,
        "_notes": existing.get("_notes", {}),
    }
    with open(SEMESTER_JSON, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)


# ─── Main ───────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(prog="sk2gog", description="SUSTech Schedule CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    # sk2gog calendar
    cal = sub.add_parser("calendar", help="Fetch/check academic calendar")
    cal.add_argument("--check", action="store_true", help="Check for updates only")
    cal.add_argument("--update", action="store_true", help="Force re-download")
    cal.add_argument("--year", type=int, help="Specific year")
    cal.add_argument("--all", action="store_true", help="Process all calendars on page")

    # sk2gog parse
    par = sub.add_parser("parse", help="Parse cached PDF(s) into semester.json")
    par.add_argument("--year", type=int, help="Specific year")

    # sk2gog date
    date_cmd = sub.add_parser("date", help="Show date info (week, day, classes)")
    date_cmd.add_argument("date", nargs="?", help="Date in YYYY-MM-DD (default: today)")

    # sk2gog week
    week_cmd = sub.add_parser("week", help="Show week number and parity")
    week_cmd.add_argument("date", nargs="?", help="Date in YYYY-MM-DD (default: today)")

    # sk2gog help
    help_cmd = sub.add_parser("help", help="Show this help")

    args = parser.parse_args()

    if args.command == "calendar":
        return cmd_calendar(args)
    elif args.command == "parse":
        return cmd_parse(args)
    elif args.command == "date":
        return cmd_date(args)
    elif args.command == "week":
        return cmd_week(args)
    elif args.command == "help":
        parser.print_help()
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
