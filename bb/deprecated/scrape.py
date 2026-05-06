#!/usr/bin/env python3
"""
BB Full Structure Scraper
- Phase 1: Discover courses from "我的课程" section, then extract sections + items per course
- Phase 2: Parallel fetch_content() for each content item

IMPORTANT: Only scrape "我的课程" (enrolled courses).
The "系统推荐课程" section contains suggested courses that are NOT dumix's.

Session file: ~/.openclaw/workspace/session.json
  Format: dict of {cookie_name: cookie_value}

Known course IDs (2026 Spring):
  _8343_1 — Physical Chemistry Experiments SE03
  _8053_1 — CAD与工程制图
  _8157_1 — EAP Spring 2026
  (more in my courses section)
"""
import json, os, sys, re, argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("ERROR: playwright not installed. Run: pip install playwright && playwright install chromium")
    sys.exit(1)

# ─── Config ────────────────────────────────────────────────────────────────────
SESSION_FILE = Path(__file__).parent / "session.json"
OUTPUT_FILE  = Path(__file__).parent / "structure.json"
BB_BASE      = "https://bb.sustech.edu.cn"
MAX_WORKERS  = 8


def load_cookies():
    """Load cookies. Returns list of dicts for Playwright add_cookies()."""
    with open(SESSION_FILE) as f:
        raw = json.load(f)
    if isinstance(raw, list):
        return raw
    return [{"name": k, "value": v, "domain": "bb.sustech.edu.cn", "path": "/"}
            for k, v in raw.items()]


def goto_page(page, url):
    """Navigate to BB page and wait for content to render."""
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    try:
        page.wait_for_selector(
            "#contentArea, #content_listContainer, .content_list, "
            "a[href*='content_id'], a[href*='launcher']",
            timeout=10000,
        )
    except Exception:
        pass
    page.wait_for_timeout(1500)


def phase1_discover_courses():
    """Find all enrolled courses from '我的课程' section on BB home."""
    cookies = load_cookies()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context()
        ctx.add_cookies(cookies)
        page = ctx.new_page()

        goto_page(page, f"{BB_BASE}/")

        # ── Find "我的课程" section and extract course links ─────────────────
        # BB renders "我的课程" as a section heading, followed by a UL of courses
        # Each course link: /webapps/blackboard/execute/launcher?type=Course&id=_XXXX_1
        courses = []
        seen_ids = set()

        # Navigate through "我的课程" section
        # The section heading "我的课程" appears as text, followed by course links
        # Best approach: find ALL course links on the page, filter to only "我的课程" ones
        #
        # Strategy: get the BB home HTML, find the "我的课程" section,
        # then extract course links from that region only.

        # Check if "我的课程" is in the page
        body_text = page.evaluate('document.body.innerText')
        if '我的课程' not in body_text:
            print("WARNING: '我的课程' not found on page")
        else:
            print("Found '我的课程' section")

        # Get all course links with their region context
        # BB uses /execute/launcher?type=Course&id=_XXXX_1 for enrolled courses
        # It also shows system-recommended courses in a separate section
        for a in page.query_selector_all('a'):
            href = a.get_attribute('href') or ''
            if 'type=Course&id=' not in href:
                continue
            text = (a.inner_text() or '').strip()
            if not text:
                continue
            # Extract the course ID from id= parameter
            m = re.search(r'id=(_(\d+)_1)', href)
            if not m:
                continue
            cid = m.group(2)  # just the numeric part e.g. "8343"
            full_id = m.group(1)  # e.g. "_8343_1"
            if cid in seen_ids:
                continue
            seen_ids.add(cid)

            # Check if this course link is in "我的课程" or "系统推荐"
            # Get the parent section context by walking up DOM
            section_label = 'unknown'
            try:
                parent = a.evaluate_handle(
                    'el => el.closest("section, div[role], .portlet, li")'
                )
                if parent:
                    parent_html = parent.evaluate('e => e.innerHTML')
                    # If the parent contains "系统推荐" it's noise
                    if '系统推荐' in parent_html or 'suggest' in parent_html.lower():
                        section_label = '系统推荐(ignore)'
                    elif '我的课程' in parent_html or 'courseListing' in parent_html:
                        section_label = '我的课程'
            except Exception:
                pass

            print(f"  [{section_label}] {cid}: {text[:60]}")
            if section_label != '系统推荐(ignore)':
                courses.append({'id': cid, 'title': text, 'full_id': full_id})

        browser.close()
        return courses


def phase1_get_course_tree(course):
    """
    Parse the BB course sidebar (#courseMenuPalette_contents) which has:
      LI.divider → <hr>, skip
      LI.subhead → section header (H3 title = section name)
      LI.clearfix → item link (a with content_id in href)
    """
    cookies = load_cookies()
    cid = course['id']

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context()
        ctx.add_cookies(cookies)
        page = ctx.new_page()

        home_url = (f"{BB_BASE}/webapps/blackboard/content/listContent.jsp"
                    f"?course_id=_{cid}_1&content_id=_{cid}_1")
        goto_page(page, home_url)

        sections = []
        current_section = None
        seen_item_ids = set()

        # Parse the sidebar UL
        menu = page.query_selector('#courseMenuPalette_contents')
        if not menu:
            print("WARNING: #courseMenuPalette_contents not found, falling back to old method")
            return phase1_get_course_tree_fallback(page, cid)

        def make_section(name):
            return {'section_id': None, 'title': name, 'href': None, 'items': []}

        # Known tool_id → real URL mappings
        tool_url_map = {
            '_136_1': f'{BB_BASE}/webapps/blackboard/execute/announcement?method=search&context=course_entry&course_id=_{cid}_1&handle=announcements_entry&mode=view',
            '_156_1': f'{BB_BASE}/webapps/blackboard/execute/gradebook?course_id=_{cid}_1',  # My Grades
            '_158_1': f'{BB_BASE}/webapps/blackboard/execute/help?course_id=_{cid}_1',       # Help
        }

        for li in menu.query_selector_all('li'):
            cls = li.get_attribute('class') or ''

            if 'divider' in cls:
                continue
            elif 'subhead' in cls:
                h3 = li.query_selector('h3 span')
                section_name = h3.inner_text().strip() if h3 else 'Untitled'
                current_section = make_section(section_name)
                sections.append(current_section)
            elif 'clearfix' in cls:
                a = li.query_selector('a')
                if not a:
                    continue
                href = a.get_attribute('href') or ''
                title = (a.inner_text() or '').strip()
                if not title:
                    continue

                # Try content_id first, then tool_id (for launchLink items)
                m = re.search(r'content_id=_(\d+)_', href)
                if m:
                    item_id = m.group(1)
                else:
                    m = re.search(r'tool_id=(_\d+_1)', href)
                    if not m:
                        continue
                    item_id = 'tool' + m.group(1)
                if item_id in seen_item_ids:
                    continue
                seen_item_ids.add(item_id)

                # No section headers found at all — create a default one
                if current_section is None:
                    current_section = make_section('Main')
                    sections.append(current_section)

                if 'listContent' in href:
                    link_type = 'content_page'
                    target_href = urljoin(BB_BASE, href)
                elif 'launchLink' in href:
                    tool_key = m.group(1) if m else None
                    if tool_key and tool_key in tool_url_map:
                        link_type = 'tool_page'
                        target_href = tool_url_map[tool_key]
                    else:
                        link_type = 'tool_link'
                        target_href = urljoin(BB_BASE, href)
                else:
                    link_type = 'other'
                    target_href = urljoin(BB_BASE, href)

                current_section['items'].append({
                    'item_id': item_id,
                    'title': title,
                    'href': target_href,
                    'type': link_type,
                })

        browser.close()
        return sections


def phase1_get_course_tree_fallback(page, cid):
    """Fallback if sidebar not found — old flat link extraction."""
    sections = []
    seen_section_ids = set()
    seen_item_ids = set()

    def extract_links():
        links = []
        for a in page.query_selector_all('a'):
            href = a.get_attribute('href') or ''
            text = (a.inner_text() or '').strip()
            if text and 'content_id=' in href and 'listContent' in href:
                links.append((None, href, text))
        for frame in page.frames:
            try:
                for a in frame.query_selector_all('a'):
                    href = a.get_attribute('href') or ''
                    text = (a.inner_text() or '').strip()
                    if text and 'content_id=' in href:
                        links.append((None, href, text))
            except Exception:
                pass
        return links

    for _, href, text in extract_links():
        m = re.search(r'content_id=_(\d+)_', href)
        if not m:
            continue
        content_id = m.group(1)
        if content_id in seen_section_ids:
            continue
        seen_section_ids.add(content_id)
        if content_id == cid:
            continue
        sections.append({
            'section_id': content_id,
            'title': text,
            'href': urljoin(BB_BASE, href),
            'items': [],
        })

    for section in sections:
        page.goto(section['href'], wait_until='domcontentloaded')
        page.wait_for_timeout(1000)
        for _, href, text in extract_links():
            m = re.search(r'content_id=_(\d+)_', href)
            if not m:
                continue
            item_id = m.group(1)
            if item_id in seen_item_ids or item_id == section['section_id']:
                continue
            seen_item_ids.add(item_id)
            section['items'].append({
                'item_id': item_id,
                'title': text,
                'href': urljoin(BB_BASE, href),
            })

    return sections


def classify_link(href):
    """Classify a BB link URL into a semantic type.

    Returns: (type_label, is_attachment)
    - is_attachment: True means this link IS a downloadable file
    - is_attachment: False means this link leads to another page to crawl
    """
    if not href or href.startswith('javascript') or href == '#':
        return 'ignore', False
    if 'bbcswebdav' in href or '/download' in href or '&download=' in href:
        return 'file', True          # Direct file download
    if 'uploadAssignment' in href:
        return 'submission', False  # BB assignment submission form
    if 'gradebook' in href:
        return 'gradebook', False   # Grades page
    if 'inlineView' in href:
        return 'inline_view', False # Inline content preview
    if 'launchLink' in href:
        return 'tool_link', False   # Announcements etc. (not course content)
    if 'listContent' in href and 'content_id' in href:
        return 'content_page', False  # Another section or item page to crawl
    if 'content' in href:
        return 'bb_content', False    # Generic BB content
    if href.startswith('http'):
        return 'external', False
    return 'other', False


def fetch_content(course_id, item, cookies):
    """
    Fetch a BB content item page and extract text + attachment links.
    Each call gets its own browser (ThreadPool safe).
    """
    content_id = item['item_id']
    title = item['title']
    item_type = item.get('type', 'content_page')

    # For tool_page items (announcements, grades, etc.), href is already the real URL
    if item_type == 'tool_page':
        url = item['href']
    else:
        url = (f"{BB_BASE}/webapps/blackboard/content/listContent.jsp"
               f"?course_id=_{course_id}_1&content_id=_{content_id}_1")

    result = {
        'course_id': course_id,
        'section': '',
        'content_id': content_id,
        'title': title,
        'content': '',
        'attachments': [],
    }

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            ctx = browser.new_context()
            for name, value in cookies.items():
                domain = ('bb.sustech.edu.cn' if name in (
                    'JSESSIONID', 'DISSESSION', 's_session_id',
                    'CdnSignedValidation', 'TGC', 'LTI launch', 'LTI_LAUNCH',
                    'lti_auth', 'BbRouter', 'X-BlackboardAppsInst',
                ) else 'cas.sustech.edu.cn')
                ctx.add_cookies([{'name': name, 'value': value,
                                   'domain': domain, 'path': '/'}])

            page = ctx.new_page()
            page.goto(url, wait_until='domcontentloaded', timeout=30000)
            try:
                page.wait_for_selector(
                    '#content_listContainer, .content_list, #contentArea, main',
                    timeout=10000,
                )
            except Exception:
                pass
            page.wait_for_timeout(2000)

            area = page.query_selector(
                '#content_listContainer, .content_list, #contentArea, main, body'
            )
            if area:
                result['content'] = html_to_text(area.inner_html())

            # BB attachment links — classify every link first
            attachment_kinds = {'file': 0, 'inline_view': 0}
            for a in page.query_selector_all('a'):
                href = a.get_attribute('href') or ''
                name = (a.inner_text() or '').strip()
                kind, is_att = classify_link(href)
                if kind == 'ignore' or not name:
                    continue
                if is_att:
                    result['attachments'].append({
                        'name': name,
                        'href': urljoin(BB_BASE, href),
                        'type': kind,
                    })
                    attachment_kinds[kind] = attachment_kinds.get(kind, 0) + 1
                elif kind == 'content_page':
                    # Track linked sub-pages (nested sections) for info
                    result.setdefault('sub_pages', []).append({
                        'title': name,
                        'href': href,
                    })

            # Track what kinds of links were on this page
            result['link_types'] = {k: v for k, v in attachment_kinds.items() if v > 0}

            browser.close()
    except Exception as e:
        result['error'] = str(e)

    return result


def html_to_text(html):
    import re
    html = re.sub(r'(?is)<script[^>]*>.*?</script>', '', html)
    html = re.sub(r'(?is)<style[^>]*>.*?</style>', '', html)
    html = re.sub(r'<br\s*/?>', '\n', html)
    html = re.sub(r'</p>', '\n\n', html)
    html = re.sub(r'<[^>]+>', '', html)
    html = re.sub(r'[ \t]+', ' ', html)
    html = re.sub(r'\n{3,}', '\n\n', html)
    return html.strip()


# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="BB Structure Scraper")
    parser.add_argument('--course', help='Scrape only this course_id (numeric, e.g. 8343)')
    args = parser.parse_args()

    # Load cookies once
    with open(SESSION_FILE) as f:
        raw = json.load(f)
    cookies = raw if isinstance(raw, dict) else {c['name']: c['value'] for c in raw}

    print('=' * 60)
    print('Phase 1: Discovering courses from "我的课程"')
    print('=' * 60)
    courses = phase1_discover_courses()
    if not courses:
        print('No courses found. Is session still valid?')
        sys.exit(1)

    if args.course:
        courses = [c for c in courses if c['id'] == args.course]
        if not courses:
            print(f'Course {args.course} not found in enrolled courses.')
            sys.exit(1)

    print(f'\n{len(courses)} enrolled course(s) to scrape')

    # Build full structure
    all_courses = []
    for course in courses:
        cid = course['id']
        print(f'\n  [{cid}] {course["title"]}')
        sections = phase1_get_course_tree(course)
        for sec in sections:
            print(f'    Section: {sec["title"]} ({len(sec["items"])} items)')
        all_courses.append({
            'course_id': cid,
            'title': course['title'],
            'sections': sections,
        })

    # Flatten all items for Phase 2
    all_items = []
    for course in all_courses:
        for section in course['sections']:
            for item in section['items']:
                all_items.append({
                    'course_id': course['course_id'],
                    'section': section['title'],
                    'item_id': item['item_id'],
                    'title': item['title'],
                    'href': item['href'],
                    'type': item.get('type', 'content_page'),
                })

    print(f'\n{len(all_items)} total items across {len(all_courses)} courses')

    # Preflight
    if all_items:
        print('\nPreflight ...', end=' ', flush=True)
        sample = fetch_content(all_items[0]['course_id'], all_items[0], cookies)
        if sample.get('error'):
            print(f"FAILED — {sample['error']}")
            resp = input('Session may have expired. Run "bb login" to refresh. Continue? [y/N] ')
            if resp.lower() != 'y':
                sys.exit(1)
        else:
            print(f"OK — '{sample['title'][:50]}', {len(sample['attachments'])} attachments")

    if not all_items:
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            json.dump({'courses': all_courses, 'results': []}, f, ensure_ascii=False, indent=2)
        print(f'Done (no items) → {OUTPUT_FILE}')
        return

    # Phase 2: parallel fetch
    print(f'\n{"=" * 60}')
    print(f'Phase 2: Fetching {len(all_items)} items ({MAX_WORKERS} workers)')
    print(f'{"=" * 60}\n')

    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(fetch_content, item['course_id'], item, cookies): item
            for item in all_items
        }
        done = 0
        for future in as_completed(futures):
            done += 1
            result = future.result()
            results.append(result)
            tag = f"ERR: {result['error']}" if result.get('error') else f"{len(result['attachments'])} files"
            print(f'  [{done:3d}/{len(all_items)}] {tag:<18} {result["title"][:55]}', flush=True)

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump({'courses': all_courses, 'results': results}, f, ensure_ascii=False, indent=2)

    ok = sum(1 for r in results if not r.get('error'))
    print(f'\nDone: {ok}/{len(results)} OK → {OUTPUT_FILE}')


if __name__ == '__main__':
    main()
