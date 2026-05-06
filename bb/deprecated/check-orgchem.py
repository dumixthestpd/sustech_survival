#!/usr/bin/env python3
"""Check OrgChem sidebar structure carefully."""
import sys, json, re
from playwright.sync_api import sync_playwright

SESSION_FILE = "/Users/dumix/.openclaw/workspace/bb_session.json"
COOKIES = json.load(open(SESSION_FILE))

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

    # Go to OrgChem course home
    page.goto("https://bb.sustech.edu.cn/webapps/blackboard/execute/launcher?type=Course&id=_8328_1&url=", timeout=20000)
    page.wait_for_timeout(4000)

    # Try to dismiss cookie popup if present
    try:
        page.click('text="确定"', timeout=2000)
        page.wait_for_timeout(500)
    except Exception:
        pass

    print("URL:", page.url)
    print()

    # Get all links with content_id
    links = page.evaluate('''
() => {
    const results = [];
    document.querySelectorAll('a').forEach(a => {
        if (a.href && a.href.includes('content_id=')) {
            const cid = a.href.match(/content_id=([^&]+)/);
            results.push({
                text: a.textContent.trim().slice(0, 100),
                href: a.href,
                cid: cid ? cid[1] : '',
                visible: a.offsetParent !== null
            });
        }
    });
    return results;
}
''')
    print(f"All links with content_id on page ({len(links)}):")
    for l in links:
        print(f"  [{l['cid']}] ({'visible' if l['visible'] else 'hidden'}) {l['text']}")
        print(f"      {l['href'][:120]}")

    browser.close()
