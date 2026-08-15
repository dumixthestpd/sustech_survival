"""Tests for sustech_survival.bb.submit_rest (REST-based BB submission)."""
from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ─── Mock data ──────────────────────────────────────────────────────────────

MOCK_UPLOAD_PAGE_HTML = """<!DOCTYPE html>
<html>
<head><title>Upload Assignment: Report of exp 5</title></head>
<body>
<form enctype="multipart/form-data" method="post"
      name="uploadAssignmentForm"
      action="/webapps/assignment/uploadAssignment?action=submit"
      id="uploadAssignmentFormId"
      onsubmit="return checkDupeFile('submit')">
  <input type="hidden" name="blackboard.platform.security.NonceUtil.nonce"
         value="d4eb31bc-35c5-4541-80aa-73d6a5f0e56d" />
  <input type="hidden" name="blackboard.platform.security.NonceUtil.nonce.ajax"
         id="ajaxNonceId" value="0a139404-ec7a-4f7d-8b6e-7577a6083844" />
  <input type="hidden" name="isAjaxSubmit" id="isAjaxSubmit" value="true" />
  <input type="hidden" name="course_id" id="course_id" value="_8328_1" />
  <input type="hidden" name="content_id" id="content_id" value="_610821_1" />
  <input type="hidden" name="attempt_id" id="attempt_id" value="" />
  <input type="hidden" name="dispatch" id="dispatch" value="" />
  <input type="hidden" name="recallUrl"
         value="/webapps/blackboard/content/listContent.jsp?content_id=_6107" />
  <input type="hidden" name="studentSubmission.text_f"
         value="BB%3FBB_dmS0o5zYW084PHDI2l5WAl82TKid2oesJAOPSbj3Jj" />
  <input type="hidden" name="studentSubmission.text_w"
         value="https://bb.sustech.edu.cn/sessions/96/960DFEAE5DB2" />
  <input type="hidden" name="studentSubmission.type" value="H" />
  <input type="hidden" name="student_commentstype" value="H" />
  <input class="hiddenInput" type="file" tabindex="-1" multiple
         aria-hidden="true" id="newFile_chooseLocalFile" />
</form>
</body>
</html>
"""

MOCK_FORM_RESPONSE_JSON = json.dumps({
    "destinationUrl": "/webapps/assignment/uploadAssignment?course_id=_8328_1&content_id=_610821_1&mode=DEFAULT"
})


# ─── _get_upload_form parsing tests ─────────────────────────────────────────

def test_get_upload_form_extracts_all_hidden_fields():
    """All hidden inputs in the form should be extracted into form_data."""
    from sustech_survival.bb.submit_rest import _get_upload_form
    with patch("sustech_survival.bb.submit_rest._bb_session") as mock_sess:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = MOCK_UPLOAD_PAGE_HTML
        mock_sess.return_value.get.return_value = mock_response
        info = _get_upload_form("8328", "610821")

    form_data = info["form_data"]
    assert form_data["isAjaxSubmit"] == "true"
    assert form_data["course_id"] == "_8328_1"
    assert form_data["content_id"] == "_610821_1"
    assert form_data["attempt_id"] == ""
    assert "blackboard.platform.security.NonceUtil.nonce" in form_data
    assert "blackboard.platform.security.NonceUtil.nonce.ajax" in form_data
    assert form_data["studentSubmission.text_w"].startswith("https://")


def test_get_upload_form_extracts_file_input_id():
    """The unnamed file input's id should be captured for reference."""
    from sustech_survival.bb.submit_rest import _get_upload_form
    with patch("sustech_survival.bb.submit_rest._bb_session") as mock_sess:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = MOCK_UPLOAD_PAGE_HTML
        mock_sess.return_value.get.return_value = mock_response
        info = _get_upload_form("8328", "610821")

    assert info["file_input_id"] == "newFile_chooseLocalFile"


def test_get_upload_form_extracts_form_action():
    """The form's action URL should be captured."""
    from sustech_survival.bb.submit_rest import _get_upload_form
    with patch("sustech_survival.bb.submit_rest._bb_session") as mock_sess:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = MOCK_UPLOAD_PAGE_HTML
        mock_sess.return_value.get.return_value = mock_response
        info = _get_upload_form("8328", "610821")

    assert info["form_action"] == "/webapps/assignment/uploadAssignment?action=submit"


def test_get_upload_form_uses_correct_url():
    """GET should hit /uploadAssignment with content_id, course_id, group_id."""
    from sustech_survival.bb.submit_rest import _get_upload_form
    with patch("sustech_survival.bb.submit_rest._bb_session") as mock_sess:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = MOCK_UPLOAD_PAGE_HTML
        mock_sess.return_value.get.return_value = mock_response
        _get_upload_form("8328", "610821")

    called_url = mock_sess.return_value.get.call_args[0][0]
    assert "content_id=_610821_1" in called_url
    assert "course_id=_8328_1" in called_url
    assert "group_id=" in called_url
    assert "action=newAttempt" in called_url


# ─── submit_assignment_rest end-to-end ──────────────────────────────────────

def test_submit_assignment_rest_dry_run(tmp_path):
    """Dry-run: GET form, do NOT POST, return descriptive message."""
    from sustech_survival.bb.submit_rest import submit_assignment_rest
    from sustech_survival.bb.result import SubmitStatus
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    with patch("sustech_survival.bb.submit_rest._bb_session") as mock_sess:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = MOCK_UPLOAD_PAGE_HTML
        mock_sess.return_value.get.return_value = mock_response
        result = submit_assignment_rest(
            "8328", "610821", str(pdf),
            name_override="<sid>-<name>-Experiment 5 (Aspirin).pdf",
            dry_run=True,
        )
    assert result.ok is True
    assert result.status == SubmitStatus.DRY_RUN
    assert "DRY-RUN" in result.message
    assert "Experiment 5" in result.message
    # The POST should NOT have been called
    mock_sess.return_value.post.assert_not_called()


def test_submit_assignment_rest_file_not_found():
    """Missing file should return FAILURE SubmitResult with clear error."""
    from sustech_survival.bb.submit_rest import submit_assignment_rest
    from sustech_survival.bb.result import SubmitStatus
    result = submit_assignment_rest(
        "8328", "610821", "/nonexistent/file.pdf", dry_run=True,
    )
    assert result.ok is False
    assert result.status == SubmitStatus.FAILURE
    assert "not found" in result.message.lower() or "no such file" in result.message.lower()
    assert result.diagnostics.get("reason") == "file_not_found"


def test_submit_assignment_rest_empty_file(tmp_path):
    """Empty file should be rejected."""
    from sustech_survival.bb.submit_rest import submit_assignment_rest
    from sustech_survival.bb.result import SubmitStatus
    pdf = tmp_path / "empty.pdf"
    pdf.write_bytes(b"")
    result = submit_assignment_rest("8328", "610821", str(pdf))
    assert result.ok is False
    assert result.status == SubmitStatus.FAILURE
    assert "empty" in result.message.lower()
    assert result.diagnostics.get("reason") == "file_empty"


def test_submit_assignment_rest_submits_form(tmp_path):
    """Live flow: GET form, POST form, parse destinationUrl."""
    from sustech_survival.bb.submit_rest import submit_assignment_rest
    from sustech_survival.bb.result import SubmitStatus
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    with patch("sustech_survival.bb.submit_rest._bb_session") as mock_sess:
        get_resp = MagicMock()
        get_resp.status_code = 200
        get_resp.text = MOCK_UPLOAD_PAGE_HTML
        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json.return_value = json.loads(MOCK_FORM_RESPONSE_JSON)
        post_resp.text = MOCK_FORM_RESPONSE_JSON
        post_resp.headers = {"Content-Type": "text/x-json;charset=UTF-8"}
        mock_sess.return_value.get.return_value = get_resp
        mock_sess.return_value.post.return_value = post_resp
        result = submit_assignment_rest("8328", "610821", str(pdf))

    assert result.ok is True
    assert result.status == SubmitStatus.SUCCESS
    assert "destinationUrl" in result.message
    assert result.destination_url is not None
    assert "/uploadAssignment" in result.destination_url
    # POST was called
    mock_sess.return_value.post.assert_called_once()


def test_submit_assignment_rest_sends_file_in_multipart(tmp_path):
    """The file must be in the multipart envelope as newFile_LocalFile0."""
    from sustech_survival.bb.submit_rest import submit_assignment_rest
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    with patch("sustech_survival.bb.submit_rest._bb_session") as mock_sess:
        get_resp = MagicMock()
        get_resp.status_code = 200
        get_resp.text = MOCK_UPLOAD_PAGE_HTML
        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json.return_value = json.loads(MOCK_FORM_RESPONSE_JSON)
        post_resp.text = MOCK_FORM_RESPONSE_JSON
        post_resp.headers = {"Content-Type": "text/x-json;charset=UTF-8"}
        mock_sess.return_value.get.return_value = get_resp
        mock_sess.return_value.post.return_value = post_resp
        result = submit_assignment_rest("8328", "610821", str(pdf))

    assert result.ok
    call_kwargs = mock_sess.return_value.post.call_args.kwargs
    # File must be present in multipart
    assert "files" in call_kwargs
    assert "newFile_LocalFile0" in call_kwargs["files"]


def test_submit_assignment_rest_includes_picker_fields(tmp_path):
    """The POST data must include the file-picker fields BB's JS adds."""
    from sustech_survival.bb.submit_rest import submit_assignment_rest
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    with patch("sustech_survival.bb.submit_rest._bb_session") as mock_sess:
        get_resp = MagicMock()
        get_resp.status_code = 200
        get_resp.text = MOCK_UPLOAD_PAGE_HTML
        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json.return_value = json.loads(MOCK_FORM_RESPONSE_JSON)
        post_resp.text = MOCK_FORM_RESPONSE_JSON
        post_resp.headers = {"Content-Type": "text/x-json;charset=UTF-8"}
        mock_sess.return_value.get.return_value = get_resp
        mock_sess.return_value.post.return_value = post_resp
        result = submit_assignment_rest(
            "8328", "610821", str(pdf),
            name_override="中文名-test.pdf",
        )

    assert result.ok
    call_kwargs = mock_sess.return_value.post.call_args.kwargs
    data = call_kwargs["data"]
    # The picker fields
    assert data["newFile_attachmentType"] == "L"
    assert data["newFile_fileId"] == "new"
    assert data["newFile_linkTitle"] == "中文名-test.pdf"
    assert data["dispatch"] == "submit"


def test_submit_assignment_rest_uses_target_name(tmp_path):
    """The staged file should have the target_name as basename."""
    from sustech_survival.bb.submit_rest import submit_assignment_rest
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    with patch("sustech_survival.bb.submit_rest._bb_session") as mock_sess:
        get_resp = MagicMock()
        get_resp.status_code = 200
        get_resp.text = MOCK_UPLOAD_PAGE_HTML
        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json.return_value = json.loads(MOCK_FORM_RESPONSE_JSON)
        post_resp.text = MOCK_FORM_RESPONSE_JSON
        post_resp.headers = {"Content-Type": "text/x-json;charset=UTF-8"}
        mock_sess.return_value.get.return_value = get_resp
        mock_sess.return_value.post.return_value = post_resp
        result = submit_assignment_rest(
            "8328", "610821", str(pdf),
            name_override="中文名-test.pdf",
        )
    assert result.ok
    files = mock_sess.return_value.post.call_args.kwargs["files"]
    assert "中文名-test.pdf" in str(files)


def test_submit_assignment_rest_handles_non_json_response(tmp_path):
    """A 200 with HTML body should surface a clear error."""
    from sustech_survival.bb.submit_rest import submit_assignment_rest
    from sustech_survival.bb.result import SubmitStatus
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    with patch("sustech_survival.bb.submit_rest._bb_session") as mock_sess:
        get_resp = MagicMock()
        get_resp.status_code = 200
        get_resp.text = MOCK_UPLOAD_PAGE_HTML
        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json.side_effect = ValueError("not json")
        post_resp.text = "<html>error</html>"
        post_resp.headers = {"Content-Type": "text/html"}
        mock_sess.return_value.get.return_value = get_resp
        mock_sess.return_value.post.return_value = post_resp
        result = submit_assignment_rest("8328", "610821", str(pdf))

    assert result.ok is False
    assert result.status == SubmitStatus.FAILURE
    assert "non-JSON" in result.message or "200" in result.message
    assert result.diagnostics.get("http_status") == 200


def test_submit_assignment_rest_handles_500(tmp_path):
    """A 500 error should be reported."""
    from sustech_survival.bb.submit_rest import submit_assignment_rest
    from sustech_survival.bb.result import SubmitStatus
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    with patch("sustech_survival.bb.submit_rest._bb_session") as mock_sess:
        get_resp = MagicMock()
        get_resp.status_code = 200
        get_resp.text = MOCK_UPLOAD_PAGE_HTML
        post_resp = MagicMock()
        post_resp.status_code = 500
        post_resp.json.side_effect = ValueError("not json")
        post_resp.text = "Internal Server Error"
        post_resp.headers = {"Content-Type": "text/plain"}
        mock_sess.return_value.get.return_value = get_resp
        mock_sess.return_value.post.return_value = post_resp
        result = submit_assignment_rest("8328", "610821", str(pdf))

    assert result.ok is False
    assert result.status == SubmitStatus.FAILURE
    assert "500" in result.message
    assert result.diagnostics.get("http_status") == 500


# ─── Backwards compat: .to_tuple() shim ─────────────────────────────────

def test_submit_result_to_tuple_for_legacy_callers():
    """Legacy `(ok, msg)` callers can use `result.to_tuple()` to get the
    old shape. New code should use the dataclass fields directly."""
    from sustech_survival.bb.result import success, failure, SubmitResult
    ok, msg = success("hi").to_tuple()
    assert ok is True
    assert msg == "hi"

    ok, msg = failure("nope").to_tuple()
    assert ok is False
    assert msg == "nope"


def test_submit_result_status_enum_values():
    """SubmitStatus values are stable strings for JSON serialization."""
    from sustech_survival.bb.result import SubmitStatus
    assert SubmitStatus.SUCCESS.value == "success"
    assert SubmitStatus.FAILURE.value == "failure"
    assert SubmitStatus.DUPLICATE.value == "duplicate"
    assert SubmitStatus.LATE_BLOCKED.value == "late_blocked"
    assert SubmitStatus.DRY_RUN.value == "dry_run"


def test_submit_result_is_duplicate_property():
    """The dedup case is now an explicit property, not a magic None."""
    from sustech_survival.bb.result import duplicate, success, failure
    assert duplicate("already there").is_duplicate is True
    assert success("ok").is_duplicate is False
    assert failure("oops").is_duplicate is False
    # And bool() collapses to False for dup (use is_duplicate for the case)
    assert not duplicate("x")


# ─── Module-level invariants ────────────────────────────────────────────────

def test_module_docstring_says_working():
    """The module docstring should declare the path is now working (so
    future maintainers don't think it's still partial)."""
    from sustech_survival.bb import submit_rest
    doc = submit_rest.__doc__
    assert doc is not None
    assert "WORKING" in doc or "working" in doc.lower()
    # Should mention the file-picker fields by name
    assert "newFile_LocalFile0" in doc
    assert "newFile_attachmentType" in doc
