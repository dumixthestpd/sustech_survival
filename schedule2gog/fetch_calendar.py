#!/usr/bin/env python3
"""
Fetch SUSTech public academic calendar PDF and parse it into semester.json.

No AppleScript — works cross-platform (macOS/Linux/Windows).

Usage:
    python3 fetch_calendar.py              # Check for updates
    python3 fetch_calendar.py --force      # Force download
    python3 fetch_calendar.py --parse      # Parse local PDF → semester.json
    python3 fetch_calendar.py --year 2026  # Specific year
    python3 fetch_calendar.py --force --parse --year 2026  # Download + parse
"""

import argparse
import hashlib
import json
import os
import re
import sys
from glob import glob
from typing import Optional

import requests

# ─── Config ───────────────────────────────────────────────────────────────────

ACADEMIC_CALENDAR_URL = "https://www.sustech.edu.cn/zh/academic-calendar.html"
CALENDAR_DIR = os.path.expanduser("~/.openclaw/workspace/sustech")
METADATA_FILE = os.path.join(CALENDAR_DIR, "calendar_metadata.json")
SEMESTER_JSON_FILE = os.path.join(CALENDAR_DIR, "semester.json")

# ─── HTTP ─────────────────────────────────────────────────────────────────────

def fetch_page(url: str) -> str:
    """Fetch a URL and return HTML content."""
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    # SUSTech page returns UTF-8 but requests mis-detects encoding
    resp.encoding = "utf-8"
    return resp.text


def download_file(url: str, dest_path: str) -> bool:
    """Download a file to dest_path. Returns True on success."""
    resp = requests.get(url, timeout=30, stream=True)
    resp.raise_for_status()
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    with open(dest_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    return True


# ─── Link Discovery ────────────────────────────────────────────────────────────

def find_calendar_links(html: str) -> list:
    """
    Parse the academic calendar page HTML and extract PDF links.

    Returns:
        [{"year": "2026", "text": "...", "url": "https://..."}, ...]
    """
    base = "https://www.sustech.edu.cn"
    # Match PDF links with Chinese year in anchor text
    # e.g. href="/uploads/files/...pdf">南方科技大学校历（2026）</a>
    pattern = re.compile(r'href="(/uploads/files/[^"]+\.pdf)"[^>]*>([^<]+)</a>')
    calendars = []
    seen_urls = set()
    for m in pattern.finditer(html):
        href, text = m.group(1), m.group(2).strip()
        url = base + href if href.startswith("/") else href
        if url in seen_urls:
            continue
        seen_urls.add(url)
        # Extract year from Chinese parentheses: （2026）
        year_m = re.search(r"\uff08(\d{4})\uff09", text)
        year = year_m.group(1) if year_m else None
        if year:
            calendars.append({"year": year, "text": text, "url": url})
    return calendars


# ─── Metadata ─────────────────────────────────────────────────────────────────

def load_metadata() -> dict:
    if os.path.exists(METADATA_FILE):
        with open(METADATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_metadata(calendars: list) -> None:
    meta = {}
    for cal in calendars:
        meta[cal["year"]] = {
            "url": cal["url"],
            "url_hash": hashlib.md5(cal["url"].encode()).hexdigest(),
            "text": cal["text"],
        }
    with open(METADATA_FILE, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)


def check_updates(calendars: list) -> list:
    meta = load_metadata()
    updates = []
    for cal in calendars:
        url_hash = hashlib.md5(cal["url"].encode()).hexdigest()
        if cal["year"] not in meta:
            updates.append((cal, "new"))
        elif meta[cal["year"]]["url_hash"] != url_hash:
            updates.append((cal, "updated"))
    return updates


# ─── PDF Download ──────────────────────────────────────────────────────────────

def ensure_dir():
    os.makedirs(CALENDAR_DIR, exist_ok=True)


def download_calendar(cal: dict, force: bool = False) -> Optional[str]:
    """Download a calendar PDF. Returns the local path, or None on failure."""
    ensure_dir()
    filename = f"academic-calendar-{cal['year']}.pdf"
    dest = os.path.join(CALENDAR_DIR, filename)

    if os.path.exists(dest) and not force:
        print(f"  Already exists: {dest}")
        return dest

    print(f"  Downloading {cal['year']}: {cal['url']}")
    print(f"  -> {dest}")
    try:
        download_file(cal["url"], dest)
        print(f"  Saved: {dest}")
        return dest
    except Exception as e:
        print(f"  Failed: {e}")
        return None


# ─── PDF Parsing ──────────────────────────────────────────────────────────────

def parse_pdf_text(year: str) -> Optional[dict]:
    """Extract semester dates from the downloaded PDF. Returns None on failure."""
    pdf_path = os.path.join(CALENDAR_DIR, f"academic-calendar-{year}.pdf")
    if not os.path.exists(pdf_path):
        print(f"PDF not found: {pdf_path}")
        print("Run: python3 fetch_calendar.py --force --year {year}")
        return None

    # Try pdftotext first (poppler)
    text = None
    try:
        import subprocess
        result = subprocess.run(
            ["pdftotext", "-layout", pdf_path, "-"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            text = result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Fallback: pdfminer.six
    if not text:
        try:
            from pdfminer.high_level import extract_text
            text = extract_text(pdf_path)
        except ImportError:
            print("Need pdftotext (poppler) or pdfminer.six to parse PDF")
            print("  poppler: brew install poppler")
            print("  pdfminer: pip install pdfminer.six")
            return None

    return parse_calendar_text(text, year)


def parse_calendar_text(text: str, year: str) -> dict:
    """
    Parse extracted PDF text to extract semester structure.

    Detects:
        - week_1_monday  (first Monday of semester)
        - first_class_day (开学 — first scheduled class day)
        - semester_end
        - holidays (Chinese New Year, Qingming, May Day, Dragon Boat)
        - compensatory days (调休)
    """
    spring = {
        "week_1_monday": None,
        "first_class_day": None,
        "semester_end": None,
        "teaching_weeks": 17,
        "holidays": [],
        "compensatory": [],
        "breaks": [],
    }

    import datetime

    # ── First class day (开学 / 上课) ─────────────────────────────────────
    # Pattern: "2月25日上课" or "2月25日开始上课"
    for m in re.finditer(r"(\d{1,2})月(\d{1,2})日.*?[上课开始]", text):
        month, day = int(m.group(1)), int(m.group(2))
        if 2 <= month <= 4:  # Spring semester starts Feb-Apr
            spring["first_class_day"] = f"{year}-{month:02d}-{day:02d}"
            break

    # ── Semester end — "暑假", "学期结束", or last July date ──────────────
    for m in re.finditer(r"[暑]假.*?(\d{1,2})月(\d{1,2})日", text):
        month, day = int(m.group(1)), int(m.group(2))
        if month >= 6:
            spring["semester_end"] = f"{year}-{month:02d}-{day:02d}"
            break

    if not spring.get("semester_end"):
        for m in re.finditer(r"(\d{1,2})月(\d{1,2})日", text):
            month, day = int(m.group(1)), int(m.group(2))
            if 6 <= month <= 7:
                spring["semester_end"] = f"{year}-{month:02d}-{day:02d}"

    # ── Derive week_1_monday from first_class_day ─────────────────────────
    if spring.get("first_class_day"):
        first = datetime.date.fromisoformat(spring["first_class_day"])
        days_since_monday = first.weekday()
        week1_monday = first - datetime.timedelta(days=days_since_monday)
        spring["week_1_monday"] = week1_monday.isoformat()

    # ── Holidays ───────────────────────────────────────────────────────────
    seen_dates = set()
    holiday_rules = [
        ("春节", r"春节.*?(\d{1,2})月(\d{1,2})日"),
        ("清明节", r"清明.*?(\d{1,2})月(\d{1,2})日"),
        ("劳动节", r"劳动.*?(\d{1,2})月(\d{1,2})日"),
        ("端午节", r"端午.*?(\d{1,2})月(\d{1,2})日"),
    ]
    for name, pattern in holiday_rules:
        for m in re.finditer(pattern, text):
            month, day = int(m.group(1)), int(m.group(2))
            date_str = f"{year}-{month:02d}-{day:02d}"
            if date_str not in seen_dates and 1 <= month <= 8:
                seen_dates.add(date_str)
                spring["holidays"].append({"date": date_str, "name": name, "cn": name})

    # ── Compensatory days (调休) ───────────────────────────────────────────
    for m in re.finditer(r"(\d{1,2})月(\d{1,2})日.*?调休", text):
        month, day = int(m.group(1)), int(m.group(2))
        date_str = f"{year}-{month:02d}-{day:02d}"
        spring["compensatory"].append({"date": date_str, "note": "调休"})

    # ── Print summary ──────────────────────────────────────────────────────
    print(f"\n=== Parsed Spring {year} ===")
    for key in ["week_1_monday", "first_class_day", "semester_end"]:
        val = spring.get(key, "NOT FOUND")
        print(f"  {key}: {val}")
    print(f"  holidays ({len(spring['holidays'])}):")
    for h in spring["holidays"]:
        print(f"    {h['date']}: {h['name']}")
    print(f"  compensatory ({len(spring['compensatory'])}):")
    for c in spring["compensatory"]:
        print(f"    {c['date']}: {c['note']}")

    return {"year": year, "spring": spring}


def write_semester_json(data: dict) -> None:
    """Merge parsed data into semester.json (preserves meta and _notes)."""
    existing = {}
    if os.path.exists(SEMESTER_JSON_FILE):
        with open(SEMESTER_JSON_FILE, "r", encoding="utf-8") as f:
            existing = json.load(f)

    merged = {
        "meta": existing.get("meta", {}),
        **data,
        "_notes": existing.get("_notes", {}),
    }

    with open(SEMESTER_JSON_FILE, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)

    print(f"\nWritten: {SEMESTER_JSON_FILE}")


# ─── CLI ─────────────────────────────────────────────────────────────────────

def guess_year(calendars: list) -> Optional[str]:
    """
    Guess the most recent year to process.
    Prioritizes: local PDFs first, then the most recent year found on the page.
    """
    # Prefer locally downloaded PDFs
    files = glob(os.path.join(CALENDAR_DIR, "academic-calendar-*.pdf"))
    if files:
        years = sorted(re.findall(r"(\d{4})", " ".join(files)), reverse=True)
        if years:
            return years[0]
    # Fall back to most recent year on the page
    if calendars:
        return max(c["year"] for c in calendars)
    return None


def fetch_all_calendars(html: str) -> list:
    """Fetch and return all calendar entries from the page."""
    calendars = find_calendar_links(html)
    if calendars:
        save_metadata(calendars)
    return calendars


def main():
    parser = argparse.ArgumentParser(
        description="Fetch and parse SUSTech public academic calendar."
    )
    parser.add_argument("--year", type=int, help="Specific year (e.g. 2026). Default: most recent year on page.")
    parser.add_argument("--force", action="store_true", help="Force re-download even if already cached")
    parser.add_argument("--parse", action="store_true", help="Parse local PDF and write semester.json")
    parser.add_argument("--check", action="store_true", help="Check for updates only")
    parser.add_argument("--all", action="store_true", help="Process all calendars found on the page")
    parser.add_argument("--offline", action="store_true", help="Skip update check — use local cache only")
    args = parser.parse_args()

    print("=== SUSTech Academic Calendar Fetcher ===\n")
    ensure_dir()

    # ── Fetch the page (used by all modes) ─────────────────────────────────
    print("Fetching academic calendar page...")
    try:
        html = fetch_page(ACADEMIC_CALENDAR_URL)
    except Exception as e:
        print(f"Failed to fetch page: {e}")
        sys.exit(1)

    calendars = find_calendar_links(html)
    if not calendars:
        print("No calendar links found on the page.")
        sys.exit(1)

    print(f"Found {len(calendars)} calendar(s) on page:")
    for cal in calendars:
        print(f"  {cal['year']}: {cal['text']}")
    print()

    # Determine which calendars to process
    page_years = {c["year"] for c in calendars}

    if args.all:
        target_calendars = calendars
    elif args.year:
        year_str = str(args.year)
        target_calendars = [c for c in calendars if c["year"] == year_str]
        if not target_calendars:
            print(f"Year {args.year} not found on this page.")
            print(f"  Available: {', '.join(sorted(page_years))}")
            sys.exit(1)
    else:
        # Default: most recent year on the page
        default_year = max(page_years)
        target_calendars = [c for c in calendars if c["year"] == default_year]
        print(f"No --year specified. Defaulting to {default_year} (most recent on page).")
        print("  Use --all to process all calendars, or --year YYYY to select one.")
        print()

    # ── Parse mode ─────────────────────────────────────────────────────────
    if args.parse:
        for cal in target_calendars:
            year = cal["year"]
            pdf_path = os.path.join(CALENDAR_DIR, f"academic-calendar-{year}.pdf")

            if not os.path.exists(pdf_path):
                if args.offline:
                    print(f"[{year}] No local PDF. Run without --offline to download.")
                    continue
                path = download_calendar(cal, force=True)
                if not path:
                    continue
            else:
                print(f"Using: {pdf_path}")

            data = parse_pdf_text(year)
            if data:
                write_semester_json(data)
            print()
        return

    # ── Check mode ─────────────────────────────────────────────────────────
    if args.check:
        if args.offline:
            print("--check with --offline: nothing to check.")
        else:
            updates = check_updates(calendars)
            if updates:
                print("Updates available:")
                for cal, reason in updates:
                    print(f"  [{reason}] {cal['year']}: {cal['text']}")
            else:
                print("All calendars up to date.")
        return

    # ── Fetch / parse mode ────────────────────────────────────────────────
    # Default: always check for updates unless --offline is set
    if not args.offline:
        updates = check_updates(target_calendars)
    else:
        updates = []

    for cal in target_calendars:
        year = cal["year"]
        pdf_path = os.path.join(CALENDAR_DIR, f"academic-calendar-{year}.pdf")
        is_update = any(u[0]["year"] == year for u in updates)

        if args.force or is_update:
            path = download_calendar(cal, force=True)
            if path:
                print(f"  Done: {path}")
        elif not args.offline and not os.path.exists(pdf_path):
            # No local PDF — download even without --force
            path = download_calendar(cal)
            if path:
                print(f"  Done: {path}")
        elif os.path.exists(pdf_path):
            print(f"  {year}: Already cached ({pdf_path})")
        else:
            print(f"  {year}: No local PDF. Run without --offline to download.")

    # Save metadata after fetch (for next-run update detection)
    if not args.offline:
        save_metadata(calendars)


if __name__ == "__main__":
    main()
