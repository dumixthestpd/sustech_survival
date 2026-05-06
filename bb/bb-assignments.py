#!/usr/bin/env python3
"""
SUSTech BB Course Assignments - General Purpose
Finds all courses and their upcoming assignments from Blackboard.
Uses headless Playwright for the full flow (login → courses → assignments).

Usage:
    python3 bb-assignments.py                  # List all courses + all assignments
    python3 bb-assignments.py <course_name>   # Assignments for matching course
    python3 bb-assignments.py --list           # Just list enrolled courses
"""

import sys
import re
import json
from playwright.sync_api import sync_playwright

CAS_URL = "https://cas.sustech.edu.cn/cas/login?service=https://bb.sustech.edu.cn/webapps/bb-sso-BBLEARN/index.jsp"
CREDS_FILE = "/Users/dumix/.openclaw/workspace/credentials.txt"


def load_credentials():
    with open(CREDS_FILE) as f:
        cred = f.read().strip().split(':')
    return cred[0], cred[1]


def parse_date(date_str):
    """Normalize Chinese date format to YYYY-MM-DD."""
    if not date_str:
        return None
    m = re.search(r'(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?', date_str)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return date_str


def extract_assignments(text):
    """Extract assignment blocks from BB content page text."""
    # Split by assignment headers
    pattern = r'((?:第[一二三四五六七八九十百\d]+(?:次|部)作业|test|quiz|exam|考试|实验)[^第<]{0,500})'
    matches = re.findall(pattern, text, re.IGNORECASE)
    
    results = []
    for match in matches:
        match = match.strip()
        if len(match) < 5:
            continue
        
        # Extract the assignment name and date
        name_match = re.match(r'([^：:!\-–\.]+?)[:\-–\.\s]+(.{0,20})', match)
        name = name_match.group(1).strip() if name_match else match[:40]
        rest = name_match.group(2) + match[len(name_match.group(0)):] if name_match else match[40:]
        
        # Extract deadline
        ddl_match = re.search(
            r'(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*(?:号|日)?(?:\s*(?:早上|下午|晚上|\d{1,2}\s*[:：]\s*\d{1,2})?)?(?:\s*(?:之前|截止|过期|due|deadline))?)',
            rest, re.IGNORECASE
        )
        ddl = parse_date(ddl_match.group(1)) if ddl_match else ''
        
        # Extract problems/content if present
        problems = re.findall(r'(?:Problem|题|Exercise|练习)[：:\s]*([^\n<]{5,100})', rest, re.IGNORECASE)
        
        results.append({
            'name': re.sub(r'[^\w\s\u4e00-\u9fff\-\(\)]', '', name)[:50],
            'deadline': ddl,
            'content': rest[:300].strip(),
            'problems': [p.strip() for p in problems[:5]]
        })
    
    return results


def run(target_course=None, list_only=False):
    """Main flow: login → get courses → get assignments."""
    username, password = load_credentials()
    all_courses = []
    results = {}
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        page = context.new_page()
        
        # === LOGIN ===
        print("[1/3] Logging in to CAS...", end=" ", flush=True)
        page.goto(CAS_URL, timeout=30000, wait_until='domcontentloaded')
        page.wait_for_load_state('networkidle', timeout=15000)
        page.fill('input[name="username"]', username)
        page.fill('input[name="password"]', password)
        page.press('input[name="password"]', 'Enter')
        page.wait_for_url('**/portal/**', timeout=30000)
        page.wait_for_timeout(5000)  # Wait for JS course list
        print("OK")
        
        # === GET COURSE LIST ===
        print("[2/3] Finding enrolled courses...", end=" ", flush=True)
        
        # Extract course links via JS
        course_data = page.evaluate('''
() => {
    const links = document.querySelectorAll('a[href*="courseMain"], a[href*="launcher?type=Course"]');
    const seen = new Set();
    const results = [];
    for (const l of links) {
        const href = l.href;
        const text = l.textContent.trim();
        if (href && text.length > 2 && !seen.has(href)) {
            seen.add(href);
            results.push({href, text});
        }
    }
    return results;
}
''')
        print(f"OK ({len(course_data)} courses)")
        
        for cd in course_data:
            # Extract course_id from href
            cid_match = re.search(r'course_id=([^&]+)', cd['href'])
            cid = cid_match.group(1) if cid_match else ''
            name = cd['text'].strip()
            
            # Clean up name
            name = re.sub(r'^(→|《|")+', '', name).strip()
            name = re.sub(r'[(（]202\d[)）]?$', '', name).strip()
            name = re.sub(r'[(（]?\d{4}[-–]\d{1,2}[)）]?$', '', name).strip()
            
            all_courses.append({'id': cid, 'name': name, 'url': cd['href']})
        
        # === GET ASSIGNMENTS ===
        print(f"[3/3] Fetching assignments for {len(course_data)} courses...\n")
        
        for i, course in enumerate(all_courses):
            cid = course['id']
            name = course['name']
            
            # Skip if filtering and name doesn't match
            if target_course and target_course.lower() not in name.lower():
                continue
            
            print(f"  [{i+1}/{len(all_courses)}] {name}")
            
            # Navigate to course
            try:
                page.goto(course['url'], timeout=20000)
                page.wait_for_load_state('networkidle', timeout=10000)
                page.wait_for_timeout(2000)
                
                # Get all content links
                content_links = page.evaluate('''
() => {
    const links = document.querySelectorAll('a[href*="content_id="]');
    const results = [];
    for (const l of links) {
        if (l.href && l.textContent.trim().length > 0) {
            results.push({href: l.href, text: l.textContent.trim().slice(0, 60)});
        }
    }
    return results;
}
''')
                
                # Check content pages for assignments
                course_assignments = []
                for cl in content_links:
                    if 'listContent' not in cl['href'] or 'content_id' not in cl['href']:
                        continue
                    
                    try:
                        page.goto(cl['href'], timeout=15000)
                        page.wait_for_load_state('networkidle', timeout=8000)
                        page.wait_for_timeout(1500)
                        
                        text = page.inner_text('body')
                        
                        assignments = extract_assignments(text)
                        for a in assignments:
                            a['source'] = cl['text']
                            course_assignments.append(a)
                    except:
                        pass
                
                if course_assignments:
                    results[name] = course_assignments
                    for a in course_assignments:
                        ddl_str = f" (due: {a['deadline']})" if a['deadline'] else ""
                        print(f"    → {a['name']}{ddl_str}")
                else:
                    print(f"    → No assignments found")
                    
            except Exception as e:
                print(f"    → Error: {str(e)[:50]}")
        
        browser.close()
    
    # === SUMMARY ===
    print(f"\n{'='*50}")
    print("SUMMARY")
    print(f"{'='*50}")
    
    if not results:
        print("No assignments found.")
        if target_course:
            print(f"No course matched '{target_course}'. Available courses:")
            for c in all_courses:
                print(f"  - {c['name']} ({c['id']})")
        return
    
    for course_name, assignments in results.items():
        print(f"\n{course_name}:")
        for a in assignments:
            ddl = f" due {a['deadline']}" if a['deadline'] else " (no deadline found)"
            print(f"  • {a['name']}{ddl}")
            if a.get('problems'):
                for p in a['problems'][:3]:
                    print(f"    - {p[:80]}")
    
    return results


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--list':
        # Just list courses
        run(list_only=True)
    elif len(sys.argv) > 1:
        run(target_course=' '.join(sys.argv[1:]))
    else:
        run()
