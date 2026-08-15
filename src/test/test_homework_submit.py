"""Tests for HomeworkItem.submit() high-level method.

The submit() method is a thin OO wrapper around the lower-level
sustech_survival.bb.submit.submit_assignment() primitive.
"""
from unittest.mock import MagicMock, patch

import pytest
from sustech_survival.bb.items import HomeworkItem


class TestHomeworkItemSubmitExists:
    """The submit() method should exist on HomeworkItem."""

    def test_homeworkitem_has_submit_method(self):
        hw = HomeworkItem(
            sub_id="x", title="HW1",
            content_id="626071", course_id="8221",
        )
        assert hasattr(hw, "submit"), \
            "HomeworkItem should expose .submit() method"
        assert callable(hw.submit)

    def test_submit_signature_accepts_required_args(self):
        import inspect
        sig = inspect.signature(HomeworkItem.submit)
        params = sig.parameters
        # file_path is positional-or-keyword
        assert "file_path" in params
        # target_name, dry_run, skip_dedup, headless are kwargs
        assert "target_name" in params
        assert "dry_run" in params
        assert "skip_dedup" in params
        assert "headless" in params


class TestHomeworkItemSubmitDelegates:
    """The submit() method should call submit_assignment with the right args."""

    def test_submit_delegates_to_submit_assignment(self, monkeypatch, tmp_path):
        """Verify the right kwargs are passed through."""
        hw = HomeworkItem(
            sub_id="x", title="HW1",
            content_id="626071", course_id="8221",
        )

        # Create a real file so Path().name works
        real_pdf = tmp_path / "original.pdf"
        real_pdf.write_bytes(b"%PDF-1.4 dummy")

        captured = {}

        def fake_submit_assignment(*args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            from sustech_survival.bb.result import success
            return success("FAKE_OK")

        # Import the lazy path
        from sustech_survival.bb import submit as submit_mod
        monkeypatch.setattr(submit_mod, "submit_assignment", fake_submit_assignment)

        # Re-import HomeworkItem to pick up the patched submit_assignment
        # (it's lazy-imported, so the patch takes effect on call)
        result = hw.submit(
            file_path=str(real_pdf),
            target_name="HW1-renamed.pdf",
            dry_run=True,
            skip_dedup=True,
            headless=False,
        )

        assert result.ok is True
        assert result.message == "FAKE_OK"
        # Args: course_id, content_id, file_paths
        assert captured["args"][0] == "8221"
        assert captured["args"][1] == "626071"
        assert captured["args"][2] == [str(real_pdf)]
        # Kwargs: name_override=target_name, dry_run, skip_dedup, headless
        assert captured["kwargs"]["name_override"] == "HW1-renamed.pdf"
        assert captured["kwargs"]["dry_run"] is True
        assert captured["kwargs"]["skip_dedup"] is True
        assert captured["kwargs"]["headless"] is False

    def test_submit_uses_basename_when_no_target_name(self, monkeypatch, tmp_path):
        """target_name defaults to file_path's basename."""
        hw = HomeworkItem(
            sub_id="x", title="HW1",
            content_id="626071", course_id="8221",
        )

        real_pdf = tmp_path / "my_basename.pdf"
        real_pdf.write_bytes(b"%PDF-1.4 dummy")

        captured = {}

        def fake_submit_assignment(*args, **kwargs):
            captured["kwargs"] = kwargs
            from sustech_survival.bb.result import success
            return success("OK")

        from sustech_survival.bb import submit as submit_mod
        monkeypatch.setattr(submit_mod, "submit_assignment", fake_submit_assignment)

        result = hw.submit(file_path=str(real_pdf))
        assert result.ok is True

        assert captured["kwargs"]["name_override"] == "my_basename.pdf"


class TestHomeworkItemDeadlineWarning:
    """Late-submission safety: if homeworkitem.ddl is in the past, submit()
    should emit a UserWarning so the user knows they're creating a late
    attempt. force_late=True suppresses it.
    """

    def _patched_submit(self, monkeypatch):
        """Return a captured-kwargs fake submit_assignment."""
        captured = {}
        def fake_submit_assignment(*args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            from sustech_survival.bb.result import success
            return success("FAKE_OK")
        from sustech_survival.bb import submit as submit_mod
        monkeypatch.setattr(submit_mod, "submit_assignment", fake_submit_assignment)
        return captured

    def test_past_deadline_iso_format_emits_warning(self, monkeypatch, tmp_path):
        """ISO 8601 deadline in the past → UserWarning."""
        import warnings
        hw = HomeworkItem(
            sub_id="x", title="HW1",
            course_id="1234", content_id="5678",
            deadline="2020-01-01T00:00:00+08:00",  # way in the past
        )
        self._patched_submit(monkeypatch)
        pdf = tmp_path / "f.pdf"
        pdf.write_bytes(b"%PDF-1.4")

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = hw.submit(file_path=str(pdf), dry_run=False, skip_dedup=True)
        assert result.ok is True
        late = [x for x in w if "LATE" in str(x.message)]
        assert len(late) == 1, f"Expected exactly 1 LATE warning, got {len(late)}: {[str(x.message) for x in w]}"
        msg_text = str(late[0].message)
        assert "deadline" in msg_text.lower()
        assert "2020-01-01" in msg_text

    def test_past_deadline_chinese_format_emits_warning(self, monkeypatch, tmp_path):
        """Chinese '2026年5月12日 23:59' format is recognized."""
        import warnings
        hw = HomeworkItem(
            sub_id="x", title="HW1",
            course_id="1234", content_id="5678",
            deadline="2020年5月12日 23:59",
        )
        self._patched_submit(monkeypatch)
        pdf = tmp_path / "f.pdf"
        pdf.write_bytes(b"%PDF-1.4")

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            hw.submit(file_path=str(pdf), dry_run=False, skip_dedup=True)
        assert any("LATE" in str(x.message) for x in w)

    def test_future_deadline_no_warning(self, monkeypatch, tmp_path):
        """Future deadline → no LATE warning."""
        import warnings
        from datetime import datetime, timezone, timedelta
        CHINA = timezone(timedelta(hours=8))
        future = (datetime.now(CHINA) + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S%z")
        hw = HomeworkItem(
            sub_id="x", title="HW1",
            course_id="1234", content_id="5678",
            deadline=future,
        )
        self._patched_submit(monkeypatch)
        pdf = tmp_path / "f.pdf"
        pdf.write_bytes(b"%PDF-1.4")

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            hw.submit(file_path=str(pdf), dry_run=False, skip_dedup=True)
        assert not any("LATE" in str(x.message) for x in w), \
            f"Future deadline should not warn, got: {[str(x.message) for x in w]}"

    def test_empty_deadline_no_warning(self, monkeypatch, tmp_path):
        """No deadline set → skip the check (can't determine)."""
        import warnings
        hw = HomeworkItem(
            sub_id="x", title="HW1",
            course_id="1234", content_id="5678",
            deadline="",
        )
        self._patched_submit(monkeypatch)
        pdf = tmp_path / "f.pdf"
        pdf.write_bytes(b"%PDF-1.4")

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            hw.submit(file_path=str(pdf), dry_run=False, skip_dedup=True)
        assert not any("LATE" in str(x.message) for x in w)

    def test_unparseable_deadline_no_warning(self, monkeypatch, tmp_path):
        """Garbage deadline string → no warning (don't false-positive)."""
        import warnings
        hw = HomeworkItem(
            sub_id="x", title="HW1",
            course_id="1234", content_id="5678",
            deadline="not a date",
        )
        self._patched_submit(monkeypatch)
        pdf = tmp_path / "f.pdf"
        pdf.write_bytes(b"%PDF-1.4")

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            hw.submit(file_path=str(pdf), dry_run=False, skip_dedup=True)
        assert not any("LATE" in str(x.message) for x in w)

    def test_force_late_suppresses_warning(self, monkeypatch, tmp_path):
        """force_late=True → no warning even with past deadline."""
        import warnings
        hw = HomeworkItem(
            sub_id="x", title="HW1",
            course_id="1234", content_id="5678",
            deadline="2020-01-01T00:00:00+08:00",
        )
        self._patched_submit(monkeypatch)
        pdf = tmp_path / "f.pdf"
        pdf.write_bytes(b"%PDF-1.4")

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            hw.submit(file_path=str(pdf), dry_run=False, skip_dedup=True, force_late=True)
        assert not any("LATE" in str(x.message) for x in w), \
            f"force_late=True should suppress, got: {[str(x.message) for x in w]}"

    def test_dry_run_does_not_emit_warning(self, monkeypatch, tmp_path):
        """dry_run=True doesn't actually submit, so no warning needed."""
        import warnings
        hw = HomeworkItem(
            sub_id="x", title="HW1",
            course_id="1234", content_id="5678",
            deadline="2020-01-01T00:00:00+08:00",
        )
        self._patched_submit(monkeypatch)
        pdf = tmp_path / "f.pdf"
        pdf.write_bytes(b"%PDF-1.4")

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            hw.submit(file_path=str(pdf), dry_run=True, skip_dedup=True)
        # dry_run: don't warn (user is just inspecting, not actually submitting)
        assert not any("LATE" in str(x.message) for x in w)

    def test_warning_message_includes_how_late(self, monkeypatch, tmp_path):
        """The warning should say how late (e.g., '5 days, 0:00:00')."""
        import warnings
        from datetime import datetime, timezone, timedelta
        CHINA = timezone(timedelta(hours=8))
        past_5_days = datetime.now(CHINA) - timedelta(days=5)
        deadline_str = past_5_days.strftime("%Y-%m-%dT%H:%M:%S%z")
        hw = HomeworkItem(
            sub_id="x", title="HW1",
            course_id="1234", content_id="5678",
            deadline=deadline_str,
        )
        self._patched_submit(monkeypatch)
        pdf = tmp_path / "f.pdf"
        pdf.write_bytes(b"%PDF-1.4")

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            hw.submit(file_path=str(pdf), dry_run=False, skip_dedup=True)
        late = [x for x in w if "LATE" in str(x.message)]
        assert len(late) == 1
        # Message should mention days
        assert "5 days" in str(late[0].message) or "4 days" in str(late[0].message), \
            f"Warning should show days late, got: {late[0].message}"


class TestParseDeadline:
    """Unit tests for the _parse_deadline helper."""

    def test_iso_with_tz(self):
        from sustech_survival.bb.items import _parse_deadline
        d = _parse_deadline("2026-05-12T23:59:00+08:00")
        assert d is not None
        assert d.year == 2026
        assert d.month == 5
        assert d.day == 12
        assert d.hour == 23
        assert d.minute == 59

    def test_iso_without_tz_naive(self):
        from sustech_survival.bb.items import _parse_deadline
        d = _parse_deadline("2026-05-12T23:59:00")
        assert d is not None
        assert d.tzinfo is None  # naive, but parseable

    def test_chinese_full(self):
        from sustech_survival.bb.items import _parse_deadline
        d = _parse_deadline("2026年5月12日 23:59")
        assert d is not None
        assert d.year == 2026 and d.month == 5 and d.day == 12
        assert d.hour == 23 and d.minute == 59

    def test_chinese_date_only(self):
        from sustech_survival.bb.items import _parse_deadline
        d = _parse_deadline("2026年5月12日")
        assert d is not None
        assert d.year == 2026 and d.month == 5 and d.day == 12

    def test_empty_string(self):
        from sustech_survival.bb.items import _parse_deadline
        assert _parse_deadline("") is None
        assert _parse_deadline("   ") is None
        assert _parse_deadline(None) is None

    def test_garbage(self):
        from sustech_survival.bb.items import _parse_deadline
        assert _parse_deadline("not a date") is None
        assert _parse_deadline("12345") is None
        assert _parse_deadline("2026-13-99") is None  # invalid month/day


class TestHomeworkItemFromSubmissionPage:
    """HomeworkItem.from_submission_page() should build an item from the
    live uploadAssignment page — title and deadline extracted from the
    raw HTML. No manual construction needed in real scripts.
    """

    MOCK_PAGE_HTML = """<!DOCTYPE html>
<html>
<head><title>Upload Assignment: Report of exp 5</title></head>
<body>
  <h1>Upload Assignment: Report of exp 5</h1>
  <div class="assignmentInfo">
    <dl>
      <dt>到期日期</dt>
      <dd>2026年5月12日 23:59</dd>
    </dl>
  </div>
  <form id="uploadAssignmentFormId" action="/webapps/assignment/uploadAssignment?action=submit">
    <input type="hidden" name="course_id" value="_8328_1" />
    <input type="hidden" name="content_id" value="_610821_1" />
  </form>
</body>
</html>
"""

    # Real BB format: "到期日期" is followed by a newline, then the date on
    # the next line. The 2026-06-07 real page had:
    #   到期日期
    #   2026年6月8日 23:59
    MOCK_PAGE_HTML_PROD_FORMAT = """<!DOCTYPE html>
<html>
<head><title>Upload Assignment: Report of exp 5</title></head>
<body>
到期日期
2026年5月12日 23:59
<form id="uploadAssignmentFormId"></form>
</body>
</html>
"""

    MOCK_PAGE_HTML_NO_DEADLINE = """<!DOCTYPE html>
<html>
<head><title>Upload Assignment: Some Assignment</title></head>
<body>
  <h1>Upload Assignment: Some Assignment</h1>
  <form id="uploadAssignmentFormId"></form>
</body>
</html>
"""

    def test_from_submission_page_returns_class_instance(self, monkeypatch):
        """Should return a HomeworkItem, not raise."""
        from sustech_survival.bb.items import HomeworkItem
        with patch("sustech_survival.bb.items._bb_session_for_discovery") as mock_sess:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.text = self.MOCK_PAGE_HTML
            mock_sess.return_value.get.return_value = mock_response
            hw = HomeworkItem.from_submission_page("8328", "610821")
        assert isinstance(hw, HomeworkItem)
        assert hw.course_id == "8328"
        assert hw.content_id == "610821"

    def test_from_submission_page_extracts_title(self, monkeypatch):
        """Title should come from the page <title> tag, not be hardcoded."""
        from sustech_survival.bb.items import HomeworkItem
        with patch("sustech_survival.bb.items._bb_session_for_discovery") as mock_sess:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.text = self.MOCK_PAGE_HTML
            mock_sess.return_value.get.return_value = mock_response
            hw = HomeworkItem.from_submission_page("8328", "610821")
        assert hw.title == "Report of exp 5"

    def test_from_submission_page_extracts_chinese_deadline(self, monkeypatch):
        """Deadline should come from '到期日期' line in Chinese format.

        Real BB has the date on a separate line after '到期日期':
            到期日期
            2026年5月12日 23:59
        """
        from sustech_survival.bb.items import HomeworkItem
        with patch("sustech_survival.bb.items._bb_session_for_discovery") as mock_sess:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.text = self.MOCK_PAGE_HTML_PROD_FORMAT
            mock_sess.return_value.get.return_value = mock_response
            hw = HomeworkItem.from_submission_page("8328", "610821")
        assert hw.deadline == "2026年5月12日 23:59"

    def test_from_submission_page_empty_deadline_when_missing(self, monkeypatch):
        """If the page has no '到期日期' line, deadline should be '' (not crash)."""
        from sustech_survival.bb.items import HomeworkItem
        with patch("sustech_survival.bb.items._bb_session_for_discovery") as mock_sess:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.text = self.MOCK_PAGE_HTML_NO_DEADLINE
            mock_sess.return_value.get.return_value = mock_response
            hw = HomeworkItem.from_submission_page("8328", "610821")
        assert hw.deadline == ""
        # Title still extracted
        assert hw.title == "Some Assignment"

    def test_from_submission_page_uses_correct_url(self, monkeypatch):
        """GET should hit /uploadAssignment with content_id, course_id, group_id."""
        from sustech_survival.bb.items import HomeworkItem
        with patch("sustech_survival.bb.items._bb_session_for_discovery") as mock_sess:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.text = self.MOCK_PAGE_HTML
            mock_sess.return_value.get.return_value = mock_response
            HomeworkItem.from_submission_page("8328", "610821")
        called_url = mock_sess.return_value.get.call_args[0][0]
        assert "content_id=_610821_1" in called_url
        assert "course_id=_8328_1" in called_url
        assert "group_id=" in called_url
        assert "action=newAttempt" in called_url

    def test_from_submission_page_then_submit_warns_late(self, monkeypatch, tmp_path):
        """End-to-end: extract from page (with past deadline) + submit → warning fires."""
        import warnings
        from sustech_survival.bb.items import HomeworkItem
        # Mock page returns a PAST deadline (prod format: "到期日期\n2020...")
        past_html = """<html>
<head><title>Upload Assignment: Old HW</title></head>
<body>
到期日期
2020年1月1日 23:59
</body>
</html>"""
        with patch("sustech_survival.bb.items._bb_session_for_discovery") as mock_sess:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.text = past_html
            mock_sess.return_value.get.return_value = mock_response
            hw = HomeworkItem.from_submission_page("1234", "5678")

        # Mock the actual submission
        def fake_submit_assignment(*args, **kwargs):
            from sustech_survival.bb.result import success
            return success("OK")
        from sustech_survival.bb import submit as submit_mod
        monkeypatch.setattr(submit_mod, "submit_assignment", fake_submit_assignment)

        pdf = tmp_path / "f.pdf"
        pdf.write_bytes(b"%PDF-1.4")

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            hw.submit(file_path=str(pdf), dry_run=False, skip_dedup=True)
        assert any("LATE" in str(x.message) for x in w), \
            f"Expected LATE warning from page-extracted past deadline, got: {[str(x.message) for x in w]}"


# ─── HomeworkItem.submit_rest — REST path tests ────────────────────────────

class TestHomeworkItemSubmitRest:
    """The submit_rest() method exists and delegates to submit_rest module."""

    def test_homeworkitem_has_submit_rest_method(self):
        hw = HomeworkItem(
            sub_id="x", title="HW1",
            content_id="626071", course_id="8221",
        )
        assert hasattr(hw, "submit_rest"), \
            "HomeworkItem should expose .submit_rest() method"
        assert callable(hw.submit_rest)

    def test_submit_rest_signature(self):
        import inspect
        sig = inspect.signature(HomeworkItem.submit_rest)
        # Required: file_path
        params = sig.parameters
        assert "file_path" in params
        # Optional: target_name, dry_run, skip_dedup, force_late
        assert "target_name" in params
        assert "dry_run" in params
        assert "skip_dedup" in params
        assert "force_late" in params

    def test_submit_rest_delegates_to_submit_assignment_rest(self, monkeypatch, tmp_path):
        """Verify the right kwargs are passed through."""
        hw = HomeworkItem(
            sub_id="x", title="HW1",
            content_id="626071", course_id="8221",
        )
        real_pdf = tmp_path / "real.pdf"
        real_pdf.write_bytes(b"%PDF-1.4\n")

        from sustech_survival.bb import submit as submit_rest_mod
        captured = {}

        def fake_submit_assignment_rest(course_id, content_id, file_path,
                                         *, name_override=None, dry_run=False,
                                         skip_dedup=False):
            captured["args"] = (course_id, content_id, file_path)
            captured["kwargs"] = {
                "name_override": name_override,
                "dry_run": dry_run,
                "skip_dedup": skip_dedup,
            }
            return True, "fake-success"

        monkeypatch.setattr(submit_rest_mod, "submit_assignment_rest",
                            fake_submit_assignment_rest)
        # Lazy import: re-import items so the patch takes effect
        from importlib import reload
        from sustech_survival.bb import items
        reload(items)

        ok, msg = items.HomeworkItem(
            sub_id="x", title="HW1",
            content_id="626071", course_id="8221",
        ).submit_rest(
            file_path=str(real_pdf),
            target_name="HW1-renamed.pdf",
            dry_run=True,
        )
        assert ok is True
        assert msg == "fake-success"
        assert captured["args"] == ("8221", "626071", str(real_pdf))
        assert captured["kwargs"]["name_override"] == "HW1-renamed.pdf"
        assert captured["kwargs"]["dry_run"] is True

    def test_submit_rest_uses_basename_when_no_target_name(self, monkeypatch, tmp_path):
        """target_name defaults to file_path's basename."""
        real_pdf = tmp_path / "my_basename.pdf"
        real_pdf.write_bytes(b"%PDF-1.4\n")

        from sustech_survival.bb import submit as submit_rest_mod
        captured = {}

        def fake_submit_assignment_rest(course_id, content_id, file_path,
                                         *, name_override=None, **kw):
            captured["kwargs"] = {"name_override": name_override}
            return True, "ok"

        monkeypatch.setattr(submit_rest_mod, "submit_assignment_rest",
                            fake_submit_assignment_rest)
        from importlib import reload
        from sustech_survival.bb import items
        reload(items)

        ok, msg = items.HomeworkItem(
            sub_id="x", title="HW1",
            content_id="626071", course_id="8221",
        ).submit_rest(file_path=str(real_pdf))
        assert captured["kwargs"]["name_override"] == "my_basename.pdf"

    def test_submit_rest_past_deadline_emits_warning(self, monkeypatch, tmp_path):
        """ISO 8601 deadline in the past → UserWarning."""
        import warnings
        hw = HomeworkItem(
            sub_id="x", title="HW1",
            course_id="1234", content_id="5678",
            deadline="2020-01-01T00:00:00+08:00",  # past
        )
        pdf = tmp_path / "x.pdf"
        pdf.write_bytes(b"%PDF-1.4\n")

        from sustech_survival.bb import submit as submit_rest_mod
        def fake_submit(*a, **kw): return True, "ok"
        monkeypatch.setattr(submit_rest_mod, "submit_assignment_rest", fake_submit)

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            ok, msg = hw.submit_rest(file_path=str(pdf), dry_run=False, skip_dedup=True)
        assert ok is True
        late = [x for x in w if "LATE" in str(x.message)]
        assert len(late) >= 1

    def test_submit_rest_dry_run_no_warning(self, monkeypatch, tmp_path):
        """dry_run suppresses the LATE warning (no real attempt made)."""
        import warnings
        hw = HomeworkItem(
            sub_id="x", title="HW1",
            course_id="1234", content_id="5678",
            deadline="2020-01-01T00:00:00+08:00",  # past
        )
        pdf = tmp_path / "x.pdf"
        pdf.write_bytes(b"%PDF-1.4\n")

        from sustech_survival.bb import submit as submit_rest_mod
        def fake_submit(*a, **kw): return True, "DRY-RUN: ok"
        monkeypatch.setattr(submit_rest_mod, "submit_assignment_rest", fake_submit)

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            ok, msg = hw.submit_rest(file_path=str(pdf), dry_run=True)
        late = [x for x in w if "LATE" in str(x.message)]
        assert len(late) == 0

    def test_submit_rest_force_late_suppresses_warning(self, monkeypatch, tmp_path):
        """force_late=True suppresses the LATE warning."""
        import warnings
        hw = HomeworkItem(
            sub_id="x", title="HW1",
            course_id="1234", content_id="5678",
            deadline="2020-01-01T00:00:00+08:00",  # past
        )
        pdf = tmp_path / "x.pdf"
        pdf.write_bytes(b"%PDF-1.4\n")

        from sustech_survival.bb import submit as submit_rest_mod
        def fake_submit(*a, **kw): return True, "ok"
        monkeypatch.setattr(submit_rest_mod, "submit_assignment_rest", fake_submit)

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            ok, msg = hw.submit_rest(file_path=str(pdf), force_late=True)
        late = [x for x in w if "LATE" in str(x.message)]
        assert len(late) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
