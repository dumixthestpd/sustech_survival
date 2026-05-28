# Pages — BB page scraping
"""
Page-level scraping: Page class, course page discovery, content page scraping,
announcements, and item preview.
"""

import re
from dataclasses import dataclass, field
from typing import List, Tuple

from playwright.sync_api import sync_playwright

BB_BASE = "https://bb.sustech.edu.cn"

try:
    from .items import (
        Item, FileItem, VideoItem, HomeworkItem, InlineItem, LinkItem,
        TextItem, FolderItem, UnknownItem, _classify_item, _html_to_text,
    )
except ImportError:
    from items import (
        Item, FileItem, VideoItem, HomeworkItem, InlineItem, LinkItem,
        TextItem, FolderItem, UnknownItem, _classify_item, _html_to_text,
    )


# Item type identifiers (class attribute on each subclass)
ITEM_TYPES = {
    "file": "file",
    "video": "video",
    "homework": "homework",
    "folder": "folder",
    "inline": "inline",
    "link": "link",
    "text": "text",
    "unknown": "unknown",
}


@dataclass
class Page:
    """
    A BB content page, scraped in real-time.

    Attributes:
        content_id   Global BB content ID (e.g. "612447")
        course_id    Numeric course ID (e.g. "8343")
        course_name  Name of the course
        title        Display title of this page
        bb_url       URL to this page
        children     List of child content_ids nested under this page
                     (pages that appear below this one in the BB tree)
    """
    content_id: str
    course_id: str = ""
    course_name: str = ""
    title: str = ""
    bb_url: str = ""
    children: List[str] = field(default_factory=list)

    def to_row(self):
        """content_id, course_id, course_name, title, children count."""
        return (
            f"{self.content_id}\t{self.course_id}\t{self.course_name[:40]}\t"
            f"{self.title[:40]}\t{len(self.children)}"
        )

    def __repr__(self):
        return self.to_row()


def _classify_page(page, bb_url: str, content_id: str) -> Tuple[List[str], str]:
    """
    Inspect a content page and return (children, bb_url).
    children = list of content_ids nested under this page.
    bb_url = URL of this page (returned for use by caller).
    """
    children = []

    # Collect links from the MAIN content area only (not sidebar nav)
    main_area = page.query_selector("#content") or page
    links = main_area.query_selector_all("a[href]")

    for a in links:
        href = a.get_attribute("href") or ""
        # Child content — only count links that:
        # 1. Are listContent pages within the same course
        # 2. Are NOT self-referencing
        # 3. Do NOT look like file downloads
        if ("listContent.jsp" in href
                and "content_id=" in href
                and not any(k in href for k in ["bbcswebdav", "xid-", "download"])):
            m = re.search(r'content_id=_(\d+)_', href)
            if m:
                child_id = m.group(1)
                if child_id != content_id:
                    children.append(child_id)

    return children, bb_url


from sustech_survival.sso import BBAuth

_bb = BBAuth()

def _playwright_cookies():
    """Load BB session in Playwright list format for ctx.add_cookies()."""
    raw = _bb.load()
    return [{"name": k, "value": v, "domain": ".bb.sustech.edu.cn", "path": "/"} for k, v in raw.items() if v]


def scrape_page(course_id: str, content_id: str,
                raw_cookies=None,
                course_name: str = "") -> Page:
    """
    Scrape a single BB content page in real-time (no cache).

    Args:
        course_id:   numeric course ID (e.g. "8343")
        content_id: global BB content ID (e.g. "612447")
        raw_cookies: playwright cookies [optional, auto-loaded if None]
        course_name: name of the course [optional, auto-loaded if empty]

    Returns:
        Page with title, bb_url, and children populated.
    """
    if raw_cookies is None:
        ensure_session()
        raw_cookies = _playwright_cookies()

    item_url = (
        f"{BB_BASE}/webapps/blackboard/content/listContent.jsp"
        f"?course_id=_{course_id}_1&content_id=_{content_id}_1&mode=reset"
    )

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context()
        ctx.add_cookies(raw_cookies)
        page = ctx.new_page()

        try:
            page.goto(item_url, wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(1500)

            # Dismiss dialogs
            for _ in range(3):
                d = page.query_selector('[role="dialog"]')
                if not d: break
                b = d.query_selector("button")
                if b:
                    b.click()
                    page.wait_for_timeout(400)

            # Title: use h1 in pageTitleDiv if available (content title only)
            # page.title() = "Week 6 – EAP Spring 2026" → just "Week 6"
            title_div = page.query_selector("#pageTitleDiv")
            if title_div:
                h1 = title_div.query_selector("h1")
                title = h1.inner_text().strip() if h1 else page.title().split(" – ")[0].strip()
            else:
                title = page.title().split(" – ")[0].strip()

            # If course_name not provided, extract from page title: "Week 6 – EAP Spring 2026"
            if not course_name and " – " in page.title():
                course_name = page.title().split(" – ", 1)[1].strip()

            children, _ = _classify_page(page, item_url, content_id)

        finally:
            page.close()

    return Page(
        content_id=content_id,
        course_id=course_id,
        course_name=course_name,
        title=title.strip(),
        bb_url=item_url,
        children=children,
    )


def discover_course_pages(course_id: str):
    """
    Fast sidebar-only discovery of all content pages in a BB course.
    Visits the course home page and extracts (content_id, title) pairs
    from the sidebar. Does NOT scrape individual pages.

    Returns list of (content_id, title, section) tuples.
    """
    ensure_session()
    cookies = _playwright_cookies()

    course_url = (
        f"{BB_BASE}/webapps/blackboard/content/listContent.jsp"
        f"?course_id=_{course_id}_1&content_id=_{course_id}_1"
    )

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context()
        ctx.add_cookies(cookies)
        page = ctx.new_page()
        page.goto(course_url, wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(1500)

        sidebar = page.query_selector("#courseMenuPalette_contents") or page

        results = []
        current_section = ""
        seen = set()

        for li in sidebar.query_selector_all("li"):
            cls = li.get_attribute("class") or ""
            if "subhead" in cls:
                h3 = li.query_selector("h3 span")
                current_section = h3.inner_text().strip() if h3 else ""
            elif "clearfix" in cls:
                a = li.query_selector("a")
                if not a:
                    continue
                href = a.get_attribute("href") or ""
                title = a.inner_text().strip()
                if not title or "content_id=" not in href:
                    continue
                m = re.search(r"content_id=_(\d+)_", href)
                if not m:
                    continue
                cid = m.group(1)
                if cid in seen:
                    continue
                seen.add(cid)
                results.append((cid, title, current_section))

        browser.close()
        return results


# ═══════════════════════════════════════════════════════════════════
# Homework — submission count & deadline from uploadAssignment page
# ═══════════════════════════════════════════════════════════════════

from datetime import datetime

# Parsed deadline + submission count from an uploadAssignment page
_HW_CACHE: dict = {}  # sub_id → (submission_count, deadline_str)


def _fetch_homework_details(upload_url: str, sub_id: str) -> tuple:
    """
    Visit an uploadAssignment page and extract:
    - submission_count: number of attempts already submitted (0 if none)
    - deadline_str:     human-readable deadline string from the page

    Results are cached per sub_id to avoid re-fetching.
    Returns (submission_count: int, deadline_str: str).
    """
    if sub_id in _HW_CACHE:
        return _HW_CACHE[sub_id]

    ensure_session()
    cookies = _playwright_cookies()

    submission_count = 0
    deadline_str = ""

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            ctx = browser.new_context()
            ctx.add_cookies(cookies)
            page = ctx.new_page()

            full_url = upload_url if upload_url.startswith("http") else BB_BASE + upload_url
            page.goto(full_url, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(3000)

            body = page.inner_text("body") or ""

            # ── Deadline ─────────────────────────────────────────────
            # Pattern: "Due Date\nWednesday, April 22, 2026\n11:59 PM"
            due_m = re.search(
                r"(?:Due Date|Closed Date|Due):?\s*\n?\s*"
                r"(\w+,\s+\w+\s+\d{1,2},\s+\d{4})\s*\n?\s*(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))",
                body,
                re.DOTALL | re.IGNORECASE,
            )
            if due_m:
                date_str = due_m.group(1).strip()   # "Wednesday, April 22, 2026"
                time_str = due_m.group(2).strip()   # "11:59 PM"
                deadline_str = f"{date_str} {time_str}"
            else:
                # Fallback: look for just the date pattern anywhere
                simple = re.search(
                    r"(?:Due|Closed|Deadline):?\s*\n?\s*"
                    r"(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})",
                    body,
                )
                if simple:
                    deadline_str = f"{simple.group(1)} {simple.group(2)}"

            # ── Submission count ────────────────────────────────────
            # Pattern: "Attempt 1 of 3", "Submission 2 of 5", etc.
            # or check for existing submitted files / submission history
            attempt_m = re.search(
                r"Attempt\s+(\d+)\s+(?:of|/)\s*(\d+)",
                body,
                re.IGNORECASE,
            )
            if attempt_m:
                submission_count = int(attempt_m.group(1))
            else:
                # Check for "1 of 2 submissions" pattern
                sub_m = re.search(
                    r"(\d+)\s+of\s+(\d+)\s+submission",
                    body,
                    re.IGNORECASE,
                )
                if sub_m:
                    submission_count = int(sub_m.group(1))

            # Also check for explicit "not submitted yet" or "no submission"
            if submission_count == 0:
                if re.search(r"no\s+submission|submission\s+not\s+made|not\s+yet\s+submitted", body, re.I):
                    submission_count = 0
                elif re.search(r"you have submitted|attempt history|previous submission", body, re.I):
                    # Count submission entries in history
                    hist = re.findall(r"(?:Submission|Attempt)\s+\d+", body)
                    submission_count = len(hist)

            page.close()
    except Exception as e:
        pass  # graceful degradation: leave count=0, deadline=""

    _HW_CACHE[sub_id] = (submission_count, deadline_str)
    return submission_count, deadline_str


# ═══════════════════════════════════════════════════════════════════
# Page / Sub-Item Preview — inspect items within a content page
# ═══════════════════════════════════════════════════════════════════

def preview_page(content_id: str, course_id: str = None) -> List[Item]:
    """
    Scrape all items within a BB content page.

    Visits the content page and parses every <li class="...contentListItem...">
    sub-item inside it, extracting titles, attachments, inline content,
    external URLs, and homework upload links.

    Args:
        content_id: global BB content ID (e.g. "598334")
        course_id:  numeric course ID (e.g. "8157"). Auto-resolved if omitted.

    Returns:
        list of Item, one per item on the page

    Example:
        items = preview_page("598334")
        for item in items:
            print(item.title, item.has_attachment)
    """
    # Import here to avoid circular reference (resolve_course uses download.py)
    from download import resolve_course

    if course_id is None:
        course_id = resolve_course(content_id)

    ensure_session()
    cookies = _playwright_cookies()

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context()
        ctx.add_cookies(cookies)
        page = ctx.new_page()
        page.goto(
            f"{BB_BASE}/webapps/blackboard/content/listContent.jsp"
            f"?course_id={course_id}&content_id={content_id}&mode=reset",
            wait_until="domcontentloaded",
            timeout=15000,
        )
        page.wait_for_timeout(1500)

        # Dismiss dialogs
        for _ in range(3):
            d = page.query_selector('[role="dialog"]')
            if not d:
                break
            b = d.query_selector("button")
            if b:
                b.click()
                page.wait_for_timeout(400)

        main = page.query_selector("#content")
        if main is None:
            page.close()
            return []

        # Find all content list item rows
        # They appear as <li id="contentListItem:{sub_id}:1" class="...">
        lis = main.query_selector_all("li")
        items = []
        homework_uploads = {}  # sub_id → upload_url, collected for post-browser fetch

        for li in lis:
            li_html = li.inner_html()
            # Only process if it looks like a content item row
            classes = li.get_attribute("class") or ""
            li_id = li.get_attribute("id") or ""

            # Extract sub_id from li_id like "contentListItem:_598524_1"
            m = re.search(r"contentListItem:_(\d+)_", li_id)
            if not m:
                continue
            sub_id = m.group(1)

            # Title from h3
            h3 = li.query_selector("h3")
            title = h3.inner_text().strip() if h3 else ""

            # Description: the vtbegenerated div contains the rich text body
            vtb = li.query_selector(".vtbegenerated")
            desc_html = vtb.inner_html().strip() if vtb else ""
            desc_text = _html_to_text(desc_html)

            # All links in this sub-item
            links = li.query_selector_all("a[href]")
            files = []
            ext_urls = []
            upload_url = ""
            content_link = ""

            for a in links:
                href = a.get_attribute("href") or ""
                text = a.inner_text().strip()[:60]
                if "bbcswebdav" in href or "xid-" in href:
                    files.append((text, href))
                elif "uploadAssignment" in href:
                    upload_url = href
                elif "content_id=" in href and "listContent" in href:
                    content_link = href
                elif href.startswith("http") and "bbcswebdav" not in href:
                    ext_urls.append((text, href))

            # Inline images: bbcswebdav images INSIDE vtbegenerated div (not file downloads)
            inline_imgs = []
            video_url = ""
            if vtb:
                # Embedded images
                for img in vtb.query_selector_all("img[src]"):
                    src = img.get_attribute("src") or ""
                    if "bbcswebdav" in src or "xid-" in src:
                        inline_imgs.append(src)
                # Embedded iframes (video players)
                for iframe in vtb.query_selector_all("iframe[src]"):
                    src = iframe.get_attribute("src") or ""
                    if "/video/player" in src or "tx-vod-BBLEARN" in src:
                        video_url = src
                        break

            # Classify and construct the correct Item subclass
            item = _classify_item(
                sub_id, title, "",
                desc_text, desc_html,
                files, inline_imgs, ext_urls,
                upload_url, video_url,
                content_link,
            )
            items.append(item)

            # Track homework items for later deadline fetch
            if item.is_homework:
                homework_uploads[sub_id] = upload_url

        page.close()

    # ── Fetch homework details OUTSIDE the Playwright block ──────────
    # Nested playwright launches conflict with parent browser session
    for sub_id, upload_url in homework_uploads.items():
        _, deadline_str = _fetch_homework_details(upload_url, sub_id)
        for item in items:
            if item.sub_id == sub_id:
                item.deadline = deadline_str
                break

    return items


# ═══════════════════════════════════════════════════════════════════
# Announcements Scraper
# ═══════════════════════════════════════════════════════════════════

def scrape_announcements(course_id: str) -> List[Item]:
    """
    Scrape all announcements for a course.

    Announcements live at a separate endpoint (/execute/announcement...)
    and are NOT part of the content page hierarchy.

    Args:
        course_id: numeric course ID (e.g. "8343")

    Returns:
        list of Item, one per announcement

    Example:
        for ann in scrape_announcements("8343"):
            print(ann.title)
            print(ann.description)
    """
    ensure_session()
    cookies = _playwright_cookies()

    ann_url = (
        f"{BB_BASE}/webapps/blackboard/execute/announcement"
        f"?method=search&context=course_entry"
        f"&course_id=_{course_id}_1&handle=announcements_entry&mode=view"
    )

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context()
        ctx.add_cookies(cookies)
        page = ctx.new_page()
        page.goto(ann_url, wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(1500)

        ann_list = page.query_selector("ul.announcementList")
        items = []
        if ann_list:
            for li in ann_list.query_selector_all("li"):
                lid = li.get_attribute("id") or ""
                # Extract sub_id from id like "_42933_1"
                m = re.search(r"_(\d+)_1", lid)
                sub_id = m.group(1) if m else ""

                h3 = li.query_selector("h3.item")
                title = h3.inner_text().strip() if h3 else ""

                details = li.query_selector(".details")
                vtb = details.query_selector(".vtbegenerated") if details else None
                desc_html = vtb.inner_html().strip() if vtb else ""
                desc_text = _html_to_text(desc_html)

                # Extract posted date
                posted_date = ""
                if details:
                    date_m = re.search(r"Posted on: (.+?)(?:\n|$)", details.inner_text())
                    if date_m:
                        posted_date = date_m.group(1).strip()

                items.append(Item(
                    sub_id=sub_id,
                    title=title,
                    description=desc_text,
                    description_html=desc_html,
                ))

        page.close()

    return items
