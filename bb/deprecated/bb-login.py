#!/usr/bin/env python3
"""
SUSTech Blackboard login via CAS.
Fetches a fresh CAS session and saves BB session cookie to file.
Usage: python3 bb-login.py <username> <password>
"""

import sys
import requests
import re
import json

COOKIE_FILE = "/tmp/bb_session.json"


def cas_login_bb(username, password):
    """Login to CAS for BB and return the JSESSIONID cookie."""
    head = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'X-Requested-With': 'XMLHttpRequest',
        'Content-Type': 'application/x-www-form-urlencoded',
    }

    service = 'https://bb.sustech.edu.cn/webapps/bb-sso-BBLEARN/index.jsp'
    login_url = f'https://cas.sustech.edu.cn/cas/login?service={service}'

    # Step 1: Get execution token
    print("[1/4] Connecting to CAS...", end=" ", flush=True)
    req = requests.get(login_url, headers=head, timeout=10)
    if req.status_code != 200:
        print(f"FAILED (HTTP {req.status_code})")
        return None
    print("OK")

    execution = re.search(r'name="execution" value="([^"]+)"', req.text)
    if not execution:
        print("FAILED: No execution token found")
        return None
    execution = execution.group(1)

    # Step 2: POST credentials
    print("[2/4] Submitting credentials...", end=" ", flush=True)
    data = {
        'username': username,
        'password': password,
        'execution': execution,
        '_eventId': 'submit',
    }
    req = requests.post(login_url, data=data, allow_redirects=False, headers=head, timeout=10)
    if req.status_code != 302 or 'Location' not in req.headers:
        print(f"FAILED (HTTP {req.status_code})")
        return None
    print("OK")

    ticket_url = req.headers['Location']

    # Step 3: Exchange ticket for BB session
    print("[3/4] Exchanging CAS ticket...", end=" ", flush=True)
    req = requests.get(ticket_url, allow_redirects=False, headers=head, timeout=10)
    
    # BB returns Set-Cookie with JSESSIONID
    set_cookie = req.headers.get('Set-Cookie', '')
    jsess_match = re.search(r'JSESSIONID=([^;]+)', set_cookie)
    if not jsess_match:
        print(f"FAILED: No JSESSIONID. BB response: {req.status_code}")
        # Try to follow redirect
        if 'Location' in req.headers:
            print(f"  -> Redirected to: {req.headers['Location'][:80]}")
        return None
    jsess = jsess_match.group(1)
    print(f"OK (JSESSIONID={jsess[:10]}...)")

    # Step 4: Validate session at BB
    print("[4/4] Validating BB session...", end=" ", flush=True)
    headers = {**head, 'Cookie': f'JSESSIONID={jsess}'}
    # Try the portal URL
    req = requests.get('https://bb.sustech.edu.cn/webapps/portal/execute/tabs/tabAction?tab_tab_group_id=_1_1', 
                       headers=headers, allow_redirects=False, timeout=10)
    location = req.headers.get('Location', '')
    if 'login' in location.lower():
        print(f"FAILED: Session not valid (redirects to {location[:60]})")
        return None
    print("OK")

    print(f"\n✅ Login successful!")
    print(f"   JSESSIONID: {jsess}")
    
    return jsess


def save_session(jsess):
    """Save session to cookie file."""
    cookie_data = {
        'jsessionid': jsess,
    }
    with open(COOKIE_FILE, 'w') as f:
        json.dump(cookie_data, f)
    print(f"   Session saved to {COOKIE_FILE}")


def main():
    if len(sys.argv) < 3:
        # Try default credentials from environment or prompt
        print("Usage: bb-login.py <username> <password>")
        print("Or set BBTEST=1 to use stored test credentials")
        sys.exit(1)

    username = sys.argv[1]
    password = sys.argv[2]

    print(f"=== BB Login for {username} ===\n")
    jsess = cas_login_bb(username, password)
    
    if jsess:
        save_session(jsess)
    else:
        sys.exit(1)


if __name__ == '__main__':
    main()
