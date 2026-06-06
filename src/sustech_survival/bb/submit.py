#!/usr/bin/env python3
"""
BB Assignment Submitter

CLI subcommands:
  python3 -m sustech_survival.bb submit <content_id> <file_path> [course_id] [--name NAME]
  python3 -m sustech_survival.bb check <content_id> [course_id]
  python3 -m sustech_survival.bb find <keyword>
  python3 -m sustech_survival.bb list-due [--limit N]

IMPORTANT: Always ask the user before running this.
"""
import json, os, re, sys, argparse, base64
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
BB_BASE = "https://bb.sustech.edu.cn"
try:
    from .download import discover_attempt_ids, scrape_attempt_details, get_column_id_for_content
except ImportError:
    from download import discover_attempt_ids, scrape_attempt_details, get_column_id_for_content
from playwright.sync_api import sync_playwright

from sustech_survival.sso import BBAuth

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

def submit(content_id, file_path, course_id=None, submitted_name=None):
    """
    Submit a file to a BB assignment.
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

    ok, msg = submit_assignment(course_num, cid, [str(file_to_upload)],
                                skip_dedup=True, submitted_name=target_name)
    return ok, msg


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


def submit_assignment(course_id, content_id, file_paths, skip_dedup=False, text_content=None, name_override=None):
    cookies = load_cookies()
    resolved = []
    for fp in file_paths:
        p = Path(fp).resolve()
        if not p.exists():
            return False, f"File not found: {p}"
        if not p.stat().st_size:
            return False, f"File is empty: {p}"
        resolved.append(p)

    total_size = sum(p.stat().st_size for p in resolved)
    print(f"  Files: {', '.join(p.name for p in resolved)}")
    print(f"  Total size: {total_size:,} bytes")
    print(f"  Course: {course_id}, Content: {content_id}")

    primary_file = resolved[0]
    # Strip the OpenClaw UUID suffix (e.g. '---cf8274ec-fab1-42d9-b616-3ab999b940cf')
    # so the submitted filename is clean.
    clean_name = re.sub(r'---[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?=\.)', '', primary_file.name)
    if clean_name != primary_file.name:
        print(f"  Stripped UUID suffix: {primary_file.name} -> {clean_name}")

    with open(primary_file, 'rb') as f:
        file_content = f.read()
    file_b64 = base64.b64encode(file_content).decode()
    fname = name_override if name_override else clean_name

    # ── Step 0: Deduplication check ─────────────────────────────────────────
    # Compare against prior submissions by filename (UUID suffix + URL decode stripped)
    import urllib.parse, hashlib
    local_hash = hashlib.md5(file_content).hexdigest()
    local_clean = re.sub(r'---[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?=\.)', '', fname)

    prior_files = []
    try:
        with sync_playwright() as p_dedup:
            browser_d = p_dedup.chromium.launch()
            ctx_d = browser_d.new_context()
            ctx_d.add_cookies(cookies)
            attempts = discover_attempt_ids(ctx_d, course_id, content_id)
            for aid, (anum, _) in attempts:
                details = scrape_attempt_details(ctx_d, course_id, content_id, aid)
                for fname_on_bb, _ in details.get('files', []):
                    # URL-decode and strip UUID suffix, then compare
                    decoded = urllib.parse.unquote(fname_on_bb)
                    bb_clean = re.sub(r'---[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?=\.)', '', decoded)
                    if bb_clean == local_clean:
                        prior_files.append((anum, fname_on_bb, aid))
            browser_d.close()
    except Exception as e:
        print(f"  Dedup check failed (continuing anyway): {e}")

    if prior_files:
        dup_list = ', '.join([f"attempt {a} ('{n}')" for a, n, _ in prior_files])
        if not skip_dedup:
            return None, f"DUPLICATE: '{local_clean}' already submitted in {dup_list}"
        print(f"  ⚠️  Dedup: '{local_clean}' found in {dup_list} — submitting anyway")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context()
        ctx.add_cookies(cookies)
        page = ctx.new_page()
        page.set_viewport_size({"width": 1280, "height": 900})

        # Step 1: Load upload page
        # NOTE: content_id MUST come before course_id; group_id= must be present
        new_attempt_url = (
            f"{BB_BASE}/webapps/assignment/uploadAssignment"
            f"?action=newAttempt&content_id=_{content_id}_1&course_id=_{course_id}_1&group_id="
        )
        page.goto(new_attempt_url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)

        # Step 2: Dismiss privacy dialog
        for _ in range(5):
            dialog = page.query_selector('[role=dialog]')
            if dialog:
                btn = dialog.query_selector('button')
                if btn:
                    btn.click(force=True)
                    page.wait_for_timeout(500)
            else:
                break

        # Step 3: Create File object in page JS (from binary)
        # NOTE: use triple-quote + .replace() — NOT f-string interpolation.
        # f-string {{}} escaping inside page.evaluate() corrupts the JS in Chromium.
        create_file_js = (
            """
            (function(){
                var binary = atob('FILE_DATA');
                var bytes = new Uint8Array(binary.length);
                for (var i = 0; i < binary.length; i++) {
                    bytes[i] = binary.charCodeAt(i);
                }
                var blob = new Blob([bytes], {type: 'application/pdf'});
                window.__bbFile = new File([blob], 'FNAME', {type: 'application/pdf', lastModified: Date.now()});
            })()
            """
            .replace('FILE_DATA', file_b64)
            .replace('FNAME', fname)
        )
        page.evaluate(create_file_js)
        js_check = page.evaluate(
            "window.__bbFile ? window.__bbFile.name + '|' + window.__bbFile.size : 'none'"
        )
        print(f"  File in JS: {js_check}")

        # Step 4: Attach via set_input_files (triggers BB's initial handler)
        file_input = page.query_selector('#newFile_chooseLocalFile')
        if not file_input:
            return False, "File input not found on page"
        file_input.set_input_files([str(primary_file)])
        page.wait_for_timeout(500)

        # Step 5: Override input.files to always return our JS File
        # BB's change handler reads input.files; we intercept so it always sees our file
        page.evaluate("""
        (function(){
            var fi = document.getElementById('newFile_chooseLocalFile');
            var origDesc = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'files');
            Object.defineProperty(fi, 'files', {
                get: function() {
                    if (window.__bbFile) return [window.__bbFile];
                    return origDesc ? origDesc.get.call(this) : [];
                },
                configurable: true
            });
        })()
        """)
        files_now = page.evaluate(
            "document.getElementById('newFile_chooseLocalFile').files.length"
        )
        print(f"  Files via override: {files_now}")

        # Step 6: Dispatch change event — BB's handler adds file to newFile_table
        page.evaluate(
            "var fi = document.getElementById('newFile_chooseLocalFile');"
            "fi.dispatchEvent(new Event('change', {bubbles: true}));"
        )
        page.wait_for_timeout(3000)

        row_count = page.evaluate("""
        (function(){
            var tbl = document.getElementById('newFile_table');
            if (!tbl) return 0;
            var tbody = tbl.querySelector('tbody');
            if (!tbody) return 0;
            return tbody.querySelectorAll('tr').length;
        })()
        """)
        link_titles = page.evaluate("""
        (function(){
            var tbl = document.getElementById('newFile_table');
            if (!tbl) return [];
            var tbody = tbl.querySelector('tbody');
            if (!tbody) return [];
            return tbody.getElementsBySelector('[name=newFile_linkTitle]').pluck('value');
        })()
        """)
        print(f"  Table rows: {row_count}, link_titles: {link_titles}")

        if row_count == 0 or not link_titles:
            return False, "BB did not add file to table. Submission aborted."

        # Step 7: checkDupeFile sets submit_form = true
        page.evaluate("checkDupeFile('submit')")
        submit_form = page.evaluate("submit_form")
        print(f"  submit_form: {submit_form}")
        if not submit_form:
            return False, "checkDupeFile rejected submission"

        # Step 8: Submit via form.submit() (bypasses onclick which can block)
        page.evaluate(
            "document.getElementById('uploadAssignmentFormId').submit()"
        )
        page.wait_for_timeout(8000)

        url = page.url
        body = page.evaluate("(function(){return document.body.innerText})()")[:500]

        if ("Review Submission" in page.title() or
            "reviewSubmission" in url or
            "复查提交历史记录" in body):
            return True, f"SUCCESS\nURL: {url}\n{body[:300]}"
        if "错误" in body or "error" in body.lower():
            return False, f"Error: {body[:300]}"
        return True, f"Complete (verify manually)\nURL: {url}\n{body[:200]}"


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
