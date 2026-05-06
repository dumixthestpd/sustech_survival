#!/bin/bash
# TIS Login Script with Status Check
# Usage: ./login-tis.sh

TIS_URL="https://tis.sustech.edu.cn"
CAS_URL="https://cas.sustech.edu.cn/cas/login?service=https%3A%2F%2Ftis.sustech.edu.cn%2Fcas"
# Use authentication/main - main page doesn't redirect properly when logged in
USER_PAGE="$TIS_URL/authentication/main"

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

keep_tis_open() {
    # Ensure at least one TIS tab remains open to maintain session
    open -a "Google Chrome" "$USER_PAGE" 2>/dev/null
}

check_login_status() {
    CURRENT_URL=$(osascript -e 'tell app "Google Chrome" to get URL of active tab of window 1' 2>/dev/null)
    echo "Current URL: $CURRENT_URL"
    
    # No Chrome window/tab open = not logged in
    if [ -z "$CURRENT_URL" ]; then
        echo "→ Not logged in (no tab)"
        return 1
    elif echo "$CURRENT_URL" | grep -qE "(cas\.sustech\.edu\.cn|/session/invalid)"; then
        echo "→ Not logged in"
        return 1
    else
        echo "→ Logged in"
        return 0
    fi
}

echo "=== TIS Login Script ==="
echo ""

# Check login status - if already logged in, just clean up and exit
echo "[1/2] Checking login status..."
check_login_status
if [ $? -eq 0 ]; then
    echo "✓ Already logged in."
    cleanup_invalid_tabs
    exit 0
fi

# Not logged in - perform CAS login
echo "[2/2] Performing login..."
open -a "Google Chrome" "$CAS_URL"
sleep 5
python3 -c "import pyautogui; pyautogui.press('enter')"
echo "Login triggered. Waiting for redirect..."
sleep 10

# Clean up invalid tabs - login should have redirected to auth/main
cleanup_invalid_tabs
echo "✓ Login complete! TIS tab open."
