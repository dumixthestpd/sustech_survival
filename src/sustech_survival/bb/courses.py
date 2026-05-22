# Courses — BB course data loading and discovery via REST API
"""
Course loading, listing, finding via REST API (no Playwright).

REST-only flow:
  1. /users/me                    → current user ID
  2. /users/{uid}/courses        → enrollment records with courseId
  3. /courses/{courseId}         → course name + details

Playwright is NOT used for course discovery — only for discovering
assignment slots when structure.json is unavailable.
"""

import json
import re
import sys
from pathlib import Path
from typing import List, Dict

try:
    from .session import BB_BASE
except ImportError:
    BB_BASE = "https://bb.sustech.edu.cn"

BB_DIR = Path(__file__).resolve().parent
COURSES_FILE = BB_DIR / "courses.json"
STRUCTURE_FILE = BB_DIR / "structure.json"

SKIP_COURSE_NAMES = {
    '大学物理', '高等数学', 'college physics', 'higher mathematics',
    '微积分', '线性代数', 'calculus', 'linear algebra',
}


# ── REST-based course discovery ────────────────────────────────────────────────

def _session():
    """Return requests.Session with BB cookies from SSO auth layer."""
    from sustech_survival.sso.authorizer import get_auth
    auth = get_auth("bb")
    raw = auth.load()
    sess = __import__('requests').Session()
    for name, value in raw.items():
        sess.cookies.set(name, value, domain=".bb.sustech.edu.cn", path="/")
    return sess


def _api(path, session=None):
    """GET BB REST endpoint. Returns JSON. Dies on auth error."""
    if session is None:
        session = _session()
    r = session.get(BB_BASE + path, timeout=15)
    if r.status_code == 401:
        print("❌ BB session expired. Run `bb.py login` to refresh.")
        sys.exit(1)
    r.raise_for_status()
    return r.json()


def scrape_enrolled_courses() -> List[Dict[str, str]]:
    """
    Fetch current user's enrolled courses via REST API.

    Uses /users/me → /users/{uid}/courses → /courses/{courseId}
    to build the full course list with names — no Playwright needed.

    Returns list of dicts: [{"id": "_8343_1", "name": "Physical Chemistry...", "href": ""}, ...]
    """
    # 1. Get current user ID
    me = _api("/learn/api/public/v1/users/me")
    uid = me["id"]

    # 2. Get all enrollments
    enrollments = _api(f"/learn/api/public/v1/users/{uid}/courses")
    seen_ids = set()
    courses = []

    for enrollment in enrollments.get("results", []):
        course_id = enrollment.get("courseId", "")  # e.g. "_8343_1"
        if not course_id or course_id in seen_ids:
            continue

        # 3. Fetch course name
        try:
            course_data = _api(f"/learn/api/public/v1/courses/{course_id}")
            name = course_data.get("name", "")
        except Exception:
            name = ""

        if not name:
            continue

        # Skip physics/math recordings
        if any(sn.lower() in name.lower() for sn in SKIP_COURSE_NAMES):
            continue

        seen_ids.add(course_id)
        courses.append({"id": course_id, "name": name, "href": ""})

    return courses


def refresh_courses_json() -> List[Dict[str, str]]:
    """Scrape live from REST API and update courses.json."""
    courses = scrape_enrolled_courses()
    COURSES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(COURSES_FILE, 'w') as f:
        json.dump({"courses": courses, "ts": __import__('time').time()}, f, indent=2, ensure_ascii=False)
    print(f"Updated {COURSES_FILE} with {len(courses)} courses.")
    for c in courses:
        print(f"  - {c['name']} ({c['id']})")
    return courses


# ── Course Data ────────────────────────────────────────────────────────────────

def load_courses():
    """Load course list from courses.json. Returns list of course dicts."""
    if not COURSES_FILE.exists():
        return []
    with open(COURSES_FILE) as f:
        data = json.load(f)
    return data.get("courses", [])


def get_course_numeric_id(course_id_str):
    """Extract numeric part from '_8343_1' → '8343'."""
    m = re.search(r"_(\d+)_", course_id_str)
    return m.group(1) if m else course_id_str


def find_course(query):
    """Find courses matching query (ID, numeric ID, or name substring)."""
    courses = load_courses()
    q = query.lower().strip()
    results = []
    for c in courses:
        cid = c.get("id", "")
        nid = c.get("numeric_id", "")
        name = c.get("name", "")
        if (q == cid.lower() or q == nid.lower()
                or q in name.lower()):
            results.append((cid, name))
    return results


def list_courses():
    """Return all courses as (course_id_str, name) tuples."""
    return [(c["id"], c.get("name", "Unknown")) for c in load_courses()]


# ── Assignment Discovery (Playwright only when structure.json unavailable) ─────

def _get_content_title(page, content_id):
    """Get the content page title via Playwright."""
    title_el = page.query_selector("title")
    if title_el:
        txt = title_el.inner_text().strip()
        if " – " in txt:
            txt = txt.split(" – ")[0]
        txt = txt.lstrip("-").lstrip(" ").strip()
        if txt and len(txt) > 2:
            return txt
    for selector in ("h1", "h2", "h3"):
        for el in page.query_selector_all(selector):
            txt = el.inner_text().strip()
            if txt and len(txt) > 2 and txt not in {
                "打开快速链接", "页面标志", "内容大纲", "键盘快捷键",
                "Top Frame Tabs", "Current Location", "Menu Management Options",
                "Course Menu:"
            } and txt.startswith("--"):
                return txt.lstrip("-").strip()
    return f"Content {content_id}"


def discover_assignments_for_course(pw_cookies, course_id_str):
    """
    Discover all BB uploadAssignment slots for a course via Playwright.
    Used as fallback when structure.json is unavailable.

    Returns list of (assignment_content_id, title) tuples.
    """
    from playwright.sync_api import sync_playwright

    # Fast path: use structure.json for content IDs
    if STRUCTURE_FILE.exists():
        try:
            with open(STRUCTURE_FILE) as f:
                data = json.load(f)
            numeric_match = re.search(r"_(\d+)_1", course_id_str)
            numeric_cid = numeric_match.group(1) if numeric_match else None

            content_ids = [
                r["content_id"] for r in data.get("results", [])
                if r.get("course_id") == numeric_cid and r.get("content_id") != numeric_cid
            ]
        except Exception:
            content_ids = None

        if content_ids:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                ctx = browser.new_context()
                ctx.add_cookies(pw_cookies)

                results = []
                for cid in content_ids:
                    page = ctx.new_page()
                    try:
                        page.goto(
                            f"{BB_BASE}/webapps/blackboard/content/listContent.jsp"
                            f"?course_id=_{course_id_str}_1&content_id=_{cid}_1&mode=reset",
                            wait_until="domcontentloaded", timeout=10000
                        )
                        page.wait_for_timeout(800)

                        for _ in range(3):
                            d = page.query_selector('[role="dialog"]')
                            if not d:
                                break
                            b = d.query_selector("button")
                            if b:
                                b.click()
                                page.wait_for_timeout(400)

                        for a in page.query_selector_all("a"):
                            href = a.get_attribute("href") or ""
                            if "uploadAssignment" not in href or "action=" in href:
                                continue
                            m = re.search(r"content_id=_(\d+)_", href)
                            if not m:
                                continue
                            upload_cid = m.group(1)
                            title = _get_content_title(page, upload_cid)
                            results.append((upload_cid, title))
                            break
                    except Exception:
                        pass
                    finally:
                        page.close()

                browser.close()
                if results:
                    return results

    # Slow fallback: Playwright recursive crawl
    def visit_page(ctx, course_id_str, content_id, depth=0):
        results = []
        page = ctx.new_page()
        try:
            page.goto(
                f"{BB_BASE}/webapps/blackboard/content/listContent.jsp"
                f"?course_id=_{course_id_str}_1&content_id=_{content_id}_1&mode=reset",
                wait_until="domcontentloaded", timeout=20000
            )
            page.wait_for_timeout(2000)

            for _ in range(3):
                d = page.query_selector('[role="dialog"]')
                if not d:
                    break
                b = d.query_selector("button")
                if b:
                    b.click()
                    page.wait_for_timeout(800)

            seen = set()
            links = []
            for a in page.query_selector_all("a"):
                href = a.get_attribute("href") or ""
                text = (a.inner_text() or "").strip()
                if "content_id=_" not in href or not text or len(text) < 3:
                    continue
                m = re.search(r"content_id=_(\d+)_\s*", href)
                if not m:
                    continue
                cid = m.group(1)
                if cid in seen:
                    continue
                seen.add(cid)
                links.append((cid, text))

            upload_links = {}
            for a in page.query_selector_all("a"):
                href = a.get_attribute("href") or ""
                if "uploadAssignment" not in href or "action=" in href:
                    continue
                m = re.search(r"content_id=_(\d+)_\s*", href)
                if m and m.group(1) not in upload_links:
                    title = next((t for c, t in links if c == m.group(1)), None)
                    upload_links[m.group(1)] = title or f"Assignment {m.group(1)}"

            if upload_links:
                for cid, title in upload_links.items():
                    results.append((cid, title))
            elif depth < 3 and links:
                for child_cid, child_title in links:
                    if child_cid == course_id_str.replace("_", "").rstrip("1"):
                        continue
                    results.extend(visit_page(ctx, course_id_str, child_cid, depth + 1))
        finally:
            page.close()
        return results

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context()
        ctx.add_cookies(pw_cookies)
        page = ctx.new_page()
        page.goto(
            f"{BB_BASE}/webapps/blackboard/content/listContent.jsp"
            f"?course_id=_{course_id_str}_1&content_id=_{course_id_str}_1",
            wait_until="domcontentloaded", timeout=20000
        )
        page.wait_for_timeout(3000)
        top_links = []
        seen = set()
        for a in page.query_selector_all("a"):
            href = a.get_attribute("href") or ""
            text = (a.inner_text() or "").strip()
            if "content_id=_" not in href or not text or len(text) < 3:
                continue
            m = re.search(r"content_id=_(\d+)_\s*", href)
            if m and m.group(1) not in seen:
                seen.add(m.group(1))
                top_links.append((m.group(1), text))
        page.close()

        all_results = []
        seen_ids = set()
        for cid, title in top_links:
            for uid, utitle in visit_page(ctx, course_id_str, cid):
                if uid not in seen_ids:
                    seen_ids.add(uid)
                    all_results.append((uid, utitle))
        browser.close()
        return all_results
