"""
tis grades — Fetch and display TIS grades with GPA.

Uses headless CAS login + JSON API. Reference: lethal233/sustech-tis-converter.
"""

import sys
from pathlib import Path as _Path

_SKILL_ROOT = _Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_SKILL_ROOT / "src"))

__all__ = ["run"]


def _login():
    from sustech_survival.tis.login import cas_login
    creds_file = _SKILL_ROOT / "credentials.txt"
    with open(creds_file) as f:
        username, password = f.read().strip().split(":", 1)
    return cas_login(username, password, "https://tis.sustech.edu.cn/cas")


def _get_grades(cookies: dict, semester: str = None):
    """
    Fetch grades from TIS grade API.
    Returns list of grade dicts.
    """
    import requests

    h = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/json",
        "Cookie": f"route={cookies['route']}; JSESSIONID={cookies['JSESSIONID']}"
    }

    r = requests.post(
        "https://tis.sustech.edu.cn/cjgl/grcjcx/grcjcx",
        json={"xn": None, "xq": None, "kcmc": None, "cxbj": "-1", "pylx": "1", "current": 1, "pageSize": 500},
        headers=h, timeout=15
    )
    if r.status_code != 200:
        raise RuntimeError(f"TIS grade API returned {r.status_code}: {r.text[:200]}")

    data = r.json()
    courses = data.get("content", {}).get("list", [])

    if semester:
        courses = [c for c in courses if semester in c.get("xnxqmc", "")]

    return courses


# ── GPA helpers ────────────────────────────────────────────────────────────────

_GPA_MAP = {
    "A+": 4.0, "A": 4.0, "A-": 3.7,
    "B+": 3.3, "B": 3.0, "B-": 2.7,
    "C+": 2.3, "C": 2.0, "C-": 1.7,
    "D": 1.0, "D-": 0.7,
    "F": 0.0,
}

_NUMERIC_GPA = {
    "95": 4.0, "90": 4.0, "85": 3.7, "80": 3.3, "77": 3.0, "73": 2.7,
    "70": 2.3, "67": 2.0, "63": 1.7, "60": 1.0,
}


def _calc_gpa(courses, credit_key="xf", grade_key="xscj"):
    """Calculate GPA from TIS grade records."""
    total_pts = 0.0
    total_creds = 0.0
    for c in courses:
        grade = str(c.get(grade_key, "")).strip()
        try:
            cred = float(c.get(credit_key, 0))
        except (TypeError, ValueError):
            continue
        if cred <= 0:
            continue

        gpa = _GPA_MAP.get(grade)
        if gpa is None:
            # Try numeric score
            score_str = str(c.get("zzcj", "")).strip()
            try:
                score = float(score_str)
                gpa = _NUMERIC_GPA.get(str(int(score)), None)
            except (ValueError, TypeError):
                gpa = None

        if gpa is not None:
            total_pts += gpa * cred
            total_creds += cred

    if total_creds == 0:
        return 0.0, 0.0
    return round(total_pts / total_creds, 3), total_creds


def _format_grade_row(c):
    """Format a single grade row for display."""
    name = c.get("kcmc", "")
    name_en = c.get("kcmc_en", "")
    code = c.get("kcdm", "")
    semester = c.get("xnxqmc", "")
    grade = str(c.get("xscj", "")).strip()
    score = str(c.get("zzcj", "")).strip()
    credit = c.get("xf", 0)
    nature = c.get("kcxz", "")
    dept = c.get("yxmc", "")

    label = name if name else name_en
    if not label:
        label = code or "未知课程"

    return {
        "课程": label,
        "学期": semester,
        "学分": credit,
        "等级": grade,
        "分数": score,
        "性质": nature,
    }


def run(semester: str = None, export: str = None):
    """
    Display TIS grades.

    Args:
        semester: Filter by semester, e.g. '2025秋季' or '2025-2026-1' (default: all).
        export: If 'csv', export to ~/.openclaw/workspace/sustech/grades.csv
    """
    print("🔑 CAS login...")
    cookies = _login()
    if not cookies:
        print("❌ TIS login failed")
        sys.exit(1)

    print("📊 Fetching grades...")
    courses = _get_grades(cookies, semester)

    if not courses:
        print("❌ No grades found")
        sys.exit(1)

    # Group by semester
    by_semester = {}
    for c in courses:
        sem = c.get("xnxqmc", "未知学期")
        by_semester.setdefault(sem, []).append(c)

    # Overall GPA
    gpa, total_creds = _calc_gpa(courses)
    print(f"\n📈 共 {len(courses)} 门课程 | 总学分 {total_creds:.0f} |  GPA: {gpa:.3f}\n")

    for sem, sem_courses in sorted(by_semester.items()):
        sem_gpa, sem_creds = _calc_gpa(sem_courses)
        print(f"  {'─' * 50}")
        print(f"  {sem}  ({len(sem_courses)} 门课, {sem_creds:.0f} 学分, GPA {sem_gpa:.3f})")
        for c in sem_courses:
            row = _format_grade_row(c)
            grade_disp = f"{row['等级']:>4}" if row['等级'] else "  N/A"
            score_disp = f"({row['分数']})" if row['分数'] else ""
            print(f"    {grade_disp} {row['课程'][:35]:<36} {row['学分']}学分")
        print()

    if export == "csv":
        import csv
        out = _SKILL_ROOT.parent.parent / "workspace" / "sustech" / "grades.csv"
        out.parent.mkdir(parents=True, exist_ok=True)
        fields = ["课程", "学期", "学分", "等级", "分数", "性质"]
        with open(out, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for c in courses:
                w.writerow(_format_grade_row(c))
        print(f"📄 已导出至 {out}")
