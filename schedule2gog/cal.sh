#!/usr/bin/env bash
# Convenience wrapper for fetch_calendar.py
# Usage: ./cal.sh              # check updates, download if new
#        ./cal.sh --parse      # download + parse → semester.json
#        ./cal.sh --check      # just check
#        ./cal.sh --year 2026  # specific year
#        ./cal.sh --all        # all calendars on page
#        ./cal.sh --offline    # use cache only

DIR="$(cd "$(dirname "$0")" && pwd)"
python3 "$DIR/fetch_calendar.py" "$@"
