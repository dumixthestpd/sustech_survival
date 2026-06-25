#!/usr/bin/env python3
"""
sustech_survival.bb.submit_rest — REST-based BB assignment submission (no Playwright).

Status (2026-06-08): WORKING. End-to-end REST submission succeeds with file attached.

The two-step flow that BB's JS uses internally:

  1. GET /webapps/assignment/uploadAssignment?action=newAttempt&...
     → returns the upload form HTML, including CSRF nonces and hidden fields
  2. POST /webapps/assignment/uploadAssignment?action=submit
     → multipart/form-data POST with ALL hidden fields + the file as
       the multipart part named `newFile_LocalFile0`

The "magic" fields that BB's file picker adds to the form when a file is staged
(see /javascript/ngui/widget.js → preparePickedFilesForSubmit / getPickedFiles):

  newFile_attachmentType         = 'L'          (LOCAL — file is in the multipart)
  newFile_fileId                 = 'new'        (placeholder for new file)
  newFile_artifactFileId         = 'undefined'  (string, not a JS undefined)
  newFile_artifactType           = 'undefined'
  newFile_artifactTypeResourceKey= 'undefined'
  newFile_linkTitle              = <target filename>  (the link title shown in BB)
  newFile_LocalFile0             = <file binary>      (the actual file)
  dispatch                       = 'submit'           (set by submitAssignment JS)

For BB's server, the file goes in the multipart envelope (just like the
Playwright path's form.submit() call) — the file is attached to the attempt
based on the field name `newFile_LocalFile0`, not on the form's <input id>.
Without the field name, the file is silently dropped (the existing submit_rest.py
"works but no file" symptom).

CSRF: the `blackboard.platform.security.NonceUtil.nonce` field must match the
session-bound nonce. It changes on every GET of the upload page, so we always
GET a fresh form before POSTing.
"""
from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path
from typing import Optional

import requests

from sustech_survival.sso import BBAuth

from .result import success, failure, dry_run as _dry_run_result

BB_BASE = "https://bb.sustech.edu.cn"

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
       "AppleWebKit/537.36 (KHTML, like Gecko) "
       "Chrome/120.0.0.0 Safari/537.36")


# ─────────────────────────────────────────────────────────────────────────
# Session / cookie helpers
# ─────────────────────────────────────────────────────────────────────────

def _bb_session() -> requests.Session:
    """Return a fresh requests.Session with current BB cookies.

    Each call creates a new session so cookies don't collide between
    separate BB REST calls (BB rotates JSESSIONID on every request and
    the cookiejar would otherwise keep BOTH the old and new values).

    Auth model: BBAuth is a per-subclass singleton (see Authorizer.__new__).
    If the in-memory session is empty (e.g. fresh interpreter, or a script
    that never called refresh), we refresh() once here so the caller doesn't
    have to remember.
    """
    auth = BBAuth()
    if not auth.session_cache:
        if not auth.refresh():
            raise RuntimeError(
                "BB auth not initialized and refresh() failed — re-login required"
            )

    sess = requests.Session()
    sess.headers["User-Agent"] = _UA
    sess.headers["X-Requested-With"] = "XMLHttpRequest"
    for k, v in auth.cookies.items():
        if v:
            sess.cookies.set(k, v, domain=".bb.sustech.edu.cn", path="/")
    return sess


def _bb_form_url(course_id: str, content_id: str, action: str = "newAttempt") -> str:
    return (f"{BB_BASE}/webapps/assignment/uploadAssignment"
            f"?action={action}"
            f"&content_id=_{content_id}_1"
            f"&course_id=_{course_id}_1"
            f"&group_id=")


# ─────────────────────────────────────────────────────────────────────────
# _get_upload_form — fetch the uploadAssignment page + parse hidden fields
# ─────────────────────────────────────────────────────────────────────────

def _get_upload_form(course_id: str, content_id: str) -> dict:
    """GET the uploadAssignment page and extract all hidden form fields.

    Returns:
        {
          "raw_html": str,
          "form_data": dict[str, str],  # name → value for every <input>
          "file_input_id": str | None,  # the id of the file input
          "form_action": str,
          "course_id": str, content_id: str,
        }
    """
    sess = _bb_session()
    url = _bb_form_url(course_id, content_id, action="newAttempt")
    r = sess.get(url, timeout=15)
    if r.status_code != 200:
        raise RuntimeError(f"GET {url} returned {r.status_code}")

    form_data: dict[str, str] = {}
    for m in re.finditer(r'<input[^>]*>', r.text):
        chunk = m.group(0)
        name_m = re.search(r'name=["\']([^"\']+)["\']', chunk)
        val_m = re.search(r'value=["\']([^"\']*)["\']', chunk)
        if name_m and val_m is not None:
            form_data[name_m.group(1)] = val_m.group(1)
    # ajaxNonceId can also live in a non-hidden input
    for m in re.finditer(r'<input[^>]*id=["\']ajaxNonceId["\'][^>]*>', r.text):
        chunk = m.group(0)
        name_m = re.search(r'name=["\']([^"\']+)["\']', chunk)
        val_m = re.search(r'value=["\']([^"\']*)["\']', chunk)
        if name_m and val_m:
            form_data[name_m.group(1)] = val_m.group(1)

    # Form action URL
    form_action_match = re.search(
        r'<form[^>]*action=["\']([^"\']+)["\'][^>]*id=["\']uploadAssignmentFormId',
        r.text,
    )
    if not form_action_match:
        form_action_match = re.search(
            r'<form[^>]*id=["\']uploadAssignmentFormId[^>]*action=["\']([^"\']+)["\']',
            r.text,
        )
    form_action = form_action_match.group(1) if form_action_match else \
        f"/webapps/assignment/uploadAssignment?action=submit"

    # File input id
    file_input_match = re.search(
        r'<input[^>]*type=["\']file["\'][^>]*id=["\']([^"\']+)["\']', r.text,
    )
    if not file_input_match:
        file_input_match = re.search(
            r'<input[^>]*id=["\']([^"\']+)["\'][^>]*type=["\']file["\']', r.text,
        )
    file_input_id = file_input_match.group(1) if file_input_match else "newFile_chooseLocalFile"

    return {
        "raw_html": r.text,
        "form_data": form_data,
        "file_input_id": file_input_id,
        "form_action": form_action,
        "course_id": course_id,
        "content_id": content_id,
    }


# ─────────────────────────────────────────────────────────────────────────
# The "magic" fields BB's file picker adds to the form when a file is staged.
# See javascript/ngui/widget.js → preparePickedFilesForSubmit, getPickedFiles.
# Without these, the file is silently dropped (server creates an attempt
# with size=0 file).
# ─────────────────────────────────────────────────────────────────────────

_FILE_PICKER_LOCAL_FIELDS = {
    "newFile_attachmentType": "L",          # 'L' = LOCAL (file is in the multipart)
    "newFile_fileId": "new",                # placeholder for new file
    "newFile_artifactFileId": "undefined",  # string 'undefined', not JS undefined
    "newFile_artifactType": "undefined",
    "newFile_artifactTypeResourceKey": "undefined",
}


# ─────────────────────────────────────────────────────────────────────────
# submit_assignment_rest — end-to-end REST submission
# ─────────────────────────────────────────────────────────────────────────

def submit_assignment_rest(
    course_id: str,
    content_id: str,
    file_path: str,
    *,
    name_override: Optional[str] = None,
    dry_run: bool = False,
    skip_dedup: bool = False,
):
    """REST-based BB submission. End-to-end working as of 2026-06-08.

    Args:
        course_id: numeric course id (e.g. "8328")
        content_id: numeric content id (e.g. "612409")
        file_path: absolute path to the file to submit
        name_override: target basename (defaults to file_path's name).
            IMPORTANT: this is the on-disk basename — BB records the staged
            file's basename as the displayed filename. We stage the file
            under this name before POSTing.
        dry_run: if True, GET the form + simulate the POST, but don't actually
            submit. Returns (True, "DRY-RUN: ...").
        skip_dedup: no-op for the REST path (REST doesn't do a per-attempt
            dedup like the Playwright path does). Preserved for API parity
            with submit.py.

    Returns:
        (ok: bool | None, message: str). On success, message contains the
        destinationUrl from BB. ok=None is unused (kept for API parity with
        submit_assignment).

    Notes:
        - Stops at the first sign of trouble with explicit error messages.
        - File is staged under target_name in $TMPDIR/bb_submits/ (same
          convention as submit.py) so the BB-side filename matches.
    """
    file_path_p = Path(file_path).expanduser().resolve()
    if not file_path_p.exists():
        return failure(f"File not found: {file_path_p}", reason="file_not_found")
    if not file_path_p.stat().st_size:
        return failure(f"File is empty: {file_path_p}", reason="file_empty")

    target_name = name_override or file_path_p.name
    target_name = Path(target_name).name  # strip any path components
    if not target_name:
        return failure(
            f"name_override is not a valid basename: {name_override!r}",
            reason="invalid_name",
        )

    print(f"  REST submit: course={course_id} content={content_id} file={target_name!r}")

    # Stage the file with the target basename — BB records the staged file's
    # basename as the displayed filename.
    staged_dir = Path(tempfile.gettempdir()) / "bb_submits"
    staged_dir.mkdir(parents=True, exist_ok=True)
    staged_path = staged_dir / target_name
    if staged_path.resolve() != file_path_p:
        shutil.copy2(file_path_p, staged_path)

    try:
        # Step 1: GET the upload form (cookies, nonces, hidden fields)
        form_info = _get_upload_form(course_id, content_id)
        form_data = dict(form_info["form_data"])
        print(f"  Form: {len(form_data)} hidden fields, file_input_id={form_info['file_input_id']!r}")

        # Step 2: add the file-picker fields (mimics what BB's JS does
        # when the user picks a file in the browser)
        form_data.update(_FILE_PICKER_LOCAL_FIELDS)
        form_data["newFile_linkTitle"] = target_name
        form_data["dispatch"] = "submit"

        if dry_run:
            return _dry_run_result(
                message=(
                    f"DRY-RUN: would submit {target_name!r} "
                    f"(file={staged_path}, {len(form_data)} form fields, "
                    f"file part=newFile_LocalFile0)"
                ),
                staged_path=staged_path,
                row_count=0,
            )

        # Step 3: POST the form with the file in the multipart envelope.
        # Fresh session — CSRF nonce is in the form data (not session-bound),
        # so any session with valid BB auth will work.
        sess = _bb_session()
        submit_url = f"{BB_BASE}/webapps/assignment/uploadAssignment?action=submit"
        files = {
            "newFile_LocalFile0": (
                target_name, open(staged_path, "rb"), "application/octet-stream",
            ),
        }
        resp = sess.post(submit_url, data=form_data, files=files, timeout=60,
                         allow_redirects=False)

        # BB returns JSON {"destinationUrl": "..."} on success, or HTML on error
        try:
            parsed = resp.json()
        except Exception:
            parsed = None

        if parsed and "destinationUrl" in parsed:
            return success(
                message=(
                    f"Submitted OK. destinationUrl: {parsed['destinationUrl']} "
                    f"file: {target_name} ({staged_path.stat().st_size} bytes)"
                ),
                destination_url=parsed["destinationUrl"],
                staged_path=staged_path,
                file_size=staged_path.stat().st_size,
            )

        if resp.status_code == 200 and parsed is None:
            # Sometimes BB returns 200 with HTML — likely a form validation
            # error. Surface the response body.
            return failure(
                f"Form POST returned 200 with non-JSON body: {resp.text[:300]}",
                http_status=200,
                response_body=resp.text[:500],
            )

        return failure(
            f"Form POST returned {resp.status_code}: {resp.text[:200]}",
            http_status=resp.status_code,
            response_body=resp.text[:500],
        )

    except Exception as e:
        return failure(f"REST submit error: {e}", exception_type=type(e).__name__)


# ─────────────────────────────────────────────────────────────────────────
# Quick demo / sanity check
# ─────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 4:
        print("Usage: submit_rest.py <course_id> <content_id> <file_path> [--dry-run]")
        sys.exit(1)
    course_id = sys.argv[1]
    content_id = sys.argv[2]
    file_path = sys.argv[3]
    dry_run = "--dry-run" in sys.argv
    ok, msg = submit_assignment_rest(
        course_id, content_id, file_path,
        dry_run=dry_run,
    )
    print(f"\nOK: {ok}")
    print(f"MSG: {msg}")
