#!/bin/bash
# SUSTech Library Login Check
# Usage: ./check.sh
# Returns: 0 if logged in, 1 if not logged in

PRIMO_HOME="https://sustc.primo.exlibrisgroup.com.cn/discovery/search?vid=86SUSTC_INST:86SUSTC"

# Open Primo home to check login status
open -a "Google Chrome" "$PRIMO_HOME"
sleep 4

# Get current URL after potential redirect
URL=$(osascript -e 'tell app "Google Chrome" to get URL of active tab of window 1' 2>/dev/null)

echo "Current URL: $URL"

# Check for NOT logged in indicators
if echo "$URL" | grep -qE "cas.sustech.edu.cn"; then
    echo "✗ NOT LOGGED IN"
    exit 1
elif echo "$URL" | grep -qE "primo.exlibrisgroup"; then
    echo "✓ LOGGED IN"
    exit 0
else
    echo "✗ UNKNOWN STATUS - treating as NOT LOGGED IN"
    exit 1
fi