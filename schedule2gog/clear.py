#!/usr/bin/env python3
"""Clear SUSTech schedule events from Google Calendar"""

import json
import os
import subprocess
import sys

def main():
    calendar_id = os.environ.get("CALENDAR_ID", "primary")
    course_filter = os.environ.get("COURSE_FILTER") or None
    
    # Get events from gog
    result = subprocess.run(
        ["gog", "calendar", "events", calendar_id,
         "--from", "2026-02-01T00:00:00+08:00",
         "--to", "2026-07-31T23:59:59+08:00",
         "--json"],
        capture_output=True, text=True
    )
    
    if result.returncode != 0:
        print(f"Error fetching events: {result.stderr}")
        return
    
    try:
        data = json.loads(result.stdout)
        # gog returns {"events": [...]}
        events = data.get("events", [])
    except json.JSONDecodeError as e:
        print(f"Error parsing events: {e}")
        return
    
    if not events:
        print("No events found.")
        return
    
    deleted = 0
    
    for event in events:
        summary = event.get("summary", "")
        description = event.get("description", "")
        event_id = event.get("id")
        
        # Check if it's a SUSTech course event (has Teacher: in description)
        if "Teacher:" in description and "Week:" in description:
            # Apply course filter if specified
            if course_filter and course_filter not in summary:
                continue
            
            start = event.get("start", {}).get("dateTime", "N/A")
            print(f"Delete: {summary} ({start[:10] if start else 'N/A'})")
            
            cmd = ["gog", "calendar", "delete", calendar_id, event_id, "--force", "--no-input"]
            result = subprocess.run(cmd, capture_output=True)
            
            if result.returncode == 0:
                deleted += 1
            else:
                print(f"  Warning: {result.stderr[:50] if result.stderr else 'already gone'}")
    
    print(f"\nDone. Deleted {deleted} events.")

if __name__ == "__main__":
    main()
