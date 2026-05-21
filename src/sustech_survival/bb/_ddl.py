"""
bb ddl — Extract assignment deadlines from Blackboard.

Uses the BB REST API (fast, no browser needed) to:
1. List enrolled courses
2. Find "我的作业" content folder per course
3. List assignment items from that folder
4. Extract due dates from item title (Week N) or body text
"""

import html as html_mod
import re
import sys
import urllib.parse
from datetime import datetime, timedelta

import requests
from playwright.sync_api import sync_playwright

# ── session ──────────────────────────────────────────────────────────────────

def _get_session():
    from sustech_survival.bb.session import BBAuth
    _auth = BBAuth()
    if not _auth.refresh():
        if not _auth.login():
            print("❌ BB login failed")
            sys.exit(1)
    cookies = _auth.cookies_for_requests(_auth.load())
    s = requests.Session()
    for name, value in cookies.items():
        s.cookies.set(name, value, domain=".sustech.edu.cn", path="/")
    return s


def _get_enrolled_courses():
    """Return list of (course_id, course_name) from BB portal via Playwright.

    The REST API doesn't include all enrolled courses. The portal page does.
    """
    cookies_dict = _get_session().cookies.get_dict(domain=".sustech.edu.cn")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        ctx.add_cookies([
            {"name": n, "value": v, "domain": ".sustech.edu.cn", "path": "/"}
            for n, v in cookies_dict.items()
        ])
        page = ctx.new_page()
        page.goto(
            "https://bb.sustech.edu.cn/webapps/portal/execute/tabs/tabAction?tab_tab_group_id=_2_1",
            timeout=15000
        )
        page.wait_for_load_state("networkidle", timeout=10000)
        page.wait_for_timeout(2000)
        page_html = page.content()
        page.close()
        browser.close()

    # BB HTML-encodes & as &amp; in href attributes
    link_re = re.compile(r'<a[^>]+href="([^"]+launcher[^"]+)"[^>]*>\s*([^<]+)\s*</a>')
    result = []
    for href_raw, text in link_re.findall(page_html):
        try:
            # Unescape HTML entities (&amp; → &) before URL parsing
            href = html_mod.unescape(href_raw)
            parsed = urllib.parse.urlparse(href)
            params = dict(urllib.parse.parse_qsl(parsed.query))
            cid = params.get('id', '')
            if cid.startswith('_') and len(cid) > 1:
                name = text.strip()
                if name:
                    result.append((cid, name))
        except Exception:
            continue
    return result


def _get_hw_content_id(session, course_id):
    """Find content_id of the '我的作业' folder in a course."""
    BASE = "https://bb.sustech.edu.cn"
    r = session.get(
        BASE + f"/learn/api/public/v1/courses/{course_id}/contents",
        timeout=15
    )
    if r.status_code != 200:
        return None
    for item in r.json().get("results", []):
        title = item.get("title", "")
        if "作业" in title or "homework" in title.lower() or "assignment" in title.lower():
            return item["id"]
    return None


def _get_assignments(session, course_id, content_id):
    """Return list of (item_id, title, due_hint) from assignment folder."""
    BASE = "https://bb.sustech.edu.cn"
    r = session.get(
        BASE + f"/learn/api/public/v1/courses/{course_id}/contents/{content_id}/children",
        timeout=15
    )
    if r.status_code != 200:
        return []
    items = []
    for item in r.json().get("results", []):
        title = item.get("title", "")
        body = item.get("body", "")
        due = _parse_due_date(title, body)
        items.append((item["id"], title, due))
    return items


def _parse_due_date(title, body):
    """Extract a human-readable due date hint from assignment title + body."""
    # Title patterns like "第12周作业" → "第12周" or "Week 12"
    m = re.search(r'第(\d+)周', title)
    if m:
        return f"第{m.group(1)}周"
    m = re.search(r'Week\s*(\d+)', title, re.I)
    if m:
        return f"Week {m.group(1)}"

    # Body: look for specific date patterns
    date_m = re.search(r'(\d{4}[-/]\d{1,2}[-/]\d{1,2}\s+\d{1,2}:\d{2})', body)
    if date_m:
        return date_m.group(1)

    # Body: "每周六晚12点-周日早8点" → weekly recurring
    if "每周" in body and "点" in body:
        return "每周六晚12点-周日早8点"

    return "见BB"


def run(days: int = 7, course_id: str = None):
    """See docs/bb.md."""

    # 1. Get enrolled courses from portal (REST API doesn't have them all)
    all_courses = _get_enrolled_courses()
    if not all_courses:
        print("❌ 无法获取课程列表，请重新登录")
        return

    # 2. Filter courses
    if course_id:
        courses = [(c, n) for c, n in all_courses if c == course_id]
    else:
        active_ids = {'_8053_1', '_8157_1', '_8221_1', '_8328_1', '_8343_1'}
        courses = [
            (c, n) for c, n in all_courses
            if "2026" in n or c in active_ids
        ]
        if not courses:
            courses = all_courses

    now = datetime.now()
    cutoff = now + timedelta(days=days)
    results = []

    for cid, cname in courses:
        hw_content_id = _get_hw_content_id(session, cid)
        if not hw_content_id:
            continue

        assignments = _get_assignments(session, cid, hw_content_id)
        for item_id, title, due in assignments:
            due_parsed = _due_hint_to_datetime(due, now)
            status = ""
            if due_parsed:
                if due_parsed < now:
                    status = "已截止"
                elif due_parsed <= cutoff:
                    status = f"还有 {(due_parsed - now).days} 天"
                else:
                    status = f"{days} 天后"
            results.append({
                "course": cname,
                "assignment": title,
                "due": due,
                "due_parsed": due_parsed,
                "status": status,
            })

    if not results:
        print("📭 暂无作业信息")
        return

    # Group by course
    print(f"📚 作业列表 ({len(results)} 项)\n")
    current_course = None
    for r in results:
        if r["course"] != current_course:
            current_course = r["course"]
            print(f"\n{'='*50}")
            print(f"  {current_course[:50]}")
            print(f"{'='*50}")
        delta_str = r["status"] if r["status"] else ""
        due_str = r["due"]
        print(f"  • {r['assignment'][:45]}")
        print(f"    截止: {due_str}  {delta_str}")


def _due_hint_to_datetime(hint, now):
    """Convert a due hint string to datetime for filtering."""
    # "每周六晚12点-周日早8点" → next Saturday 23:59
    if "每周" in hint and "周六" in hint:
        days_until_sat = (5 - now.weekday()) % 7
        if days_until_sat == 0:
            days_until_sat = 7  # next Saturday, not today
        next_sat = now + timedelta(days=days_until_sat)
        return next_sat.replace(hour=23, minute=59, second=0)

    # Week pattern: "第12周"
    m = re.search(r'第(\d+)周', hint)
    if m:
        week = int(m.group(1))
        # Spring 2026 started around 2026-02-23 (week 1)
        semester_start = datetime(2026, 2, 23)
        due_date = semester_start + timedelta(weeks=week - 1)
        due_date = due_date.replace(hour=23, minute=59, second=0)
        return due_date

    # Week pattern: "Week 12"
    m = re.search(r'Week\s*(\d+)', hint, re.I)
    if m:
        week = int(m.group(1))
        semester_start = datetime(2026, 2, 23)
        due_date = semester_start + timedelta(weeks=week - 1)
        due_date = due_date.replace(hour=23, minute=59, second=0)
        return due_date

    # Date pattern: "2026-05-25 23:59"
    for fmt in ["%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M"]:
        try:
            return datetime.strptime(hint, fmt)
        except ValueError:
            continue

    return None
