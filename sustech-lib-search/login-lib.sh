#!/bin/bash
# Login to SUSTech Library (Primo) via CAS authentication
# Opens CAS login directly, presses Enter to submit (credentials autofilled by Chrome)

CAS_URL="https://cas.sustech.edu.cn/cas/login?service=https%3A%2F%2Fsustc.primo.exlibrisgroup.com.cn%2Finfra%2FcasRedirect?ctx=/primaws"
PRIMO_HOME="https://sustc.primo.exlibrisgroup.com.cn/discovery/search?vid=86SUSTC_INST:86SUSTC"

echo "=== SUSTech Library Login Script ==="
echo ""

# Check if already logged in
echo "[1/2] Checking login status..."
CURRENT_URL=$(osascript -e 'tell app "Google Chrome" to get URL of active tab of window 1' 2>/dev/null)
echo "Current URL: $CURRENT_URL"

if echo "$CURRENT_URL" | grep -qE "primo.exlibrisgroup.com.cn" && echo "$CURRENT_URL" | grep -qv "cas"; then
    echo "✓ Already logged in."
    exit 0
fi

# Not logged in - perform CAS login
echo "[2/2] Performing login via CAS..."
open -a "Google Chrome" "$CAS_URL"

echo "Waiting for CAS redirect..."
sleep 5

echo "Pressing Enter to submit login..."
python3 -c "import pyautogui; pyautogui.press('enter')"

echo "Waiting for redirect..."
sleep 10

# Check final URL
FINAL_URL=$(osascript -e 'tell app "Google Chrome" to get URL of active tab of window 1' 2>/dev/null)
echo "Current URL: $FINAL_URL"

if echo "$FINAL_URL" | grep -qE "primo.exlibrisgroup" && echo "$FINAL_URL" | grep -qv "cas"; then
    echo "✓ Logged in successfully to SUSTech Library"
else
    echo "⚠ May need manual login or still on CAS page"
fi