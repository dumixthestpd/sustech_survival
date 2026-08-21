#!/usr/bin/env python3
"""
sustech_survival.bb.submit — REST-based BB assignment submission (no Playwright).

This module is the single BB submitter. The legacy Playwright-driven
submitter and the ``bb._playwright`` module were removed; the pure-REST
path (formerly ``bb.submit_rest``) was moved here.

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

Public API:
  submit_assignment_rest(course_id, content_id, file_path, *, name_override,
                         dry_run, skip_dedup)  → SubmitResult   (the primitive)
  submit_file(content_id, file_path, course_id=None, submitted_name=None)
                                                → (ok, message) tuple (legacy CLI shape)
  submit_assignment(course_id, content_id, file_paths, *, skip_dedup,
                    text_content, name_override, dry_run, headless)
                                                → SubmitResult   (legacy-signature wrapper)
  check_attempts(content_id, course_id=None)   → (attempt_count, assignment_name)
  get_attempt_info(course_id, content_id)      → (attempt_count, assignment_name, True)
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Optional

import requests

from sustech_survival import _cache
from sustech_survival.sso import BBAuth
from sustech_survival.consequence import (
    Severity, Consequence, consequence_rich,
)

from .result import success, failure, dry_run as _dry_run_result

BB_BASE = "https://bb.sustech.edu.cn"

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
       "AppleWebKit/537.36 (KHTML, like Gecko) "
       "Chrome/120.0.0.0 Safari/537.36")

# Kept for callers that import bb_auth from this module (e.g. tests).
bb_auth = BBAuth()

# Characters Windows forbids in a file/dir name. The on-disk staged file is
# sanitized to avoid copy2/copyfile crashing (WinError 123) on a target name
# that is fine as a BB multipart filename but not as a filesystem path.
_ILLEGAL_FS_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _safe_staged_name(target_name: str, fallback_suffix: str = ".pdf") -> str:
    """Return a deterministic, filesystem-safe basename for a staged file.

    ``target_name`` may legally contain characters that are fine in a BB
    multipart filename but illegal in a Windows filesystem path (e.g.
    ``<sid>-<name>-report.pdf``). The on-disk name is only a staging token —
    BB's displayed name comes from the multipart filename, not the disk path.
    """
    safe = _ILLEGAL_FS_CHARS.sub("_", target_name)
    safe = safe.strip().strip(".") or ("file" + fallback_suffix)
    # Guard against reserved Windows names (CON, PRN, AUX, NUL, COM1-9, LPT1-9)
    stem = safe.split(".")[0].upper()
    if stem in {"CON", "PRN", "AUX", "NUL"} or (
        stem.startswith("COM") and stem[3:].isdigit()
    ) or (stem.startswith("LPT") and stem[3:].isdigit()):
        safe = "staged_" + safe
    return safe


# -------------------------------------------------------------------------
# Session / cookie helpers
# -------------------------------------------------------------------------

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
    for c in auth.session.cookies:
        if c.value:
            sess.cookies.set(c.name, c.value, domain=".bb.sustech.edu.cn", path="/")
    return sess


def _bb_form_url(course_id: str, content_id: str, action: str = "newAttempt") -> str:
    return (f"{BB_BASE}/webapps/assignment/uploadAssignment"
            f"?action={action}"
            f"&content_id=_{content_id}_1"
            f"&course_id=_{course_id}_1"
            f"&group_id=")


def _num_id(bb_id) -> str:
    """'_8053_1' -> '8053'; bare '8053' stays '8053'."""
    m = re.search(r'_(\d+)_(\d+)$', str(bb_id))
    return m.group(1) if m else str(bb_id)


def _clean_filename(name: str) -> str:
    """Strip the OpenClaw UUID suffix from a filename (e.g. 'x---cf8274ec-....pdf')."""
    return re.sub(
        r'---[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?=\.)',
        '', name,
    )


# -------------------------------------------------------------------------
# _get_upload_form — fetch the uploadAssignment page + parse hidden fields
# -------------------------------------------------------------------------

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


# -------------------------------------------------------------------------
# The "magic" fields BB's file picker adds to the form when a file is staged.
# See javascript/ngui/widget.js → preparePickedFilesForSubmit, getPickedFiles.
# Without these, the file is silently dropped (server creates an attempt
# with size=0 file).
# -------------------------------------------------------------------------

_FILE_PICKER_LOCAL_FIELDS = {
    "newFile_attachmentType": "L",          # 'L' = LOCAL (file is in the multipart)
    "newFile_fileId": "new",                # placeholder for new file
    "newFile_artifactFileId": "undefined",  # string 'undefined', not JS undefined
    "newFile_artifactType": "undefined",
    "newFile_artifactTypeResourceKey": "undefined",
}


# -------------------------------------------------------------------------
# submit_assignment_rest — end-to-end REST submission (the primitive)
# -------------------------------------------------------------------------

@consequence_rich(Consequence(
    name="bb.submit_assignment_rest",
    severity=Severity.MEDIUM,
    irreversible=True,
    what_changes="Submits a file to a BB assignment (creates/replaces an attempt).",
    risk=("Submitting the wrong file to a graded assignment counts as your "
          "attempt. Confirm the file, course, and assignment before committing."),
    verify_url="https://bb.sustech.edu.cn/webapps/assignment/uploadAssignment?content_id=_{content_id}_1&course_id=_{course_id}_1&mode=view",
))
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
            submit. Returns a DRY_RUN SubmitResult.
        skip_dedup: no-op for the REST path (REST doesn't do a per-attempt
            dedup like the old Playwright path did). Preserved for API parity.

    Returns:
        SubmitResult (see bb.result). On success, message contains the
        destinationUrl from BB.

    Notes:
        - Stops at the first sign of trouble with explicit error messages.
        - File is staged under target_name in
          ~/.sustech_survival/cache/bb/submits/ so the
          BB-side filename matches.
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

    # Staging: BB records the *multipart filename* (form_data["newFile_linkTitle"])
    # as the displayed name, so the on-disk staged name need not equal target_name.
    # The on-disk name is sanitized to a safe basename because Windows rejects
    # chars like `< > : " | ? *` in filesystem paths (a real bug: dry-run with a
    # `<sid>-<name>-...pdf` name_override crashed on shutil.copy2). Dry-run never
    # needs the copy — it only reports what *would* be submitted.
    # Staging under the bb module cache (~/.sustech_survival/cache/bb/submits)
    # so BB upload staging lives inside the project's storage; clearing the
    # bb cache clears staging too.
    staged_dir = _cache.cache_path("bb", "submits")
    staged_name = _safe_staged_name(target_name, file_path_p.suffix)
    staged_path = staged_dir / staged_name

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

        # Only a real (non-dry) submit needs to stage the file for the POST.
        staged_dir.mkdir(parents=True, exist_ok=True)
        if staged_path.resolve() != file_path_p:
            shutil.copy2(file_path_p, staged_path)

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


# -------------------------------------------------------------------------
# submit_file — convenience wrapper (legacy `bb.submit_file` API)
# -------------------------------------------------------------------------

def submit_file(content_id, file_path, course_id=None, submitted_name=None):
    """Submit a file to a BB assignment via REST (no browser).

    Renamed from `submit()` on 2026-06-08 to fix the module-shadowing bug:
    `bb/__init__.py` was doing `from .submit import submit`, which bound
    the function to the `bb` package namespace and broke
    `import sustech_survival.bb.submit as m` (it returned the function
    instead of the module). Use `submit_file()` going forward, or
    `submit_assignment_rest()` for the lower-level primitive.

    Resolves the owning course automatically when `course_id` is omitted.

    Returns (success: bool, message: str) — the legacy tuple shape
    (via SubmitResult.to_tuple()).
    """
    from sustech_survival.bb.download import resolve_course

    if course_id is None:
        try:
            course_id = resolve_course(content_id)
        except Exception as e:
            return failure(
                f"Cannot resolve course_id for content_id={content_id}: {e} "
                f"Provide --course explicitly.",
                reason="course_not_found",
            ).to_tuple()
        if not course_id:
            return failure(
                f"Cannot resolve course_id for content_id={content_id}. "
                f"Provide --course explicitly.",
                reason="course_not_found",
            ).to_tuple()

    fp = Path(file_path).expanduser().resolve()
    if not fp.exists():
        return failure(f"File not found: {fp}", reason="file_not_found").to_tuple()

    target_name = submitted_name if submitted_name else _clean_filename(fp.name)
    result = submit_assignment_rest(
        _num_id(course_id),
        _num_id(content_id),
        str(fp),
        name_override=target_name,
        skip_dedup=True,
    )
    # Backwards compat: keep the legacy (ok, msg) tuple for the CLI.
    # New code should use submit_assignment_rest() / SubmitResult directly.
    return result.to_tuple()


# -------------------------------------------------------------------------
# submit_assignment — legacy-signature wrapper over the REST primitive
# -------------------------------------------------------------------------

def submit_assignment(course_id, content_id, file_paths, skip_dedup=False,
                      text_content=None, name_override=None,
                      dry_run=False, headless=True):
    """Submit file(s) to a BB assignment — REST-backed compat wrapper.

    This keeps the old Playwright-era signature so existing callers
    (e.g. ``HomeworkItem.submit``) keep working. It delegates to
    ``submit_assignment_rest``; only the FIRST file in ``file_paths`` is
    submitted (the REST multipart path supports one ``newFile_LocalFile0``
    part). ``headless`` and ``text_content`` are accepted for API
    compatibility and ignored (there is no browser, and REST text
    submission is not supported).

    Returns a SubmitResult.
    """
    if not file_paths:
        return failure("No files to submit: file_paths is empty", reason="no_files")
    if text_content:
        return failure(
            "text_content is not supported by the REST submit path (no VTBE "
            "encryption key via requests). File submission only.",
            reason="text_unsupported",
        )
    return submit_assignment_rest(
        _num_id(course_id),
        _num_id(content_id),
        str(file_paths[0]),
        name_override=name_override,
        dry_run=dry_run,
        skip_dedup=skip_dedup,
    )


# -------------------------------------------------------------------------
# Attempt checks — REST-based (reimplemented from the Playwright scrapers)
# -------------------------------------------------------------------------

def check_attempts(content_id, course_id=None):
    """Return (attempt_count, assignment_name) for a content item.

    REST-based: resolves the course, looks up the gradebook column and
    lists attempts via the gradebook API — no browser.
    """
    from sustech_survival.bb.download import (
        resolve_course, get_assignment_attempts,
        get_column_id_for_content, get_content_item,
    )

    if course_id is None:
        course_id = resolve_course(content_id)
    cid = _num_id(course_id)
    content = _num_id(content_id)

    assignment_name = ""
    try:
        item = get_content_item(cid, content)
        if item:
            assignment_name = item.get("title", "") or ""
    except Exception:
        pass

    column_id = get_column_id_for_content(cid, content)
    attempts = get_assignment_attempts(cid, column_id) if column_id else []
    return len(attempts), assignment_name


def get_attempt_info(course_id, content_id):
    """Check BB for existing attempt count and assignment name (REST).

    Returns (attempt_count, assignment_name, session_valid). The third
    element is always True — the REST path raises on auth failure instead
    of returning a session flag (kept for API parity with the old
    Playwright implementation).
    """
    count, name = check_attempts(content_id, course_id=course_id)
    return count, name, True


__all__ = [
    "BB_BASE",
    "submit_assignment_rest",
    "submit_file",
    "submit_assignment",
    "check_attempts",
    "get_attempt_info",
]


# -------------------------------------------------------------------------
# Quick demo / sanity check
# -------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 4:
        print("Usage: submit.py <course_id> <content_id> <file_path> [--dry-run]")
        sys.exit(1)
    course_id = sys.argv[1]
    content_id = sys.argv[2]
    file_path = sys.argv[3]
    dry_run = "--dry-run" in sys.argv
    result = submit_assignment_rest(
        course_id, content_id, file_path,
        dry_run=dry_run,
    )
    print(f"\nOK: {result.ok}")
    print(f"MSG: {result.message}")
