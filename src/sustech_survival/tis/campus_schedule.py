"""TIS Campus-wide Course Schedule (全校课表).

API: POST https://tis.sustech.edu.cn/Xsxktz/queryRwxxcxList
Auth: CAS session cookies (route, JSESSIONID)
Content-Type: application/x-www-form-urlencoded

Params (form data):
    p_xn       academic year, e.g. "2025-2026"
    p_xq       semester, e.g. "2" (1=fall, 2=spring)
    p_xnxq     combined semester name, e.g. "2026春季"
    p_gjz      keyword search (course name)
    p_xiaoqu   campus ("一期校区", "二期校区", etc.)
    p_kkyx     college code (e.g. "010030")
    p_rwlx     task type (e.g. "01"=理论课)
    p_kclb     course category (use codes from queryKclb)
    p_kcxz     course nature ("必修", "选修", etc.)
    p_chapylx  cultivation type
    pageNum    page number (default 1)
    pageSize   page size (default 500)

Response: {total: N, pageSize: 500, rwList: {list: [course_items]}}
"""

import sys
from pathlib import Path as _Path

_SKILL_ROOT = _Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_SKILL_ROOT))


def _login():
    import re, requests
    creds_file = _SKILL_ROOT / "credentials.txt"
    with open(creds_file) as f:
        username, password = f.read().strip().split(":", 1)
    service_url = "https://tis.sustech.edu.cn/cas"
    encoded_service = service_url.replace(":", "%3A").replace("/", "%2F")
    login_url = f"https://cas.sustech.edu.cn/cas/login?service={encoded_service}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "X-Requested-With": "XMLHttpRequest",
    }
    req = requests.get(login_url, headers=headers, timeout=15)
    execution = re.search(r'name="execution" value="([^"]+)"', req.text).group(1)
    data = {
        "username": username,
        "password": password,
        "execution": execution,
        "_eventId": "submit",
    }
    req = requests.post(login_url, data=data, allow_redirects=False, headers=headers, timeout=15)
    ticket_url = req.headers["Location"]
    req = requests.get(ticket_url, allow_redirects=False, headers=headers, timeout=15)
    set_cookie = req.headers.get("Set-Cookie", "")
    route = re.search(r"route=([^;]+)", set_cookie).group(1)
    jsess = re.search(r"JSESSIONID=([^;]+)", set_cookie).group(1)
    return {"route": route, "JSESSIONID": jsess}


def _get_session():
    """Return current-semester session cookies dict, logging in if needed."""
    # Reuse cookies from TIS session if still valid
    return _login()


def get_campus_schedule(xn="2025-2026", xq="2", page_size=500, page_num=1, **kwargs):
    """Fetch the full campus course schedule.

    Args:
        xn: Academic year, e.g. "2025-2026"
        xq: Semester — "1" (Fall/秋季) or "2" (Spring/春季)
        page_size: Results per page (max 500, default 500)
        page_num: Page number (default 1)
        **kwargs: Additional filters:
            p_xiaoqu (campus), p_kkyx (college code), p_kclb (category code),
            p_kcxz (course nature), p_gjz (keyword), p_rwlx (task type)

    Returns:
        dict with keys: total, pageSize, rwList (list of course dicts)
    """
    cookies = _get_session()
    h = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/x-www-form-urlencoded",
        "Cookie": f"route={cookies['route']}; JSESSIONID={cookies['JSESSIONID']}",
    }
    params = {
        "p_xn": xn,
        "p_xq": xq,
        "p_xnxq": None,
        "p_gjz": "",
        "p_xiaoqu": "",
        "p_kkyx": "",
        "p_rwlx": "",
        "p_kclb": "",
        "p_kcxz": "",
        "p_chaxunpylx": "",     # ''=default filtered, '1'=undergrad, '2'=grad, '3'=both+all history
        "pageNum": str(page_num),
        "pageSize": str(page_size),
    }
    params.update(kwargs)
    import requests
    r = requests.post(
        "https://tis.sustech.edu.cn/Xsxktz/queryRwxxcxList",
        data=params,
        headers=h,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def get_semester_courses(semester=None):
    """Get all courses for a semester as a flat list.

    Args:
        semester: "2025-2026-1" (Fall 2025) or "2025-2026-2" (Spring 2026)
                  Defaults to current semester (Spring 2026).

    Returns:
        List of course dicts with full details.
    """
    if semester is None:
        xn, xq = "2025-2026", "2"
    else:
        parts = semester.split("-")
        xn = parts[0] + "-" + parts[1]
        xq = parts[2]

    data = get_campus_schedule(xn=xn, xq=xq)
    return data.get("rwList", {}).get("list", [])


# ── CLI ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import json

    print("Fetching Spring 2026 campus schedule...")
    data = get_campus_schedule(xn="2025-2026", xq="2")
    items = data.get("rwList", {}).get("list", [])
    print(f"Total courses: {data.get('total')} | Page size: {data.get('pageSize')}")
    print(f"Returned: {len(items)}")

    # Print first 3 as summary
    for course in items[:3]:
        print(f"\n  {course.get('kcmc')} ({course.get('kcdm')})")
        print(f"  {course.get('kkyxmc')} | {course.get('dgjsmc', 'TBA')}")
        print(f"  {course.get('sksj', 'TBA')} @ {course.get('xiaoqumc', '')}")
        print(f"  {course.get('kclbmc')} / {course.get('kcxzmc')} | {course.get('xf')} credits")
