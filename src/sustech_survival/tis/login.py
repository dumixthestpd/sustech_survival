#!/usr/bin/env python3
"""
SUSTech CAS Login - Pure Python, no browser required.
Login to TIS or other CAS-protected services using direct HTTP.
Works for: TIS (confirmed), BB (ticket works but session validation is browser-only)

Usage:
    python3 cas-login.py <username> <password> [service_url]
    
Examples:
    python3 cas-login.py 12413021 mypass
    python3 cas-login.py 12413021 mypass "https://tis.sustech.edu.cn/authentication/main"
"""

import sys
import requests
import re
import json

SESSION_FILE = "/tmp/sustech_cas_session.json"

# Default services
TIS_SERVICE = "https://tis.sustech.edu.cn/cas"
BB_SERVICE = "https://bb.sustech.edu.cn/webapps/bb-sso-BBLEARN/index.jsp"


def cas_login(username, password, service_url=None):
    """Login to SUSTech CAS and return session cookies (route + JSESSIONID)."""
    if service_url is None:
        service_url = TIS_SERVICE

    encoded_service = service_url.replace(':', '%3A').replace('/', '%2F')
    login_url = f"https://cas.sustech.edu.cn/cas/login?service={encoded_service}"

    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'X-Requested-With': 'XMLHttpRequest',
    }

    print(f"[*] Connecting to CAS...")
    req = requests.get(login_url, headers=headers, timeout=10)
    if req.status_code != 200:
        print(f"[!] CAS returned HTTP {req.status_code}")
        return None

    execution = re.search(r'name="execution" value="([^"]+)"', req.text)
    if not execution:
        print("[!] No execution token found in CAS page")
        return None
    execution = execution.group(1)

    print(f"[*] Logging in as {username}...")
    data = {
        'username': username,
        'password': password,
        'execution': execution,
        '_eventId': 'submit',
    }
    req = requests.post(login_url, data=data, allow_redirects=False, headers=headers, timeout=10)
    
    if req.status_code != 302 or 'Location' not in req.headers:
        print(f"[!] Login failed (HTTP {req.status_code})")
        if req.status_code == 200:
            # Check for error message
            error = re.search(r'class="errors"[^>]*>([^<]+)', req.text)
            if error:
                print(f"    Error: {error.group(1)}")
        return None

    print(f"[*] Exchanging ticket...")
    ticket_url = req.headers['Location']
    req = requests.get(ticket_url, allow_redirects=False, headers=headers, timeout=10)

    set_cookie = req.headers.get('Set-Cookie', '')
    route = re.search(r'route=([^;]+)', set_cookie)
    jsess = re.search(r'JSESSIONID=([^;]+)', set_cookie)

    if not route or not jsess:
        print(f"[!] No session cookies returned. Status: {req.status_code}")
        return None

    cookies = {'route': route.group(1), 'JSESSIONID': jsess.group(1)}
    print(f"[+] Logged in successfully!")
    print(f"    route: {cookies['route'][:15]}...")
    print(f"    JSESSIONID: {cookies['JSESSIONID'][:15]}...")

    return cookies


def save_session(cookies, service="tis"):
    """Save session cookies to file."""
    data = {'cookies': cookies, 'service': service}
    with open(SESSION_FILE, 'w') as f:
        json.dump(data, f)
    print(f"    Saved to {SESSION_FILE}")


def test_tis(cookies):
    """Test TIS access with session cookies."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'X-Requested-With': 'XMLHttpRequest',
        'Cookie': f"route={cookies['route']}; JSESSIONID={cookies['JSESSIONID']}"
    }
    req = requests.get('https://tis.sustech.edu.cn/authentication/main', headers=headers, timeout=10)
    if req.status_code == 200 and 'login' not in req.url.lower():
        print(f"[+] TIS access: OK")
        return True
    else:
        print(f"[!] TIS access: {req.status_code} ({req.url[:60]})")
        return False


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    username = sys.argv[1]
    password = sys.argv[2]
    service = sys.argv[3] if len(sys.argv) > 3 else None

    print(f"=== CAS Login: {username} ===\n")
    cookies = cas_login(username, password, service)
    if not cookies:
        sys.exit(1)

    save_session(cookies)

    # For TIS, also test it
    if not service or 'tis' in service:
        print("")
        test_tis(cookies)


if __name__ == '__main__':
    main()
