#!/usr/bin/env python3
"""Sync SUSTech schedule to Google Calendar - with holiday support"""

import csv
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta

# Day of week mapping
DAY_OFFSET = {
    "星期一": 0,
    "星期二": 1,
    "星期三": 2,
    "星期四": 3,
    "星期五": 4,
    "星期六": 5,
    "星期日": 6,
}

# Period to time mapping
# Morning: 1-4节, 50min each, 10min break (except 2-3 has 30min)
#   1: 08:00-08:50, 2: 09:00-09:50, 3: 10:20-11:10, 4: 11:20-12:10
# Afternoon: 5-8节, 14:00 start, same break pattern
#   5: 14:00-14:50, 6: 15:00-15:50, 7: 16:20-17:10, 8: 17:20-18:10
# Evening: 9-10节
#   9: 19:00-19:50, 10: 20:00-20:50
PERIOD_START = {
    1: "08:00", 2: "09:00", 3: "10:20", 4: "11:20",
    5: "14:00", 6: "15:00", 7: "16:20", 8: "17:20",
    9: "19:00", 10: "20:00"
}

PERIOD_END = {
    1: "08:50", 2: "09:50", 3: "11:10", 4: "12:10",
    5: "14:50", 6: "15:50", 7: "17:10", 8: "18:10",
    9: "19:50", 10: "20:50"
}

DAY_SHORT = {
    "星期一": "Mon", "星期二": "Tue", "星期三": "Wed",
    "星期四": "Thu", "星期五": "Fri", "星期六": "Sat", "星期日": "Sun"
}

# Day name mapping for compensatory notes (周一, 周二, etc.)
DAY_NAME_MAP = {
    "星期一": "周一", "星期二": "周二", "星期三": "周三",
    "星期四": "周四", "星期五": "周五", "星期六": "周六", "星期日": "周日"
}

CALENDAR_DIR = os.path.expanduser("~/.openclaw/workspace/sustech")
SEMESTER_CONFIG = os.path.join(CALENDAR_DIR, "semester.json")

def load_semester_config():
    """Load semester dates and holidays from config"""
    if os.path.exists(SEMESTER_CONFIG):
        with open(SEMESTER_CONFIG, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None

def is_holiday(date_str, config):
    """Check if date is a holiday"""
    if not config:
        return False
    holidays = config.get('spring', {}).get('holidays', [])
    return any(h['date'] == date_str for h in holidays)

def is_no_class_day(date_str, config):
    """Check if date is a no-class day (arrival, sports meet, etc.)"""
    if not config:
        return False
    no_class = config.get('spring', {}).get('no_class_days', [])
    return any(n['date'] == date_str for n in no_class)

def is_compensatory(date_str, config):
    """Check if date is a compensatory work day"""
    if not config:
        return None
    compensatory = config.get('spring', {}).get('compensatory', [])
    for c in compensatory:
        if c['date'] == date_str:
            return c
    return None

def get_compensatory_for_day(day_name, week_type, week_num, config):
    """
    Get compensatory date for a specific day+week_type+week.

    Compensatory entries have:
    - for_week: applies only to a specific week (e.g. 运动会/清明 Week 8 → April 4)
    - for_week_type: applies to a week type (e.g. 单周 Tuesday → May 9)
    """
    if not config:
        return None
    compensatory = config.get('spring', {}).get('compensatory', [])
    day_short = DAY_NAME_MAP.get(day_name, day_name)
    for c in compensatory:
        note = c.get('note', '')
        if day_short not in note:
            continue
        # for_week: tied to a specific holiday week
        for_week = c.get('for_week')
        if for_week is not None:
            if for_week == week_num:
                return c.get('date')
            continue
        # for_week_type: tied to a week-type restriction
        for_week_type = c.get('for_week_type')
        if for_week_type is not None:
            if for_week_type == week_type or week_type == "周":
                return c.get('date')
            continue
    return None

def get_existing_events(calendar_id):
    """Fetch existing calendar events to detect contradictions"""
    result = subprocess.run(
        ["gog", "calendar", "events", calendar_id,
         "--from", "2026-02-01T00:00:00+08:00",
         "--to", "2026-07-31T23:59:59+08:00",
         "--max", "500",
         "--json"],
        capture_output=True, text=True, env={**os.environ, "GOG_ACCOUNT": os.environ.get("GOG_ACCOUNT", "")}
    )
    if result.returncode != 0:
        return {}
    
    try:
        data = json.loads(result.stdout)
        events = data.get("events", [])
        # Key by "date_start" for fast lookup
        existing = {}
        for e in events:
            start = e.get("start", {}).get("dateTime", "")[:16]  # YYYY-MM-DDTHH:MM
            summary = e.get("summary", "")
            # Key includes date + course name
            key = f"{start}|{summary}"
            existing[key] = e
        return existing
    except:
        return {}

def check_contradiction(course_name, start_dt, location, existing_events):
    """
    Check for contradictions:
    - DUPLICATE: exact same event exists (same date+time+course)
    - CONTRADICTION: same course on same date but DIFFERENT time or location
    Returns: "duplicate", "contradiction", or None
    """
    start_key = start_dt[:16]  # YYYY-MM-DDTHH:MM
    
    # Check exact duplicate
    key = f"{start_key}|{course_name}"
    if key in existing_events:
        return "duplicate"
    
    # Check contradiction - same course, same date but different time/location
    for existing_key, existing_event in existing_events.items():
        if f"|{course_name}" in existing_key:
            existing_start = existing_key.split("|")[0]
            if existing_start == start_key:
                # Same date and time - check location
                existing_location = existing_event.get("location", "")
                if existing_location != location:
                    return "contradiction"
    
    return None

def main():
    courses_file = os.environ.get("COURSES_FILE")
    if not courses_file:
        print("Error: COURSES_FILE environment variable not set!")
        print(f"   Please set COURSES_FILE or ensure sync.sh sets it")
        return 1
    calendar_id = os.environ.get("CALENDAR_ID", "primary")
    week_filter = os.environ.get("WEEK_FILTER") or None
    course_filter = os.environ.get("COURSE_FILTER") or None
    dry_run = os.environ.get("DRY_RUN", "false") == "true"
    
    print(f"📂 Using courses file: {courses_file}")
    
    if not os.path.exists(courses_file):
        print(f"Error: Courses file not found: {courses_file}")
        return 1
    
    # Load semester config
    config = load_semester_config()
    
    if config:
        print(f"📅 Loaded semester config: {config.get('year')}")
        week_1_monday = config.get('spring', {}).get('week_1_monday')
        if week_1_monday:
            SEMESTER_START = datetime.strptime(week_1_monday, "%Y-%m-%d")
            print(f"   Week 1 starts: {week_1_monday}")
        
        holidays = config.get('spring', {}).get('holidays', [])
        if holidays:
            print(f"   Holidays: {len(holidays)} days")
        
        compensatory = config.get('spring', {}).get('compensatory', [])
        if compensatory:
            print(f"   Compensatory: {len(compensatory)} days")
    else:
        print("⚠️ No semester config found, using default dates")
        SEMESTER_START = None  # Loaded from config
    
    print("")
    
    # Parse week filter
    if week_filter and "-" in week_filter:
        filter_start, filter_end = map(int, week_filter.split("-"))
    else:
        filter_start = filter_end = None
    
    total_events = 0
    skipped_holidays = 0
    added_compensatory = 0
    skipped_duplicates = 0
    
    # Fetch existing events for duplicate detection
    if not dry_run:
        print("🔍 Checking for existing events...")
        existing_events = get_existing_events(calendar_id)
        if existing_events:
            print(f"   Found {len(existing_events)} existing events")
        print("")
    
    with open(courses_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            course_name = row.get("Course Name", "").strip()
            teacher = row.get("Teacher", "").strip()
            schedule = row.get("Schedule", "").strip()
            
            if not course_name or not schedule:
                continue
            
            # Filter by course name (exact match)
            if course_filter and course_filter != course_name:
                continue
            
            print(f"Course: {course_name} ({teacher})")
            
            # Parse schedule - split by semicolon
            for sched in schedule.split(";"):
                sched = sched.strip()
                if not sched:
                    continue
                
                # Parse week range
                import re
                week_match = re.match(r"(\d+)-(\d+)(周|单周|双周)", sched)
                if not week_match:
                    continue
                
                week_start, week_end = int(week_match.group(1)), int(week_match.group(2))
                week_type = week_match.group(3)
                
                # Apply week filter
                if filter_start:
                    week_start = max(week_start, filter_start)
                    week_end = min(week_end, filter_end)
                    if week_start > week_end:
                        continue
                
                # Parse day and period
                day_match = re.search(r"星期(.)第(\d+)-(\d+)节", sched)
                if not day_match:
                    continue
                
                day_name = "星期" + day_match.group(1)
                period_start = int(day_match.group(2))
                period_end = int(day_match.group(3))
                
                # Get location
                location_match = re.search(r"第\d+-\d+节\s*(.+)$", sched)
                location = location_match.group(1).strip() if location_match else ""
                
                day_offset = DAY_OFFSET.get(day_name)
                if day_offset is None:
                    continue
                
                start_time = PERIOD_START.get(period_start)
                end_time = PERIOD_END.get(period_end)
                if not start_time or not end_time:
                    continue
                
                # Generate events for each week
                for week_num in range(week_start, week_end + 1):
                    # Skip odd/even weeks
                    if week_type == "单周" and week_num % 2 == 0:
                        continue
                    if week_type == "双周" and week_num % 2 == 1:
                        continue
                    
                    # Calculate date: week 1 Monday + (week-1)*7 + day_offset
                    event_date = SEMESTER_START + timedelta(weeks=week_num - 1, days=day_offset)
                    event_date_str = event_date.strftime("%Y-%m-%d")
                    
                    comp = None  # Track if this is a compensatory day
                    
                    # Check if no-class day (arrival, sports meet, etc.)
                    # But NOT if this date is a compensatory day — compensatory overrides no_class
                    if is_no_class_day(event_date_str, config) and not is_compensatory(event_date_str, config):
                        print(f"  ⛔ SKIP {event_date_str} {DAY_SHORT.get(day_name)}: {day_name} is a no-class day")
                        skipped_holidays += 1
                        continue
                    
                    # Check if holiday
                    if is_holiday(event_date_str, config):
                        # Check if there's a compensatory day for this day+week_type+week
                        comp_date = get_compensatory_for_day(day_name, week_type, week_num, config)
                        if comp_date:
                            print(f"  ⛔ SKIP {event_date_str} {DAY_SHORT.get(day_name)}: Holiday")
                            print(f"     → Adding class on compensatory day {comp_date} (Week {week_num})")
                            # Use compensatory date instead
                            event_date_str = comp_date
                            event_date = datetime.strptime(event_date_str, "%Y-%m-%d")
                            added_compensatory += 1
                            comp = {"date": comp_date, "note": "compensatory"}
                        else:
                            print(f"  ⛔ SKIP {event_date_str} {DAY_SHORT.get(day_name)}: Holiday")
                            skipped_holidays += 1
                            continue
                    elif day_name == "星期二" and (week_num % 2 == 1):
                        # For Tuesday classes in odd weeks, check if Monday of that week is a holiday
                        # If so, apply compensatory (e.g., May 9 for May 4 holiday)
                        monday_date = SEMESTER_START + timedelta(weeks=week_num - 1, days=0)  # Monday of this week
                        monday_str = monday_date.strftime("%Y-%m-%d")
                        if is_holiday(monday_str, config):
                            # Monday is holiday, check for Tuesday compensatory
                            comp_date = get_compensatory_for_day(day_name, week_type, week_num, config)
                            if comp_date:
                                print(f"  ⛔ {monday_str} {DAY_SHORT.get('星期一')} is Holiday! Moving {day_name} class to {comp_date}")
                                event_date_str = comp_date
                                event_date = datetime.strptime(event_date_str, "%Y-%m-%d")
                                added_compensatory += 1
                                comp = {"date": comp_date, "note": "compensatory"}
                            print(f"  ⛔ SKIP {event_date_str} {DAY_SHORT.get(day_name)}: Holiday")
                            skipped_holidays += 1
                            continue
                    elif is_compensatory(event_date_str, config):
                        # This date IS a compensatory day - add class here
                        comp = is_compensatory(event_date_str, config)
                        print(f"  ⚠️ {event_date_str} is 调休! Adding {week_type} class")
                        added_compensatory += 1
                    
                    start_dt = f"{event_date_str}T{start_time}:00"
                    end_dt = f"{event_date_str}T{end_time}:00"
                    
                    description = f"Teacher: {teacher}"
                    if location:
                        description += f"\nLocation: {location}"
                    description += f"\nWeek: {week_num} ({week_type})"
                    if comp:
                        description += f"\n⚠️ Compensatory day"
                    
                    day_short_str = DAY_SHORT.get(day_name, day_name)
                    
                    print(f"  {event_date_str} {day_short_str} {period_start}-{period_end}节 @ {location} (Week {week_num})")
                    
                    # Check for contradiction (duplicate or conflicting event)
                    if not dry_run:
                        conflict = check_contradiction(course_name, start_dt, location, existing_events)
                        if conflict == "duplicate":
                            print(f"    ⚠️ DUPLICATE - skipping")
                            skipped_duplicates += 1
                            continue
                        elif conflict == "contradiction":
                            print(f"    ❌ CONTRADICTION - existing event has different time/location! Stopping.")
                            print(f"    Please clear calendar and resync.")
                            return  # Stop sync
                    
                    if dry_run:
                        print(f"    [DRY-RUN] Would create: {course_name}")
                    else:
                        cmd = [
                            "gog", "calendar", "create", calendar_id,
                            "--summary", course_name,
                            "--from", f"{start_dt}+08:00",
                            "--to", f"{end_dt}+08:00",
                            "--description", description,
                            "--location", location,
                            "--force", "--no-input"
                        ]
                        result = subprocess.run(cmd, capture_output=True, env={**os.environ, "GOG_ACCOUNT": os.environ.get("GOG_ACCOUNT", "")})
                        
                        # Add to existing_events so subsequent checks detect duplicates in this run
                        if result.returncode == 0:
                            key = f"{start_dt[:16]}|{course_name}"
                            existing_events[key] = {"location": location}
                    
                    total_events += 1
            
            print()
    
    print(f"Done. {'Would create' if dry_run else 'Created'} {total_events} events.")
    if skipped_holidays > 0:
        print(f"Skipped {skipped_holidays} holiday dates.")
    if added_compensatory > 0:
        print(f"Added {added_compensatory} compensatory day sessions.")
    if skipped_duplicates > 0:
        print(f"⚠️ Skipped {skipped_duplicates} duplicate events.")

if __name__ == "__main__":
    main()
