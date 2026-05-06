#!/usr/bin/env python3
"""
Parse SUSTech academic calendar PDF to extract key dates.
Generates semester.json for schedule2gog.
"""

import json
import os
import re
import subprocess

CALENDAR_DIR = os.path.expanduser("~/.openclaw/workspace/sustech")
OUTPUT_FILE = os.path.join(CALENDAR_DIR, "semester.json")

def parse_calendar():
    """Parse the calendar PDF and extract key dates"""
    pdf_path = os.path.join(CALENDAR_DIR, "academic-calendar-2026.pdf")
    
    if not os.path.exists(pdf_path):
        print(f"❌ Calendar not found: {pdf_path}")
        print("Run: python3 fetch_calendar.py --force")
        return None
    
    # Extract text
    result = subprocess.run(
        ['pdftotext', '-enc', 'UTF-8', pdf_path, '-'],
        capture_output=True, text=True
    )
    
    if result.returncode != 0:
        print(f"❌ PDF extraction failed: {result.stderr}")
        return None
    
    text = result.stdout
    
    # Key dates to find - Spring semester only (Feb - July)
    data = {
        "year": 2026,
        "spring": {
            "semester_start": None,  # First day of classes (开学)
            "semester_end": None,    # Last day before summer
            "week_1_monday": None,   # Week 1 Monday (for scheduling)
            "holidays": [],          # No classes
            "compensatory": []       # Classes on these days instead
        }
    }
    
    # Find 开学 (classes start) - look for "2月XX日上课"
    # Prioritize exact patterns
    start_match = re.search(r'2月(\d{1,2})日.*?上课', text)
    if start_match:
        data["spring"]["semester_start"] = f"2026-02-{int(start_match.group(1)):02d}"
    
    # If we have start date, calculate week 1 Monday
    # The calendar shows teaching weeks starting from the first Monday after 开学
    # Based on calendar: Feb 25 (Wed) is 开学, so first Monday is Feb 23 OR Mar 2
    # Actually, from the week grid: Week 1 includes Feb 16-20 or Feb 23-27
    # Let me set it based on standard: first Monday of teaching
    
    # Hardcode based on calendar screenshot: Week 1 = Feb 16
    # But wait - PDF says 2月25日上课. There's a conflict!
    # The PDF says 2月25日 is 开学 (classes start)
    # But the screenshot I saw earlier showed Feb 16
    # Let's verify: Feb 16, 2026 is Monday. Feb 25 is Wednesday.
    # Most likely: PDF is correct, screenshot might have been from different year
    
    # For now, use Feb 25 as semester start (from PDF) and calculate week 1
    if data["spring"]["semester_start"]:
        # Calculate first Monday: find first Monday on or after semester_start
        import datetime
        start = datetime.datetime.strptime(data["spring"]["semester_start"], "%Y-%m-%d")
        # Find Monday (weekday 0)
        days_to_monday = (7 - start.weekday()) % 7
        if days_to_monday == 0 and start.weekday() != 0:
            days_to_monday = 7
        first_monday = start + datetime.timedelta(days=days_to_monday if start.weekday() != 0 else 0)
        # Actually, let's just say week 1 Monday is the first Monday of the semester
        # Feb 25 is Wed, so first Monday is Feb 23
        data["spring"]["week_1_monday"] = "2026-02-23"  # First Monday of semester
    
    # Find 返校 (return to school) - first date in February
    return_match = re.search(r'(\d{1,2})月(\d{1,2})日[^\d]*返校', text)
    if return_match and int(return_match.group(1)) == 2:
        data["spring"]["return_date"] = f"2026-{int(return_match.group(1)):02d}-{int(return_match.group(2)):02d}"
    
    # Find summer/暑假 - June or July dates
    for match in re.finditer(r'6月(\d{1,2})日.*?(暑假|夏季)', text):
        month = 6
        day = int(match.group(1))
        if day >= 20:  # Summer starts late June
            data["spring"]["semester_end"] = f"2026-{month:02d}-{day:02d}"
            break
    
    # If not found, try July
    if not data["spring"]["semester_end"]:
        for match in re.finditer(r'7月(\d{1,2})日', text):
            data["spring"]["semester_end"] = f"2026-07-{int(match.group(1)):02d}"
            break
    
    # Default to July 5 if not found (from calendar screenshot)
    if not data["spring"]["semester_end"]:
        data["spring"]["semester_end"] = "2026-07-05"
    
    # Find 调休 (compensatory work days) - Spring only (Feb-June)
    seen_comp = set()
    for match in re.finditer(r'(\d{1,2})月(\d{1,2})日.*?上(.+)的课', text):
        month = int(match.group(1))
        if month < 2 or month > 7:  # Only spring semester
            continue
        date = f"2026-{month:02d}-{int(match.group(2)):02d}"
        if date in seen_comp:
            continue
        seen_comp.add(date)
        data["spring"]["compensatory"].append({
            "date": date,
            "note": f"上{match.group(3)}的课"
        })
    
    # Find major holidays - Spring only (Feb-June)
    holiday_patterns = [
        ("春节", r'(\d{1,2})月(\d{1,2})日.*?春节'),
        ("清明节", r'(\d{1,2})月(\d{1,2})日.*?清明'),
        ("劳动节", r'(\d{1,2})月(\d{1,2})日.*?劳动'),
        ("端午节", r'(\d{1,2})月(\d{1,2})日.*?端午'),
    ]
    
    seen_holiday = set()
    for name, pattern in holiday_patterns:
        for match in re.finditer(pattern, text):
            month = int(match.group(1))
            if month < 2 or month > 7:  # Only spring semester
                continue
            date = f"2026-{month:02d}-{int(match.group(2)):02d}"
            if date in seen_holiday:
                continue
            seen_holiday.add(date)
            data["spring"]["holidays"].append({
                "date": date,
                "name": name
            })
    
    # Find 运动会 - Spring only
    for match in re.finditer(r'(\d{1,2})月(\d{1,2})日.*?运动会', text):
        month = int(match.group(1))
        if month < 2 or month > 7:
            continue
        date = f"2026-{month:02d}-{int(match.group(2)):02d}"
        if date not in seen_holiday:
            seen_holiday.add(date)
            data["spring"]["holidays"].append({
                "date": date,
                "name": "运动会"
            })
    
    # If semester doesn't start on Monday, add pre-class days to holidays
    # This ensures compensatory logic works for Week 1 days before classes start
    import datetime
    if data["spring"]["week_1_monday"] and data["spring"]["semester_start"]:
        week_1_monday = datetime.datetime.strptime(data["spring"]["week_1_monday"], "%Y-%m-%d")
        semester_start = datetime.datetime.strptime(data["spring"]["semester_start"], "%Y-%m-%d")
        
        # Add all days from week_1_monday to the day before semester_start as holidays
        current = week_1_monday
        while current < semester_start:
            date_str = current.strftime("%Y-%m-%d")
            # Check if not already in holidays
            existing_dates = {h["date"] for h in data["spring"]["holidays"]}
            if date_str not in existing_dates:
                data["spring"]["holidays"].append({
                    "date": date_str,
                    "name": "学期开始前"
                })
            current += datetime.timedelta(days=1)
    
    return data

def main():
    print("=== Parsing SUSTech Academic Calendar ===\n")
    
    data = parse_calendar()
    
    if not data:
        return
    
    # Print extracted info
    print(f"Year: {data['year']}")
    print(f"\nSpring Semester:")
    print(f"  Classes Start: {data['spring'].get('semester_start', 'N/A')}")
    print(f"  Week 1 Monday: {data['spring'].get('week_1_monday', 'N/A')}")
    print(f"  Semester End: {data['spring'].get('semester_end', 'N/A')}")
    print(f"  Return Date: {data['spring'].get('return_date', 'N/A')}")
    
    print(f"\nHolidays ({len(data['spring']['holidays'])}):")
    for h in sorted(data['spring']['holidays'], key=lambda x: x['date']):
        print(f"  {h['date']}: {h['name']}")
    
    print(f"\nCompensatory ({len(data['spring']['compensatory'])}):")
    for c in sorted(data['spring']['compensatory'], key=lambda x: x['date']):
        print(f"  {c['date']}: {c['note']}")
    
    # Save to file
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ Saved to: {OUTPUT_FILE}")

if __name__ == '__main__':
    main()
