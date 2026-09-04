"""See docs/courses.md."""

import re
from pathlib import Path as _Path

SKILL_ROOT = _Path(__file__).resolve().parent.parent.parent.parent

__all__ = ["run", "get_current_courses"]

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


def get_courses(session, semester: str = None):
    """Fetch courses from TIS grade API (same endpoint as grades)."""
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
        raise NetworkError(f"TIS returned {r.status_code}: {r.text[:200]}")
    courses = r.json().get("content", {}).get("list", [])
    if semester:
        courses = [c for c in courses if semester in c.get("xnxqmc", "")]
    return courses


def run(semester: str = None, format: str = "table"):
    """See docs/courses.md."""
    print("🔑 CAS login...")
    try:
        session = makesession()
    except SessionExpired as e:
        print(f"❌ {e}")
        raise

    print("📚 Fetching courses...")
    try:
        courses = get_courses(session, semester)
    except (SessionExpired, NetworkError) as e:
        print(f"❌ {e}")
        raise

    if not courses:
        print("❌ No courses found")
        raise SessionExpired("No courses returned — semester may not be published yet")

    # Group by semester
    by_sem = {}
    for c in courses:
        sem = c.get("xnxqmc", "未知")
        by_sem.setdefault(sem, []).append(c)

    if format == "csv":
        import csv

        out = _SKILL_ROOT.parent.parent / "workspace" / "sustech" / "courses_tis.csv"
        out.parent.mkdir(parents=True, exist_ok=True)
        fields = ["课程代码", "课程名称", "学期", "学分", "课程性质", "院系"]
        with open(out, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for c in courses:
                w.writerow({
                    "课程代码": c.get("kcdm", ""),
                    "课程名称": c.get("kcmc", "") or c.get("kcmc_en", ""),
                    "学期": c.get("xnxqmc", ""),
                    "学分": c.get("xf", ""),
                    "课程性质": c.get("kcxz", ""),
                    "院系": c.get("yxmc", ""),
                })
        print(f"📄 已导出至 {out}")
        return

    # Default: human-readable table
    for sem, sem_courses in sorted(by_sem.items()):
        total_credits = sum(c.get("xf", 0) for c in sem_courses)
        print(f"\n{'-' * 55}")
        print(f"  {sem}  ({len(sem_courses)} 门课, {total_credits:.0f} 学分)")
        print(f"  {'-' * 55}")
        for c in sem_courses:
            code = c.get("kcdm", "")
            name = c.get("kcmc", "") or c.get("kcmc_en", "")
            credit = c.get("xf", 0)
            teacher = c.get("dgjsmc", "") or ""
            display = f"{code} {name}" if code else name
            print(f"    {display[:45]:<46} {credit:.1f}学分")
            if teacher:
                print(f"      👤 {teacher}")


def get_current_courses():
    """Return the current (in-progress) semester's enrolled courses.

    The grade API that ``get_courses()`` reads only returns semesters that
    already have posted grades — a just-started term (e.g. Fall 2026 in its
    first weeks) has none, so ``get_courses()`` shows nothing for it. The live
    term's courses come from the personal timetable (xszykb) instead.

    Returns a list of dicts shaped like ``get_courses()`` rows ({kcdm, kcmc,
    xnxqmc, xf, dgjsmc}); ``xf`` (credits) is not provided by the timetable
    source and is left 0 (the CLI renders it conditionally). Rows are
    de-duplicated by course name, so a lecture and its experiment keep their
    separate rows while multiple meetings of one course collapse to one.
    """
    from sustech_survival.tis import schedule as _sched
    try:
        sem = _sched.current_semester()
        rows = _sched.semester_schedule()
    except SessionExpired:
        raise
    except RuntimeError as e:
        raise SessionExpired(f"TIS schedule auth failed: {e}") from e
    except Exception as e:
        # Flaky off-campus / proxy connections surface here as raw requests
        # exceptions from the schedule helpers; fold them into NetworkError so
        # the CLI can print a clean message instead of a traceback.
        raise NetworkError(f"TIS schedule query failed: {e}") from e

    term_label = sem.get("XNXQ") or ""
    seen = set()
    out = []
    for r in rows:
        name = (r.get("KCWZSM") or "").strip()
        if not name:
            name = (r.get("SKSJ") or "").split("\n")[0].strip()
        if not name or name in seen:
            continue
        seen.add(name)
        # Course code is embedded in the 教学班 id, e.g. 2026-2027-1-CS323-001.
        code = ""
        m = re.match(r"^\d{4}-\d{4}-\d-(.+?)-\d+$", r.get("RWH") or "")
        if m:
            code = m.group(1)
        lines = (r.get("SKSJ") or "").split("\n")
        teacher = re.sub(r"[\[\]]", "", lines[1]).strip() if len(lines) > 1 else ""
        out.append({
            "kcdm": code,
            "kcmc": name,
            "xnxqmc": term_label,
            "xf": 0,
            "dgjsmc": teacher,
        })
    return out