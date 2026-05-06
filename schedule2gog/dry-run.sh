#!/bin/bash
# Dry-run mode - preview events without creating them
cd "$(dirname "$0")"
exec ./sync.sh --dry-run "$@"
