#!/bin/bash
# schedule2gog - Sync SUSTech schedule to Google Calendar
# Usage: ./sync.sh [--dry-run] [--weeks RANGE] [--course NAME]

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
COURSES_FILE="${COURSES_FILE:-$HOME/.openclaw/workspace/sustech/26spring/courses.csv}"
export COURSES_FILE
CALENDAR_ID="${CALENDAR_ID:-primary}"
SEMESTER_START=""  # Loaded from config

# Options
DRY_RUN=false
WEEK_FILTER=""
COURSE_FILTER=""
CLEAR_FIRST=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --weeks)
            WEEK_FILTER="$2"
            shift 2
            ;;
        --course)
            COURSE_FILTER="$2"
            shift 2
            ;;
        --clear)
            CLEAR_FIRST=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Clear existing events first (unless --dry-run, or --course which is partial)
if [[ "$CLEAR_FIRST" == "true" && "$DRY_RUN" != "true" ]]; then
    echo "=== Clearing existing SUSTech schedule events ==="
    if [[ -n "$COURSE_FILTER" ]]; then
        bash "$SCRIPT_DIR/clear.sh" --course "$COURSE_FILTER"
    else
        bash "$SCRIPT_DIR/clear.sh"
    fi
    echo ""
fi

# Check prerequisites
if [[ ! -f "$COURSES_FILE" ]]; then
    echo "Error: Courses file not found: $COURSES_FILE"
    echo "Run: cd ~/.openclaw/workspace/skills/sustech-survival/tis && python3 fetch_courses.py"
    exit 1
fi

# Check gog auth
if ! gog auth list 2>/dev/null | grep -q "@"; then
    echo "Error: gog not authenticated. Run: gog auth add your@email.com --services calendar"
    exit 1
fi

echo "Syncing SUSTech schedule to Google Calendar..."
echo "Calendar: $CALENDAR_ID"
echo ""

# Run Python script with environment variables
export COURSES_FILE="$COURSES_FILE"
export CALENDAR_ID="$CALENDAR_ID"
export SEMESTER_START="$SEMESTER_START"
export WEEK_FILTER="$WEEK_FILTER"
export COURSE_FILTER="$COURSE_FILTER"
export DRY_RUN="$DRY_RUN"

python3 "$SCRIPT_DIR/sync.py"
