#!/usr/bin/env python3
"""
SUSTech BB Headless Login using Playwright.
Uses a headless Chromium browser to complete the full CAS+BB SSO login flow.
Saves session cookies to ~/.openclaw/workspace/bb_session.json

Usage:
    python3 headless-login.py <username> <password>
"""

import sys
import json
from playwright.sync_api import sync_playwright

BB_PORTAL = "https://bb.sustech.edu.cn/webapps/portal/execute/tabs/tabAction?tab_tab_group_id=_1_1"
CAS_URL = "https://cas.sustech.edu.cn/cas/login?service=https://bb.sustech.edu.cn/webapps/bb-sso-BBLEARN/index.jsp"
COOKIE_FILE = "/Users/dumix/.openclaw/workspace/bb_session.json"


def login(username, password):
    cookies_result = {}
    
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage']
        )
        context = browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        page = context.new_page()
        
        print("[1/3] Opening CAS login page...")
        page.goto(CAS_URL, timeout=15000)
        page.wait_for_load_state('networkidle', timeout=10000)
        
        print("[2/3] Filling credentials...")
        page.fill('input[name="username"]', username)
        page.fill('input[name="password"]', password)
        page.press('input[name="password"]', 'Enter')
        
        print("[3/3] Waiting for BB portal...")
        try:
            page.wait_for_url('**/portal/**', timeout=20000)
            print(f"[+] Logged in! URL: {page.url[:80]}")
        except Exception as e:
            print(f"[!] Did not reach BB portal. Final URL: {page.url[:80]}")
        
        # Get all relevant cookies
        cookies = context.cookies()
        bb_cookie_names = ['JSESSIONID', 'DISSESSION', 'TGC', 's_session_id', 'CdnSignedValidation']
        for c in cookies:
            if c['name'] in bb_cookie_names:
                cookies_result[c['name']] = c['value']
        
        browser.close()
    
    return cookies_result


def save_cookies(cookies):
    """Save session cookies to file."""
    with open(COOKIE_FILE, 'w') as f:
        json.dump(cookies, f, indent=2)
    print(f"[+] Cookies saved to {COOKIE_FILE}")


def test_session(cookies):
    """Test if the saved session works against BB."""
    import requests
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'X-Requested-With': 'XMLHttpRequest',
    }
    cookie_str = '; '.join(f"{k}={v}" for k, v in cookies.items())
    headers['Cookie'] = cookie_str
    
    r = requests.get(BB_PORTAL, headers=headers, allow_redirects=False, timeout=10)
    location = r.headers.get('Location', '')
    if 'login' in location.lower():
        print(f"[!] Session invalid (redirects to {location[:60]})")
        return False
    print(f"[+] Session valid! BB responded: {r.status_code}")
    return True


def main():
    if len(sys.argv) < 3:
        print("Usage: headless-login.py <username> <password>")
        sys.exit(1)
    
    username = sys.argv[1]
    password = sys.argv[2]
    
    print(f"=== BB Headless Login: {username} ===\n")
    cookies = login(username, password)
    
    if not cookies:
        print("[!] Login failed")
        sys.exit(1)
    
    print(f"\n[+] Got cookies: {list(cookies.keys())}")
    save_cookies(cookies)
    print("")
    test_session(cookies)


if __name__ == '__main__':
    main()
