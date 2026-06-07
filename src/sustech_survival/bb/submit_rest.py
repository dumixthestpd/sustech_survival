#!/usr/bin/env python3
"""
sustech_survival.bb.submit_rest — REST-based BB assignment submission (no Playwright).

Status (2026-06-08): partial implementation. The pure REST path is blocked by
BB's JS-driven file upload flow (the uploadAssignment form's file input has
no `name` attribute; file upload is handled by `widget.FilePicker` uploading
to `/webapps/cmsmain/execute/resourcePicker`, which is a content-collection
flow that requires a session-bound "file picker" ID).

The form-submit step (POST to `/webapps/assignment/uploadAssignment?action=submit`)
works via requests. It creates an attempt record on the server, but the file
isn't actually attached (size=0 in the attempt receipt).

This module provides:
  1. _get_upload_form(course_id, content_id)
       — GET the upload page, extract nonces + hidden fields
  2. _post_upload_form(course_id, content_id, form_data, file=None)
       — POST the form via multipart. Returns BB's JSON
         {"destinationUrl": "..."} on success, or error text
  3. submit_assignment_rest(course_id, content_id, file_path,
                            name_override=None, dry_run=False, skip_dedup=False)
       — end-to-end: GET form, upload file (best-effort), POST form, parse
         the destinationUrl response, return (ok, message)

If you need a working submission RIGHT NOW, use `submit.py` (Playwright).
This module is here for the long-term REST migration.
"""
from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path
from typing import Optional

import requests

from sustech_survival.sso import BBAuth

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
    """
    auth = BBAuth()
    ok, reason = auth.ensure()
    if not ok:
        raise RuntimeError(f"BB auth failed: {reason}")

    sess = requests.Session()
    sess.headers["User-Agent"] = _UA
    for k, v in auth.cookies.items():
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
          "raw_html": str,            # the full page HTML (for debugging)
          "form_data": dict[str, str],  # name → value for every <input type=hidden>
          "file_input_id": str | None, # the id of the file input (no name attr)
          "form_action": str,          # the form's action URL
          "course_id": str, content_id: str,
        }

    Raises:
        RuntimeError if the page doesn't have a form, or auth is invalid.
    """
    sess = _bb_session()
    url = _bb_form_url(course_id, content_id, action="newAttempt")
    r = sess.get(url, timeout=15)
    if r.status_code != 200:
        raise RuntimeError(f"GET {url} returned {r.status_code}")

    form_data: dict[str, str] = {}
    for m in re.finditer(r'<input[^>]*type=["\']hidden["\'][^>]*>', r.text):
        chunk = m.group(0)
        name_m = re.search(r'name=["\']([^"\']+)["\']', chunk)
        val_m = re.search(r'value=["\']([^"\']*)["\']', chunk)
        if name_m and val_m is not None:
            form_data[name_m.group(1)] = val_m.group(1)
    # ajaxNonceId is also a hidden field (sometimes outside the type=hidden pattern)
    for m in re.finditer(r'<input[^>]*id=["\']ajaxNonceId["\'][^>]*>', r.text):
        chunk = m.group(0)
        name_m = re.search(r'name=["\']([^"\']+)["\']', chunk)
        val_m = re.search(r'value=["\']([^"\']*)["\']', chunk)
        if name_m and val_m:
            form_data[name_m.group(1)] = val_m.group(1)

    # Find the form's action URL
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

    # Find the file input's id (no name attribute on BB's form)
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
# _upload_file_to_resource_picker — pre-stage the file via the content
# collection upload endpoint. This is needed because BB's uploadAssignment
# form's file input has no `name` attribute, so the file isn't included
# in the form's multipart POST. Instead, the file is uploaded separately
# via widget.FilePicker → /webapps/cmsmain/execute/resourcePicker.
#
# Status (2026-06-08): not yet working — the resourcePicker endpoint
# requires its own form flow (different nonces, different cookies).
# ─────────────────────────────────────────────────────────────────────────

def _upload_file_to_resource_picker(
    file_path: str,
    course_id: str,
    target_name: str,
    sess: Optional[requests.Session] = None,
) -> Optional[dict]:
    """Upload `file_path` to BB's content collection, returning a file-picker
    descriptor that the uploadAssignment form can reference.

    Returns None if not implemented yet.
    """
    raise NotImplementedError(
        "resourcePicker upload not implemented — see module docstring. "
        "For now, use sustech_survival.bb.submit.submit_assignment (Playwright)."
    )


# ─────────────────────────────────────────────────────────────────────────
# _post_upload_form — POST the form (multipart). Creates an attempt on
# the server. The file isn't actually attached (size=0) because the
# uploadAssignment form's file input has no name. We use this as a
# stepping-stone toward a full REST path.
# ─────────────────────────────────────────────────────────────────────────

def _post_upload_form(
    course_id: str,
    content_id: str,
    form_data: dict,
    file_path: Optional[str] = None,
) -> dict:
    """POST the uploadAssignment form with multipart encoding.

    Args:
        course_id, content_id: BB numeric IDs
        form_data: hidden fields from _get_upload_form()
        file_path: optional local file. Sent as a multipart part named
            'newFile_chooseLocalFile' (the file input's id). BB's server
            will accept the multipart envelope but won't actually attach
            the file (the uploadAssignment form's file input has no
            `name` attribute, so BB's standard form processing doesn't
            read it). For real file upload, use Playwright OR implement
            _upload_file_to_resource_picker().

    Returns:
        {
          "status_code": int,
          "json": dict | None,        # parsed response body if Content-Type is JSON
          "raw_text": str,            # raw response body
          "content_type": str,
        }
    """
    sess = _bb_session()
    submit_url = f"{BB_BASE}/webapps/assignment/uploadAssignment?action=submit"

    files = None
    if file_path:
        p = Path(file_path)
        files = {
            "newFile_chooseLocalFile": (
                p.name, open(p, "rb"), "application/octet-stream",
            ),
        }

    r = sess.post(
        submit_url,
        data=form_data,
        files=files,
        timeout=30,
        allow_redirects=True,
    )

    # BB's webapp returns either JSON ({"destinationUrl": "..."}) or HTML
    parsed_json: Optional[dict] = None
    try:
        parsed_json = r.json()
    except Exception:
        parsed_json = None

    return {
        "status_code": r.status_code,
        "json": parsed_json,
        "raw_text": r.text,
        "content_type": r.headers.get("Content-Type", ""),
    }


# ─────────────────────────────────────────────────────────────────────────
# submit_assignment_rest — end-to-end REST submission (currently partial)
# ─────────────────────────────────────────────────────────────────────────

def submit_assignment_rest(
    course_id: str,
    content_id: str,
    file_path: str,
    *,
    name_override: Optional[str] = None,
    dry_run: bool = False,
    skip_dedup: bool = False,
) -> tuple:
    """REST-based BB submission. Currently a thin wrapper around the
    form-submit step. File attachment is NOT yet working — the file is
    sent in the multipart envelope but BB's server doesn't extract it
    from the unnamed file input.

    Args:
        course_id: numeric course id (e.g. "8328")
        content_id: numeric content id (e.g. "610821")
        file_path: absolute path to the file to submit
        name_override: target basename to use (defaults to file_path's name)
        dry_run: if True, do GET form + simulate file upload, don't POST submit
        skip_dedup: bypass any dedup check (no-op for now since dedup isn't
            implemented for REST path)

    Returns:
        (ok: bool | None, message: str). ok=None means "duplicate detected"
        (consistent with submit.py), but for REST path this branch isn't used.

    Status:
        - GET form: works
        - POST form (multipart, no file): works (creates attempt, size=0)
        - POST form (multipart, with file): the form accepts the request but
          the file is NOT actually attached (size=0 attempt)
        - Real file upload via resourcePicker: NOT YET IMPLEMENTED
    """
    file_path_p = Path(file_path).expanduser().resolve()
    if not file_path_p.exists():
        return False, f"File not found: {file_path_p}"
    if not file_path_p.stat().st_size:
        return False, f"File is empty: {file_path_p}"

    target_name = name_override or file_path_p.name
    target_name = Path(target_name).name  # strip any path components

    print(f"  REST submit: course={course_id} content={content_id} file={target_name!r}")

    # Stage the file with the target basename (mirrors submit.py behavior).
    # BB records the staged file's basename as the displayed filename.
    staged_dir = Path(tempfile.gettempdir()) / "bb_submits"
    staged_dir.mkdir(parents=True, exist_ok=True)
    staged_path = staged_dir / target_name
    if staged_path.resolve() != file_path_p:
        shutil.copy2(file_path_p, staged_path)

    try:
        # Step 1: GET the upload form (cookies, nonces, hidden fields)
        form_info = _get_upload_form(course_id, content_id)
        form_data = form_info["form_data"]
        print(f"  Form: {len(form_data)} hidden fields, file_input_id={form_info['file_input_id']!r}")

        if dry_run:
            # Dry-run: report what we would do, do NOT POST
            return True, (
                f"DRY-RUN: would submit {target_name!r} "
                f"(file={staged_path}, {len(form_data)} hidden fields). "
                f"NOTE: REST file attachment not yet implemented; "
                f"use submit.py for real submission."
            )

        # Step 2: POST the form with the file in multipart (best-effort).
        # BB's server creates an attempt but won't attach the file because
        # the form's file input has no `name` attribute.
        result = _post_upload_form(
            course_id, content_id, form_data,
            file_path=str(staged_path),
        )

        if result["json"] and "destinationUrl" in result["json"]:
            dest = result["json"]["destinationUrl"]
            return True, (
                f"Form submitted. destinationUrl: {dest}. "
                f"NOTE: file size=0 in attempt receipt — REST file upload "
                f"not yet implemented. Use submit.py for real submission."
            )

        if result["status_code"] != 200:
            return False, (
                f"Form POST returned {result['status_code']}: "
                f"{result['raw_text'][:200]}"
            )

        return False, (
            f"Form POST returned 200 but no destinationUrl: "
            f"{result['raw_text'][:200]}"
        )

    except Exception as e:
        return False, f"REST submit error: {e}"


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
