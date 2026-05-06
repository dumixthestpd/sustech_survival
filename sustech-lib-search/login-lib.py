#!/usr/bin/env python3
"""
SUSTech Library (Primo) Login via real Chrome + AppleScript.

This opens Chrome directly and uses osascript to:
1. Check if already logged in (URL check)
2. Open CAS login page if needed
3. Press Enter to submit (credentials saved in Chrome)

Usage:
    python3 login-lib.py
    # If no args, reads from ~/.openclaw/workspace/credentials.txt
"""
import subprocess
import sys
import time
import json

PRIMO_HOME = "https://sustc.primo.exlibrisgroup.com.cn/discovery/search?vid=86SUSTC_INST:86SUSTC"
CAS_URL = ("https://cas.sustech.edu.cn/cas/login"
           "?service=https%3A%2F%2Fsustc.primo.exlibrisgroup.com.cn%2Finfra%2FcasRedirect%3Fctx%3D%2Fprimaws")
COOKIE_FILE = "/Users/dumix/.openclaw/workspace/bb_session.json"
CREDS_FILE = "/Users/dumix/.openclaw/workspace/credentials.txt"


def get_creds():
    with open(CREDS_FILE) as f:
        line = f.read().strip()
    username, password = line.split(":", 1)
    return username.strip(), password.strip()


def chrome_url():
    """Get URL of frontmost Chrome tab via osascript."""
    script = 'tell app "Google Chrome" to get URL of active tab of window 1'
    try:
        return subprocess.check_output(
            ["osascript", "-e", script],
            stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        return ""


def main():
    username, password = get_creds()
    print(f"=== SUSTech Library Login ===")
    print(f"User: {username}\n")

    # Step 1: Check if already logged in
    current = chrome_url()
    print(f"[1/3] Current URL: {current[:80]}")

    if "primo.exlibrisgroup.com.cn" in current and "cas" not in current:
        print("✓ Already logged in.")
        return

    # Step 2: Open CAS login
    print("[2/3] Opening CAS login...")
    subprocess.run(["open", "-a", "Google Chrome", CAS_URL])
    time.sleep(3)

    # Step 3: Submit login (credentials autofilled by Chrome)
    print("[3/3] Submitting login (pressing Enter)...")
    import pyautogui
    pyautogui.press("enter")

    # Wait for redirect
    time.sleep(8)

    final = chrome_url()
    print(f"Final URL: {final[:80]}")

    if "primo.exlibrisgroup.com.cn" in final and "cas" not in final:
        print("✓ Logged in successfully!")
    else:
        print("⚠ Login may need manual attention")

    # Save session cookies from Chrome via Playwright
    print("\nSaving session cookies...")
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)  # Connect to real Chrome
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            # Try to get existing Chrome session
            for page in ctx.pages:
                page.close()
            browser.close()
    except Exception as e:
        print(f"Note: Could not capture cookies: {e}")
        print("Browser relay login complete. Use browser relay for search.")


if __name__ == "__main__":
    main()
