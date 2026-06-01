# ─────────────────────────────────────────────────────────────────────────────
# programs.py — WS Student Exchange Program search & browse
#
# REST endpoints discovered (2026-06-01):
#   GET /Main/GetSmartLeftMenuTData.do               ← JSON menu tree
#   GET /StudentExchange_2247/GetShortProjectListForStudent.do   ← paginated list
#   GET /StudentExchange_2247/GetShortProjectListCountForStudent.do ← count
#   GET /StudentExchange_2247/ProjectDetail2247.do   ← HTML detail page
# ─────────────────────────────────────────────────────────────────────────────
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

import requests

from ..sso import WSAuth

# ── Base URL ────────────────────────────────────────────────────────────────────
WS_BASE = "https://ws.sustech.edu.cn"

# ── Auth singleton ─────────────────────────────────────────────────────────────
_AUTH: WSAuth | None = None


def _auth() -> WSAuth:
    global _AUTH
    if _AUTH is None:
        _AUTH = WSAuth()
    try:
        ok, _ = _AUTH.check()
    except Exception:
        ok = False
    if not ok:
        _AUTH.login()
    return _AUTH


def _session() -> requests.Session:
    return _auth().session


def _user_token() -> tuple[str, str]:
    """
    Extract userToken + ts from the WS menu API.
    Both are stable for the lifetime of the session.
    """
    s = _session()
    menu = json.loads(
        s.get(f"{WS_BASE}/Main/GetSmartLeftMenuTData.do", timeout=10).text
    )
    sample = menu[0]["FunctionList"][0]["Pages"][0]["PageUrl"]
    m = re.search(r"userToken=([A-F0-9]+)", sample)
    ts_m = re.search(r"ts=(\d+)", sample)
    return m.group(1), ts_m.group(1) if ts_m else "891"


# ── Helpers ─────────────────────────────────────────────────────────────────

_MS_DATE_RE = re.compile(r"\\/Date\((-?\d+)\)\\/")


def _parse_ms_date(raw: str) -> str | None:
    """Parse MS JSON date /Date(ms)/ to YYYY-MM-DD string."""
    m = _MS_DATE_RE.match(raw)
    if not m:
        return None
    ms = int(m.group(1))
    if ms < 0:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d")
    except (ValueError, OSError):
        return None


def _decode(s: str) -> str:
    """Decode numeric HTML entities like &#33258; → text. Does NOT decode &nbsp;."""
    return re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), s)


# ── Key fields kept in list response ───────────────────────────────────────────
_PROGRAM_LIST_FIELDS = {
    "ID", "Code", "Name", "NameEn", "YearCode",
    "ProjectType", "ProjectTypeText",
    "RegionCode", "RegionName",
    "ProjectSchoolName", "ProjectAgencyName", "ProjectMajor",
    "ApplyBeginDate", "ApplyEndDate",
    "ApplyBeginDateText", "ApplyEndDateText",
    "ApplyStartAndEndDateText",
    "ApplyRange", "ApplyRangeText",
    "ApplyCondition",
    "StudentExchangeProjectGradeID", "StudentExchangeProjectGradeIDText",
    "StudentExchangeProjectClassID", "StudentExchangeProjectClassIDText",
    "StudentExchangeProjectStudyTimeID", "StudentExchangeProjectStudyTimeIDText",
    "StudentExchangeProjectStatusID", "StudentExchangeProjectStatusIDText",
    "StudentExchangeOutCatagoryIDTexts",
    "IsValid", "IsValidText", "IsValidTextByEndDate",
    "IsAppliable",
    "IsContainCourse", "IsContainCourseText",
    "IsAllowedDelay", "IsAllowedFee", "IsAllowedXueFen",
    "IsHasCondition",
    "ApplyStudentCount", "LuQuStudentCount",
    "ReadCount",
    "Fee1", "Fee2", "Fee3", "Fee4", "FeeDescript",
    "ProjectDescription",
    "ContactAagenceName", "ContactorName",
    "ContactorTelphone", "ContactorEmail",
    "TokenKey", "ProjectImageUrl",
    "EnrollInfoList", "MajorInfoList", "ProjectTimeInfoList",
    "ProjectCourseDescription",
    "EnrollSchoolNameList", "EnrollRegionNameList",
}


# ── API: list programs ─────────────────────────────────────────────────────────

def list_programs(
    *,
    page: int = 1,
    page_size: int = 10,
    year_code: str | None = None,
    region_code: str | None = None,
    project_type: int | None = None,
    grade_id: int | None = None,
    keywords: str | None = None,
) -> dict[str, Any]:
    """
    Paginated program list with optional filters.

    Returns
        record_count, page, page_size, programs (list of cleaned dicts)
    """
    user_token, ts = _user_token()
    s = _session()

    params: dict[str, Any] = {
        "pageSize": page_size,
        "currentPageIndex": page,
        "ts": ts,
        "userToken": user_token,
    }
    if year_code:
        params["YearCode"] = year_code
    if region_code:
        params["RegionCode"] = region_code
    if project_type:
        params["ProjectType"] = project_type
    if keywords:
        params["KeyWords"] = keywords

    r = s.get(
        f"{WS_BASE}/StudentExchange_2247/GetShortProjectListForStudent.do",
        params=params,
        timeout=15,
    )
    raw = json.loads(r.text)

    programs = []
    for item in raw.get("DataList", []):
        p = {
            k: v
            for k, v in item.items()
            if k in _PROGRAM_LIST_FIELDS and v not in ("", None, [])
        }
        # Decode HTML entities in strings
        for k, v in list(p.items()):
            if isinstance(v, str):
                p[k] = _decode(v)
        # Parse MS date fields
        for dk in (
            "ApplyBeginDate", "ApplyEndDate",
            "ProjectBeginDate", "ProjectEndDate",
            "CreatedDate", "ModifiedDate",
        ):
            if dk in p and isinstance(p[dk], str) and p[dk].startswith("/Date"):
                p[dk] = _parse_ms_date(p[dk])
        # Normalise token field
        p["token"] = p.pop("TokenKey", "")
        programs.append(p)

    return {
        "record_count": raw.get("RecordCount", 0),
        "page": raw.get("CurrentPageIndex", page),
        "page_size": raw.get("PageSize", page_size),
        "programs": programs,
    }


def search_programs(query: str, page: int = 1, page_size: int = 10) -> dict[str, Any]:
    """Search programs by keyword."""
    return list_programs(keywords=query, page=page, page_size=page_size)


def get_count(
    year_code: str | None = None,
    region_code: str | None = None,
    project_type: int | None = None,
    keywords: str | None = None,
) -> int:
    """Return total count matching filters."""
    user_token, ts = _user_token()
    s = _session()
    params: dict[str, Any] = {"ts": ts, "userToken": user_token}
    if year_code:
        params["YearCode"] = year_code
    if region_code:
        params["RegionCode"] = region_code
    if project_type:
        params["ProjectType"] = project_type
    if keywords:
        params["KeyWords"] = keywords

    r = s.get(
        f"{WS_BASE}/StudentExchange_2247/GetShortProjectListCountForStudent.do",
        params=params,
        timeout=10,
    )
    try:
        data = json.loads(r.text)
        return int(data.get("RecordCount", 0))
    except (json.JSONDecodeError, ValueError):
        return 0


# ── API: program detail ───────────────────────────────────────────────────────

def get_program_detail(
    id: int | str,
    code: str | None = None,
    token: str | None = None,
) -> dict[str, Any] | None:
    """
    Fetch full detail for a program ID.

    Pass ``id`` (required). ``code`` and ``token`` are auto-resolved from
    the program list if omitted (costs one extra HTTP request).

    Returns
        {"sections": {section_name: {field: value}},
         "tables": [[[cell, ...], ...], ...],
         "token": str,
         "raw_length": int}
    or None on error.
    """
    # Resolve code+token via list lookup if not supplied
    if not code or not token:
        user_token, ts = _user_token()
        s = _session()
        list_url = f"{WS_BASE}/StudentExchange_2247/GetShortProjectListForStudent.do"
        found_code: str | None = None
        found_token: str | None = None
        for pg in range(1, 4):
            params = {
                "pageSize": 20,
                "currentPageIndex": pg,
                "ts": ts,
                "userToken": user_token,
            }
            raw = json.loads(s.get(list_url, params=params, timeout=10).text)
            for item in raw.get("DataList", []):
                if str(item["ID"]) == str(id):
                    found_code = item.get("Code")
                    found_token = item.get("TokenKey")
                    break
            if found_code or not raw.get("DataList"):
                break
        code = found_code or code
        token = found_token or token

    user_token, ts = _user_token()
    s = _session()
    params: dict[str, Any] = {"ID": id, "ts": ts, "userToken": user_token}
    if code:
        params["Code"] = code
    if token:
        params["token"] = token

    r = s.get(
        f"{WS_BASE}/StudentExchange_2247/ProjectDetail2247.do",
        params=params,
        timeout=10,
    )
    if r.status_code != 200 or len(r.text) < 500 or "非授权访问" in r.text:
        return None

    result = _parse_detail_html(r.text)
    result["token"] = token or ""
    return result


def _parse_detail_html(html: str) -> dict[str, Any]:
    """
    Parse ProjectDetail2247.do HTML response into structured sections.

    Layout pattern: each section has
        <h4 class="sub-title">Section Name</h4>
        <blockquote>
            <p class="p"><strong>Label：&nbsp;&nbsp;</strong>Value</p>
            <p class="p"><strong>Label：&nbsp;&nbsp;</strong></p>   ← value on next <p>
            <p class="p"><strong>Next Label：&nbsp;&nbsp;</strong>Value</p>
        </blockquote>
    """
    sections: dict[str, dict[str, str]] = {}

    blocks = re.split(
        r'<h4[^>]*class="sub-title"[^>]*>(.*?)</h4>\s*<blockquote',
        html, re.DOTALL
    )
    if len(blocks) > 1:
        it = iter(blocks[1:])
        for title_html, body_html in zip(it, it):
            section = re.sub(r"<[^>]+>", "", title_html).strip() or "基本信息"

            raw_pairs = re.findall(r'<p class="p">(.*?)</p>', body_html, re.DOTALL)
            pairs: dict[str, str] = {}
            pending_key: str | None = None

            for raw in raw_pairs:
                sm = re.search(r'<strong[^>]*>(.*?)</strong>', raw)
                if sm:
                    label = re.sub(r"<[^>]+>", "", sm.group(1)).strip()
                    label = re.sub(r"&[a-z]+;", "", label)  # strip &nbsp; etc.
                    label = _decode(label).rstrip("：").strip()
                    rest = sm.string[sm.end():]
                    rest_clean = re.sub(r"<[^>]+>", "", rest).strip()
                    rest_clean = re.sub(r"&[a-z]+;", "", rest_clean)
                    rest_clean = _decode(rest_clean)
                    if rest_clean:
                        pairs[label] = rest_clean
                    else:
                        pending_key = label
                elif pending_key:
                    val = re.sub(r"<[^>]+>", "", raw).strip()
                    val = re.sub(r"&[a-z]+;", "", val)
                    val = _decode(val)
                    if val:
                        pairs[pending_key] = val
                    pending_key = None

            if pairs:
                sections[section] = pairs

    # Extract tables (filter out laytpl template rows)
    tables_data: list[list[list[str]]] = []
    for tbl in re.findall(r'<table[^>]*>(.*?)</table>', html, re.DOTALL):
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', tbl, re.DOTALL)
        table_rows: list[list[str]] = []
        for row in rows:
            cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
            cells = [
                _decode(re.sub(r"<[^>]+>", "", c).strip())
                for c in cells
            ]
            # Drop laytpl template artefacts
            cells = [c for c in cells if c and not c.startswith("{{")]
            if cells:
                table_rows.append(cells)
        if table_rows:
            tables_data.append(table_rows)

    return {"sections": sections, "tables": tables_data, "raw_length": len(html)}
