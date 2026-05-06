#!/usr/bin/env python3
"""
SUSTech academic calendar parser using pdftohtml positional data.

Uses pdftohtml -c to get exact (top, left, text) for every text element.
Calendar is a table: date numbers in left columns (Mon-Sun), event notes
in right column (left > 500). Both share the same Y band = same calendar week.

Strategy:
1. Extract all positioned elements
2. Find "第N周" anchors → each is a week row
3. Group elements by week row using Y-band clustering
4. For each row, extract date+event pairs from note cells
5. Handle multi-event cells by splitting on date boundaries
"""

import re
import os
import sys
import json
import datetime
import subprocess
from typing import Optional


HTML_PATH = "/tmp/sustech_cal.html"


def extract_positions(html_path: str) -> list:
    """Extract all positioned text elements from pdftohtml HTML output."""
    with open(html_path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    elements = []
    pat = re.compile(
        r'<p[^>]*style="position:absolute;top:(\d+)px;left:(\d+)px[^"]*"[^>]*>(.*?)</p>',
        re.DOTALL
    )
    for m in pat.finditer(content):
        top = int(m.group(1))
        left = int(m.group(2))
        raw = m.group(3)
        text = re.sub(r'<[^>]+>', '', raw).replace('&#160;', ' ').replace('\xa0', ' ').strip()
        text = re.sub(r'\s+', ' ', text).strip()
        if text:
            elements.append({"text": text, "top": top, "left": left})
    return elements


def split_note_chunks(note: str) -> list:
    """
    Split a multi-event note cell into (date_str, event_text) pairs.

    E.g. "2月24日��在校研究生返校2月28日��上单周周一的课"
    -> [("2月24日", "在校研究生返校"), ("2月28日", "上单周周一的课")]

    A note cell can contain multiple date+event pairs concatenated.
    We split on each "XX月XX日" boundary.
    """
    date_pat = re.compile(r'(\d{1,2})月(\d{1,2})日')
    chunks = []
    prev_end = 0
    prev_date_str = ""

    for m in date_pat.finditer(note):
        month, day = int(m.group(1)), int(m.group(2))
        date_str = f"{month}月{day}日"

        if prev_date_str:
            # Text between previous date and this one = event for prev date
            event_text = note[prev_end:m.start()].strip()
            chunks.append((prev_date_str, event_text))

        prev_date_str = date_str
        prev_end = m.end()

    # Last date's event text (everything after it)
    if prev_date_str:
        remaining = note[prev_end:].strip()
        chunks.append((prev_date_str, remaining))

    return chunks


def build_week_rows(elements: list) -> list:
    """
    Group elements into week rows using "第N周" anchors.
    """
    week_pat = re.compile(r'第(\d+)周')
    week_anchors = [
        {"top": el["top"], "week_num": int(week_pat.search(el["text"]).group(1))}
        for el in elements
        if week_pat.search(el["text"])
    ]

    rows = []
    for i, anchor in enumerate(week_anchors):
        row_top = anchor["top"]
        row_bottom = (
            week_anchors[i + 1]["top"]
            if i + 1 < len(week_anchors)
            else anchor["top"] + 80
        )

        row_elements = [
            el for el in elements
            if row_top - 10 <= el["top"] <= row_bottom + 10
        ]

        date_cells = {}  # left position -> text
        notes = []

        for el in row_elements:
            if 240 <= el["left"] <= 500:
                date_cells[el["left"]] = el["text"]
            elif el["left"] > 500:
                notes.append(el["text"])

        rows.append({
            "week_num": anchor["week_num"],
            "top": anchor["top"],
            "date_cells": date_cells,
            "notes": notes,
        })

    return rows


def parse_calendar_html(html_path: str, year: str) -> dict:
    """
    Parse the HTML calendar. Returns {year, spring: {...}}
    """
    elements = extract_positions(html_path)
    rows = build_week_rows(elements)

    print(f"Found {len(rows)} week rows", file=sys.stderr)

    holidays = {}    # date_str -> canonical_name
    comps = {}        # date_str -> note

    # Holiday name normalization
    holiday_aliases = {
        "春节": "春节", "清明": "清明节", "清明节": "清明节",
        "劳动节": "劳动节", "端午": "端午节", "端午节": "端午节",
        "Apr 5": "清明节", "May 1": "劳动节", "June 19": "端午节",
        "Feb 17": "春节",
    }

    comp_pat = re.compile(r'上([单双])周周([一二三四五六日])的?课')

    for row in rows:
        for note in row["notes"]:
            if len(note) < 3:
                continue

            chunks = split_note_chunks(note)

            for date_str, event_text in chunks:
                # Parse the date
                dm = re.search(r'(\d{1,2})月(\d{1,2})日', date_str)
                if not dm:
                    continue
                month, day = int(dm.group(1)), int(dm.group(2))
                ds = f"{year}-{month:02d}-{day:02d}"

                # Check: compensatory (上单周/上双周 + 周X)
                if comp_pat.search(event_text):
                    cm = comp_pat.search(event_text)
                    week_type = cm.group(1)
                    weekday_char = cm.group(2)
                    comps[ds] = f"上{week_type}周周{weekday_char}的课"
                    continue

                # Check: holiday by keyword
                for alias, canonical in holiday_aliases.items():
                    if alias in event_text or alias in date_str:
                        holidays[ds] = canonical
                        break

    spring = {
        "week_1_monday": None,
        "first_class_day": None,
        "semester_end": None,
        "teaching_weeks": 17,
        "holidays": [{"date": ds, "name": name} for ds, name in sorted(holidays.items())],
        "compensatory": [{"date": ds, "note": note} for ds, note in sorted(comps.items())],
        "breaks": [],
    }

    return {"year": year, "spring": spring}


if __name__ == "__main__":
    html_path = sys.argv[1] if len(sys.argv) > 1 else HTML_PATH
    year = sys.argv[2] if len(sys.argv) > 2 else "2026"
    result = parse_calendar_html(html_path, year)
    print(json.dumps(result, indent=2, ensure_ascii=False))
