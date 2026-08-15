# Pages — thin REST-based shim (2026-08-10 refactor)
"""
Page-level scraping for bb/. This module used to be Playwright-based; it
was rewritten to REST after the codebase already had canonical REST helpers
in ``sustech_survival.bb.query`` (the canonical entry points for course
discovery + content tree walking + item metadata).

Use ``sustech_survival.bb.query`` directly for new code:

  - discover_courses()         → /learn/api/public/v1/courses
  - walk_contents(course_id)   → /learn/api/public/v1/courses/{cid}/contents[/...]
  - discover_pages(course_id)  → walks the tree, returns [(cid, title, section)]
  - scrape_page_items(cid, course_id, course_name)
                               → /learn/api/public/v1/courses/{bid}/contents/{cid}
                                  with _fields=id,title,body,contentHandler,hasChildren
  - classify_item_type(handler) → maps contentHandler.id → item type string
  - resolve_course(content_id) → reverse-lookup

What this shim still provides (for backward compat with cli.py + tests):

  - bb_auth           : BBAuth singleton (re-exported from query.py)
  - preview_page(...) : REST-based replacement for the old Playwright
                        preview_page(); converts query.scrape_page_items()
                        dicts → Item subclass instances
"""
from __future__ import annotations

import re
from typing import List

# Canonical REST helpers — use these directly in new code.
from sustech_survival.bb.query import (
    api,
    classify_item_type,
    discover_courses,
    discover_pages,
    extract_bbcswebdav,
    resolve_course,
    scrape_page_items,
    walk_contents,
)
from sustech_survival.bb.items import (
    Item, FileItem, VideoItem, HomeworkItem, InlineItem, LinkItem,
    TextItem, FolderItem, UnknownItem, html_to_text,
)

# BBAuth singleton — re-exported for test_bb_session.py + cli.py.
from sustech_survival.sso import BBAuth
bb_auth = BBAuth()

BB_BASE = "https://bb.sustech.edu.cn"


def _dict_to_item(row: dict) -> Item:
    """Convert one row dict (from query.scrape_page_items) → Item subclass.

    Mapping:
      "file"      → FileItem (files: list of (name, url))
      "video"     → VideoItem (video_url: first bbcswebdav URL from body)
      "homework"  → HomeworkItem (deadline, course_id, content_id)
      "folder"    → FolderItem (sub_id only)
      "inline"    → InlineItem (inline_imgs: list of bbcswebdav URLs)
      "link"      → LinkItem (ext_urls: empty)
      "text"      → TextItem (description: body stripped)
      "unknown"   → UnknownItem
    """
    itype = row.get("type", "unknown")
    sub_id = row.get("id", "")
    title = row.get("title", "")
    desc = row.get("desc", "")
    files = row.get("files", []) or []
    bid = f"_{row.get('course', '')}_1"
    cid = f"_{sub_id}_1"
    bb_url = f"{BB_BASE}/webapps/blackboard/content/listContent.jsp?course_id={bid}&content_id={cid}"

    if itype == "file":
        return FileItem(sub_id, title, bb_url, desc, "", files=files)
    if itype == "video":
        video_url = files[0][1] if files else ""
        return VideoItem(sub_id, title, bb_url, desc, "", video_url=video_url)
    if itype == "homework":
        course_id = row.get("course", "")
        return HomeworkItem(
            sub_id, title, bb_url, desc, "",
            files=[], submission_count=row.get("n", 0),
            deadline=row.get("ddl", ""),
            content_id=sub_id, course_id=course_id, group_id="",
        )
    if itype == "folder":
        return FolderItem(sub_id, title, bb_url, desc, "")
    if itype == "inline":
        return InlineItem(sub_id, title, bb_url, desc, "",
                          inline_imgs=[u for _, u in files])
    if itype == "link":
        return LinkItem(sub_id, title, bb_url, desc, "", ext_urls=[])
    if itype == "text":
        return TextItem(sub_id, title, bb_url, desc, "")
    return UnknownItem(sub_id, title, bb_url, desc, "")


def preview_page(content_id: str, course_id: str = None) -> List[Item]:
    """REST-based replacement for the old Playwright preview_page().

    Fetches the content item via /learn/api/public/v1/courses/{bid}/contents/{cid}
    and converts the resulting dict → Item subclass. Returns a list (typically
    length 1) of Item instances matching the old Item-API surface that cli.py
    consumes.

    Args:
        content_id: global BB content ID (e.g. "598334")
        course_id:  numeric course ID (e.g. "8157"). Auto-resolved if omitted.

    Returns:
        list of Item instances (may be empty if REST fails or content_id not found)

    Example:
        items = preview_page("598334")
        for item in items:
            print(item.title, item.has_attachment)
    """
    if course_id is None:
        course_id = resolve_course(content_id)
    rows = scrape_page_items(content_id, course_id, course_name="")
    return [_dict_to_item(r) for r in rows]


__all__ = [
    # Re-exports for backward compatibility
    "bb_auth",
    "api",
    "BB_BASE",
    # Functions (legacy API preserved)
    "preview_page",
    # Also expose canonical REST helpers
    "discover_courses",
    "discover_pages",
    "walk_contents",
    "scrape_page_items",
    "classify_item_type",
    "resolve_course",
    "extract_bbcswebdav",
    # Item classes re-exported for cli.py convenience
    "Item", "FileItem", "VideoItem", "HomeworkItem", "InlineItem",
    "LinkItem", "TextItem", "FolderItem", "UnknownItem",
]