#!/usr/bin/env python3
"""
Explore BB course structure using Playwright with existing session.
Run with: /usr/bin/python3 explore-bb.py [course_name]
"""
import sys, json, re
from playwright.sync_api import sync_playwright

SESSION_FILE = "/Users/dumix/.openclaw/workspace/bb_session.json"
BB_PORTAL = "https://bb.sustech.edu.cn/webapps/portal/execute/tabs/tabAction?tab_tab_group_id=_1_1"

def load_session():
    with open(SESSION_FILE) as f:
        return json.load(f)

def explore_courses(cookies, target=None):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        for name, value in cookies.items():
            domain = 'bb.sustech.edu.cn' if name in ('JSESSIONID', 'DISSESSION', 's_session_id', 'CdnSignedValidation', 'TGC') else 'cas.sustech.edu.cn'
            path = '/' if domain == 'bb.sustech.edu.cn' else '/cas'
            try:
                context.add_cookies([{'name': name, 'value': value, 'domain': domain, 'path': path}])
            except Exception:
                pass
        page = context.new_page()
        page.goto(BB_PORTAL, timeout=15000)
        page.wait_for_timeout(4000)
        if 'login' in page.url.lower():
            print("SESSION EXPIRED")
            browser.close()
            return
        print(f"Logged in. URL: {page.url}\n")

        # Get course list
        course_links = page.evaluate('''
() => {
    const links = document.querySelectorAll('a[href*="courseMain"], a[href*="launcher?type=Course"]');
    const seen = new Set();
    const results = [];
    for (const l of links) {
        if (l.href && l.textContent.trim().length > 2 && !seen.has(l.href)) {
            seen.add(l.href);
            results.push({href: l.href, text: l.textContent.trim().slice(0, 80)});
        }
    }
    return results;
}
''')
        courses = []
        for cl in course_links:
            m = re.search(r'course_id=([^&]+)', cl['href'])
            if not m: m = re.search(r'launcher\?type=Course&id=([^&]+)', cl['href'])
            cid = m.group(1) if m else ''
            name = re.sub(r'^→\s*|^《|》$', '', cl['text'].strip())
            name = re.sub(r'\s*\(?\d{4}[-/]\d{1,2}\)?\s*$', '', name).strip()
            skip = ['大学物理', '高等数学', '微积分', '线性代数', 'calculus', 'linear algebra']
            if any(s.lower() in name.lower() for s in skip):
                continue
            if cid and name:
                courses.append({'id': cid, 'name': name, 'href': cl['href']})

        for c in courses:
            if target and target.lower() not in c['name'].lower():
                continue
            print(f"\n{'='*60}")
            print(f"COURSE: {c['name']} ({c['id']})")
            print(f"{'='*60}")

            # Navigate to course home
            course_url = f"https://bb.sustech.edu.cn/webapps/blackboard/execute/launcher?type=Course&id={c['id']}&url="
            page.goto(course_url, timeout=15000)
            page.wait_for_timeout(3000)

            # Get ALL sidebar links
            sidebar_items = page.evaluate('''
() => {
    const items = [];
    const lis = document.querySelectorAll('#modules_list li, .moduleItem, .courseMenuBBbs .item, div[id^="paletteItem"]');
    for (const li of lis) {
        const link = li.querySelector('a');
        const span = li.querySelector('span[itemname], span.title, span');
        if (link) {
            const href = link.href || '';
            const text = link.textContent.trim();
            const title = link.getAttribute('title') || text;
            if (href && text.length > 1) {
                const cidMatch = href.match(/content_id=([^&\s]+)/);
                const cid = cidMatch ? cidMatch[1] : '';
                items.push({text, title, href, cid});
            }
        }
    }
    // Fallback: get by onclick or direct navigation links
    if (items.length === 0) {
        const allLinks = document.querySelectorAll('a');
        for (const l of allLinks) {
            if (l.href && l.href.includes('content_id=') && l.textContent.trim().length > 2) {
                const href = l.href;
                const text = l.textContent.trim().slice(0, 100);
                const cidMatch = href.match(/content_id=([^&\s]+)/);
                const cid = cidMatch ? cidMatch[1] : '';
                items.push({text, title: text, href, cid});
            }
        }
    }
    return items;
}
''')
            print(f"SIDEBAR ITEMS ({len(sidebar_items)}):")
            for item in sidebar_items:
                print(f"  [{item['cid']}] {item['text'][:80]}")
                if item['href']:
                    print(f"      href: {item['href'][:100]}")

            # Try to get content page for each item that looks like an assignment
            assign_section = None
            for item in sidebar_items:
                text_lower = item['text'].lower()
                if any(k in text_lower for k in ['assignment', '作业', 'report', '实验报告', 'due', 'deadline', 'plagiarism', 'bibliography']):
                    assign_section = item
                    break

            if assign_section:
                print(f"\n  DEEP-DIVING: {assign_section['text'][:80]}")
                page.goto(assign_section['href'], timeout=15000)
                page.wait_for_timeout(3000)
                body_text = page.inner_text('body')
                # Print first 2000 chars
                print(f"  CONTENT:\n{body_text[:2000]}")
                print(f"  ...")

        browser.close()

if __name__ == '__main__':
    cookies = load_session()
    target = ' '.join(sys.argv[1:]) if len(sys.argv) > 1 else None
    explore_courses(cookies, target)
