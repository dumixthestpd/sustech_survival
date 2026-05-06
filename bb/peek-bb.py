#!/usr/bin/env python3
"""Peek at actual BB content pages."""
import sys, json, re
from playwright.sync_api import sync_playwright

SESSION_FILE = "/Users/dumix/.openclaw/workspace/bb_session.json"
COOKIES = json.load(open(SESSION_FILE))

def peek(url, label):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        for name, value in COOKIES.items():
            domain = 'bb.sustech.edu.cn' if name in ('JSESSIONID', 'DISSESSION', 's_session_id', 'CdnSignedValidation', 'TGC') else 'cas.sustech.edu.cn'
            path = '/' if domain == 'bb.sustech.edu.cn' else '/cas'
            try:
                context.add_cookies([{'name': name, 'value': value, 'domain': domain, 'path': path}])
            except Exception:
                pass
        page = context.new_page()
        page.goto(url, timeout=20000)
        page.wait_for_timeout(4000)
        text = page.inner_text('body')
        browser.close()
    print(f"\n{'#'*60}")
    print(f"# {label}")
    print(f"# URL: {url}")
    print(f"{'#'*60}")
    print(text[:4000])
    print("...")

BASE = "https://bb.sustech.edu.cn"

# PhysChem - Experimental arrangement
peek(f"{BASE}/webapps/blackboard/content/listContent.jsp?course_id=_8343_1&content_id=_611409_1&mode=reset",
     "PhysChem - Experimental arrangement")

# PhysChem - Experiment 1 report page
peek(f"{BASE}/webapps/blackboard/content/listContent.jsp?course_id=_8343_1&content_id=_611414_1&mode=reset",
     "PhysChem - Experiment 1 Report (Combustion)")

# OrgChem - Assignments container
peek(f"{BASE}/webapps/blackboard/content/listContent.jsp?course_id=_8328_1&content_id=_610793_1&mode=reset",
     "OrgChem - Assignments")

# EAP - Written Assignments
peek(f"{BASE}/webapps/blackboard/content/listContent.jsp?course_id=_8157_1&content_id=_598353_1&mode=reset",
     "EAP - Written Assignments")
