#!/usr/bin/env python3
"""
BB Full Structure Scraper
- Playwright for sidebar (JS-rendered)
- Parallel content fetch via ThreadPoolExecutor
- Fixed section detection
"""
import sys, json, re
from playwright.sync_api import sync_playwright
from concurrent.futures import ThreadPoolExecutor, as_completed

SESSION_FILE = "/Users/dumix/.openclaw/workspace/bb_session.json"
BASE = "https://bb.sustech.edu.cn"
PORTAL = f"{BASE}/webapps/portal/execute/tabs/tabAction?tab_tab_group_id=_1_1"
COOKIES = json.load(open(SESSION_FILE))
SKIP_NAMES = ['大学物理', '高等数学', '微积分', '线性代数', 'calculus', 'linear algebra']

def clean_text(text):
    text = re.sub(r'跳到内容.*?(?=\n)', '', text, flags=re.DOTALL)
    text = re.sub(r'Skip To Content.*?(?=\n)', '', text, flags=re.DOTALL)
    text = re.sub(r'Open Quick Links.*?(?=\n)', '', text, flags=re.DOTALL)
    text = re.sub(r'Quick Links.*?(?=\n)', '', text, flags=re.DOTALL)
    text = re.sub(r'隐私、Cookie.*?确定\s*', '', text, flags=re.DOTALL)
    text = re.sub(r' Blackboard.*', '', text)
    text = re.sub(r'全局菜单.*?课程\s*\n', '\n', text, flags=re.DOTALL)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def fetch_content(href):
    """Fetch content preview for one item via Playwright."""
    result = {'href': href, 'content_preview': ''}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
            )
            for name, value in COOKIES.items():
                domain = 'bb.sustech.edu.cn' if name in ('JSESSIONID','DISSESSION','s_session_id','CdnSignedValidation','TGC') else 'cas.sustech.edu.cn'
                path = '/' if domain == 'bb.sustech.edu.cn' else '/cas'
                try:
                    ctx.add_cookies([{'name': name, 'value': value, 'domain': domain, 'path': path}])
                except Exception:
                    pass
            page = ctx.new_page()
            page.goto(href, timeout=20000)
            page.wait_for_timeout(3000)
            for _ in range(3):
                try:
                    page.click('text="确定"', timeout=1000)
                    page.wait_for_timeout(300)
                except Exception:
                    break
            text = page.inner_text('body')
            text = clean_text(text)
            for marker in ['\nContent\n', '\n内容\n', 'Content\n\n', '内容\n\n']:
                idx = text.find(marker)
                if idx > -1:
                    text = text[idx + len(marker):]
                    break
            result['content_preview'] = text[:2000]
            browser.close()
    except Exception as e:
        result['content_preview'] = f'[ERROR: {e}]'
    return result


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(
        user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    )
    for name, value in COOKIES.items():
        domain = 'bb.sustech.edu.cn' if name in ('JSESSIONID','DISSESSION','s_session_id','CdnSignedValidation','TGC') else 'cas.sustech.edu.cn'
        path = '/' if domain == 'bb.sustech.edu.cn' else '/cas'
        try:
            ctx.add_cookies([{'name': name, 'value': value, 'domain': domain, 'path': path}])
        except Exception:
            pass

    page = ctx.new_page()
    page.goto(PORTAL, timeout=20000)
    page.wait_for_timeout(4000)
    try:
        page.click('text="确定"', timeout=2000)
        page.wait_for_timeout(1000)
    except Exception:
        pass

    if 'login' in page.url.lower():
        print("SESSION EXPIRED", file=sys.stderr)
        sys.exit(1)

    # Get course list
    raw_links = page.evaluate('''
() => {
    const seen = new Set();
    const results = [];
    document.querySelectorAll('a[href*="courseMain"], a[href*="launcher?type=Course"]').forEach(l => {
        if (l.href && l.textContent.trim().length > 2 && !seen.has(l.href)) {
            seen.add(l.href);
            results.push({href: l.href, text: l.textContent.trim().slice(0, 80)});
        }
    });
    return results;
}
''')

    courses = []
    for cl in raw_links:
        m = re.search(r'course_id=([^&]+)', cl['href'])
        if not m: m = re.search(r'launcher\?type=Course&id=([^&]+)', cl['href'])
        cid = m.group(1) if m else ''
        name = re.sub(r'^→\s*|^《|》$', '', cl['text'].strip())
        name = re.sub(r'\s*\(?\d{4}[-/]\d{1,2}\)?\s*$', '', name).strip()
        if cid and name and not any(s.lower() in name.lower() for s in SKIP_NAMES):
            courses.append({'id': cid, 'name': name})

    print(f"Courses: {len(courses)}", file=sys.stderr)

    # Get sidebar for each course
    all_items = []
    for course in courses:
        cid = course['id']
        course_url = f"{BASE}/webapps/blackboard/execute/launcher?type=Course&id={cid}&url="
        page.goto(course_url, timeout=20000)
        page.wait_for_timeout(3000)
        try:
            page.click('text="确定"', timeout=1500)
            page.wait_for_timeout(500)
        except Exception:
            pass

        sidebar_data = page.evaluate('''
() => {
    const results = [];

    // Find section headers — BB uses various markers
    const headerSelectors = '.courseMenuGroupHeader, h3.courseMenuHeading, .sectionTitle, .courseMenuHeading';
    const headers = {};
    document.querySelectorAll(headerSelectors).forEach(h => {
        const t = h.textContent.trim();
        if (t) headers[t] = t;
    });

    // Walk all sidebar list items with content_id links
    // Use the main course menu container
    const menu = document.querySelector('#modules_list, .courseMenuBBbs, #course-menu, .courseMenuModule');
    if (!menu) {
        // Fallback: all links with content_id
        document.querySelectorAll('a[href*="content_id="]').forEach(a => {
            const cidMatch = a.href.match(/content_id=([^&\\s]+)/);
            const text = a.textContent.trim();
            if (cidMatch && text.length > 1) {
                results.push({section: 'Other', title: text.slice(0, 100), cid: cidMatch[1], href: a.href});
            }
        });
        return results;
    }

    // For each header, collect following items until next header
    const allHeaders = Array.from(menu.querySelectorAll(headerSelectors.join(',')));
    const allItems = Array.from(menu.querySelectorAll('li'));

    // Map each <li> to its nearest preceding header
    allItems.forEach(li => {
        const link = li.querySelector('a[href*="content_id="]');
        if (!link) return;
        const cidMatch = link.href.match(/content_id=([^&\\s]+)/);
        if (!cidMatch) return;
        const cid = cidMatch[1];
        const text = link.textContent.trim();
        if (!text || text.length < 2) return;

        // Find nearest preceding header
        let section = 'Other';
        const liRect = li.getBoundingClientRect ? li.getBoundingClientRect().top : 999999;
        for (const h of allHeaders) {
            const hRect = h.getBoundingClientRect ? h.getBoundingClientRect().top : 0;
            if (hRect < liRect) {
                section = h.textContent.trim().slice(0, 60);
                break;
            }
        }
        section = section.replace(/^—\s*/, '').replace(/\s*—$/, '').trim() || 'Other';

        // Clean title
        const title = text.replace(/^—\s*/, '').slice(0, 100);

        results.push({section, title, cid, href: link.href});
    });

    // Deduplicate
    const seen = new Set();
    return results.filter(r => {
        if (seen.has(r.cid)) return false;
        seen.add(r.cid);
        return true;
    });
}
''')

        for item in sidebar_data:
            all_items.append({
                'course': course['name'],
                'course_id': cid,
                'section': item['section'],
                'title': item['title'],
                'cid': item['cid'],
                'href': item['href'],
            })

        print(f"  {course['name']}: {len(sidebar_data)} items", file=sys.stderr)

    print(f"Total items: {len(all_items)}", file=sys.stderr)

    # Keep Playwright open for later use (content fetched in parallel separately)
    browser.close()


# Phase 2: Fetch content for ALL items in parallel
print("Fetching content (parallel, 8 workers)...", file=sys.stderr)
content_map = {}
with ThreadPoolExecutor(max_workers=8) as ex:
    futures = {ex.submit(fetch_content, item['href']): item for item in all_items}
    done = 0
    for future in as_completed(futures):
        item = futures[future]
        result = future.result()
        content_map[item['href']] = result['content_preview']
        done += 1
        sys.stderr.write(f"\r  {done}/{len(all_items)}")
        sys.stderr.flush()

for item in all_items:
    item['content_preview'] = content_map.get(item['href'], '')

print(file=sys.stderr)

# Save
output = {
    'scraped_at': str(__import__('datetime').datetime.now()),
    'courses': [{'id': c['id'], 'name': c['name']} for c in courses],
    'items': all_items,
}
out = '/tmp/bb_structure.json'
with open(out, 'w', encoding='utf-8') as f:
    json.dump(output, f, indent=2, ensure_ascii=False)
print(f"Saved: {out}", file=sys.stderr)

# Print EAP Week 6 as sample
for item in all_items:
    if 'Week 6' in item['title'] and item['course'] == 'EAP Spring 2026':
        print(f"\n=== EAP Week 6 ===")
        print(f"Section: {item['section']}")
        print(f"Title: {item['title']}")
        print(f"Content:\n{item['content_preview'][:500]}")
