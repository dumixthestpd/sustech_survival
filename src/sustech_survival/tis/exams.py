"""TIS Exam Schedule — Spring 2026 final exams."""

from pathlib import Path as _Path

_SKILL_ROOT = _Path(__file__).resolve().parent.parent.parent.parent

__all__ = ["run"]

from sustech_survival.exceptions import NetworkError
from sustech_survival.sso import TISAuth

_ta = None  # TISAuth singleton (in-memory session, auto-refresh on expiry)


def _auth():
    """Return valid cookies from TISAuth, or raise RuntimeError."""
    global _ta
    if _ta is None:
        _ta = TISAuth(skill_dir=str(_SKILL_ROOT))
    ok, reason = _ta.ensure()
    if not ok:
        raise RuntimeError(f"TIS auth failed: {reason}")
    return _ta.cookies


def _fetch_exams(cookies: dict):
    """Fetch exam schedule from TIS student exam endpoint."""
    import requests

    h = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/json",
        "Cookie": f"route={cookies['route']}; JSESSIONID={cookies['JSESSIONID']}"
    }
    try:
        r = requests.post(
            "https://tis.sustech.edu.cn/component/queryKsxxByXs",
            json={}, headers=h, timeout=15
        )
    except requests.RequestException as e:
        raise NetworkError(f"TIS exam endpoint unreachable: {e}")
    if r.status_code == 401:
        raise InvalidCredentials("TIS session rejected — re-run bb.py login")
    if r.status_code != 200:
        raise NetworkError(f"TIS exam API returned {r.status_code}")
    return r.json()  # returns a plain list (not wrapped in content/)


# Period -> time mapping (SUSTech standard)
_PERIOD_TIMES = {
    1: "08:00-08:50", 2: "08:55-09:45", 3: "10:00-10:50", 4: "10:55-11:45",
    5: "13:00-13:50", 6: "13:55-14:45", 7: "15:00-15:50", 8: "15:55-16:45",
    9: "17:00-17:50", 10: "17:55-18:45", 11: "19:00-19:50", 12: "19:55-20:45",
    13: "21:00-21:50",
}


def run(export: str = None):
    """Fetch and display the student's exam schedule.

    Args:
        export: "csv" to export to ~/.openclaw/workspace/sustech/exams.csv
    """
    print("🔑 Checking session...")
    try:
        cookies = _auth()
    except (NetworkError, RuntimeError) as e:
        print(f"❌ {e}")
        raise

    print("📅 Fetching exam schedule...")
    try:
        exams = _fetch_exams(cookies)
    except (NetworkError, RuntimeError) as e:
        print(f"❌ {e}")
        raise

    if not exams:
        print("❌ No exam data found (finals may not be published yet)")
        raise SessionExpired("No exams returned — schedule may not be published yet")

    # Sort by date
    exams = sorted(exams, key=lambda x: x.get("KSRQ", ""))

    # Group by date
    by_date = {}
    for e in exams:
        date = e.get("KSRQ", "未知")
        by_date.setdefault(date, []).append(e)

    print(f"\n📋 2026春季期末考试 — 共 {len(exams)} 门\n")

    for date in sorted(by_date.keys()):
        day_exams = by_date[date]
        day_name = day_exams[0].get("XQJMC", "")
        day_name_en = day_exams[0].get("XQJMC_EN", "")
        print(f"  {'─' * 60}")
        print(f"  📆 {date} ({day_name} / {day_name_en})")
        print(f"  {'─' * 60}")
        for e in day_exams:
            course = e.get("KCMC", "?")
            code = e.get("KCDM", "")
            exam_type = e.get("KSSJDMC", "考试")
            time_slot = e.get("KSJTSJ", "?")
            building = e.get("JXLMC", "")
            room = e.get("JXCDMC", "")
            campus = e.get("XIAOQUBMC", "") or "一期校区"
            start_period = e.get("KSJC", "?")
            end_period = e.get("JSJC", "?")
            sem = e.get("XNXQMC", "")

            if start_period and end_period:
                periods = f"第{start_period}-{end_period}节"
            else:
                periods = ""

            location = f"{building} {room}".strip()

            print(f"    {course} ({code})")
            print(f"      🕐 {time_slot} | {periods}")
            print(f"      📍 {location} ({campus})")
            print(f"      📚 {exam_type}")
            print()

    # Export
    if export == "csv":
        import csv
        out = _SKILL_ROOT.parent.parent / "workspace" / "sustech" / "exams.csv"
        out.parent.mkdir(parents=True, exist_ok=True)
        fields = ["KCMC", "KCDM", "KSRQ", "XQJMC", "KSJTSJ", "KSJC", "JSJC",
                  "JXLMC", "JXCDMC", "XIAOQUBMC", "KSSJDMC", "XNXQMC"]
        with open(out, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(exams)
        print(f"📄 已导出至 {out}")