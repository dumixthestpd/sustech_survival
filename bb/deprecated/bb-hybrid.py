#!/usr/bin/env python3
"""
SUSTech BB Hybrid Scraper
Phase 1: requests for login + sidebar/course structure (fast)
Phase 2: Playwright for JS-rendered content pages (accurate)

Cookie flow: Phase 1 logs in via requests, saves cookies.
Phase 2 reuses those cookies in Playwright — no CAS needed during Phase 2.

Usage:
    python3 bb-hybrid.py                  # Full scan all courses
    python3 bb-hybrid.py <course>        # Specific course
    python3 bb-hybrid.py --phase1        # Login + structure only
    python3 bb-hybrid.py --phase2        # JS content extraction only
    python3 bb-hybrid.py --list           # List cached courses
"""

import sys, os, re, json, time
import requests
from playwright.sync_api import sync_playwright

BB_PORTAL = "https://bb.sustech.edu.cn/webapps/portal/execute/tabs/tabAction?tab_tab_group_id=_1_1"
CAS_URL = "https://cas.sustech.edu.cn/cas/login?service=https://bb.sustech.edu.cn/webapps/bb-sso-BBLEARN/index.jsp"
CREDS_FILE = "/Users/dumix/.openclaw/workspace/credentials.txt"
SESSION_FILE = "/Users/dumix/.openclaw/workspace/bb_session.json"
CACHE_FILE = "/tmp/bb_scan_cache.json"


def load_creds():
    with open(CREDS_FILE) as f:
        c = f.read().strip().split(':')
    return c[0], c[1]


def dedup_cookies(jar):
    seen = {}
    for k, v in jar.items():
        if k not in seen:
            seen[k] = v
    return seen


def save_session(cookies_dict):
    with open(SESSION_FILE, 'w') as f:
        json.dump(cookies_dict, f, indent=2)


def load_session():
    if not os.path.exists(SESSION_FILE):
        return None
    try:
        with open(SESSION_FILE) as f:
            data = f.read().strip()
        if not data:
            return None
        return json.loads(data)
    except (json.JSONDecodeError, IOError):
        return None


def login_requests():
    """Login via requests. Returns cookie dict. Fresh session each attempt."""
    username, password = load_creds()
    for attempt in range(3):
        s = requests.Session()
        s.headers['User-Agent'] = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        try:
            r = s.get(CAS_URL, timeout=10)
            if r.status_code != 200 or not r.text or 'execution' not in r.text:
                time.sleep(2)
                continue
            execution = re.search(r'name="execution" value="([^"]+)"', r.text).group(1)
            r = s.post(CAS_URL, data={
                'username': username, 'password': password,
                'execution': execution, '_eventId': 'submit'
            }, allow_redirects=False, timeout=10)
            if r.status_code != 302 or 'Location' not in r.headers:
                time.sleep(2)
                continue
            redirect_url = r.headers['Location']
            r = s.get(redirect_url, allow_redirects=False, timeout=10)
            r = s.get('https://bb.sustech.edu.cn/webapps/bb-sso-BBLEARN/index.jsp', allow_redirects=True, timeout=10)
            cookies = dedup_cookies(dict(s.cookies))
            print(f"[Phase1] Logged in. Cookies: {list(cookies.keys())}")
            return cookies
        except Exception as e:
            time.sleep(2)
            continue
    raise Exception("Login failed")


def get_courses_via_playwright(cookies=None):
    cookies = cookies or load_session()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        if cookies:
            for name, value in cookies.items():
                domain = 'bb.sustech.edu.cn' if name in ('JSESSIONID', 'DISSESSION', 's_session_id', 'CdnSignedValidation', 'TGC') else 'cas.sustech.edu.cn'
                path = '/' if domain == 'bb.sustech.edu.cn' else '/cas'
                try:
                    context.add_cookies([{'name': name, 'value': value, 'domain': domain, 'path': path}])
                except Exception:
                    pass
        page = context.new_page()
        page.goto(BB_PORTAL, timeout=15000)
        page.wait_for_timeout(5000)
        if 'login' in page.url.lower():
            browser.close()
            return []
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
        browser.close()
        courses = []
        for cl in course_links:
            m = re.search(r'course_id=([^&]+)', cl['href'])
            if not m:
                m = re.search(r'launcher\?type=Course&id=([^&]+)', cl['href'])
            cid = m.group(1) if m else ''
            name = re.sub(r'^→\s*|^《|》$', '', cl['text'].strip())
            name = re.sub(r'\s*\(?\d{4}[-/]\d{1,2}\)?\s*$', '', name).strip()
            if cid and name:
                # Only include if it has a real sidebar (enrolled course, not general recording)
                # Skip courses whose names suggest they're catch-all / not actually enrolled
                skip_names = ['大学物理', '高等数学', 'college physics', 'higher mathematics', 
                            '微积分', '线性代数', 'calculus', 'linear algebra']
                if any(sn.lower() in name.lower() for sn in skip_names):
                    continue
                courses.append({'id': cid, 'name': name, 'href': cl['href']})
        return courses


def get_sidebar_via_requests(session_cookies, course_id):
    url = f'https://bb.sustech.edu.cn/webapps/blackboard/execute/launcher?type=Course&id={course_id}&url='
    jar = requests.cookies.RequestsCookieJar()
    for k, v in session_cookies.items():
        jar.set(k, v, domain='bb.sustech.edu.cn', path='/')
    r = requests.get(url, cookies=jar, timeout=10)
    item_blocks = re.findall(r'<li id="(paletteItem:[^"]+)"[^>]*>(.*?)</li>', r.text, re.DOTALL)
    sidebar = {}
    current = 'Other'
    section_kw = ['Course Materials', 'Assignments', 'About', 'Tools', 'Help', 'Week', 'Resources', 'Groups', '课程', '材料', 'Feedback']
    for _, block in item_blocks:
        m = re.search(r'<span title="([^"]+)"', block)
        title = re.sub(r'&#\d+;', "'", m.group(1) if m else '').strip()
        cid_m = re.search(r'content_id=([^&\s"]+)', block)
        cid = cid_m.group(1) if cid_m else ''
        if not cid and any(kw in title for kw in section_kw):
            current = title
            continue
        if cid and len(title) > 1:
            sidebar.setdefault(current, []).append({'Title': title, 'cid': cid, 'course_id': course_id})
    return sidebar


def is_assignment(title, section):
    """Check if a sidebar item is a real graded homework/task with a deadline."""
    title_l = title.lower()
    section_l = section.lower()
    
    # Hard skip - these are definitely NOT assignments
    skip = [
        'syllabus', 'course outline', 'instructor', 'schedule', 'about', 'help', 'groups',
        'tools', '资源', '教材', 'textbook', 'safety', '通知', '公告', '评分标准',
        '评分', 'course introduction', 'week', '课程', '课程内容', '课件', '实验',
        'Q&A', 'introduction', '分组', '实验室安全', '实验安排', '实验视频', '实验课件',
        '课前预告', '复习', 'learning objective', 'teaching schedule', 'teaching plan',
        'experiment 0', 'safety notification', 'sign-up', 'signup', 'group',
        'course material',
    ]
    if any(s in title_l for s in skip):
        return False
    
    # Course Materials section = lecture content, not homework
    if 'course material' in section_l:
        return False
    
    # Must have submission/deadline-relevant keywords
    positive = [
        'assignment', 'homework', '作业', 'report', '实验报告',
        'test', 'quiz', 'exam', '考试',
        'written', 'bibliography', 'reflection', 'literature', 'research',
        'plagiarism', 'problem set', 'exercise', 'practice',
        'due', 'deadline', '截止',
    ]
    if any(p in title_l for p in positive):
        return True
    
    return False


def run_phase1():
    print("[Phase 1] Starting...")
    cookies = None
    try:
        cookies = login_requests()
        save_session(cookies)
    except Exception as e:
        print(f"[Phase 1] Login failed: {e}")
        cookies = load_session()
        if cookies:
            print("[Phase 1] Using cached cookies.")
        else:
            return [], {}
    save_session(cookies)
    print("[Phase 1] Getting course list via Playwright...")
    courses = get_courses_via_playwright(cookies)
    print(f"[Phase 1] Found {len(courses)} courses:")
    for c in courses:
        print(f"  - {c['name']} ({c['id']})")
    print("[Phase 1] Getting sidebars via requests...")
    sidebars = {}
    for c in courses:
        try:
            sidebar = get_sidebar_via_requests(cookies, c['id'])
            sidebars[c['id']] = sidebar
            for section, items in sidebar.items():
                assign_items = [(i['Title'], i['cid']) for i in items if is_assignment(i['Title'], section)]
                if assign_items:
                    print(f"\n  {c['name']} > {section}:")
                    for t, cid in assign_items[:5]:
                        print(f"    - {t} ({cid})")
        except Exception as e:
            print(f"  Error for {c['name']}: {e}")
    with open(CACHE_FILE, 'w') as f:
        json.dump({'courses': courses, 'sidebars': sidebars}, f, indent=2, ensure_ascii=False)
    print(f"\n[Phase 1] Done.")
    return courses, sidebars


def run_phase2(target=None):
    cookies = load_session()
    if not cookies:
        print("[Phase 2] No session. Run --phase1 first.")
        return
    if not os.path.exists(CACHE_FILE):
        print("[Phase 2] No cache. Run --phase1 first.")
        return
    with open(CACHE_FILE) as f:
        data = json.load(f)
    courses = data['courses']
    sidebars = data['sidebars']
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
        page.wait_for_timeout(3000)
        if 'login' in page.url.lower():
            print("[Phase 2] Session expired. Run --phase1 again.")
            browser.close()
            return
        print("[Phase 2] Extracting assignments...\n")
        results = {}
        for c in courses:
            cid, name = c['id'], c['name']
            if target and target.lower() not in name.lower():
                continue
            if cid not in sidebars:
                continue
            sidebar = sidebars[cid]
            for section, items in sidebar.items():
                for item in items:
                    title = item['Title']
                    item_cid = item['cid']
                    if not is_assignment(title, section):
                        continue
                    print(f"[Phase 2] {name} > {title}...", end=" ", flush=True)
                    url = f'https://bb.sustech.edu.cn/webapps/blackboard/content/listContent.jsp?course_id={cid}&content_id={item_cid}&mode=reset'
                    try:
                        page.goto(url, timeout=15000)
                        page.wait_for_load_state('networkidle', timeout=8000)
                        page.wait_for_timeout(2000)
                        text = page.inner_text('body')
                        # Extract deadline - broader patterns
                        ddl_m = re.search(
                            r'(?:due|deadline|截止|in\s+Week[^.\n]{0,50}|before[^.\n]{0,50}|过期)[^.\n]{0,150}',
                            text, re.IGNORECASE
                        )
                        ddl = ddl_m.group(0).strip() if ddl_m else 'No deadline'
                        pts_m = re.search(r'(\d+\s*points?)', text, re.IGNORECASE)
                        pts = pts_m.group(1) if pts_m else ''
                        print(f"DDL: {ddl}" + (f" | {pts}" if pts else ""))
                        results[f"{name} > {title}"] = {
                            'course': name, 'section': section, 'title': title,
                            'ddl': ddl, 'points': pts, 'preview': text[:800]
                        }
                    except Exception as e:
                        print(f"Error: {e}")
        browser.close()
        with open('/tmp/bb_assignment_results.json', 'w') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"\n=== SUMMARY ===")
        for key, item in results.items():
            print(f"\n{item['course']} > {item['section']} > {item['title']}")
            print(f"  Deadline: {item['ddl']}" + (f" | {item['points']}" if item['points'] else ""))
        return results


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else None
    args = sys.argv[2:]
    if mode == '--phase1':
        run_phase1()
    elif mode == '--phase2':
        target = ' '.join(args) if args else None
        run_phase2(target)
    elif mode == '--list':
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE) as f:
                data = json.load(f)
            print("Cached courses:")
            for c in data['courses']:
                print(f"  - {c['name']} ({c['id']})")
        else:
            print("No cache. Run --phase1 first.")
    else:
        target = ' '.join(sys.argv[1:]) if len(sys.argv) > 1 else None
        print("=== BB Hybrid Scanner ===\n")
        courses, _ = run_phase1()
        if target or courses:
            print(f"\n=== Phase 2 ===")
            run_phase2(target)


if __name__ == '__main__':
    main()
