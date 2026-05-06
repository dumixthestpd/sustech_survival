#!/usr/bin/env bash
# Semester week calculator
# Usage: ./week.sh           # today's week
#        ./week.sh 2026-04-20  # specific date
#        ./week.sh next monday

DIR="$(cd "$(dirname "$0")" && pwd)"
python3 "$DIR/semester_week.py" "$@"
