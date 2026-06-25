#!/usr/bin/env python3
"""
BB Assignment Submitter

CLI subcommands:
  python3 -m sustech_survival.bb submit <content_id> <file_path> [course_id] [--name NAME]
  python3 -m sustech_survival.bb check <content_id> [course_id]
  python3 -m sustech_survival.bb find <keyword>
  python3 -m sustech_survival.bb list-due [--limit N]

IMPORTANT: Always ask the user before running this.

Submission strategy (post 2026-06-07 fix):
  1. Copy the source PDF to a temp path whose basename IS the target filename
  2. set_input_files() on that path
  3. Poll newFile_table for the row to appear (BB's handler can be slow)
  4. Submit

No JS-side rename, no DataTransfer override, no manual dispatchEvent. BB
records the staged file's basename as the displayed filename. This avoids
the duplicate-file bug where the previous two-step flow produced 2 rows
in newFile_table (one with local name, one with the target name).

`name_override` (if provided) is the on-disk target basename — it is NOT
a separate JS-side rename flag. There is no JS rename path.
"""
import json, os, re, sys, argparse, base64, shutil, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
BB_BASE = "https://bb.sustech.edu.cn"
try:
    from .download import discover_attempt_ids, scrape_attempt_details, get_column_id_for_content
except ImportError:
    from download import discover_attempt_ids, scrape_attempt_details, get_column_id_for_content
from playwright.sync_api import sync_playwright

from sustech_survival.sso import BBAuth

from .result import (
    SubmitResult, SubmitStatus,
    success, failure, duplicate, dry_run as _dry_run_factory,
)

bb_auth = BBAuth()


def num_id(bb_id):
    """'_8053_1' -> '8053'"""
    m = re.search(r'_(\d+)_(\d+)$', str(bb_id))
    return m.group(1) if m else str(bb_id)


def clean_filename(name: str) -> str:
    """Strip OpenClaw UUID suffix for clean BB filename."""
    return re.sub(
        r'---[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?=\.)',
        '', name
    )


def load_cookies():
    """Load cookies for Playwright (list format for ctx.add_cookies)."""
    raw = bb_auth.load()
    return [{"name": k, "value": v, "domain": ".bb.sustech.edu.cn", "path": "/"} for k, v in raw.items() if v]


def requests_session():
    """Return a requests.Session with BB cookies attached."""
    import requests as _requests
    sess = _requests.Session()
    cookies = bb_auth.load()
    for name, value in cookies.items():
        if value:
            sess.cookies.set(name, value, domain=".bb.sustech.edu.cn", path="/")
    return sess


# ─────────────────────────────────────────────────────────────────
# AI-facing wrappers  (migrated from __main__.py)
# ─────────────────────────────────────────────────────────────────

def submit_file(content_id, file_path, course_id=None, submitted_name=None):
    """
    Submit a file to a BB assignment.

    Renamed from `submit()` on 2026-06-08 to fix the module-shadowing bug:
    `bb/__init__.py` was doing `from .submit import submit`, which bound
    the function to the `bb` package namespace and broke
    `import sustech_survival.bb.submit as m` (it returned the function
    instead of the module). Use `submit_file()` going forward, or
    `submit_assignment()` for the lower-level primitive.

    Returns (success: bool, message: str).
    """
    from sustech_survival.bb.download import resolve_course

    if course_id is None:
        course_id = resolve_course(content_id)
        if not course_id:
            return False, f"Cannot resolve course_id for content_id={content_id}. Provide --course explicitly."

    course_num = num_id(course_id)
    cid = num_id(content_id)

    file_path = Path(file_path).expanduser().resolve()
    if not file_path.exists():
        return False, f"File not found: {file_path}"

    clean_name = clean_filename(file_path.name)
    target_name = submitted_name if submitted_name else clean_name
    if target_name != file_path.name:
        import shutil, tempfile
        clean_path = Path(tempfile.gettempdir()) / target_name
        shutil.copy2(file_path, clean_path)
        file_to_upload = clean_path
    else:
        file_to_upload = file_path

    result = submit_assignment(course_num, cid, [str(file_to_upload)],
                              skip_dedup=True, name_override=target_name)
    # Backwards compat: keep the legacy (ok, msg) tuple for the CLI.
    # New code should use the SubmitResult directly.
    return result.to_tuple()


def check_attempts(content_id, course_id=None):
    """Return (attempt_count, assignment_name)."""
    from sustech_survival.bb.download import resolve_course
    if course_id is None:
        course_id = resolve_course(content_id)
    result = get_attempt_info(num_id(course_id), num_id(content_id))
    return result[0], result[1]


def list_upcoming(limit=10):
    """List all upcoming BB assignments with due dates."""
    from sustech_survival.bb.courses import load_courses
    cookies = load_cookies()
    courses = load_courses()

    def num(bb_id):
        m = re.search(r'_(\d+)_(\d+)$', str(bb_id))
        return m.group(1) if m else str(bb_id)

    upcoming = []

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

    def due_sort(item):
        m = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', item[4])
        if m:
            return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return (9999, 99, 99)

    upcoming.sort(key=due_sort)
    return upcoming[:limit]


def find_assignment(keyword):
    """Search all BB pages for an assignment by keyword."""
    from sustech_survival.bb.courses import load_courses
    from sustech_survival.bb.download import discover_attempt_ids
    cookies = load_cookies()
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
                    if keyword.lower() in title.lower():
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


def submit_assignment(course_id, content_id, file_paths, skip_dedup=False,
                     text_content=None, name_override=None,
                     dry_run=False, headless=True):
    """Submit file(s) to a BB assignment.

    Returns (ok: bool|None, message: str). ok=None means "DUPLICATE detected
    and skip_dedup=False" (the caller can decide to retry with skip_dedup=True).

    Args:
        course_id: numeric course ID (no underscores), e.g. '8221'
        content_id: numeric content ID (no underscores), e.g. '626071'
        file_paths: list of local file paths to upload
        skip_dedup: if True, submit even if a prior attempt has the same name
        text_content: optional inline text to attach (rarely used)
        name_override: target basename to use as the BB-side filename. This
                       is the on-disk basename, NOT a JS-side rename. If the
                       source file already has the right name, no copy is made.
        dry_run: if True, stop after the file is in the table — do NOT submit.
                 Returns (True, "DRY-RUN: rows=N, link_titles=[...]").
        headless: Playwright headless flag (default True)
    """
    cookies = load_cookies()
    # Refresh the session first so cookies on disk + in-memory are current.
    # Without this, load_cookies() may return stale cookies (the on-disk file
    # is only written on login, not on every in-memory refresh).
    try:
        bb_auth.refresh()
    except Exception as e:
        print(f"  ⚠️  Session refresh failed (continuing with on-disk cookies): {e}")
        # Fall back: populate in-memory from on-disk so requests_session works
        if cookies:
            bb_auth.set_session({c["name"]: c["value"] for c in cookies})
    # Re-load cookies from the in-memory cache (post-refresh) so Playwright uses fresh
    cookies = [
        {"name": c.name, "value": c.value, "domain": ".bb.sustech.edu.cn", "path": "/"}
        for c in bb_auth.requests_session.cookies if c.value
    ]
    resolved = []
    for fp in file_paths:
        p = Path(fp).resolve()
        if not p.exists():
            return failure(f"File not found: {p}", reason="file_not_found")
        if not p.stat().st_size:
            return failure(f"File is empty: {p}", reason="file_empty")
        resolved.append(p)

    total_size = sum(p.stat().st_size for p in resolved)
    print(f"  Files: {', '.join(p.name for p in resolved)}")
    print(f"  Total size: {total_size:,} bytes")
    print(f"  Course: {course_id}, Content: {content_id}")

    primary_file = resolved[0]
    # Strip the OpenClaw UUID suffix (e.g. '---cf8274ec-fab1-42d9-b616-3ab999b940cf')
    clean_name = re.sub(r'---[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?=\.)', '', primary_file.name)
    if clean_name != primary_file.name:
        print(f"  Stripped UUID suffix: {primary_file.name} -> {clean_name}")

    fname = name_override if name_override else clean_name
    # Validate: must be a plain basename (no path separators)
    fname = Path(fname).name
    if not fname:
        return False, f"name_override is not a valid basename: {name_override!r}"

    # ── Step 0: Pre-rename. Copy source to /tmp/bb_submits/<fname> if needed.
    # BB records the staged file's basename as the displayed filename. By
    # giving the file the right name on disk, we avoid any JS-side rename.
    # This is the 2026-06-07 fix for the duplicate-file bug.
    staged_dir = Path(tempfile.gettempdir()) / "bb_submits"
    staged_dir.mkdir(parents=True, exist_ok=True)
    staged_path = staged_dir / fname
    if staged_path.resolve() != primary_file.resolve():
        shutil.copy2(primary_file, staged_path)

    # ── Step 0b: Deduplication check (best-effort, REST-based) ──────────────
    # Compare the staged filename against prior attempts. Uses REST not Playwright
    # so it doesn't trigger the session shadowing bug in get_column_id_for_content.
    # Failures are silently ignored (the previous Playwright version is a fallback).
    prior_files = []
    try:
        import urllib.parse
        # Build a quick requests session for the dedup REST check.
        # bb_auth.requests_session is already populated from the refresh above.
        _sess = bb_auth.requests_session
        # column_id is needed for /attempts; look it up via gradebook columns
        cols = _sess.get(
            f"{BB_BASE}/learn/api/public/v1/courses/_{course_id}_1/gradebook/columns",
            params={"_fields": "id,contentId"},
            timeout=10,
        ).json().get("results", [])
        col_id = None
        for c in cols:
            if c.get("contentId") == f"_{content_id}_1":
                col_id = c.get("id")
                break
        if col_id:
            r = _sess.get(
                f"{BB_BASE}/learn/api/public/v1/courses/_{course_id}_1/gradebook/columns/{col_id}/attempts",
                timeout=10,
            )
            if r.status_code == 200:
                # The API doesn't return file names — only the attempt list.
                # So we just report the count. The actual filename comparison
                # would need Playwright (which is the previous slow path).
                attempts_count = len(r.json().get("results", []))
                if attempts_count > 0:
                    print(f"  ℹ️  {attempts_count} prior attempt(s) found for this assignment")
    except Exception as e:
        print(f"  Dedup REST check failed (continuing anyway): {e}")

    if prior_files and not skip_dedup:
        return duplicate(
            f"DUPLICATE: '{fname}' already submitted in {prior_files}",
            prior_files=prior_files,
        )

    # ── Step 1: Launch Playwright, navigate, dismiss dialog, set_input_files ─
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        try:
            ctx = browser.new_context()
            ctx.add_cookies(cookies)
            page = ctx.new_page()
            page.set_viewport_size({"width": 1280, "height": 900})

            # Load upload page. content_id MUST come before course_id; group_id= required.
            new_attempt_url = (
                f"{BB_BASE}/webapps/assignment/uploadAssignment"
                f"?action=newAttempt&content_id=_{content_id}_1&course_id=_{course_id}_1&group_id="
            )
            page.goto(new_attempt_url, wait_until="domcontentloaded", timeout=30000)
            # Wait for network idle so BB's JS handlers (Prototype.js + jQuery) finish
            # initializing. Without this, set_input_files fires the change event before
            # the handler is bound, and the file is never added to newFile_table.
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            page.wait_for_timeout(2000)

            # Dismiss privacy dialog. The page has TWO [role=dialog] elements:
            # a fullscreen lb-wrapper lightbox (1280x720) and the inner visible
            # dialog (418x284). Only the inner one has the real "确定" button.
            # Skip the wrapper — clicking its button is a no-op or a mis-click.
            page.evaluate("""
            (function(){
                var dialogs = document.querySelectorAll('[role=dialog]');
                for (var i=0; i<dialogs.length; i++){
                    var d = dialogs[i];
                    var rect = d.getBoundingClientRect();
                    if (rect.width >= 1000 && rect.height >= 700) continue;  // skip wrapper
                    var btns = d.querySelectorAll('button');
                    for (var j=0; j<btns.length; j++){
                        var t = (btns[j].innerText || '').trim();
                        if (t === '确定' || t === 'OK' || t === 'Accept' || t === 'I agree') {
                            btns[j].click();
                            return;
                        }
                    }
                }
            })()
            """)
            page.wait_for_timeout(1500)

            # ── Step 2: set_input_files on the staged path. ─────────────────
            # This is the ONLY file-handling step. No DataTransfer, no JS File
            # override, no manual change-event dispatch. set_input_files fires
            # its own change event; BB's handler reads the file's basename and
            # adds 1 row to newFile_table.
            fi = page.query_selector("#newFile_chooseLocalFile")
            if not fi:
                return failure("File input not found on page", reason="dom_missing")
            fi.set_input_files([str(staged_path)])

            # Poll newFile_table for up to 10s. BB's handler can be slow on
            # first attempt — Vue reactive state + jQuery form setup.
            def _read_state():
                return page.evaluate("""
                (function(){
                    var fi = document.getElementById('newFile_chooseLocalFile');
                    var inputCount = fi ? fi.files.length : -1;
                    var tbl = document.getElementById('newFile_table');
                    if (!tbl) return [inputCount, -1, []];
                    var tbody = tbl.querySelector('tbody');
                    if (!tbody) return [inputCount, -2, []];
                    var rows = tbody.querySelectorAll('tr');
                    var titles = [];
                    tbody.querySelectorAll('[name=newFile_linkTitle]').forEach(function(e){titles.push(e.value)});
                    return [inputCount, rows.length, titles];
                })()
                """)
            row_count = 0
            link_titles = []
            for _ in range(20):  # 20 × 500ms = 10s
                page.wait_for_timeout(500)
                input_count, row_count, link_titles = _read_state()
                if row_count > 0:
                    break

            if row_count <= 0:
                return failure(
                    f"BB did not add file to table after 10s poll "
                    f"(input_files={input_count}, link_titles={link_titles})",
                    reason="dom_poll_timeout",
                    row_count=row_count,
                    link_titles=list(link_titles),
                )

            # Verify: the single row's linkTitle should equal our target basename
            if row_count > 1:
                print(f"  ⚠️  Table has {row_count} rows (expected 1) — possible duplicate file bug")
            if link_titles and link_titles[0] != fname:
                print(f"  ⚠️  linkTitle mismatch: expected {fname!r}, got {link_titles[0]!r}")

            diag = f"rows={row_count}, link_titles={link_titles}, staged={staged_path}"

            if dry_run:
                return _dry_run_factory(
                    message=f"DRY-RUN: {diag}",
                    staged_path=staged_path,
                    link_titles=tuple(link_titles),
                    row_count=row_count,
                )

            # ── Step 3: BB dedup check + submit ───────────────────────────────
            page.evaluate("checkDupeFile('submit')")
            submit_form = page.evaluate("submit_form")
            if not submit_form:
                return failure(
                    f"checkDupeFile rejected submission. {diag}",
                    reason="check_dupe_rejected",
                )

            page.evaluate("document.getElementById('uploadAssignmentFormId').submit()")
            page.wait_for_timeout(8000)

            url = page.url
            title = page.title()
            body = page.evaluate("(function(){return document.body.innerText})()")[:500]

            if ("Review Submission" in title or "reviewSubmission" in url
                    or "复查提交历史记录" in body):
                # Pull the confirmation UUID
                import re as _re
                m = _re.search(
                    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
                    body,
                )
                conf = m.group(1) if m else "no-conf-num"
                return success(
                    message=f"SUCCESS. Confirmation: {conf}. {diag}\nURL: {url}",
                    destination_url=url,
                    confirmation_uuid=conf,
                    staged_path=staged_path,
                    link_titles=tuple(link_titles),
                    row_count=row_count,
                )
            if "错误" in body or "error" in body.lower():
                return failure(
                    f"Error: {body[:300]}\n{diag}",
                    reason="post_submit_error",
                    destination_url=url,
                )
            return success(
                message=f"Complete (verify manually). URL: {url}\n{diag}",
                destination_url=url,
                staged_path=staged_path,
                link_titles=tuple(link_titles),
                row_count=row_count,
                verification="manual",
            )
        finally:
            browser.close()


def get_attempt_info(course_id, content_id):
    """Check BB to find existing attempt count and assignment name.
    Returns (attempt_count, assignment_name, session_valid).
    Uses the shared discover_attempt_ids from session.py (same logic as
    bb_download_submissions.py) to reliably enumerate all prior attempts.
    """
    cookies = load_cookies()

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context()
        ctx.add_cookies(cookies)

        # Get assignment name from the upload page title
        # Uses correct param order: content_id before course_id, with group_id=
        page = ctx.new_page()
        page.goto(
            f'{BB_BASE}/webapps/assignment/uploadAssignment'
            f'?action=newAttempt&content_id=_{content_id}_1&course_id=_{course_id}_1&group_id=',
            wait_until='domcontentloaded',
            timeout=20000
        )
        page.wait_for_timeout(3000)
        title = page.title() or ''
        m = re.search(r'Upload Assignment:\s*(.+)', title)
        assignment_name = m.group(1).strip() if m else 'unknown'
        page.close()

        # Discover all prior attempts + files using the reliable shared logic
        attempts = discover_attempt_ids(ctx, course_id, content_id)
        attempt_count = len(attempts)

        if attempts:
            last_ts = attempts[-1][1][1]  # (aid, (num, ts))
            print(f"  Prior attempts found: {attempt_count} (last: {last_ts})")
            # Show file names per attempt
            for aid, (anum, ts) in attempts:
                try:
                    details = scrape_attempt_details(ctx, course_id, content_id, aid)
                    files_str = ', '.join([f"'{n}'" for n, _ in details.get('files', [])]) or 'no files'
                    graded = '✅' if details.get('graded') else '⬜'
                    score = details.get('score', '')
                    score_str = f" [{score}]" if score else ''
                    print(f"    [{graded}] Attempt {anum} ({ts}) — {files_str}{score_str}")
                except Exception:
                    print(f"    Attempt {anum} ({ts})")
        else:
            print(f"  No prior submissions found on BB.")

        return attempt_count, assignment_name, True


def main():
    parser = argparse.ArgumentParser(description="Submit BB Assignment")
    parser.add_argument("--course", required=True, help="Course ID (numeric)")
    parser.add_argument("--content", required=True, help="Content/section ID (numeric)")
    parser.add_argument("--files", required=False, nargs='+', help="File path(s)")
    parser.add_argument("--yes", action="store_true", help="Skip confirmation prompt")
    parser.add_argument("--list", action="store_true", help="List prior attempts only, do not submit")
    parser.add_argument("--name", help="Override submitted filename (instead of local filename)")
    args = parser.parse_args()

    print("BB Assignment Submitter")
    print(f"  Course: {args.course}, Content: {args.content}")
    if args.files:
        print(f"  Files: {', '.join(args.files)}")
    print()

    # Check session validity first
    session_ok, reason = check_session()
    if not session_ok:
        print(f"❌ {reason}")
        sys.exit(1)

    # Check session + attempt count
    try:
        attempt_count, assignment_name, session_ok = get_attempt_info(args.course, args.content)
    except Exception as e:
        print(f"❌ Could not reach BB: {e}")
        sys.exit(1)

    if not session_ok:
        print("❌ Session invalid or expired. Run `bb.py refresh` first.")
        sys.exit(1)

    next_attempt = attempt_count + 1
    print(f"  Assignment: {assignment_name}")
    print(f"  Prior attempts: {attempt_count}")
    print(f"  This would be: attempt #{next_attempt}")
    print()

    if args.list:
        # --list only: show attempts and exit
        print("Use --files to submit.")
        sys.exit(0)

    if not args.files:
        print("❌ --files required. Use --list to see prior attempts first.")
        sys.exit(1)

    print("⚠️  WARNING: This will submit a REAL file to Blackboard.")
    print("   It counts as an official submission attempt.")
    print()

    if not args.yes:
        if sys.stdin.isatty():
            try:
                response = input("Proceed with submission? [y/N]: ").strip().lower()
                if response != 'y':
                    print("Aborted. No submission made.")
                    sys.exit(0)
            except EOFError:
                print("No terminal input. Use --yes flag.")
                sys.exit(1)
        else:
            print("Not a TTY. Use --yes flag to confirm.")
            sys.exit(1)

    success, msg = submit_assignment(args.course, args.content, args.files, name_override=args.name)
    print()
    if success is None and msg.startswith("DUPLICATE"):
        print(f"⚠️  {msg}")
        print("Submit anyway? Use --yes to override.")
        if not args.yes:
            try:
                response = input("Submit anyway? [y/N]: ").strip().lower()
                if response != 'y':
                    print("Aborted.")
                    sys.exit(0)
            except EOFError:
                print("No terminal input. Use --yes flag.")
                sys.exit(1)
            # Retry without dedup check (user explicitly chose to submit)
            success, msg = submit_assignment(args.course, args.content, args.files, skip_dedup=True, name_override=args.name)
            if success is None:
                print(f"❌ {msg}")
                sys.exit(1)
    elif success:
        print(f"✅ {msg}")
    else:
        print(f"❌ {msg}")
        sys.exit(1)


if __name__ == "__main__":
    main()
