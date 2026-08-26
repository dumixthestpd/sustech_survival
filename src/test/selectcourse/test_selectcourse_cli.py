"""Offline regression tests for the unified course-selection CLI."""
from __future__ import annotations

from click.testing import CliRunner

import sustech_survival.selectcourse as selectcourse_pkg
from sustech_survival.cli.main import selectcourse_cmd


class _FakeSelectCourseClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def list_courses(self, **kwargs):
        return []

    def my_courses(self):
        return [{"name": "Regression Test Course"}]


def test_selectcourse_list_imports_sibling_client(monkeypatch):
    monkeypatch.setattr(
        selectcourse_pkg, "SelectCourseClient", _FakeSelectCourseClient
    )

    result = CliRunner().invoke(selectcourse_cmd, ["list", "--json"])

    assert result.exit_code == 0, result.output
    assert result.output.strip() == "[]"


def test_selectcourse_enrolled_imports_sibling_client(monkeypatch):
    monkeypatch.setattr(
        selectcourse_pkg, "SelectCourseClient", _FakeSelectCourseClient
    )

    result = CliRunner().invoke(selectcourse_cmd, ["enrolled", "--json"])

    assert result.exit_code == 0, result.output
    assert "Regression Test Course" in result.output
