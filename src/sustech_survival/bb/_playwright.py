"""
bb _playwright — Playwright-required BB functions.

This module is the ONLY place in the bb/ package that imports playwright.
Everything else is pure REST. If a function is in here, the user needs
`pip install playwright && playwright install chromium` to use it.

What requires Playwright (and why pure REST doesn't work):

  1. **Scrape submitted file URLs** (`scrape_attempt_files_via_browser`):
     The gradebook REST API returns attempt metadata but NOT the URLs of
     the actual submitted files. The only way to find those URLs is to
     render the assignment view page in a browser, where Prototype.js
     builds them dynamically from session-bound form state.

  2. **Text-only resubmits via VTBE** (`_bb_text_resubmit_via_browser`):
     The `BB?BB_` VTBE encryption key lives in opaque session storage
     (403 from `requests`). The TinyMCE iframe does server-side encryption
     via DWR + `window.postMessage` — the key is in the VTBE server's
     response, never exposed to client JS. So text submission requires
     a real browser.

What does NOT require Playwright (already in download.py / submit_rest.py):
  - File uploads (multipart POST with newFile_LocalFile0)
  - Course/content tree walking
  - Gradebook column / attempt discovery
  - Content file URLs for x-bb-document (bbcswebdav)
  - Authentication via the REST `requests.Session`

The split is enforced at the import level: if you `import bb._playwright`,
you opt into the Playwright dependency. The other bb/ modules never
import this — they raise a clear ImportError if a caller asks for a
Playwright-only function.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Tuple
from urllib.parse import unquote

import re


def scrape_attempt_files_via_browser(
    course_id: str,
    content_id: str,
    attempt_id: str,
) -> Tuple[str, List[Tuple[str, str]]]:
    """Navigate assignment view page via Playwright to collect file download links.

    Returns (timestamp_str, [(filename, url)]).

    The gradebook REST API does not expose submitted file URLs — only the
    attempt metadata (id, created, score, feedback). The file URLs are
    constructed by Prototype.js when rendering the view page, using a
    session-bound token. This is the only place in the bb/ package that
    Playwright is required.

    Per the user's directive: "if the user asks for text submission, then
    let them install playwright to do it" — file DOWNLOAD is in the same
    boat. Most agents don't need it; the rare "download my submission" flow
    is the one case where Playwright earns its keep.
    """
    from playwright.sync_api import sync_playwright
    import sustech_survival.bb.submit as bb_submit  # local to avoid circular

    cookies = bb_submit.load_cookies()

    page_url = (
        f"https://bb.sustech.edu.cn/webapps/assignment/uploadAssignment"
        f"?course_id=_{course_id}_1&content_id=_{content_id}_1"
        f"&attempt_id=_{attempt_id}_1&mode=view"
    )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        ctx.add_cookies(cookies)
        page = ctx.new_page()
        page.goto(page_url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2000)

        # Dismiss dialogs
        for _ in range(5):
            d = page.query_selector('[role="dialog"]')
            if not d:
                break
            btn = d.query_selector("button")
            if btn:
                btn.click()
                page.wait_for_timeout(600)

        # Timestamp
        ts = ""
        try:
            dp = page.query_selector(r"text=/\d{1,2}[-/]\d{1,2}[-/]\d{2,4}/")
            ts = dp.inner_text()[:40] if dp else ""
        except Exception:
            pass

        # File links
        files = []
        seen = set()
        for a in page.query_selector_all("a"):
            href = a.get_attribute("href") or ""
            if "download" not in href.lower():
                continue
            if href in seen:
                continue
            seen.add(href)
            fname_raw = re.search(r"fileName=([^&]+)", href)
            fname = unquote(fname_raw.group(1)) if fname_raw else "file"
            files.append((_slugify(fname), href))

        page.close()
    return ts, files


def _slugify(name: str) -> str:
    """Minimal slugify for filenames — same as download.slugify but local to avoid
    a hard dependency on bb.download at import time."""
    name = re.sub(r"[^\w\s.-]", "_", name)
    return re.sub(r"\s+", "_", name).strip("_")[:200]


__all__ = ["scrape_attempt_files_via_browser"]
