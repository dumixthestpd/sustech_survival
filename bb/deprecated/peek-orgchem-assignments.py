#!/usr/bin/env python3
import json, re
from playwright.sync_api import sync_playwright

cookies = json.load(open('/Users/dumix/.openclaw/workspace/bb_session.json'))
BASE = "https://bb.sustech.edu.cn"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
    )
    for name, value in cookies.items():
        domain = 'bb.sustech.edu.cn' if name in ('JSESSIONID', 'DISSESSION', 's_session_id', 'CdnSignedValidation', 'TGC') else 'cas.sustech.edu.cn'
        path = '/' if domain == 'bb.sustech.edu.cn' else '/cas'
        try:
            context.add_cookies([{'name': name, 'value': value, 'domain': domain, 'path': path}])
        except Exception:
            pass
    page = context.new_page()

    # First visit course home to establish session
    page.goto(f"{BASE}/webapps/blackboard/execute/launcher?type=Course&id=_8328_1&url=", timeout=20000)
    page.wait_for_timeout(3000)
    try:
        page.click('text="确定"', timeout=2000)
    except:
        pass

    # Now visit Assignments page
    page.goto(f"{BASE}/webapps/blackboard/content/listContent.jsp?course_id=_8328_1&content_id=_610793_1&mode=reset", timeout=20000)
    page.wait_for_timeout(4000)
    try:
        page.click('text="确定"', timeout=2000)
        page.wait_for_timeout(1000)
    except:
        pass

    print("URL:", page.url)
    text = page.inner_text('body')
    # Strip privacy notice
    text = re.sub(r'隐私、Cookie.*?确定\s*', '', text, flags=re.DOTALL)
    print(text.strip()[:3000])
    browser.close()
