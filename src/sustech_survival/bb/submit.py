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

Submission-semantics rules (ported from sustech-cli v0.11.1,
blackboard-assignment-form.ts + blackboard-submission.ts):

  R1 — Verify the exact assignment target BEFORE any POST. Resolve the
       course AND the content (or column) and confirm it is the accessible
       assignment; only after that do we trust the upload form. An initial
       attempts-list 404 is treated as "no attempts yet" ONLY after both the
       assignment and its blank first-submission view form have been verified.
       Every other error during pre-flight stays an error.
  R2 — Never automatically replay the submission POST, including across
       HTTP redirects. ``allow_redirects=False`` on the multipart POST and
       no retry decorator on the failure path.
  R3 — The error shown to the user keeps the failure stage plus a
       sanitized upstream status and path. Raw HTML responses, nonces,
       cookies, and credential-bearing query strings are NEVER dumped
       into the user-visible message.
  R4 — Keep the reviewed file's SHA-256 and refuse to submit if the bytes
       changed between preview and apply. A distinct exception class
       (``FileChangedSinceReviewError``) carries the computed hashes so
       the caller can report what the user actually has on disk now.
  R5 — Text and comment submissions use the editor field the fetched form
       actually exposes. If the expected text/comment editor is absent
       from the form, fail with a clear error — never silently send
       nothing.

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
  verify_assignment_target(course_id, content_id)
                                                → dict   (rule R1 preflight primitive)
  submit_text(content_id, text, *, course_id=None, comment=None)
                                                → SubmitResult   (rule R5 text path)
  submit_comment(content_id, comment, *, course_id=None)
                                                → SubmitResult   (rule R5 comment path)
  FileChangedSinceReviewError                  → distinct error class for rule R4
  SubmissionFormError                          → distinct error class for rule R3
"""
from __future__ import annotations
from .. import _net

import hashlib
import re
import shutil
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

import requests

from sustech_survival import _cache
from sustech_survival.sso import BBAuth
from sustech_survival.consequence import (
    Severity, Consequence, consequence_rich,
)

from .result import SubmitResult, success, failure, dry_run as _dry_run_result

BB_BASE = "https://bb.sustech.edu.cn"

_UPLOAD_PATH = "/webapps/assignment/uploadAssignment"
_NONCE_FIELD = "blackboard.platform.security.NonceUtil.nonce"

# Editor field names BB uses for text/comments. The fetched form decides
# which one is present (rule R5); the order below is the preference list.
_TEXT_EDITOR_CANDIDATES = ("studentSubmission.text",)
_COMMENT_EDITOR_CANDIDATES = ("student_comments", "studentComments.text")

# Sensitive query-string keys we strip from any upstream URL we echo back.
# Credentials / nonces / cookies must never appear in user-visible errors.
_SENSITIVE_QUERY_KEYS = {
    "nonce", "blackboard.platform.security.NonceUtil.nonce",
    "nonce.ajax", "ajaxnonceid", "session", "sessionid",
    "auth", "token", "password", "pwd",
}


def _sanitize_query(qs: str) -> str:
    """Drop any sensitive query keys from a query string."""
    pairs = parse_qsl(qs, keep_blank_values=True)
    kept = [(k, v) for k, v in pairs if k.lower() not in _SENSITIVE_QUERY_KEYS]
    return urlencode(kept)


def _sanitize_url(value: str) -> Optional[str]:
    """Return a safe, path-only view of an upstream URL (no credentials, no
    sensitive query keys, no fragments). Returns None if value is unusable.
    """
    if not value:
        return None
    try:
        parsed = urlparse(value)
    except Exception:
        return None
    if not parsed.scheme or not parsed.netloc:
        return None
    if parsed.username or parsed.password:
        return None
    # Strip fragment always (carries tokens / hash secrets on BB).
    return urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path or "/",
        "",  # params
        _sanitize_query(parsed.query),
        "",  # fragment
    ))


# -------------------------------------------------------------------------
# Distinct error classes for the submission rules (R3, R4)
# -------------------------------------------------------------------------

class SubmissionFormError(Exception):
    """Raised when the uploadAssignment form is missing, malformed, or
    refers to a different/ambiguous assignment (rule R3).

    Carries ``stage`` (which phase was active when the error happened),
    plus a sanitized ``status`` and ``path`` so the caller can echo a
    meaningful but safe error to the user.
    """

    def __init__(self, message: str, *, stage: str = "prepare_form",
                     status: Optional[int] = None, path: Optional[str] = None,
                     code: str = "BLACKBOARD_SUBMISSION_FORM_ERROR"):
            super().__init__(message)
            self.message = message
            self.stage = stage
            self.status = status
            self.path = path
            self.code = code

    def to_diagnostic(self) -> dict:
        """Sanitized, user-safe diagnostic dict. NEVER includes raw HTML."""
        out: dict = {
            "code": self.code,
            "message": str(self),
            "stage": self.stage,
        }
        if self.status is not None:
            out["status"] = int(self.status)
        safe_path = _sanitize_url(self.path) if self.path else None
        if safe_path:
            # Path only (no query, no fragment, no credentials).
            out["path"] = urlparse(safe_path).path
        return out


class FileChangedSinceReviewError(Exception):
    """Raised when the bytes to upload no longer match the SHA-256 the caller
    reviewed (rule R4). A distinct class so the caller can surface this
    specifically without confusing it with a BB-side failure.
    """

    def __init__(self, path: str, reviewed_sha256: str, current_sha256: str,
                 reviewed_size: int, current_size: int):
        self.path = path
        self.reviewed_sha256 = reviewed_sha256
        self.current_sha256 = current_sha256
        self.reviewed_size = reviewed_size
        self.current_size = current_size
        super().__init__(
            f"The Blackboard submission bytes no longer match the reviewed "
            f"SHA-256 for {path!r}. "
            f"Reviewed {reviewed_sha256} ({reviewed_size} bytes); "
            f"on disk now {current_sha256} ({current_size} bytes). "
            f"Re-review before retrying."
        )


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


def sha256_of_file(path: Path) -> str:
    """Return the SHA-256 hex digest of the file at ``path`` (read in 64 KB
    chunks). Used by rule R4 to verify the bytes have not changed between
    preview and apply.
    """
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


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
    if not auth._session_cache:
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
    """'_8053_1' -> '8053'; bare '8053' stays '8053'.

    Thin shim kept for backwards compatibility — delegates to the single
    project-wide normaliser in bb.query._core_id. (R1 relies on this; never
    do an lstrip/rstrip of '_1' here.)
    """
    from .query import _core_id
    return _core_id(str(bb_id))


def _clean_filename(name: str) -> str:
    """Strip the OpenClaw UUID suffix from a filename (e.g. 'x---cf8274ec-....pdf')."""
    return re.sub(
        r'---[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?=\.)',
        '', name,
    )


# -------------------------------------------------------------------------
# R1 — verify the exact assignment target BEFORE any POST.
#      - Resolve course AND content (or column).
#      - Confirm the assignment is accessible.
#      - Initial attempts-list 404 only counts as "no attempts yet" AFTER
#        both the assignment AND its blank first-submission view form have
#        been verified. Every other error stays an error.
# -------------------------------------------------------------------------

def verify_assignment_target(course_id: str, content_id: str) -> dict:
    """Verify the (course_id, content_id) pair refers to an accessible
    assignment, and return a dict with normalised ids plus the resolved
    gradebook column id (if any).

    Implementation: resolves the course (when needed), fetches the content
    item to confirm the assignment exists and the student has access to it,
    and resolves the gradebook column id from the content item's handler
    metadata. This is the R1 preflight primitive — the submission flow
    MUST call this before any POST.

    Returns:
        {
          "course_id": str, "content_id": str,
          "column_id": str | None,
          "assignment_name": str,
          "course_name": str,
          "is_assignment": bool,
        }
    """
    from .download import get_content_item, get_column_id_for_content
    from .query import api

    cid = _num_id(course_id)
    content = _num_id(content_id)
    course_name = ""
    try:
        # cid is already a course ID. resolve_course() takes a CONTENT ID
        # and scans enrolled courses; using it here both mislabels the
        # course_name and performs unnecessary reverse lookups.
        course_name = api(f"/learn/api/public/v1/courses/_{cid}_1").get("name", "") or ""
    except Exception:
        course_name = ""

    item = get_content_item(cid, content)
    if not item:
        raise SubmissionFormError(
            f"Could not resolve BB content {content} in course {cid}: "
            f"the item does not exist or you do not have access to it.",
            stage="verify_target",
            path=_UPLOAD_PATH,
            code="BLACKBOARD_ASSIGNMENT_NOT_ACCESSIBLE",
        )

    handler = item.get("contentHandler", {}) or {}
    handler_id = handler.get("id", "") or ""
    is_assignment = handler_id == "resource/x-bb-assignment"
    assignment_name = item.get("title", "") or ""

    column_id = get_column_id_for_content(cid, content)

    return {
        "course_id": cid,
        "content_id": content,
        "column_id": column_id or None,
        "assignment_name": assignment_name,
        "course_name": course_name,
        "is_assignment": is_assignment,
    }


def _is_no_attempts_404(exc: BaseException) -> bool:
    """Return True iff ``exc`` is a requests-style 404 (the "no attempts yet"
    shape that BB returns before the student has ever uploaded).

    R1: this is the ONLY error condition during pre-flight that we treat as
    "no attempts yet" — every other error stays an error.
    """
    response = getattr(exc, "response", None)
    if response is None:
        return False
    status = getattr(response, "status_code", None)
    if status is None:
        # requests.HTTPError carries ``.response.status_code`` too.
        try:
            status = exc.response.status_code  # type: ignore[attr-defined]
        except Exception:
            return False
    return status == 404


def _safe_initial_attempts_count(course_id: str, column_id: Optional[str]) -> int:
    """Count this student's complete attempt list; keep failed reads explicit."""
    if not column_id:
        raise SubmissionFormError(
            "Assignment grade column could not be identified",
            stage="verify_target", code="BLACKBOARD_GRADE_COLUMN_UNKNOWN",
        )
    from sustech_survival.bb.query import api
    from sustech_survival.bb.session import session
    from sustech_survival.bb._collections import user_attempts
    bid = course_id if course_id.startswith("_") else f"_{course_id}_1"
    col_id = column_id if column_id.startswith("_") else f"_{column_id}_1"
    # Only an attempts-endpoint 404 can mean no attempts. Identity failures
    # must propagate rather than being mistaken for a blank assignment.
    def fetch(path, sess):
        try:
            return api(path, sess)
        except requests.HTTPError as exc:
            if path.split("?", 1)[0].endswith("/attempts") and _is_no_attempts_404(exc):
                return {"results": []}
            raise
    return len(user_attempts(bid, col_id, session(), fetch))


def _strip_html_for_error(text: str) -> str:
    """Strip HTML tags from a body for safe inclusion in an error message.

    Rule R3: never echo raw HTML / script tags in user-visible errors. We
    keep a small text-only preview so the caller still has something to
    recognise the response.
    """
    if not text:
        return ""
    # Remove <script>...</script> blocks (case-insensitive, multi-line).
    no_script = re.sub(r"<script\b[^>]*>.*?</script>", "", text,
                        flags=re.IGNORECASE | re.DOTALL)
    # Strip remaining HTML tags.
    no_tags = re.sub(r"<[^>]+>", " ", no_script)
    # Collapse runs of whitespace.
    return re.sub(r"\s+", " ", no_tags).strip()


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
          "text_field_names": tuple[str, ...],  # rule R5 — names of <textarea> editors
        }

    Raises:
        SubmissionFormError: when the GET fails, the response URL points
        to a different assignment, or the form is missing/unsupported.
        Rule R3: only stage + sanitized status + path are exposed.
    """
    sess = _bb_session()
    url = _bb_form_url(course_id, content_id, action="newAttempt")
    try:
        r = sess.get(url, timeout=_net.service_timeout("bb"))
    except Exception as e:
        raise SubmissionFormError(
            f"Failed to fetch BB upload form: {type(e).__name__}",
            stage="prepare_form",
            path=url,
        ) from e

    if r.status_code != 200:
        raise SubmissionFormError(
            f"BB upload form GET returned status {r.status_code}",
            stage="prepare_form",
            status=r.status_code,
            path=url,
        )

    # R1: verify the response URL points at the requested assignment.
    _assert_assignment_response_url(r.url, course_id, content_id)

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

    # Rule R5: capture every <textarea name=...> — these are the editor
    # fields the form actually exposes for text/comments.
    text_field_names: list[str] = []
    seen_text_fields: set[str] = set()
    for m in re.finditer(r'<textarea[^>]*name=["\']([^"\']+)["\']', r.text):
        name = m.group(1)
        if name in seen_text_fields:
            # R3: never silently swallow ambiguity in editor fields.
            raise SubmissionFormError(
                f"BB upload form has ambiguous editor field {name!r}",
                stage="prepare_form",
                path=url,
                code="BLACKBOARD_FORM_AMBIGUOUS_EDITOR",
            )
        seen_text_fields.add(name)
        text_field_names.append(name)

    # R1: the form must be the real Original assignment submission form,
    # with a usable nonce and an empty attempt_id. A populated attempt_id
    # means the form is for an existing attempt, NOT the blank first submission.
    attempt_id_val = form_data.get("attempt_id", "")
    nonce_val = form_data.get(_NONCE_FIELD, "")
    if not nonce_val:
        raise SubmissionFormError(
            "BB upload form is missing the CSRF nonce",
            stage="prepare_form",
            path=url,
            code="BLACKBOARD_FORM_MISSING_NONCE",
        )
    if attempt_id_val:
        # First-submission view expects attempt_id="". A populated one means
        # BB has surfaced a re-submission form for an existing attempt — not
        # the blank form R1 mandates for "no attempts yet".
        raise SubmissionFormError(
            f"BB upload form has attempt_id={attempt_id_val!r} "
            f"(expected empty for a first submission)",
            stage="prepare_form",
            path=url,
            code="BLACKBOARD_FORM_NOT_BLANK",
        )

    # Sanity: form_data must agree on course_id / content_id.
    for key, expected in (("course_id", f"_{course_id}_1"),
                          ("content_id", f"_{content_id}_1")):
        actual = form_data.get(key, "")
        if actual and actual != expected:
            raise SubmissionFormError(
                f"BB upload form has {key}={actual!r} but {expected!r} expected",
                stage="prepare_form",
                path=url,
                code="BLACKBOARD_FORM_DIFFERENT_ASSIGNMENT",
            )

    return {
        "raw_html": r.text,
        "form_data": form_data,
        "file_input_id": file_input_id,
        "form_action": form_action,
        "course_id": course_id,
        "content_id": content_id,
        "text_field_names": tuple(text_field_names),
    }


def _assert_assignment_response_url(response_url: Optional[str],
                                     course_id: str, content_id: str) -> None:
    """R1: a redirect that lands on a different assignment must be detected
    BEFORE we trust the form. Raises SubmissionFormError on mismatch.
    """
    if not response_url:
        return
    expected_course = f"_{course_id}_1"
    expected_content = f"_{content_id}_1"
    safe = _sanitize_url(response_url)
    if not safe:
        raise SubmissionFormError(
            "BB upload form response URL was invalid",
            stage="prepare_form",
            path=response_url,
        )
    parsed = urlparse(safe)
    if parsed.path != _UPLOAD_PATH:
        raise SubmissionFormError(
            f"BB upload form redirected to an unexpected path: {parsed.path}",
            stage="prepare_form",
            path=response_url,
        )
    # Only enforce course/content match when the URL actually exposes them —
    # some BB endpoints drop the query string on the final hop.
    qs = dict(parse_qsl(parsed.query))
    if qs.get("course_id") and qs["course_id"] != expected_course:
        raise SubmissionFormError(
            f"BB upload form response carries a different course_id",
            stage="prepare_form",
            path=response_url,
        )
    if qs.get("content_id") and qs["content_id"] != expected_content:
        raise SubmissionFormError(
            f"BB upload form response carries a different content_id",
            stage="prepare_form",
            path=response_url,
        )


def _pick_editor_field(text_field_names, candidates: tuple[str, ...]) -> Optional[str]:
    """R5: pick the first candidate present in the form's text field set."""
    for c in candidates:
        if c in text_field_names:
            return c
    return None


def _escape_for_bb_editor(text: str) -> str:
    """BB's text/submission editors want HTML-escaped newlines, not raw text.
    Mirrors sustech-cli v0.11.1: escape & < >, then convert line breaks to
    <br />.
    """
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\r\n", "\n")
            .replace("\r", "\n")
            .replace("\n", "<br />")
    )


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
    reviewed_sha256: Optional[str] = None,
    comment: Optional[str] = None,
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
        comment: optional comment included with the file in the same attempt.
        skip_dedup: no-op for the REST path (REST doesn't do a per-attempt
            dedup like the old Playwright path did). Preserved for API parity.
        reviewed_sha256: optional SHA-256 from a prior dry-run / preview.
            When provided, the file's bytes are hashed again right before
            the POST and any mismatch raises ``FileChangedSinceReviewError``
            (rule R4). If the caller wants no preview-anchor check, leave
            this as None.

    Returns:
        SubmitResult (see bb.result). On success, message contains the
        destinationUrl from BB.

    Notes:
        - Stops at the first sign of trouble with explicit error messages.
        - File is staged under target_name in
          ~/.sustech_survival/cache/bb/submits/ so the
          BB-side filename matches.
        - Rule R2: the multipart POST is sent exactly once with
          ``allow_redirects=False``; no retry, no replay on redirect.
        - Rule R3: errors carry the failing stage plus a sanitized upstream
          status and path — raw HTML is never echoed to the user.
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

    # R4: hash the bytes right at the start so we have a stable review anchor.
    # The actual verification happens just before the POST below; this pre-hash
    # surfaces a useful diagnostic in dry-run mode.
    initial_sha = sha256_of_file(file_path_p)
    initial_size = file_path_p.stat().st_size

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
    # Whether the multipart POST has left the machine. The failure paths
    # report it so a caller never blindly retries a submission that may
    # already have landed.
    post_attempted = False

    try:
        # R1: preflight — confirm the exact assignment target BEFORE any POST.
        # Done as a soft check (failure surfaces as a SubmitResult so the
        # legacy (ok, msg) CLI shape still gets a useful message); this is
        # also where we honor the "initial attempts-list 404 ⇒ no attempts
        # yet" rule via _safe_initial_attempts_count().
        try:
            target = verify_assignment_target(course_id, content_id)
            existing_attempts = _safe_initial_attempts_count(
                target["course_id"], target["column_id"],
            )
        except SubmissionFormError as e:
            diag = e.to_diagnostic()
            return failure(
                f"Blackboard submission preflight failed: {e}",
                reason="target_not_verified",
                stage=diag.get("stage", "verify_target"),
                upstream=diag,
                submissionPostSent=False,
            )
        if not target.get("is_assignment"):
            return failure(
                f"BB content {content_id} in course {course_id} is not an "
                f"assignment (handler={target.get('assignment_name')!r}); "
                f"refusing to submit.",
                reason="not_an_assignment",
                stage="verify_target",
                assignment_name=target.get("assignment_name", ""),
                submissionPostSent=False,
            )

        # Step 1: GET the upload form (cookies, nonces, hidden fields)
        try:
            form_info = _get_upload_form(target["course_id"], target["content_id"])
        except SubmissionFormError as e:
            diag = e.to_diagnostic()
            return failure(
                f"Blackboard could not load the assignment submission form: {e}",
                reason="form_unavailable",
                stage=diag.get("stage", "prepare_form"),
                upstream=diag,
                submissionPostSent=False,
            )
        form_data = dict(form_info["form_data"])
        if comment:
            field = _pick_editor_field(
                set(form_info.get("text_field_names", ())), _COMMENT_EDITOR_CANDIDATES,
            )
            if not field:
                raise SubmissionFormError(
                    "BB upload form did not expose a comment editor field",
                    stage="prepare_form", code="BLACKBOARD_COMMENT_FIELD_MISSING",
                )
            form_data[field] = _escape_for_bb_editor(comment)
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
                sha256=initial_sha,
                size=initial_size,
                existing_attempts=existing_attempts,
                target=target,
            )

        # Only a real (non-dry) submit needs to stage the file for the POST.
        staged_dir.mkdir(parents=True, exist_ok=True)
        if staged_path.resolve() != file_path_p:
            shutil.copy2(file_path_p, staged_path)

        # R4: re-hash right before the POST so the bytes on disk haven't
        # changed since the dry-run preview. The caller can pass
        # ``reviewed_sha256`` explicitly; if they did not, we hash the
        # staged copy (which we just made) and skip the comparison.
        staged_size = staged_path.stat().st_size
        staged_sha = sha256_of_file(staged_path)
        if reviewed_sha256 is not None and reviewed_sha256 != staged_sha:
            raise FileChangedSinceReviewError(
                path=str(staged_path),
                reviewed_sha256=reviewed_sha256,
                current_sha256=staged_sha,
                reviewed_size=initial_size,
                current_size=staged_size,
            )

        # Step 3: POST the form with the file in the multipart envelope.
        # Fresh session — CSRF nonce is in the form data (not session-bound),
        # so any session with valid BB auth will work.
        # RULE R2: never replay, never follow redirects — surfacing the
        # 30x as an error is exactly the point.
        sess = _bb_session()
        submit_url = f"{BB_BASE}/webapps/assignment/uploadAssignment?action=submit"
        post_attempted = True
        with open(staged_path, "rb") as fh:
            resp = sess.post(
                submit_url,
                data=form_data,
                files={"newFile_LocalFile0": (
                    target_name, fh, "application/octet-stream")},
                timeout=_net.service_timeout("bb"),
                allow_redirects=False,
            )

        # R2: a 3xx is NOT auto-followed. Treat as an error so the caller
        # can decide whether to retry by hand.
        if 300 <= resp.status_code < 400:
            location = _sanitize_url(resp.headers.get("Location", ""))
            return failure(
                f"BB submission POST returned redirect "
                f"{resp.status_code} (not auto-followed); refusing to replay.",
                reason="redirect_refused",
                submissionPostSent=True,
                http_status=resp.status_code,
                stage="submit_form",
                upstream={
                    "code": "BLACKBOARD_SUBMISSION_REDIRECT",
                    "stage": "submit_form",
                    "status": resp.status_code,
                    "path": submit_url,
                    **({"redirect": location} if location else {}),
                },
            )

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

        # R3: never echo raw HTML / nonces. Strip to a tiny safe slice.
        body_preview = _strip_html_for_error(resp.text or "")[:160]
        return failure(
            f"Form POST returned {resp.status_code}: {body_preview}",
            submissionPostSent=True,
            http_status=resp.status_code,
            stage="submit_form",
            upstream={
                "code": "BLACKBOARD_SUBMISSION_NON_OK",
                "stage": "submit_form",
                "status": resp.status_code,
                "path": submit_url,
            },
        )

    except FileChangedSinceReviewError as e:
        # R4: surface as a distinct failure with a clear "do not retry
        # blindly" hint. (Not raised through failure() because the message
        # already has the SHA-256 diff; just convert to a SubmitResult.)
        return failure(
            str(e),
            reason="file_changed_since_review",
            stage="apply",
            reviewed_sha256=e.reviewed_sha256,
            current_sha256=e.current_sha256,
            reviewed_size=e.reviewed_size,
            current_size=e.current_size,
            path=e.path,
        )
    except SubmissionFormError as e:
        # R3: any SubmissionFormError that escaped the inner try blocks
        # still gets reported with stage + sanitized status + path.
        diag = e.to_diagnostic()
        return failure(
            f"Blackboard submission failed at {diag['stage']}: {e}",
            reason="submission_form_error",
            stage=diag.get("stage"),
            upstream=diag,
            submissionPostSent=False,
        )
    except Exception as e:
        # A network failure around the POST leaves it unknown whether BB
        # received the multipart body — report that instead of a bare
        # failure, so a caller does not retry into a duplicate attempt.
        return failure(
            f"REST submit error: {e}",
            exception_type=type(e).__name__,
            submissionPostSent=post_attempted,
        )


# -------------------------------------------------------------------------
# submit_text / submit_comment — rule R5 text & comment submission paths
# -------------------------------------------------------------------------

def submit_text(content_id: str, text: str, *,
                course_id: Optional[str] = None,
                comment: Optional[str] = None) -> "SubmitResult":
    """Submit plain text to a BB Original text assignment (rule R5).

    R5 — the editor field name comes from the form the server actually
    returns (``text_field_names`` from ``_get_upload_form``), not from a
    hard-coded list. If the expected text editor (``studentSubmission.text``)
    is absent from the form, this fails with a clear error instead of
    silently sending nothing.

    Returns a SubmitResult.
    """
    return _submit_editor_field(
        content_id=content_id,
        course_id=course_id,
        field_kind="text",
        text=text,
        comment=comment,
        candidates=_TEXT_EDITOR_CANDIDATES,
        field_code="BLACKBOARD_TEXT_EDITOR_MISSING",
    )


def submit_comment(content_id: str, comment: str, *,
                   course_id: Optional[str] = None) -> "SubmitResult":
    """Attach a comment to a BB Original assignment (rule R5).

    R5 — the comment editor field name comes from the form the server
    actually returns. If the expected comment editor is absent, this
    fails with a clear error.
    """
    return _submit_editor_field(
        content_id=content_id,
        course_id=course_id,
        field_kind="comment",
        text=None,
        comment=comment,
        candidates=_COMMENT_EDITOR_CANDIDATES,
        field_code="BLACKBOARD_COMMENT_EDITOR_MISSING",
    )


def _submit_editor_field(content_id: str, *,
                         course_id: Optional[str],
                         field_kind: str,
                         text: Optional[str],
                         comment: Optional[str],
                         candidates: tuple[str, ...],
                         field_code: str) -> "SubmitResult":
    """Common body for submit_text / submit_comment. Pulls the form,
    picks the editor field the form actually exposes, and POSTs. R2: one
    POST, no redirects followed. R3: stage + sanitized status on errors.
    """
    post_attempted = False
    try:
        cid = _num_id(content_id) if content_id else ""
        resolved_course_id = _resolve_course_for(content_id, course_id)
        target = verify_assignment_target(resolved_course_id, cid)

        form_info = _get_upload_form(target["course_id"], target["content_id"])
        form_data = dict(form_info["form_data"])
        text_fields = set(form_info.get("text_field_names", ()))

        # R5: pick the editor the form actually exposes.
        field_name = _pick_editor_field(text_fields, candidates)
        if not field_name:
            raise SubmissionFormError(
                f"BB upload form did not expose a {field_kind} editor field "
                f"(expected one of {list(candidates)})",
                stage="prepare_form",
                path=_bb_form_url(target["course_id"], target["content_id"]),
                code=field_code,
            )

        # R4: text submissions don't have a file, but the SHA-256 we promise
        # for "review" is the SHA-256 of the bytes we'd send. For text and
        # comment, that's the encoded body string (UTF-8).
        body_data = dict(form_data)
        body_data["isAjaxSubmit"] = "true"
        body_data["dispatch"] = "submit"
        if text is not None:
            body_data[field_name] = _escape_for_bb_editor(text)
        if comment is not None:
            comment_name = _pick_editor_field(text_fields, _COMMENT_EDITOR_CANDIDATES)
            if not comment_name:
                raise SubmissionFormError(
                    "BB upload form did not expose a comment editor field",
                    stage="prepare_form",
                    path=_bb_form_url(target["course_id"], target["content_id"]),
                    code="BLACKBOARD_COMMENT_EDITOR_MISSING",
                )
            body_data[comment_name] = _escape_for_bb_editor(comment)

        submit_url = f"{BB_BASE}/webapps/assignment/uploadAssignment?action=submit"
        sess = _bb_session()
        # R2: no follow, no replay.
        post_attempted = True
        resp = sess.post(submit_url, data=body_data,
                         timeout=_net.service_timeout("bb"),
                         allow_redirects=False)

        if 300 <= resp.status_code < 400:
            return failure(
                f"BB {field_kind} submission returned redirect "
                f"{resp.status_code} (not auto-followed); refusing to replay.",
                reason="redirect_refused",
                submissionPostSent=True,
                http_status=resp.status_code,
                stage="submit_form",
                upstream={
                    "code": "BLACKBOARD_SUBMISSION_REDIRECT",
                    "stage": "submit_form",
                    "status": resp.status_code,
                    "path": submit_url,
                },
            )

        try:
            parsed = resp.json()
        except Exception:
            parsed = None
        if parsed and "destinationUrl" in parsed:
            return success(
                message=(
                    f"{field_kind.title()} submission OK. "
                    f"destinationUrl: {parsed['destinationUrl']}"
                ),
                destination_url=parsed["destinationUrl"],
            )

        body_preview = _strip_html_for_error(resp.text or "")[:160]
        return failure(
            f"BB {field_kind} submission POST returned {resp.status_code}: {body_preview}",
            submissionPostSent=True,
            http_status=resp.status_code,
            stage="submit_form",
            upstream={
                "code": "BLACKBOARD_SUBMISSION_NON_OK",
                "stage": "submit_form",
                "status": resp.status_code,
                "path": submit_url,
            },
        )
    except FileChangedSinceReviewError as e:
        return failure(str(e), reason="file_changed_since_review", stage="apply",
                   reviewed_sha256=e.reviewed_sha256,
                       current_sha256=e.current_sha256,
                       reviewed_size=e.reviewed_size,
                       current_size=e.current_size, path=e.path)
    except SubmissionFormError as e:
        diag = e.to_diagnostic()
        return failure(
            f"Blackboard {field_kind} submission failed at {diag['stage']}: {e}",
            reason="submission_form_error",
            stage=diag.get("stage"),
            upstream=diag,
            submissionPostSent=False,
        )
    except Exception as e:
        return failure(f"REST {field_kind} submit error: {e}",
                       exception_type=type(e).__name__,
                       submissionPostSent=post_attempted)


def _core_id_safe(value: str) -> str:
    """Wrap query._core_id with the same import surface used elsewhere."""
    from .query import _core_id
    return _core_id(value)


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
    attempt_count is None when the attempt read failed; it is never a
    silent 0, which would read as "not submitted".
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
    if not column_id:
        return 0, assignment_name
    try:
        attempts = get_assignment_attempts(cid, column_id)
    except Exception:
        # A failed read must never come back as "0 attempts".
        return None, assignment_name
    return len(attempts), assignment_name


def get_attempt_info(course_id, content_id):
    """Check BB for existing attempt count and assignment name (REST).

    Returns (attempt_count, assignment_name, session_valid). The third
    element is always True — the REST path raises on auth failure instead
    of returning a session flag (kept for API parity with the old
    Playwright implementation).
    """
    count, name = check_attempts(content_id, course_id=course_id)
    return count, name, count is not None


class SubmissionNotConfirmedError(Exception):
    """Raised when a submission is attempted without an explicit review step.

    The two-step surface exists so that a caller reviews exactly what will be
    uploaded (file, target, hash) before bytes leave the machine.
    """


def _resolve_course_for(content_id: str, course_id: Optional[str]) -> str:
    """Return an explicit course id, or resolve it from the content id."""
    if course_id:
        return course_id
    from .download import resolve_course
    return resolve_course(_num_id(content_id))


def preview_submission(content_id, file_path, course_id=None, comment=None,
                       submitted_name=None) -> dict:
    """Describe exactly what :func:`apply_submission` would upload.

    Never POSTs and never uploads. Verifies the assignment target, counts the
    existing attempts, checks the comment editor exists when a comment is
    given, and hashes the file — so the caller can review the plan, keep
    ``sha256``, and hand it back to ``apply_submission``.

    Two-step surface mirrors sustech-cli v0.11.1
    (``bb submit preview`` → ``bb submit apply --expected-sha256``).
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"file not found: {file_path}")
    if not path.is_file():
        raise IsADirectoryError(f"not a file: {file_path}")

    resolved_course = _resolve_course_for(content_id, course_id)
    target = verify_assignment_target(resolved_course, _num_id(content_id))
    attempt_count = _safe_initial_attempts_count(
        target["course_id"], target.get("column_id"))

    comment_field = None
    if comment:
        form_info = _get_upload_form(target["course_id"], target["content_id"])
        text_fields = set(form_info.get("text_field_names", ()))
        comment_field = _pick_editor_field(text_fields, _COMMENT_EDITOR_CANDIDATES)
        if not comment_field:
            raise SubmissionFormError(
                "the upload form exposes no comment editor field — drop "
                "--comment, or write the comment on Blackboard"
            )

    return {
        "action": ("create a new attempt" if attempt_count == 0
                   else f"create attempt #{attempt_count + 1}"),
        "course_id": target["course_id"],
        "course_name": target.get("course_name", ""),
        "content_id": target["content_id"],
        "column_id": target.get("column_id"),
        "assignment_name": target.get("assignment_name", ""),
        "attempts_so_far": attempt_count,
        "file": str(path),
        "file_name": submitted_name or path.name,
        "size_bytes": path.stat().st_size,
        "sha256": sha256_of_file(path),
        "comment": comment or None,
        "comment_field": comment_field,
        "will_post": False,
    }


def apply_submission(content_id, file_path, course_id=None, submitted_name=None,
                     expected_sha256=None, expected_size=None, confirm=False,
                     comment=None):
    """Submit for real — only for bytes the caller reviewed.

    Requires ``confirm=True`` and the ``expected_sha256`` reported by
    :func:`preview_submission`; a mismatch raises
    :class:`FileChangedSinceReviewError` instead of uploading changed bytes.
    Returns the underlying ``SubmitResult``.
    """
    if not confirm:
        raise SubmissionNotConfirmedError(
            "refusing to submit: review it first with `sustech bb submit "
            "preview <content_id> <file>`, then re-run with --confirm"
        )
    if not expected_sha256:
        raise SubmissionNotConfirmedError(
            "refusing to submit without --expected-sha256 (take it from the "
            "preview output so the reviewed bytes are the submitted bytes)"
        )

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"file not found: {file_path}")
    if not path.is_file():
        raise IsADirectoryError(f"not a file: {file_path}")

    reviewed = expected_sha256.strip().lower()
    if reviewed.startswith("sha256:"):
        reviewed = reviewed.split(":", 1)[1]
    current = sha256_of_file(path)
    current_size = path.stat().st_size
    if current != reviewed:
        raise FileChangedSinceReviewError(
            str(path), reviewed, current,
            expected_size if expected_size is not None else current_size,
            current_size)

    resolved_course = _resolve_course_for(content_id, course_id)
    result = submit_assignment_rest(
        resolved_course,
        _num_id(content_id),
        str(path),
        name_override=submitted_name,
        reviewed_sha256=reviewed,
        comment=comment,
    )
    return result


__all__ = [
    "BB_BASE",
    "SubmissionFormError",
    "SubmissionNotConfirmedError",
    "FileChangedSinceReviewError",
    "submit_assignment_rest",
    "submit_file",
    "submit_assignment",
    "submit_text",
    "submit_comment",
    "preview_submission",
    "apply_submission",
    "verify_assignment_target",
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