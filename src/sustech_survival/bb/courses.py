# Courses — course data loading, discovery, and live scraping
"""
Course loading, listing, finding, and assignment discovery.
All pulled from session.py during the modularization.
"""
import json, re, sys
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from playwright.sync_api import sync_playwright

try:
    from .session import BB_BASE, load_session
except ImportError:
    from session import BB_BASE, load_session

BB_DIR = Path(__file__).resolve().parent
COURSES_FILE = BB_DIR / "courses.json"
STRUCTURE_FILE = BB_DIR / "structure.json"

# ── Live Scraping — get YOUR enrolled courses from BB portal ──────────────────

SKIP_COURSE_NAMES = {
    '大学物理', '高等数学', 'college physics', 'higher mathematics',
    '微积分', '线性代数', 'calculus', 'linear algebra',
}

BB_PORTAL = "https://bb.sustech.edu.cn/webapps/portal/execute/tabs/tabAction?tab_tab_group_id=_1_1"


def scrape_enrolled_courses() -> List[Dict[str, str]]:
    """
    Visit the BB portal "课程" tab and extract the CURRENT USER's enrolled courses.
    Uses Playwright JS to find 'courseMain' and 'launcher?type=Course' links.

    Returns list of dicts: [{"id": "_8343_1", "name": "Physical Chemistry...", "href": "..."}, ...]

    Raises RuntimeError if not logged in.
    """
    raw, pw = load_session()
    if not pw:
        raise RuntimeError("Not logged into BB — run 'bb.py login' first")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context()
        ctx.add_cookies(pw)

        page = ctx.new_page()
        page.goto(BB_PORTAL, timeout=15000)
        page.wait_for_timeout(6000)

        if 'login' in page.url.lower():
            browser.close()
            raise RuntimeError("BB session expired — re-login required")

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
        seen_ids = set()
        for cl in course_links:
            href = cl['href']
            # Extract course_id from either courseMain?course_id=_XXX_1 or launcher?type=Course&id=_XXX_1
            # Extract course_id — two URL formats:
            #   courseMain?course_id=_XXX_1   → extract _XXX_1
            #   launcher?type=Course&id=_XXX_1 → extract _XXX_1
            m = re.search(r'(?:course_id|id)=(_?\d+_?\d+)', href)
            if not m:
                continue
            raw = m.group(1)  # e.g. "8053_1" or "_8462_1" or "30021580_2026SP_1"
            # Normalize: strip leading _, split, take first numeric segment, append _1
            raw = raw.lstrip('_')
            num = raw.split('_')[0]  # first numeric part
            if not num.isdigit():
                continue
            cid = f"_{num}_1"
            if cid in seen_ids:
                continue
            name = re.sub(r'^→\s*|^《|》$', '', cl['text'].strip())
            name = re.sub(r'\s*\(?\d{4}[-/]\d{1,2}\)?\s*$', '', name).strip()
            if not name or len(name) < 3:
                continue
            # Skip catch-all/non-course recordings (physics/math lecture recordings)
            if any(sn.lower() in name.lower() for sn in SKIP_COURSE_NAMES):
                continue
            seen_ids.add(cid)
            courses.append({'id': cid, 'name': name, 'href': href})

        return courses


def refresh_courses_json() -> List[Dict[str, str]]:
    """
    Scrape live from BB portal and update courses.json.
    Returns the scraped course list.
    """
    courses = scrape_enrolled_courses()
    COURSES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(COURSES_FILE, 'w') as f:
        json.dump({"courses": courses, "ts": __import__('time').time()}, f, indent=2, ensure_ascii=False)
    print(f"Updated {COURSES_FILE} with {len(courses)} courses.")
    for c in courses:
        print(f"  - {c['name']} ({c['id']})")
    return courses

# ── Course Data ─────────────────────────────────────────────────────────────

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


# ── Course Discovery ────────────────────────────────────────────────────────

NAV_NOISE = {"打开快速链接", "页面标志", "内容大纲", "键盘快捷键", "Top Frame Tabs",
                "Current Location", "Menu Management Options", "Course Menu:"}


def _get_content_title(page, content_id):
    """Get the content page title. Tries page title, then filtered h1/h2, then falls back."""
    # Page title is most reliable: "Page Name – Course Name" or "Page Name"
    title_el = page.query_selector("title")
    if title_el:
        txt = title_el.inner_text().strip()
        # Strip " – Course Name" suffix and leading "--" or "- " from BB naming
        if " – " in txt:
            txt = txt.split(" – ")[0]
        txt = txt.lstrip("-").lstrip(" ").strip()
        if txt and len(txt) > 2:
            return txt

    # h1/h2/h3: skip navigation chrome
    for selector in ("h1", "h2", "h3"):
        for el in page.query_selector_all(selector):
            txt = el.inner_text().strip()
            if txt and len(txt) > 2 and txt not in NAV_NOISE and txt.startswith("--"):
                return txt.lstrip("-").strip()
    return f"Content {content_id}"


def discover_assignments_for_course(pw_cookies, course_id_str):
    """
    Discover all BB uploadAssignment slots for a course.

    Returns list of (assignment_content_id, title) tuples.

    Uses structure.json to get content IDs, then visits each content page
    sequentially in one browser to find uploadAssignment links.

    Falls back to slow recursive crawl if structure.json is unavailable.
    """
    from playwright.sync_api import sync_playwright
    from session import BB_BASE

    # Fast path: use structure.json for content IDs, sequential single-browser check
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

                        # Dismiss cookie dialog
                        for _ in range(3):
                            d = page.query_selector('[role="dialog"]')
                            if not d: break
                            b = d.query_selector("button")
                            if b:
                                b.click()
                                page.wait_for_timeout(400)

                        for a in page.query_selector_all("a"):
                            href = a.get_attribute("href") or ""
                            if "uploadAssignment" not in href or "action=" in href:
                                continue
                            m = re.search(r"content_id=_(\d+)_", href)
                            if not m: continue
                            upload_cid = m.group(1)
                            title = _get_content_title(page, upload_cid)
                            results.append((upload_cid, title))
                            break  # one assignment per content page
                    except Exception:
                        pass
                    finally:
                        page.close()

                browser.close()

                if results:
                    return results

    # Slow fallback: recursive crawl
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
                if not d: break
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
                if not m: continue
                cid = m.group(1)
                if cid in seen: continue
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
            if "content_id=_" not in href or not text or len(text) < 3: continue
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
