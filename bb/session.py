#!/usr/bin/env python3
"""
Session — auth (login/refresh/session check) for BB.
All BB operations import session constants and auth helpers from here.
"""
import json, re, sys, os, requests
from pathlib import Path

BB_BASE = "https://bb.sustech.edu.cn"
CAS_URL = "https://cas.sustech.edu.cn/cas/login?service=https://bb.sustech.edu.cn/webapps/bb-sso-BBLEARN/index.jsp"
BB_DIR = Path(__file__).resolve().parent
SESSION_FILE = BB_DIR / "session.json"
COURSES_FILE = BB_DIR / "courses.json"
CREDS_FILE = BB_DIR / "creds.txt"
STRUCTURE_FILE = BB_DIR / "structure.json"


# ── Session / Auth ─────────────────────────────────────────────────────────

def load_session():
    """Load BB session. Returns (raw_dict, playwright_list)."""
    with open(SESSION_FILE) as f:
        raw = json.load(f)
    if isinstance(raw, list):
        return raw, raw
    pw = [{"name": k, "value": v, "domain": "bb.sustech.edu.cn", "path": "/"}
          for k, v in raw.items()]
    return raw, pw


def check_session():
    """Check if BB session is valid. Returns (bool, reason)."""
    try:
        raw, pw = load_session()
    except FileNotFoundError:
        return False, "No session. Run: python3 bb.py login"
    except Exception as e:
        return False, f"Session corrupt: {e}"

    try:
        s = requests.Session()
        for c in pw:
            s.cookies.set(c['name'], c['value'], domain=c['domain'], path=c['path'])
        r = s.get(BB_BASE + "/webapps/portal/execute/tabs/tabAction?tab_tab_group_id=_1_1",
                   headers={"Accept": "text/html"}, timeout=10, allow_redirects=False)
        if r.status_code in (302, 303):
            loc = r.headers.get("Location", "")
            if "cas.sustech.edu.cn" in loc or "login" in loc.lower():
                return False, "Session expired. Run: python3 bb.py refresh"
        return True, ""
    except Exception as e:
        return False, f"Could not reach BB: {e}"


def ensure_session():
    """Ensure session is valid, auto-refresh if expired. Returns (bool, reason)."""
    ok, reason = check_session()
    if ok:
        return True, ""
    # Try refresh
    if refresh():
        return True, ""
    return False, "Session invalid. Run: python3 bb.py login"


def refresh():
    """Re-authenticate via CAS+requests. Returns True on success."""
    try:
        with open(CREDS_FILE) as f:
            username, password = f.read().strip().split(':')
    except Exception as e:
        print(f"❌ Cannot read creds: {e}"); return False

    s = requests.Session()
    s.headers['User-Agent'] = 'Mozilla/5.0'
    r = s.get(CAS_URL, timeout=10)
    execution = re.search(r'name="execution" value="([^"]+)"', r.text)
    if not execution:
        print("FAIL: no execution token"); return False

    r = s.post(CAS_URL, data={
        "username": username, "password": password,
        "execution": execution.group(1), "_eventId": "submit",
        "submit": "\u63d0\u4ea4",   # "提交" in unicode
    }, allow_redirects=False, timeout=10)

    if r.status_code not in (302, 303):
        print(f"FAIL: {r.status_code} {r.text[:100]}"); return False
    loc = r.headers.get("Location", "")
    if loc.startswith("https://cas.sustech.edu.cn"):
        print(f"FAIL: wrong credentials"); return False

    # Follow the ticket redirect to BB
    r = s.get(loc, timeout=10)

    cookies = {c.name: c.value for c in s.cookies}
    if not cookies:
        print("FAIL: no cookies received"); return False

    with open(SESSION_FILE, 'w') as f:
        json.dump(cookies, f)

    # Reset cached course data — these are session-scoped
    for cache_file in (COURSES_FILE, STRUCTURE_FILE):
        if cache_file.exists():
            cache_file.unlink()

    print(f"✅ Session saved ({len(cookies)} cookies: {list(cookies.keys())})")
    return True


def login():
    """Headless Playwright login for manual CAS login.
    Opens browser so user can log in manually, then waits for redirect to BB."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto(CAS_URL, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(1000)
        print("Browser opened — log in manually via CAS.")
        print("Waiting for redirect to Blackboard...")
        try:
            page.wait_for_url("**/bb.sustech.edu.cn**", timeout=0)
        except Exception:
            pass
        page.wait_for_timeout(2000)
        cookies = ctx.cookies()
        cookie_map = {c['name']: c['value'] for c in cookies}
        with open(SESSION_FILE, 'w') as f:
            json.dump(cookie_map, f)

        # Reset cached course data — these are session-scoped
        for cache_file in (COURSES_FILE, STRUCTURE_FILE):
            if cache_file.exists():
                cache_file.unlink()

        print(f"✅ Session saved ({len(cookie_map)} cookies): {list(cookie_map.keys())}")


# ── Slugify ─────────────────────────────────────────────────────────────

def slugify(name, keep_extension=True):
    """Safe filename."""
    if keep_extension and '.' in name:
        parent, basename = os.path.split(name)
        if basename.count('.') >= 1:
            name_part, ext = basename.rsplit('.', 1)
            safe = re.sub(r'[\\/:*?"<>|\s]', '_', name_part).strip()[:80]
            return f"{safe}.{ext}"
    return re.sub(r'[\\/:*?"<>|]', '_', name).strip()[:80]


# ── CLI ─────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2 or sys.argv[1] == "check":
        ok, reason = check_session()
        print("✅ Session valid" if ok else f"❌ {reason}")
        return
    cmd = sys.argv[1]
    if cmd == "login": login()
    elif cmd == "refresh": sys.exit(0 if refresh() else 1)
    else: print(f"Usage: python3 session.py [check|login|refresh]")


if __name__ == "__main__":
    main()