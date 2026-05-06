#!/bin/bash
# Clear schedule events from Google Calendar
# Usage: ./clear.sh [--course NAME] [--from YYYY-MM-DD] [--to YYYY-MM-DD]

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CALENDAR_ID="${CALENDAR_ID:-primary}"
SEMESTER_START="2026-02-16"
SEMESTER_END="2026-06-30"

COURSE_FILTER=""
DATE_FROM="$SEMESTER_START"
DATE_TO="$SEMESTER_END"

while [[ $# -gt 0 ]]; do
    case $1 in
        --course)
            COURSE_FILTER="$2"
            shift 2
            ;;
        --from)
            DATE_FROM="$2"
            shift 2
            ;;
        --to)
            DATE_TO="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "Clearing SUSTech schedule events from calendar: $CALENDAR_ID"
echo "Date range: $DATE_FROM to $DATE_TO"
echo ""

# Get all events in the range
EVENTS=$(gog calendar events "$CALENDAR_ID" \
    --from "${DATE_FROM}T00:00:00+08:00" \
    --to "${DATE_TO}T23:59:59+08:00" \
    --json 2>/dev/null)

if [[ -z "$EVENTS" || "$EVENTS" == "[]" ]]; then
    echo "No events found in the semester range."
    exit 0
fi

# Use Python to filter and delete events
CALENDAR_ID="$CALENDAR_ID" COURSE_FILTER="$COURSE_FILTER" python3 "$SCRIPT_DIR/clear.py" <<< "$EVENTS"
