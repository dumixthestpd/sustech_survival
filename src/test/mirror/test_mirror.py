"""Offline tests for the mirror module's pure-Python helpers.

Skips the live HTTP path (which is exercised in dev — these tests
just guard the no-network surface: URL building, code normalization,
PDF extraction with a real local file, dept listing parsing, error
classes).
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest


# -- URL + normalization ------------------------------------------------------


def test_syllabus_url_uppercases_code():
    from sustech_survival.mirror.syllabus import syllabus_url
    assert syllabus_url("cle022") == "https://mirrors.sustech.edu.cn/courses/syllabus/CLE022.pdf"
    assert syllabus_url("  mse202  ") == "https://mirrors.sustech.edu.cn/courses/syllabus/MSE202.pdf"
    assert syllabus_url("CH103") == "https://mirrors.sustech.edu.cn/courses/syllabus/CH103.pdf"


def test_syllabus_html_url():
    from sustech_survival.mirror.syllabus import syllabus_html_url
    assert syllabus_html_url("MSE202") == (
        "https://mirrors.sustech.edu.cn/courses/syllabus/html/MSE202.html"
    )


def test_mirror_base_constant():
    from sustech_survival.mirror.syllabus import MIRROR_BASE
    assert MIRROR_BASE == "https://mirrors.sustech.edu.cn"


# -- PDF extraction (uses a real PDF if one is on disk) ----------------------


def _local_pdf() -> Path | None:
    p = Path.home() / ".sustech_survival" / "downloads" / "syllabus" / "CLE022.pdf"
    return p if p.exists() else None


def test_extract_text_returns_nonempty_for_real_pdf():
    pdf = _local_pdf()
    if pdf is None:
        pytest.skip("CLE022.pdf not in ~/.sustech_survival/downloads/syllabus/")
    from sustech_survival.mirror.syllabus import extract_text
    text = extract_text(pdf.read_bytes())
    # Real syllabus PDFs from mirrors.sustech.edu.cn should mention the
    # course code and "COURSE SPECIFICATION" marker. If this fails on a
    # new file format, the regex below is the thing to update.
    assert "CLE022" in text
    assert "COURSE SPECIFICATION" in text or "课程详述" in text


def test_extract_text_on_empty_bytes_raises_friendly():
    from sustech_survival.mirror.syllabus import extract_text, SyllabusFetchError
    with pytest.raises(SyllabusFetchError):
        extract_text(b"")


# -- Error classes -----------------------------------------------------------


def test_syllabus_error_inheritance():
    from sustech_survival.mirror.syllabus import (
        SyllabusError,
        SyllabusNotFound,
        SyllabusFetchError,
    )
    assert issubclass(SyllabusNotFound, SyllabusError)
    assert issubclass(SyllabusFetchError, SyllabusError)
    with pytest.raises(SyllabusError):
        raise SyllabusNotFound("test")
    with pytest.raises(SyllabusError):
        raise SyllabusFetchError("test")


# -- HTML directory parsing -------------------------------------------------


def test_parse_directory_hrefs_decodes_unicode():
    from sustech_survival.mirror.syllabus import _parse_directory_hrefs
    html = """
    <a href="../">Parent directory/</a>
    <a href="%E6%9D%90%E6%96%99%E7%A7%91%E5%AD%A6%E4%B8%8E%E5%B7%A5%E7%A8%8B%E7%B3%BB/">材料系/</a>
    <a href="MSE202.pdf">MSE202.pdf</a>
    <a href="?C=N&O=A">sort</a>
    """
    out = _parse_directory_hrefs(html, base="/x/", only_dirs=True)
    assert out == ["材料科学与工程系"]


def test_parse_directory_hrefs_files_when_not_only_dirs():
    from sustech_survival.mirror.syllabus import _parse_directory_hrefs
    html = '<a href="MSE202.pdf">MSE202.pdf</a>'
    out = _parse_directory_hrefs(html, base="/x/", only_dirs=False)
    assert "MSE202.pdf" in out


# -- TIS fallback: TIS rows → unified dict shape ----------------------------


def _row(**kw):
    """Build a fake TIS grade row with sensible defaults."""
    base = {
        "kcdm": "MSE202", "kcmc": "物理化学", "kcmc_en": "Physical Chemistry",
        "yxmc": "材料系", "yxmc_en": "MSE",
        "kcxz": "必修", "kcxzen": "Required",
        "kclb": "专业基础课", "kclben": "MR",
        "khfs": "考试", "khfs_en": "examination",
        "xf": 3, "zzcj": "74", "pm": "40", "zrs": "62",
        "xnxqmc": "2026春季", "xnxq": "2025-20262",
    }
    base.update(kw)
    return base


def test_from_grade_row_unified_shape():
    from sustech_survival.mirror.tis_fallback import _from_grade_row
    d = _from_grade_row(_row(), source="tis_grades")
    assert d["code"] == "MSE202"
    assert d["name"] == "物理化学"
    assert d["name_en"] == "Physical Chemistry"
    assert d["department"] == "材料系"
    assert d["credits"] == 3
    assert d["score"] == "74"
    assert d["rank"] == "40"
    assert d["class_size"] == "62"
    assert d["semester"] == "2026春季"
    assert d["source"] == "tis_grades"
    # raw row is preserved for callers that want everything
    assert d["raw"]["kcdm"] == "MSE202"


def test_from_grade_row_empty_score():
    from sustech_survival.mirror.tis_fallback import _from_grade_row
    d = _from_grade_row(_row(zzcj="", pm="", zrs=""), source="tis_grades")
    assert d["score"] == ""
    assert d["rank"] == ""
    assert d["class_size"] == ""


def test_from_catalog_row_unified_shape():
    from sustech_survival.mirror.tis_fallback import _from_catalog_row
    fake = MagicMock()
    fake.code = "BIO103"
    fake.name = "生物学原理"
    fake.credits = 3.0
    fake.teachers = ["教师A", "教师B"]
    d = _from_catalog_row(fake, source="tis_catalog")
    assert d["code"] == "BIO103"
    assert d["name"] == "生物学原理"
    assert d["credits"] == 3.0
    assert d["score"] == ""  # catalog doesn't carry scores
    assert d["source"] == "tis_catalog"


def test_fetch_course_text_renders_human_readable(monkeypatch):
    from sustech_survival.mirror.tis_fallback import _from_grade_row
    from sustech_survival.mirror.tis_fallback import fetch_course_text
    # fetch_course_text only knows about its return value, so call the
    # inner helper directly and pipe through the same formatter.
    from sustech_survival.mirror import tis_fallback as t
    # Reach into the private formatter via the public path: round-trip.
    # NOTE: monkeypatch handles teardown so this doesn't leak into other
    # tests (earlier revision used bare `t.fetch_course_json = ...` and
    # leaked).
    monkeypatch.setattr(t, "fetch_course_json",
                        MagicMock(return_value=_from_grade_row(_row(), source="tis_grades")))
    out = fetch_course_text("MSE202")
    assert "MSE202" in out
    assert "物理化学" in out
    assert "材料系" in out
    assert "Credits: 3" in out
    assert "Score: 74" in out
    assert "Source: tis_grades" in out


# -- fetch_course_json end-to-end (mocked) ----------------------------------


def test_fetch_course_json_returns_none_for_empty_code():
    from sustech_survival.mirror.tis_fallback import fetch_course_json
    assert fetch_course_json("") is None
    result = fetch_course_json(None)  # type: ignore[arg-type]
    assert result is None


def test_fetch_course_json_prefers_grades_over_catalog(monkeypatch):
    """When the user has taken the course, grades data wins over catalog."""
    from sustech_survival.mirror import tis_fallback as t

    fake_auth = MagicMock()
    fake_auth.ensure.return_value = (True, "stub")
    fake_get_courses = MagicMock(return_value=[
        _row(kcdm="MSE202"),
        _row(kcdm="BIO103", kcmc="生命科学概论"),
    ])

    # Patch the SOURCES the function imports, by name (the function does
    # `from sustech_survival.sso import TISAuth` and
    # `from sustech_survival.tis.courses import get_courses` inside).
    monkeypatch.setattr("sustech_survival.sso.TISAuth", lambda: fake_auth)
    monkeypatch.setattr("sustech_survival.tis.courses.get_courses", fake_get_courses)

    out = t.fetch_course_json("MSE202")
    assert out is not None
    assert out["source"] == "tis_grades"
    assert out["code"] == "MSE202"


def test_fetch_course_json_case_insensitive(monkeypatch):
    from sustech_survival.mirror import tis_fallback as t
    fake_auth = MagicMock(ensure=MagicMock(return_value=(True, "x")))
    monkeypatch.setattr("sustech_survival.sso.TISAuth", lambda: fake_auth)
    monkeypatch.setattr("sustech_survival.tis.courses.get_courses",
                        lambda s: [_row(kcdm="MSE202")])
    out = t.fetch_course_json("mse202")
    assert out is not None
    assert out["code"] == "MSE202"
    out2 = t.fetch_course_json("  MSE202  ")
    assert out2 is not None
    assert out2["code"] == "MSE202"


def test_fetch_course_json_returns_none_when_no_data(monkeypatch):
    """When TISAuth fails AND catalog returns nothing, return None."""
    from sustech_survival.mirror import tis_fallback as t
    fake_auth = MagicMock(ensure=MagicMock(return_value=(False, "no auth")))
    monkeypatch.setattr("sustech_survival.sso.TISAuth", lambda: fake_auth)
    assert t.fetch_course_json("DOESNOTEXIST") is None


# -- program (本科人才培养方案): the 404 regression ---------------------------
#
# 2019–2024 are *directories* of per-major PDFs on the mirror, only 2025级 is a
# single whole-school PDF, and the mirror 404s a raw UTF-8 path. The old code
# guessed `<year>本科人才培养方案.pdf` offline, so every directory year printed
# and downloaded a URL that answered 404. These tests pin the resolved behavior.


def _mirror_cli():
    from sustech_survival.mirror import cli as m
    return m


def test_program_urls_are_percent_encoded():
    m = _mirror_cli()
    pdf_url, dir_url = m._program_urls("2024级")
    assert pdf_url.startswith("https://mirrors.sustech.edu.cn/courses/%E6%9C%AC%E7%A7%91")
    assert pdf_url.endswith(".pdf") and dir_url.endswith("/")
    assert "%E7%BA%A7" in pdf_url          # 级 encoded — the raw byte path 404s
    assert "级" not in pdf_url


def test_program_kind_tries_the_pdf_then_the_directory(monkeypatch):
    m = _mirror_cli()
    pdf_url, dir_url = m._program_urls("2024级")
    monkeypatch.setattr(m, "_probe_code", lambda url: 200 if url == pdf_url else 404)
    assert m._program_kind("2024级") == ("file", pdf_url)
    monkeypatch.setattr(m, "_probe_code", lambda url: 200 if url == dir_url else 404)
    assert m._program_kind("2024级") == ("dir", dir_url)
    monkeypatch.setattr(m, "_probe_code", lambda url: 404)
    assert m._program_kind("2024级") == ("missing", "")


def test_pdf_rows_skips_directories_and_non_pdf():
    m = _mirror_cli()
    rows = [("a.pdf", "a.pdf", False), ("sub/", "sub/", True), ("notes.txt", "notes.txt", False)]
    assert m._pdf_rows(rows) == [("a.pdf", "a.pdf")]


def test_program_url_prints_the_directory_url(monkeypatch):
    from click.testing import CliRunner
    m = _mirror_cli()
    _pdf, dir_url = m._program_urls("2024级")
    monkeypatch.setattr(m, "_probe_code", lambda url: 200 if url == dir_url else 404)
    res = CliRunner().invoke(m.mirror_cmd, ["program", "url", "2024级"])
    assert res.exit_code == 0, res.output
    assert res.output.strip() == dir_url


def test_program_url_fails_loudly_for_an_unknown_year(monkeypatch):
    from click.testing import CliRunner
    m = _mirror_cli()
    monkeypatch.setattr(m, "_probe_code", lambda url: 404)
    res = CliRunner().invoke(m.mirror_cmd, ["program", "url", "1999级"])
    assert res.exit_code == 1
    assert "no training plan" in res.output


def test_program_list_prints_name_and_encoded_url(monkeypatch):
    from click.testing import CliRunner
    m = _mirror_cli()
    _pdf, dir_url = m._program_urls("2024级")
    monkeypatch.setattr(m, "_program_kind", lambda year: ("dir", dir_url))
    monkeypatch.setattr(m, "_autoindex_rows", lambda url: [
        ("00-2024级通识培养方案.pdf",
         "00-2024%E7%BA%A7%E9%80%9A%E8%AF%86%E5%9F%B9%E5%85%BB%E6%96%B9%E6%A1%88.pdf", False),
        ("subdir/", "subdir/", True),
    ])
    res = CliRunner().invoke(m.mirror_cmd, ["program", "list", "2024级"])
    assert res.exit_code == 0, res.output
    lines = [ln for ln in res.output.strip().splitlines() if ln.strip()]
    assert len(lines) == 1, res.output
    name, _, url = lines[0].partition("\t")
    assert name == "00-2024级通识培养方案.pdf"
    assert url.startswith(dir_url) and url.endswith(".pdf")


def test_program_list_of_a_file_year_prints_that_one_pdf(monkeypatch):
    from click.testing import CliRunner
    m = _mirror_cli()
    pdf_url, _dir = m._program_urls("2025级")
    monkeypatch.setattr(m, "_program_kind", lambda year: ("file", pdf_url))
    res = CliRunner().invoke(m.mirror_cmd, ["program", "list", "2025级"])
    assert res.exit_code == 0, res.output
    assert res.output.strip() == f"2025级本科人才培养方案.pdf\t{pdf_url}"


def test_program_get_bare_on_a_directory_year_takes_the_00_compendium(monkeypatch, tmp_path):
    """Both lanes agree: a bare `get <dir year>` fetches the 00-通识 compendium."""
    from click.testing import CliRunner
    m = _mirror_cli()
    _pdf, dir_url = m._program_urls("2024级")
    monkeypatch.setattr(m, "_program_kind", lambda year: ("dir", dir_url))
    monkeypatch.setattr(m, "_autoindex_rows", lambda url: [
        ("00-2024级通识培养方案.pdf", "00-x.pdf", False),
        ("01-2024级金数.pdf", "01-y.pdf", False),
    ])
    seen = []
    monkeypatch.setattr(m, "_download",
                        lambda url, target, overwrite: seen.append((url, str(target))) or True)
    res = CliRunner().invoke(m.mirror_cmd, ["program", "get", "2024级", "-o", str(tmp_path)])
    assert res.exit_code == 0, res.output
    assert len(seen) == 1, seen
    assert seen[0][0] == f"{dir_url}00-x.pdf"
    assert "--all" in res.output and "--index" in res.output


def test_program_get_index_downloads_only_that_pdf(monkeypatch, tmp_path):
    from click.testing import CliRunner
    m = _mirror_cli()
    _pdf, dir_url = m._program_urls("2024级")
    monkeypatch.setattr(m, "_program_kind", lambda year: ("dir", dir_url))
    monkeypatch.setattr(m, "_autoindex_rows", lambda url: [
        ("00-通识.pdf", "00-x.pdf", False),
        ("01-金数.pdf", "01-y.pdf", False),
    ])
    seen = []
    monkeypatch.setattr(m, "_download",
                        lambda url, target, overwrite: seen.append((url, str(target))) or True)
    res = CliRunner().invoke(
        m.mirror_cmd, ["program", "get", "2024级", "--index", "01", "-o", str(tmp_path)])
    assert res.exit_code == 0, res.output
    assert len(seen) == 1, seen
    url, target = seen[0]
    assert url == f"{dir_url}01-y.pdf"
    assert target.replace("\\", "/").endswith("2024级本科人才培养方案/01-金数.pdf")


def test_program_get_file_year_downloads_the_pdf(monkeypatch, tmp_path):
    from click.testing import CliRunner
    m = _mirror_cli()
    pdf_url, _dir = m._program_urls("2025级")
    monkeypatch.setattr(m, "_program_kind", lambda year: ("file", pdf_url))
    seen = []
    monkeypatch.setattr(m, "_download",
                        lambda url, target, overwrite: seen.append((url, str(target))) or True)
    res = CliRunner().invoke(m.mirror_cmd, ["program", "get", "2025级", "-o", str(tmp_path)])
    assert res.exit_code == 0, res.output
    assert seen and seen[0][0] == pdf_url
    assert seen[0][1].replace("\\", "/").endswith("2025级本科人才培养方案.pdf")
