#!/bin/bash
# TIS Login Check - Robust Version
# Usage: ./check.sh
# Returns: 0 if logged in, 1 if not logged in

# Use authentication/main page - more reliable than main page
USER_PAGE="https://tis.sustech.edu.cn/authentication/main"

cleanup_invalid_tabs() {
    # Close useless tabs: /session/invalid, TIS home page
    osascript -e '
    tell application "Google Chrome"
        set windowList to windows
        repeat with w in windowList
            set tabList to tabs of w
            repeat with i from (count of tabList) to 1 by -1
                set t to item i of tabList
                set tURL to URL of t
                if tURL contains "/session/invalid" or tURL is "https://tis.sustech.edu.cn/" or tURL is "https://tis.sustech.edu.cn" or tURL contains "/user/me" then
                    close t
                end if
            end repeat
        end repeat
    end tell
    ' 2>/dev/null
}

# Open user page to check login status
open -a "Google Chrome" "$USER_PAGE"
sleep 3

# Get current URL after potential redirect
URL=$(osascript -e 'tell app "Google Chrome" to get URL of active tab of window 1' 2>/dev/null)

echo "Current URL: $URL"

# Check for NOT logged in indicators:
# 1. Redirected to CAS login
# 2. Session invalid/expired
if echo "$URL" | grep -qE "(cas\.sustech\.edu\.cn|/session/invalid)"; then
    echo "✗ NOT LOGGED IN"
    # Keep at least one TIS tab to maintain session
    cleanup_invalid_tabs
    open -a "Google Chrome" "$USER_PAGE"
    exit 1
elif echo "$URL" | grep -q "authentication/main"; then
    echo "✓ LOGGED IN"
    # Already has TIS tab open, keep it
    cleanup_invalid_tabs
    exit 0
else
    echo "✗ UNKNOWN STATUS - treating as NOT LOGGED IN"
    cleanup_invalid_tabs
    open -a "Google Chrome" "$USER_PAGE"
    exit 1
fi
