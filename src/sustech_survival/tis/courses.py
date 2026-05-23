"""See docs/courses.md."""

import sys
from pathlib import Path as _Path

_SKILL_ROOT = _Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_SKILL_ROOT / "src"))

__all__ = ["run"]


def _make_session():
    """Build a requests.Session with valid TIS cookies via SSO auth layer."""
    import requests
    from sustech_survival.sso import TISAuth

    auth = TISAuth(skill_dir=str(_SKILL_ROOT))
    ok, msg = auth.check()
    if not ok:
        # Try refresh (reads credentials, re-runs CAS ticket exchange)
        ok = auth.refresh()
    if not ok:
        return None

    raw = auth.load()
    sess = requests.Session()
    sess.headers["User-Agent"] = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    for k, v in raw.items():
        sess.cookies.set(k, v, domain="tis.sustech.edu.cn")
    return sess


def _get_grades(session, semester: str = None):
    """Fetch grades from TIS grade API."""
    r = session.post(
        "https://tis.sustech.edu.cn/cjgl/grcjcx/grcjcx",
        json={"xn": None, "xq": None, "kcmc": None, "cxbj": "-1", "pylx": "1", "current": 1, "pageSize": 500},
        headers={
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/json",
        },
        timeout=15,
    )
    if r.status_code != 200:
        raise RuntimeError(f"TIS returned {r.status_code}: {r.text[:200]}")
    courses = r.json().get("content", {}).get("list", [])
    if semester:
        courses = [c for c in courses if semester in c.get("xnxqmc", "")]
    return courses


def run(semester: str = None, format: str = "table"):
    """See docs/courses.md."""
    print("🔑 CAS login...")
    session = _make_session()
    if not session:
        print("❌ TIS login failed")
        sys.exit(1)

    print("📚 Fetching courses...")
    courses = _get_grades(session, semester)

    if not courses:
        print("❌ No courses found")
        sys.exit(1)

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
        print(f"\n{'─' * 55}")
        print(f"  {sem}  ({len(sem_courses)} 门课, {total_credits:.0f} 学分)")
        print(f"  {'─' * 55}")
        for c in sem_courses:
            code = c.get("kcdm", "")
            name = c.get("kcmc", "") or c.get("kcmc_en", "")
            credit = c.get("xf", 0)
            teacher = c.get("dgjsmc", "") or ""
            display = f"{code} {name}" if code else name
            print(f"    {display[:45]:<46} {credit:.1f}学分")
            if teacher:
                print(f"      👤 {teacher}")
