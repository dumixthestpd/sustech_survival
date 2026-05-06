#!/bin/bash
# BB Login Check - Check Blackboard login status
# Usage: ./check-login.sh
# Returns: 0 if logged in, 1 if not logged in

BB_PAGE="https://bb.sustech.edu.cn"

# Open BB page to check login status
open -a "Google Chrome" "$BB_PAGE"
sleep 3

# Get current URL after potential redirect
URL=$(osascript -e 'tell app "Google Chrome" to get URL of active tab of window 1' 2>/dev/null)

echo "Current URL: $URL"

# Check for NOT logged in indicators:
# 1. Redirected to CAS login
# 2. Session invalid/expired
if echo "$URL" | grep -qE "cas\.sustech\.edu\.cn"; then
    echo "✗ NOT LOGGED IN"
    exit 1
elif echo "$URL" | grep -qE "(portal/execute/tabs|bb-sso-BBLEARN)"; then
    echo "✓ LOGGED IN"
    exit 0
elif echo "$URL" | grep -qE "bb\.sustech\.edu\.cn/webapps/"; then
    echo "✓ LOGGED IN (on BB page)"
    exit 0
else
    echo "✗ UNKNOWN STATUS - treating as NOT LOGGED IN"
    exit 1
fi
