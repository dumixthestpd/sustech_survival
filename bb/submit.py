#!/usr/bin/env python3
"""
⚠️  WARNING: Running this script SUBMITS A REAL FILE TO BLACKBOARD. ⚠️
It counts as an official submission attempt. Use with extreme caution.

BB Assignment Submitter — submits files to a BB assignment slot.

Key insight: BB uses Prototype.js file-change handler that reads input.files
when processing the change event. We work around this with:
  1. set_input_files to trigger BB's initial JS setup
  2. Override input.files to return our File (created from binary in JS)
  3. Dispatch change event — BB's handler adds the file to the table
  4. Run checkDupeFile, then form.submit()

Usage:
  python3 bb_submit.py --course 8328 --content 610812 --files /path/to/file.pdf

IMPORTANT: Always ask the user before running this. Every test/dev run creates
           a real BB submission and counts as an attempt.
"""
import json, os, re, sys, argparse, base64
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
try:
    from .session import BB_BASE, load_session, discover_attempt_ids, check_session
except ImportError:
    from session import BB_BASE, load_session, discover_attempt_ids, check_session
from playwright.sync_api import sync_playwright

SESSION_FILE = Path(__file__).parent / "session.json"


def load_cookies():
    """Load cookies for Playwright (list format)."""
    return load_session()[1]


def submit_assignment(course_id, content_id, file_paths):
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
    fname = clean_name

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context()
        ctx.add_cookies(cookies)
        page = ctx.new_page()
        page.set_viewport_size({"width": 1280, "height": 900})

        # Step 1: Load upload page
        new_attempt_url = (
            f"{BB_BASE}/webapps/assignment/uploadAssignment"
            f"?action=newAttempt&course_id=_{course_id}_1&content_id=_{content_id}_1"
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
        page = ctx.new_page()
        page.goto(
            f'{BB_BASE}/webapps/assignment/uploadAssignment'
            f'?action=newAttempt&course_id=_{course_id}_1&content_id=_{content_id}_1',
            wait_until='domcontentloaded',
            timeout=20000
        )
        page.wait_for_timeout(3000)
        title = page.title() or ''
        m = re.search(r'Upload Assignment:\s*(.+)', title)
        assignment_name = m.group(1).strip() if m else 'unknown'
        page.close()

        # Discover all prior attempts using the reliable shared logic
        attempts = discover_attempt_ids(ctx, course_id, content_id)
        attempt_count = len(attempts)

        if attempts:
            last_ts = attempts[-1][1][1]  # (aid, (num, ts))
            print(f"  Prior attempts found: {attempt_count} (last: {last_ts})")
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

    success, msg = submit_assignment(args.course, args.content, args.files)
    print()
    if success:
        print(f"✅ {msg}")
    else:
        print(f"❌ {msg}")
        sys.exit(1)


if __name__ == "__main__":
    main()
