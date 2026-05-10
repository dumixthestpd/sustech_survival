#!/usr/bin/env python3
"""
BB Assignment Submitter — clean skill entry point.

This is the AI-facing skill for BB submission. It wraps submit.py's logic
with smart defaults and safety checks.

Usage:
    python3 bb_submit_skill.py submit <content_id> <course_id> <file_path>
    python3 bb_submit_skill.py check <content_id> <course_id>
    python3 bb_submit_skill.py list-due
    python3 bb_submit_skill.py find-assignment <keyword>
"""
import sys, re, json
from pathlib import Path

# Hardcoded absolute path — this skill always lives at this location
SKILL_SRC = Path('/Users/dumix/.openclaw/workspace/skills/sustech_survival/src')
SKILL_DIR = SKILL_SRC.parent

# Ensure sustech_survival is importable
if str(SKILL_SRC) not in sys.path:
    sys.path.insert(0, str(SKILL_SRC))
sys.path.insert(0, str(SKILL_DIR / "src"))

BB_BASE = "https://bb.sustech.edu.cn"


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────

def load_session():
    from sustech_survival.bb.session import load_session
    return load_session()

def resolve_course(content_id):
    from sustech_survival.bb.download import resolve_course
    return resolve_course(content_id)

def num_id(bb_id):
    """_8053_1 → 8053"""
    m = re.search(r'_(\d+)_(\d+)$', str(bb_id))
    return m.group(1) if m else str(bb_id)

def clean_filename(name: str) -> str:
    """Strip OpenClaw UUID suffix for clean BB filename."""
    return re.sub(
        r'---[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?=\.)',
        '', name
    )

def check_session():
    from sustech_survival.bb.session import check_session
    return check_session()


# ─────────────────────────────────────────────────────────────────
# Submit
# ─────────────────────────────────────────────────────────────────

def submit(content_id, file_path, course_id=None):
    """
    Submit a file to a BB assignment.

    Returns (success: bool, message: str)
    """
    if course_id is None:
        course_id = resolve_course(content_id)
        if not course_id:
            return False, f"Cannot resolve course_id for content_id={content_id}. Provide --course explicitly."

    course_num = num_id(course_id)
    cid = num_id(content_id)

    file_path = Path(file_path).expanduser().resolve()
    if not file_path.exists():
        return False, f"File not found: {file_path}"

    # Clean filename (remove OpenClaw UUID suffix)
    clean_name = clean_filename(file_path.name)
    if clean_name != file_path.name:
        import shutil, tempfile
        clean_path = Path(tempfile.gettempdir()) / clean_name
        shutil.copy2(file_path, clean_path)
        file_to_upload = clean_path
    else:
        file_to_upload = file_path

    # Submit via submit.py
    from sustech_survival.bb.submit import submit_assignment
    ok, msg = submit_assignment(course_num, cid, [str(file_to_upload)], skip_dedup=True)
    return ok, msg


def check_attempts(content_id, course_id=None):
    """Return (attempt_count, assignment_name). Raises on error."""
    if course_id is None:
        course_id = resolve_course(content_id)

    from sustech_survival.bb.submit import get_attempt_info
    result = get_attempt_info(num_id(course_id), num_id(content_id))
    # result is (attempt_count, assignment_name, session_ok)
    return result[0], result[1]


def list_upcoming(limit=10):
    """List all upcoming BB assignments with due dates (next `limit` assignments)."""
    from sustech_survival.bb.courses import load_courses
    from sustech_survival.bb.download import discover_attempt_ids, scrape_attempt_details
    from playwright.sync_api import sync_playwright

    session = load_session()
    raw, cookies = session
    courses = load_courses()

    def num(bb_id):
        m = re.search(r'_(\d+)_(\d+)$', str(bb_id))
        return m.group(1) if m else str(bb_id)

    upcoming = []  # (course_name, title, content_id, course_id, due_date_str, is_week10)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        ctx.add_cookies(cookies)

        for c in courses:
            course_id = num(c['id'])
            course_name = c['name']

            # Visit the course content page
            page = ctx.new_page()
            try:
                url = f'{BB_BASE}/webapps/blackboard/content/listContent.jsp?course_id={c["id"]}&content_id={c["id"]}&mode=reset'
                page.goto(url, wait_until='domcontentloaded', timeout=20000)
                page.wait_for_timeout(2000)

                for _ in range(3):
                    d = page.query_selector('[role=dialog]')
                    if not d: break
                    b = d.query_selector('button')
                    if b: b.click()
                    page.wait_for_timeout(400)

                # Find all homework (uploadAssignment) links
                lis = page.query_selector_all('li')
                for li in lis:
                    li_id = li.get_attribute('id') or ''
                    if 'contentListItem' not in li_id:
                        continue
                    m = re.search(r'contentListItem:_(\d+)_', li_id)
                    if not m: continue
                    sub_id = m.group(1)

                    h3 = li.query_selector('h3')
                    title = h3.inner_text().strip() if h3 else ''

                    upload_a = li.query_selector('a[href*=uploadAssignment]')
                    if not upload_a:
                        continue

                    # Visit newAttempt page to get due date
                    page2 = ctx.new_page()
                    due_url = f'{BB_BASE}/webapps/assignment/uploadAssignment?action=newAttempt&content_id=_{sub_id}_1&course_id=_{course_id}_1&group_id='
                    page2.goto(due_url, wait_until='domcontentloaded', timeout=15000)
                    page2.wait_for_timeout(2000)
                    for _ in range(3):
                        d = page2.query_selector('[role=dialog]')
                        if not d: break
                        b = d.query_selector('button')
                        if b: b.click()
                        page2.wait_for_timeout(400)

                    body = page2.inner_text('body')
                    m_due = re.search(r'到期日期\s*\n?\s*(\d{4}年\d{1,2}月\d{1,2}日[^\n]*)', body)
                    due = m_due.group(1).strip() if m_due else 'unknown'
                    page2.close()

                    upcoming.append((course_name, title, sub_id, course_id, due))
            except Exception:
                pass
            page.close()
        browser.close()

    # Sort by due date
    def due_sort(item):
        m = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', item[4])
        if m:
            return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return (9999, 99, 99)

    upcoming.sort(key=due_sort)

    return upcoming[:limit]


def find_assignment(keyword):
    """Search all BB pages for an assignment by keyword (title/content)."""
    from sustech_survival.bb.courses import load_courses
    from playwright.sync_api import sync_playwright

    session = load_session()
    raw, cookies = session
    courses = load_courses()

    def num(bb_id):
        m = re.search(r'_(\d+)_(\d+)$', str(bb_id))
        return m.group(1) if m else str(bb_id)

    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        ctx.add_cookies(cookies)

        for c in courses:
            course_id = num(c['id'])
            course_name = c['name']

            page = ctx.new_page()
            try:
                url = f'{BB_BASE}/webapps/blackboard/content/listContent.jsp?course_id={c["id"]}&content_id={c["id"]}&mode=reset'
                page.goto(url, wait_until='domcontentloaded', timeout=20000)
                page.wait_for_timeout(2000)

                for _ in range(3):
                    d = page.query_selector('[role=dialog]')
                    if not d: break
                    b = d.query_selector('button')
                    if b: b.click()
                    page.wait_for_timeout(400)

                # Get all homework items
                lis = page.query_selector_all('li')
                for li in lis:
                    li_id = li.get_attribute('id') or ''
                    if 'contentListItem' not in li_id:
                        continue
                    m = re.search(r'contentListItem:_(\d+)_', li_id)
                    if not m: continue
                    sub_id = m.group(1)

                    h3 = li.query_selector('h3')
                    title = h3.inner_text().strip() if h3 else ''

                    upload_a = li.query_selector('a[href*=uploadAssignment]')
                    if not upload_a:
                        continue

                    # Check if keyword matches
                    if keyword.lower() in title.lower():
                        # Get due date
                        page2 = ctx.new_page()
                        due_url = f'{BB_BASE}/webapps/assignment/uploadAssignment?action=newAttempt&content_id=_{sub_id}_1&course_id=_{course_id}_1&group_id='
                        page2.goto(due_url, wait_until='domcontentloaded', timeout=15000)
                        page2.wait_for_timeout(2000)
                        for _ in range(3):
                            d = page2.query_selector('[role=dialog]')
                            if not d: break
                            b = d.query_selector('button')
                            if b: b.click()
                            page2.wait_for_timeout(400)

                        body = page2.inner_text('body')
                        m_due = re.search(r'到期日期\s*\n?\s*(\d{4}年\d{1,2}月\d{1,2}日[^\n]*)', body)
                        due = m_due.group(1).strip() if m_due else 'unknown'

                        # Check if already submitted
                        from sustech_survival.bb.download import discover_attempt_ids
                        attempts = discover_attempt_ids(ctx, course_id, sub_id)
                        submitted = len(attempts) > 0

                        results.append({
                            'course': course_name,
                            'course_id': course_id,
                            'content_id': sub_id,
                            'title': title,
                            'due': due,
                            'submitted': submitted,
                            'attempt_count': len(attempts),
                        })
                        page2.close()
            except Exception:
                pass
            page.close()
        browser.close()

    return results


# ─────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="BB Submission Skill")
    sub = parser.add_subparsers(dest="cmd")

    check_p = sub.add_parser("check", help="Check attempt count for assignment")
    check_p.add_argument("content_id")
    check_p.add_argument("course_id", nargs="?", default=None)

    submit_p = sub.add_parser("submit", help="Submit a file to BB assignment")
    submit_p.add_argument("content_id")
    submit_p.add_argument("file_path")
    submit_p.add_argument("course_id", nargs="?", default=None)

    due_p = sub.add_parser("list-due", help="List upcoming assignments with due dates")
    due_p.add_argument("--limit", type=int, default=20)

    find_p = sub.add_parser("find", help="Find assignment by keyword")
    find_p.add_argument("keyword")

    args = parser.parse_args()

    if args.cmd == "check":
        count, name = check_attempts(args.content_id, args.course_id)
        print(f"Assignment: {name}")
        print(f"Prior attempts: {count}")
        print(f"Next would be: #{count + 1}")

    elif args.cmd == "submit":
        ok, msg = submit(args.content_id, args.file_path, args.course_id)
        print(f"Success: {ok}")
        print(msg)

    elif args.cmd == "list-due":
        upcoming = list_upcoming(limit=args.limit)
        for course_name, title, cid, coid, due, *_ in upcoming:
            print(f"[{due}] {course_name} | {title} (c={cid}, co={coid})")

    elif args.cmd == "find":
        results = find_assignment(args.keyword)
        for r in results:
            status = "✅ submitted" if r['submitted'] else "⬜ not submitted"
            print(f"{status} | [{r['course']}] {r['title']} (c={r['content_id']}, co={r['course_id']}) | due: {r['due']}")

    else:
        parser.print_help()