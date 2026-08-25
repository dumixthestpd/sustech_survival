"""See docs/grades.md."""

from pathlib import Path as _Path

SKILL_ROOT = _Path(__file__).resolve().parent.parent.parent.parent

__all__ = ["run"]

from sustech_survival.exceptions import NetworkError, SessionExpired
from sustech_survival.sso import TISAuth


def make_session():
    """Build a requests.Session with valid TIS cookies via SSO auth layer."""
    auth = TISAuth(skill_dir=str(SKILL_ROOT))
    ok, msg = auth.check()
    if not ok:
        ok = auth.refresh()
    if not ok:
        raise SessionExpired(f"TIS auth failed: {msg}")
    return auth.session


def get_grades(session, semester: str = None):
    """
    Fetch grades from TIS grade API.
    Returns list of grade dicts.
    """
    r = session.post(
        "https://tis.sustech.edu.cn/cjgl/grcjcx/grcjcx",
        json={"xn": None, "xq": None, "kcmc": None, "cxbj": "-1", "pylx": "1", "current": 1, "pageSize": 500},
        headers={
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/json",
        },
        timeout=15,
    )
    if r.status_code == 401:
        raise SessionExpired("TIS session expired. Re-authenticate.")
    if r.status_code != 200:
        raise NetworkError(f"TIS grade API returned {r.status_code}: {r.text[:200]}")

    data = r.json()
    courses = data.get("content", {}).get("list", [])

    if semester:
        courses = [c for c in courses if semester in c.get("xnxqmc", "")]

    return courses


# -- GPA helpers ----------------------------------------------------------------

# SUSTech official 4.0 GPA conversion table (本科)
# Source: https://sustech.online/study/ → GPA换算表（本科）
_GPA_MAP = {
    "A+": 4.00, "A": 3.94, "A-": 3.85,
    "B+": 3.73, "B": 3.55, "B-": 3.32,
    "C+": 3.09, "C": 2.78, "C-": 2.42,
    "D+": 2.08, "D": 1.63, "D-": 1.15,
    "F": 0.00,
}

# Standard Chinese university 4.0 scale (百分制 → GPA点)
_NUMERIC_GPA = {
    "100": 4.0, "99": 4.0, "98": 4.0, "97": 4.0, "96": 4.0,
    "95": 4.0, "94": 4.0, "93": 4.0, "92": 4.0, "91": 4.0, "90": 4.0,
    "89": 3.7, "88": 3.7, "87": 3.7, "86": 3.7, "85": 3.7,
    "84": 3.3, "83": 3.3, "82": 3.3, "81": 3.3, "80": 3.3,
    "79": 3.0, "78": 3.0, "77": 3.0,
    "76": 2.7, "75": 2.7, "74": 2.7, "73": 2.7,
    "72": 2.3, "71": 2.3, "70": 2.3,
    "69": 2.0, "68": 2.0, "67": 2.0,
    "66": 1.7, "65": 1.7, "64": 1.7, "63": 1.7,
    "62": 1.0, "61": 1.0, "60": 1.0,
}


def calc_gpa(courses, credit_key="xf", grade_key="xscj"):
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


def format_grade_row(c):
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
    """See docs/grades.md."""
    print("🔑 CAS login...")
    try:
        session = makesession()
    except SessionExpired as e:
        print(f"❌ {e}")
        raise

    print("📊 Fetching grades...")
    try:
        courses = get_grades(session, semester)
    except (SessionExpired, NetworkError) as e:
        print(f"❌ {e}")
        raise

    if not courses:
        print("❌ No grades found")
        raise SessionExpired("No grades returned — semester may not be published yet")

    # Group by semester
    by_semester = {}
    for c in courses:
        sem = c.get("xnxqmc", "未知学期")
        by_semester.setdefault(sem, []).append(c)

    # Overall GPA
    gpa, total_creds = calc_gpa(courses)
    print(f"\n📈 共 {len(courses)} 门课程 | 总学分 {total_creds:.0f} |  GPA: {gpa:.3f}\n")

    for sem, sem_courses in sorted(by_semester.items()):
        sem_gpa, sem_creds = calc_gpa(sem_courses)
        print(f"  {'-' * 50}")
        print(f"  {sem}  ({len(sem_courses)} 门课, {sem_creds:.0f} 学分, GPA {sem_gpa:.3f})")
        for c in sem_courses:
            row = format_grade_row(c)
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
                w.writerow(format_grade_row(c))
        print(f"📄 已导出至 {out}")