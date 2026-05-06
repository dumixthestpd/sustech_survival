#!/usr/bin/env python3
"""
BB Content & Submissions Discoverer — recursive version

Course home page → section pages → item pages (3 levels)
  Level 1: Course home → section links
  Level 2: Section page → item links (some sections nest items one level deeper)
  Level 3: Item page → downloadable files + submission history URL

Output: content_discovery.json with full mapping of all content items

Usage:
  python3 bb-discover-content.py              # all courses
  python3 bb-discover-content.py --course 8343  # one course
"""
import json, re, argparse
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("ERROR: playwright not installed.")
    exit(1)

BB_BASE = "https://bb.sustech.edu.cn"
SESSION_FILE = Path(__file__).parent / "session.json"
OUTPUT_FILE = Path(__file__).parent / "content_discovery.json"


def load_cookies():
    with open(SESSION_FILE) as f:
        raw = json.load(f)
    if isinstance(raw, list):
        return raw
    return [{"name": k, "value": v, "domain": "bb.sustech.edu.cn", "path": "/"}
            for k, v in raw.items()]


def dismiss_dialog(page):
    for _ in range(3):
        dialog = page.query_selector('[role="dialog"]')
        if not dialog:
            break
        btn = dialog.query_selector("button")
        if btn:
            btn.click()
            page.wait_for_timeout(800)


def visit_page_and_dismiss(page, url):
    """Navigate and dismiss any dialogs."""
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(2000)
    dismiss_dialog(page)


def extract_items_from_page(page, course_id):
    """
    Extract all content item links from a page.
    Returns list of {content_id, title, href, url_type}
    url_type: 'listContent' | 'inlineView' | 'uploadAssignment' | 'section'
    """
    items = []
    seen_cids = set()

    for a in page.query_selector_all("a"):
        href = a.get_attribute("href") or ""
        text = (a.inner_text() or "").strip()
        if not text or len(text) < 3:
            continue
        if "content_id=" not in href:
            continue

        m = re.search(r"content_id=_(\d+)_", href)
        if not m:
            continue
        cid = m.group(1)
        if cid in seen_cids:
            continue
        if cid == course_id:
            continue

        seen_cids.add(cid)

        if "uploadAssignment" in href and "action=" not in href:
            url_type = "uploadAssignment"
        elif "inlineView" in href:
            url_type = "inlineView"
        elif "listContent" in href:
            url_type = "listContent"
        else:
            url_type = "other"

        items.append({
            "content_id": cid,
            "title": text,
            "href": href,
            "url_type": url_type,
        })

    return items


def get_item_page_url(content_id, course_id):
    """Build the item page URL using listContent with mode=reset."""
    return (
        f"{BB_BASE}/webapps/blackboard/content/listContent.jsp"
        f"?course_id=_{course_id}_1&content_id=_{content_id}_1&mode=reset"
    )


def scrape_item_page(page, content_id, course_id, title):
    """
    Visit an item page and extract:
    - Downloadable files (bbcswebdav/download)
    - Submission history URL
    """
    url = get_item_page_url(content_id, course_id)
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(3000)
    dismiss_dialog(page)

    files = []
    submission_url = None

    for a in page.query_selector_all("a"):
        href = a.get_attribute("href") or ""
        text = (a.inner_text() or "").strip()

        if ("bbcswebdav" in href or "/download" in href
                or "&download=" in href) and text:
            files.append({"name": text, "href": href})

        if ("uploadAssignment" in href and "action=" not in href
                and "download" not in href):
            if not submission_url:
                submission_url = href

    return files, submission_url


def discover_course(ctx, course_id, course_title):
    """
    Full recursive discovery for one course.
    Returns list of discovered content items with files and submission URLs.
    """
    page = ctx.new_page()

    # ── Level 1: Course home → section links ─────────────────────────────────
    visit_page_and_dismiss(
        page,
        f"{BB_BASE}/webapps/blackboard/content/listContent.jsp"
        f"?course_id=_{course_id}_1&content_id=_{course_id}_1"
    )

    level1_items = extract_items_from_page(page, course_id)
    print(f"  Course home: {len(level1_items)} top-level links")

    all_items = []
    section_content_ids = set()

    # Categorize: sections (listContent) vs direct items
    for item in level1_items:
        if item["url_type"] == "listContent":
            section_content_ids.add(item["content_id"])
        else:
            # Direct item (inlineView or uploadAssignment) — scrape immediately
            all_items.append(item)

    # ── Level 2: Visit each section to find nested items ───────────────────
    for sec_cid in section_content_ids:
        sec_url = (
            f"{BB_BASE}/webapps/blackboard/content/listContent.jsp"
            f"?course_id=_{course_id}_1&content_id=_{sec_cid}_1"
        )
        visit_page_and_dismiss(page, sec_url)
        nested = extract_items_from_page(page, course_id)

        if nested:
            print(f"    Section {sec_cid}: {len(nested)} nested items")
            for item in nested:
                item["parent_section_id"] = sec_cid
                all_items.append(item)
        else:
            # Section with no nested items — it's a direct content page
            all_items.append({
                "content_id": sec_cid,
                "title": next(
                    (i["title"] for i in level1_items if i["content_id"] == sec_cid), f"Section_{sec_cid}"
                ),
                "href": sec_url,
                "url_type": "listContent",
                "parent_section_id": None,
            })

    page.close()

    # ── Level 3: Scrape each item page for files + submission URLs ──────────
    results = []
    for item in all_items:
        cid = item["content_id"]
        page2 = ctx.new_page()
        files, submission_url = scrape_item_page(
            page2, cid, course_id, item["title"]
        )
        page2.close()

        files_str = f"{len(files)} files" if files else "no files"
        sub_str = "has submission" if submission_url else "no submission"
        print(f"    [{cid}] {item['title'][:40]}: {files_str}, {sub_str}")

        results.append({
            "course_id": course_id,
            "course_title": course_title,
            "content_id": cid,
            "title": item["title"],
            "url_type": item["url_type"],
            "parent_section_id": item.get("parent_section_id"),
            "files": files,
            "submission_history_url": submission_url,
        })

    return results


def main():
    parser = argparse.ArgumentParser(description="Discover BB content + submissions")
    parser.add_argument("--course", help="Course ID (default: all)")
    parser.add_argument("--output", help="Output JSON file")
    args = parser.parse_args()

    output_file = Path(args.output) if args.output else OUTPUT_FILE

    # Get course list — try structure file or fall back to BB home
    courses = []
    structure_file = Path(__file__).parent / "structure.json"
    if structure_file.exists():
        with open(structure_file) as f:
            data = json.load(f)
        for course in data.get("courses", []):
            cid = course["course_id"]
            if args.course and cid != args.course:
                continue
            courses.append((cid, course.get("title", f"Course_{cid}")))
    else:
        # Must provide --course if no structure file
        if not args.course:
            print("ERROR: No structure file. Use --course to specify course ID.")
            exit(1)
        courses = [(args.course, f"Course_{args.course}")]

    print(f"BB Content Discovery — {len(courses)} course(s)")
    all_results = []

    cookies = load_cookies()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context()
        ctx.add_cookies(cookies)

        for cid, title in courses:
            print(f"\n{'='*60}")
            print(f"Course: {title} ({cid})")
            print(f"{'='*60}")
            results = discover_course(ctx, cid, title)
            all_results.extend(results)

        browser.close()

    # Save
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump({"discovered": all_results}, f, ensure_ascii=False, indent=2)

    total_files = sum(len(r["files"]) for r in all_results)
    total_subs = sum(1 for r in all_results if r["submission_history_url"])
    print(f"\n{'='*60}")
    print(f"Done: {len(all_results)} items, {total_files} files, {total_subs} with submissions")
    print(f"→ {output_file}")


if __name__ == "__main__":
    main()
