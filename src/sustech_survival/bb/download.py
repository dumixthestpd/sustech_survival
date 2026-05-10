#!/usr/bin/env python3
"""
BB Downloader Module — download course materials and submitted assignments.

Content IDs are globally unique in Blackboard — no course_id needed.

API:
  from download import download_content

  download_content("612447")         # experiment manual (course material)
  download_content("612345")         # lab report submission (if already submitted)

  # Lower-level (returns filename+url, no download):
  from download import scrape_content_files
  title, files = scrape_content_files("612447")

CLI (submissions only):
  python3 download.py --course 8343
  python3 download.py --content 612342 --attempt 1
"""

import json, os, re, sys, argparse
from pathlib import Path
from urllib.parse import unquote

import requests
from playwright.sync_api import sync_playwright

BB_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BB_DIR))

try:
    from .session import BB_BASE, ensure_session, load_session, slugify
except ImportError:
    from session import BB_BASE, ensure_session, load_session, slugify

DEFAULT_ASSIGNMENTS = [
    ("612409", "Experiment 0-Safety Notification"),
    ("612342", "Experiment 1-Report (Combustion)"),
    ("612344", "Experiment 2-Report (Rotation)"),
    ("612346", "Experiment 3-Report (Binary)"),
    ("612349", "Experiment 4-Report (Vapor pressure) A"),
    ("612354", "Experiment 4-Report (Vapor pressure) B"),
    ("612459", "Experiment 5-Report (Tension)"),
    ("612356", "Experiment 6-Report (Viscosity)"),
    ("612358", "Experiment 7-Report (EMF)"),
]


def parse_filename_from_url(url):
    m = re.search(r'fileName=([^&]+)', url)
    return unquote(m.group(1)) if m else None


def pct_decode(string):
    """Decode percent-encoded string (e.g. %E6%AE%B5... → Chinese chars)."""
    return re.sub(r'%([0-9A-Fa-f]{2})', lambda x: chr(int(x.group(1), 16)), string)


def dismiss_dialogs(page):
    for _ in range(5):
        dialog = page.query_selector('[role="dialog"]')
        if not dialog:
            break
        btn = dialog.query_selector("button")
        if btn:
            btn.click()
            page.wait_for_timeout(600)


def scrape_attempt_files(ctx, course_id, content_id, attempt_id):
    """
    Navigate to a specific attempt's view page and collect its download links.
    Returns (timestamp_str, [(filename, url)])

    Preview (no download): pass ctx from preview_attempt() instead.
    """
    page = ctx.new_page()
    page.goto(
        f"{BB_BASE}/webapps/assignment/uploadAssignment"
        f"?course_id=_{course_id}_1&content_id=_{content_id}_1"
        f"&attempt_id={attempt_id}&mode=view",
        wait_until="domcontentloaded",
        timeout=30000,
    )
    page.wait_for_timeout(2000)

    dismiss_dialogs(page)

    # Get timestamp from visible text
    # Look for the date pattern (e.g. "26-3-28" or "2026-3-28") near the attempt header
    ts = ""
    try:
        date_pattern = page.query_selector(r"text=/\d{1,2}[-/]\d{1,2}[-/]\d{2,4}/")
        if date_pattern:
            ts = date_pattern.inner_text()[:40]
    except Exception:
        pass

    # Collect download links
    files = []
    seen = set()
    for a in page.query_selector_all("a"):
        href = a.get_attribute("href") or ""
        if "download" not in href.lower():
            continue
        if href in seen:
            continue
        seen.add(href)
        fname_raw = parse_filename_from_url(href) or "file"
        fname = slugify(pct_decode(fname_raw))
        files.append((fname, href))

    page.close()
    return ts, files


def preview_attempt(course_id: str, content_id: str, attempt_id: str) -> dict:
    """
    Preview a submission attempt — returns file info WITHOUT downloading.

    Checks the file URL via HEAD request to get Content-Disposition and size.
    Also checks for image feedback in comments.

    Returns dict:
      timestamp   — submission datetime
      files       — list of {name, url, size_bytes, content_type, is_image}
      graded      — bool
      grade       — numeric string or None
      comment     — plain text (images replaced with [图片反馈])
      comment_images — list of image URLs found in comment
      comment_date — feedback timestamp or None
    """
    raw, pw = load_session()
    session_cookies = {c["name"]: c["value"] for c in pw}

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context()
        ctx.add_cookies(pw)

        # Get attempt details (timestamp, files, grade, comments)
        details = scrape_attempt_details(ctx, course_id, content_id, attempt_id)

        # For each file, do a ranged GET to get size + content-type without downloading full file
        enriched_files = []
        for fname, href in details.get("files", []):
            full_url = href if href.startswith("http") else BB_BASE + href
            try:
                # Use a range request to get content-type + size without downloading the whole file
                r = requests.get(full_url, cookies=session_cookies,
                                  timeout=10, stream=True,
                                  headers={"Range": "bytes=0-0"})
                r.close()
                ct = r.headers.get("Content-Type", "application/octet-stream")
                # Try Content-Length from range response first, then from headers
                cl = r.headers.get("Content-Length") or r.headers.get("Content-Range", "").split("/")[-1]
                try:
                    size = int(cl)
                except (ValueError, IndexError):
                    size = 0
            except Exception:
                size = 0
                ct = "application/octet-stream"
            is_img = any(img_type in ct.lower() for img_type in ["image/", "jpeg", "png", "gif", "webp"])
            enriched_files.append({
                "name": fname,
                "url": full_url,
                "size_bytes": size,
                "content_type": ct,
                "is_image": is_img,
            })

        # Extract image URLs from comment HTML
        comment_imgs = []
        if details.get("comment_html"):
            comment_imgs = re.findall(r'<img[^>]+src="([^"]+)"', details["comment_html"])

        browser.close()

        return {
            "timestamp": details.get("timestamp", ""),
            "files": enriched_files,
            "graded": details.get("graded", False),
            "grade": details.get("grade"),
            "comment": details.get("comment"),
            "comment_images": comment_imgs,
            "comment_date": details.get("comment_date"),
        }


def scrape_attempt_details(ctx, course_id, content_id, attempt_id):
    """
    Navigate to a specific attempt's view page and collect all details.

    Returns a dict:
      timestamp     — submission datetime string
      files         — list of (filename, url)
      graded        — bool, whether the attempt has been graded
      grade         — numeric string (e.g. "88.00") or None
      comment       — plain text of feedback (images replaced with [图片反馈]) or None
      comment_html  — raw HTML of feedback content, or None
      comment_date  — feedback timestamp or None
    """
    page = ctx.new_page()
    page.goto(
        f"{BB_BASE}/webapps/assignment/uploadAssignment"
        f"?course_id=_{course_id}_1&content_id=_{content_id}_1"
        f"&attempt_id={attempt_id}&mode=view",
        wait_until="domcontentloaded",
        timeout=30000,
    )
    page.wait_for_timeout(2000)

    dismiss_dialogs(page)

    # Timestamp
    ts = ""
    try:
        date_pattern = page.query_selector(r"text=/\d{1,2}[-/]\d{1,2}[-/]\d{2,4}/")
        if date_pattern:
            ts = date_pattern.inner_text()[:40]
    except Exception:
        pass

    # Files
    files = []
    seen = set()
    for a in page.query_selector_all("a"):
        href = a.get_attribute("href") or ""
        if "download" not in href.lower():
            continue
        if href in seen:
            continue
        seen.add(href)
        fname_raw = parse_filename_from_url(href) or "file"
        fname = slugify(pct_decode(fname_raw))
        files.append((fname, href))

    # Grading / feedback check
    graded = False
    grade = None
    comment = None
    comment_html = None
    comment_date = None

    try:
        comment_el = page.query_selector(".comment")
        if comment_el:
            vtb = comment_el.query_selector(".vtbegenerated")
            if vtb:
                graded = True
                html = vtb.inner_html()
                # Grade: check aggregateGrade input value (always shows last graded score)
                try:
                    agg_el = page.query_selector("#aggregateGrade")
                    if agg_el:
                        g = agg_el.get_attribute("value") or ""
                        grade = g.strip() or None
                except Exception:
                    pass
                # Comment text — replace images with marker
                text_parts = []
                for child in vtb.query_selector_all("*"):
                    try:
                        tag = child.evaluate("el => el.tagName")
                        if tag == "IMG":
                            text_parts.append("[图片反馈]")
                        else:
                            t = child.inner_text().strip()
                            if t:
                                text_parts.append(t)
                    except Exception:
                        pass
                comment = " ".join(text_parts).strip() or None
                comment_html = html

            # Comment date
            try:
                date_el = comment_el.query_selector(".dateStamp")
                if date_el:
                    comment_date = date_el.inner_text().strip()
            except Exception:
                pass
    except Exception:
        pass

    page.close()
    return {
        "timestamp": ts,
        "files": files,
        "graded": graded,
        "grade": grade,
        "comment": comment,
        "comment_html": comment_html,
        "comment_date": comment_date,
    }


def download_file(out_path, download_url, session_cookies):
    resp = requests.get(BB_BASE + download_url, cookies=session_cookies,
                        timeout=30, stream=True)
    resp.raise_for_status()
    with open(out_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=65536):
            f.write(chunk)
    return out_path


# ── Course Material Download (experiment manuals, slides, etc.) ─────────────

_CONTENT_ID_MAP = None

def _build_cid_map():
    """Build content_id → course_id mapping from courses.json."""
    global _CONTENT_ID_MAP
    if _CONTENT_ID_MAP is not None:
        return
    _CONTENT_ID_MAP = {}
    try:
        with open(BB_DIR / 'courses.json') as f:
            d = json.load(f)
        for c in d.get('courses', []):
            for sec_items in c.get('sections', {}).values():
                for item in sec_items:
                    icid = str(item.get('cid', ''))
                    if icid and not icid.startswith('tool_'):
                        _CONTENT_ID_MAP[icid] = c['id']
    except Exception:
        pass  # courses.json may not exist yet


def resolve_course(content_id):
    """Return the course_id that owns this content_id."""
    _build_cid_map()
    course_id = _CONTENT_ID_MAP.get(str(content_id))
    if course_id:
        return course_id
    raise ValueError(f"content_id {content_id} not found in courses.json — scrape first with bb.py scrape")


def _fetch_content_page(ctx, course_id, content_id):
    """Visit content page and return (page_title, [(filename, href)])."""
    page = ctx.new_page()
    try:
        page.goto(
            f"{BB_BASE}/webapps/blackboard/content/listContent.jsp"
            f"?course_id=_{course_id}_1&content_id=_{content_id}_1&mode=reset",
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

        title = page.inner_text('title') or str(content_id)

        files = []
        for a in page.query_selector_all('a[href]'):
            href = a.get_attribute('href') or ''
            name = a.inner_text() or ''
            if ('bbcswebdav' in href or '/download' in href
                    or 'fileName=' in href or 'xid-' in href) and name.strip():
                files.append((name.strip(), href))

        return title, files
    finally:
        page.close()


def scrape_content_files(content_id):
    """
    Scrape downloadable files from a BB content page by content_id alone.

    Returns:
        (title: str, files: list of (name, href))
        Raises ValueError if content_id is not in courses.json.
    """
    ensure_session()
    raw, pw = load_session()
    course_id = resolve_course(content_id)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context()
        ctx.add_cookies(pw)
        return _fetch_content_page(ctx, course_id, content_id)


def download_content(content_id, out_dir=None):
    """
    Download all files from a BB content page (experiment manual, slides, etc.).

    Args:
        content_id: global BB content ID (e.g. "612447" for PhysChem Exp 3)
        out_dir: output directory (default: ~/Downloads/BB-content/)

    Returns:
        list of saved file paths

    Raises:
        ValueError if content_id is not found in courses.json

    Example:
        download_content("612447")  # Experiment 3 Binary Phase Diagram
    """
    title, files = scrape_content_files(content_id)
    if not files:
        print(f"[download_content] No files on page: {title}")
        return []

    out_dir = Path(out_dir) if out_dir else Path.home() / 'Downloads' / 'BB-content'
    out_dir.mkdir(parents=True, exist_ok=True)

    raw, pw = load_session()
    session_cookies = {c['name']: c['value'] for c in pw}

    saved = []
    for name, url in files:
        full_url = url if url.startswith('http') else BB_BASE + url
        try:
            r = requests.get(full_url, cookies=session_cookies,
                              timeout=30, stream=True, allow_redirects=True)
            r.raise_for_status()

            # Filename from Content-Disposition or fall back to link text
            cd = r.headers.get('Content-Disposition', '')
            m = re.search(r'filename[*]?["\']?([^"\';]+)', cd)
            if m:
                filename = m.group(1).strip('"').strip("'")
            else:
                filename = name

            out_path = out_dir / filename
            with open(out_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=65536):
                    f.write(chunk)
            saved.append(str(out_path))
            size = out_path.stat().st_size
            print(f"  ✓ {title}: {filename} ({size} bytes)")
        except Exception as e:
            print(f"  ✗ {name}: {e}")

    return saved


def download_course_assignments(session_cookies, pw_cookies, course_id,
                                  assignments, output_dir, attempt_filter=None):
    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context()
        ctx.add_cookies(pw_cookies)

        for content_id, title in assignments:
            out_dir = output_dir / slugify(title)
            out_dir.mkdir(parents=True, exist_ok=True)

            print(f"\n  [{content_id}] {title[:40]}")

            # Step 1: discover all attempts for this assignment
            try:
                attempts = discover_attempt_ids(ctx, course_id, content_id)
            except Exception as e:
                print(f"    ⚠ Failed to discover attempts: {e}")
                attempts = []

            if not attempts:
                print(f"    No submission history found")
                results.append({"content_id": content_id, "title": title,
                                 "downloaded": [], "count": 0, "errors": []})
                continue

            print(f"    {len(attempts)} attempt(s) found")
            for aid, (anum, ts) in attempts:
                print(f"      Attempt {anum} ({ts[:25]}): {aid}")

            # Step 2: fetch files for each attempt
            total_files = 0
            for aid, (anum, ts) in attempts:
                if attempt_filter is not None and anum != attempt_filter:
                    continue

                try:
                    ats, files = scrape_attempt_files(ctx, course_id, content_id, aid)
                except Exception as e:
                    print(f"    ⚠ Attempt {anum}: scrape error: {e}")
                    files = []

                # Deduplicate by filename
                unique_files = []
                seen_fnames = set()
                for fname, href in files:
                    if fname not in seen_fnames:
                        seen_fnames.add(fname)
                        unique_files.append((fname, href))
                files = unique_files

                print(f"    Attempt {anum}: {len(files)} file(s)")
                total_files += len(files)

                for fname, href in files:
                    if len(attempts) > 1:
                        stem, ext = os.path.splitext(fname)
                        out_path = out_dir / f"attempt{anum}_{stem}{ext}"
                    else:
                        out_path = out_dir / fname

                    if out_path.exists():
                        print(f"      (exists: {out_path.name})")
                        continue
                    try:
                        downloaded_path = download_file(out_path, href, session_cookies)
                        size = downloaded_path.stat().st_size
                        print(f"      ✓ {out_path.name} ({size:,})")
                    except Exception as e:
                        print(f"      ✗ {fname}: {e}")

            results.append({
                "content_id": content_id,
                "title": title,
                "count": total_files,
                "downloaded": [],
                "errors": [],
            })

        browser.close()

    return results


# ── Attempt Discovery (used by download_course_assignments) ─────────────────

def discover_attempt_ids(ctx, course_id, content_id):
    """Visit submission history, expand all attempts. Returns sorted list."""
    page = ctx.new_page()
    page.goto(
        f"{BB_BASE}/webapps/assignment/uploadAssignment"
        f"?course_id=_{course_id}_1&content_id=_{content_id}_1",
        wait_until="domcontentloaded",
        timeout=30000,
    )
    page.wait_for_timeout(2000)

    for _ in range(5):
        d = page.query_selector('[role="dialog"]')
        if not d: break
        b = d.query_selector("button")
        if b: b.click(); page.wait_for_timeout(600)

    toggle = page.query_selector("text=单击以显示/隐藏所有尝试")
    if toggle:
        try:
            toggle.click(timeout=3000)
            page.wait_for_timeout(1500)
        except Exception: pass

    html = page.content()
    all_aids = list(dict.fromkeys(m.group(1) for m in re.finditer(r'attempt_id=([^&\s"\']+)', html)))

    attempt_info = {}
    for row in page.query_selector_all(".attemptInfo, .attemptNumber"):
        try:
            txt = row.inner_text().strip()
            # Try Chinese "第 X 次尝试" first, then English "Attempt X"
            m = re.match(r'第\s*(\d+)\s*次尝试\s*(.+)', txt)
            if not m:
                m = re.match(r'Attempt\s+(\d+)\s*(.+)', txt, re.IGNORECASE)
            if not m: continue
            anum, ts = int(m.group(1)), m.group(2).strip()[:30]
            try:
                aid = row.evaluate("""
                    el => {
                        let cur = el;
                        for (let i = 0; i < 10 && cur; cur = cur.parentElement, i++) {
                            const html = cur.innerHTML || '';
                            const m = html.match(/attempt_id=([^&\\s"']+)/);
                            if (m) return m[1];
                        }
                        return '';
                    }
                """)
            except Exception:
                aid = ""
            if aid and aid in all_aids:
                attempt_info[aid] = (anum, ts)
        except Exception: continue

    for i, aid in enumerate(all_aids):
        if aid not in attempt_info:
            attempt_info[aid] = (i + 1, "unknown")

    result = sorted(attempt_info.items(), key=lambda x: x[1][0])
    page.close()
    return result  # [(attempt_id, (num, timestamp)), ...]


# ── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Download BB submitted files (all attempts)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--course",  default="8343",
                        help="Course ID (default: 8343 — Physical Chemistry)")
    parser.add_argument("--content",  help="Download only this content_id")
    parser.add_argument("--output",  default="./downloads",
                        help="Output directory (default: ./downloads)")
    parser.add_argument("--attempt", type=int, default=None,
                        help="Download only this attempt number (1-based)")

    args = parser.parse_args()
    output_dir = Path(args.output)

    assignments = DEFAULT_ASSIGNMENTS if args.course == "8343" and not args.content else []

    if args.content:
        assignments = [(args.content, f"Assignment {args.content}")]
    elif not assignments:
        from courses import list_courses, discover_assignments_for_course
        courses = list_courses()
        found = [(cid, name) for cid, name in courses if args.course in cid]
        if found:
            cid_str, course_name = found[0]
            _, pw = load_session()
            assignments = discover_assignments_for_course(pw, cid_str)
            print(f"Discovered {len(assignments)} assignments for {course_name}")
        else:
            print(f"Unknown course {args.course} and no --content specified")
            sys.exit(1)

    session_cookies, pw_cookies = load_session()

    print(f"BB Submission Downloader (multi-attempt)")
    print(f"  Course:  {args.course}")
    print(f"  Assignments: {len(assignments)}")
    print(f"  Output:  {output_dir}")
    print(f"  Attempt filter: {args.attempt or 'all'}")

    all_results = download_course_assignments(
        session_cookies, pw_cookies, args.course, assignments,
        output_dir, attempt_filter=args.attempt,
    )

    total_files = sum(r["count"] for r in all_results)
    print(f"\n{'='*60}")
    print(f"Done: {total_files} files across {len(all_results)} assignments")
    for r in all_results:
        status = f"{r['count']} file(s)" if r["count"] else "no submissions"
        print(f"  [{r['content_id']}] {r['title'][:40]}: {status}")


# ── Homework Submission ───────────────────────────────────────────────────────

def submit_homework(content_id, file_path=None, *, course_id=None, comment=None, text_content=None, file_paths=None):
    """
    Submit a homework assignment by uploading files and/or text.

    Args:
        content_id:  homework content ID, e.g. "622821"  (or "_622821_1" also OK)
        file_path:   path to file (single file, for backward compat)
        course_id:   optional course ID (auto-resolved if omitted)
        comment:     optional comment text
        text_content: optional text content to submit
        file_paths:  list of file paths (preferred over file_path)

    Returns:
        True on success, raises RuntimeError on failure.

    Example:
        submit_homework("622821", file_paths=["/tmp/hw.pdf"], course_id="8221")
        submit_homework("622821", text_content="My answer here")
    """
    from .submit import submit_assignment

    # Resolve content_id
    cid = str(content_id).lstrip('_').split('_')[0]

    # Resolve course_id if not given
    if course_id is None:
        course_id = resolve_course(cid)
        if not course_id:
            raise ValueError(f"Cannot resolve course_id for content_id={cid}. "
                             "Specify course_id= explicitly.")

    course_num = str(course_id).lstrip('_').split('_')[0]

    # Build file list (file_paths preferred, file_path for compat)
    paths = file_paths or []
    if isinstance(file_path, (list, tuple)):
        paths = [str(p) for p in file_path]
    elif file_path:
        paths = [str(file_path)]

    ok, msg = submit_assignment(
        course_num, cid,
        paths,
        skip_dedup=True,
        text_content=text_content
    )
    if ok:
        return True
    raise RuntimeError(msg)

    # BB URL form IDs: course_id=_8221_1  content_id=_622821_1
    bb_course_id = f"_{course_num}_1"
    bb_content_id = f"_{cid}_1"

    upload_url = (
        f"{BB_BASE}/webapps/assignment/uploadAssignment"
        f"?content_id={bb_content_id}&course_id={bb_course_id}&group_id=&mode=view"
    )

    file_path = Path(file_path).expanduser().resolve()
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    # BB appends a hash to the uploaded filename — rename to a clean name
    # derived from the original, keeping only the meaningful parts
    original_name = file_path.name
    # Strip any trailing UUID-like segment (e.g. "---67d7c368-90f9-42e6...")
    import re
    clean_name = re.sub(r'-{3}[0-9a-f-]{36}\.([^.]+)$', r'.\1', original_name)
    if clean_name != original_name:
        import tempfile, os
        temp_dir = Path(tempfile.gettempdir())
        clean_path = temp_dir / clean_name
        import shutil
        shutil.copy2(file_path, clean_path)
        file_to_upload = clean_path
        print(f"[submit] Renamed: {original_name!r} → {clean_name!r}")
    else:
        file_to_upload = file_path

    print(f"[submit] Navigating to submission page...")
    errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context()
        ctx.add_cookies(pw)

        page = ctx.new_page()
        page.on("dialog", lambda d: (d.accept(), errors.append(d.message)))

        # 1. Navigate to the upload form
        page.goto(upload_url, timeout=15000)
        page.wait_for_load_state("networkidle", timeout=15000)

        # 2. Attach the file
        file_input = page.locator('input[type="file"]')
        file_input.set_input_files(str(file_to_upload), timeout=10000)
        print(f"[submit] File attached: {file_to_upload.name}")

        # 3. Dismiss cookie/privacy dialog if present
        for _ in range(5):
            dlg = page.query_selector('[role="dialog"]')
            if not dlg:
                break
            btns = dlg.query_selector_all("button")
            if btns:
                btns[0].click()
                page.wait_for_timeout(400)

        # 4. Optional comment
        if comment:
            # The rich-text iframe for comments
            frame = page.frame_locator('iframe[title="Rich Text Area"]')
            frame.locator("body").fill(comment)

        # 5. Click submit (it's an <input type="submit" name="bottom_提交">)
        page.click('input[name="bottom_提交"]', timeout=10000)

        # 5. Wait for redirect to history view (successful submit redirects to
        #    .../uploadAssignment?course_id=...&content_id=...&mode=view)
        page.wait_for_url(lambda url: "mode=view" in url and "content_id=" in url,
                          timeout=15000)
        page.wait_for_load_state("networkidle", timeout=15000)
        print(f"[submit] Redirected to: {page.url}")

        # 6. Check for success indicators
        page_text = page.inner_text('body')
        page_html = page.content()

        browser.close()

    success = (
        "成功" in page_text
        or "success" in page_text.lower()
        or "submitted" in page_text.lower()
        or "d0b057b9" in page_html  # confirmation ID prefix
    )

    if success:
        print(f"[submit] ✓ Submission successful!")
        return True

    raise RuntimeError(
        "Could not confirm submission success. "
        "Check the page manually to verify."
    )


if __name__ == "__main__":
    main()
