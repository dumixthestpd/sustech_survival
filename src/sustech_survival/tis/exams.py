"""TIS Exam Schedule — Spring 2026 final exams."""

from pathlib import Path as _Path

_SKILL_ROOT = _Path(__file__).resolve().parent.parent.parent.parent

__all__ = ["run"]

from sustech_survival.exceptions import InvalidCredentials, NetworkError


def _login():
    """CAS login returning cookies dict, or raising an exception."""
    import re, requests

    creds_file = _SKILL_ROOT / "credentials.txt"
    if not creds_file.exists():
        raise InvalidCredentials("credentials.txt not found — run: bb.py login")
    with open(creds_file) as f:
        username, password = f.read().strip().split(":", 1)
    service_url = "https://tis.sustech.edu.cn/cas"
    encoded_service = service_url.replace(":", "%3A").replace("/", "%2F")
    login_url = f"https://cas.sustech.edu.cn/cas/login?service={encoded_service}"
    h = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
         "X-Requested-With": "XMLHttpRequest"}
    try:
        req = requests.get(login_url, headers=h, timeout=10)
        req.raise_for_status()
    except requests.RequestException as e:
        raise NetworkError(f"CAS login GET failed: {e}")
    exec_match = re.search(r'name="execution" value="([^"]+)"', req.text)
    if not exec_match:
        raise InvalidCredentials("CAS execution token not found in login page")
    data = {"username": username, "password": password,
            "execution": exec_match.group(1), "_eventId": "submit"}
    try:
        req = requests.post(login_url, data=data, allow_redirects=False, headers=h, timeout=10)
    except requests.RequestException as e:
        raise NetworkError(f"CAS login POST failed: {e}")
    ticket_url = req.headers.get("Location", "")
    if not ticket_url:
        raise InvalidCredentials("CAS login rejected — check username/password in credentials.txt")
    try:
        req = requests.get(ticket_url, allow_redirects=False, headers=h, timeout=10)
    except requests.RequestException as e:
        raise NetworkError(f"Ticket exchange failed: {e}")
    set_cookie = req.headers.get("Set-Cookie", "")
    route = re.search(r"route=([^;]+)", set_cookie)
    jsess = re.search(r"JSESSIONID=([^;]+)", set_cookie)
    if not route or not jsess:
        raise InvalidCredentials("CAS did not set session cookies — service URL may have changed")
    return {"route": route.group(1), "JSESSIONID": jsess.group(1)}


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
    print("🔑 CAS login...")
    try:
        cookies = _login()
    except (InvalidCredentials, NetworkError) as e:
        print(f"❌ {e}")
        raise

    print("📅 Fetching exam schedule...")
    try:
        exams = _fetch_exams(cookies)
    except (InvalidCredentials, NetworkError) as e:
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