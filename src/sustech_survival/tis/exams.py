"""TIS Exam Schedule — Spring 2026 final exams."""

import sys
from pathlib import Path as _Path

_SKILL_ROOT = _Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_SKILL_ROOT / "src"))

__all__ = ["run"]


def _login():
    import re, requests
    creds_file = _SKILL_ROOT / "credentials.txt"
    with open(creds_file) as f:
        username, password = f.read().strip().split(":", 1)
    service_url = "https://tis.sustech.edu.cn/cas"
    encoded_service = service_url.replace(":", "%3A").replace("/", "%2F")
    login_url = f"https://cas.sustech.edu.cn/cas/login?service={encoded_service}"
    h = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36", "X-Requested-With": "XMLHttpRequest"}
    req = requests.get(login_url, headers=h, timeout=10)
    execution = re.search(r'name="execution" value="([^"]+)"', req.text).group(1)
    data = {"username": username, "password": password, "execution": execution, "_eventId": "submit"}
    req = requests.post(login_url, data=data, allow_redirects=False, headers=h, timeout=10)
    ticket_url = req.headers["Location"]
    req = requests.get(ticket_url, allow_redirects=False, headers=h, timeout=10)
    set_cookie = req.headers.get("Set-Cookie", "")
    route = re.search(r"route=([^;]+)", set_cookie).group(1)
    jsess = re.search(r"JSESSIONID=([^;]+)", set_cookie).group(1)
    return {"route": route, "JSESSIONID": jsess}


def _fetch_exams(cookies: dict):
    """Fetch exam schedule from TIS student exam endpoint."""
    import requests

    h = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/json",
        "Cookie": f"route={cookies['route']}; JSESSIONID={cookies['JSESSIONID']}"
    }
    r = requests.post(
        "https://tis.sustech.edu.cn/component/queryKsxxByXs",
        json={},
        headers=h,
        timeout=15
    )
    if r.status_code != 200:
        raise RuntimeError(f"TIS exam API returned {r.status_code}")
    return r.json()  # returns a plain list (not wrapped in content/)


# Period -> time mapping (SUSTech standard)
_PERIOD_TIMES = {
    1: "08:00-08:50",
    2: "08:55-09:45",
    3: "10:00-10:50",
    4: "10:55-11:45",
    5: "13:00-13:50",
    6: "13:55-14:45",
    7: "15:00-15:50",
    8: "15:55-16:45",
    9: "17:00-17:50",
    10: "17:55-18:45",
    11: "19:00-19:50",
    12: "19:55-20:45",
    13: "21:00-21:50",
}


def run(export: str = None):
    """Fetch and display the student's exam schedule.

    Args:
        export: "csv" to export to ~/.openclaw/workspace/sustech/exams.csv
    """
    print("🔑 CAS login...")
    cookies = _login()
    if not cookies:
        print("❌ TIS login failed")
        sys.exit(1)

    print("📅 Fetching exam schedule...")
    exams = _fetch_exams(cookies)

    if not exams:
        print("❌ No exam data found (finals may not be published yet)")
        sys.exit(1)

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
            exam_type = e.get("KSSJDMC", "考试")  # 期末考试 etc
            time_slot = e.get("KSJTSJ", "?")
            building = e.get("JXLMC", "")
            room = e.get("JXCDMC", "")
            campus = e.get("XIAOQUBMC", "") or "一期校区"
            start_period = e.get("KSJC", "?")
            end_period = e.get("JSJC", "?")
            sem = e.get("XNXQMC", "")

            # Period range
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


if __name__ == "__main__":
    run()
