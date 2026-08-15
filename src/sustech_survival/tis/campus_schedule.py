"""TIS Campus-wide Course Schedule (全校课表).

API: POST https://tis.sustech.edu.cn/Xsxktz/queryRwxxcxList
Auth: CAS session cookies (route, JSESSIONID)
Content-Type: application/x-www-form-urlencoded

Params (form data):
    p_xn           academic year, e.g. "2025-2026"
    p_xq           semester (1=fall, 2=spring)
    p_chaxunpylx  cultivation type: ''=default filtered (~188),
                   '1'=undergrad only (~1200/sem),
                   '2'=grad only (~445/sem),
                   '3'=full campus list (1488 for Spr2026, paginate to get all)
    p_xiaoqu       campus ("一期校区", "二期校区", etc.)
    p_kkyx         college code (e.g. "010030")
    p_kclb         course category code (from queryKclb)
    p_kcxz         course nature ("必修", "选修", etc.)
    p_gjz          keyword search
    p_rwlx         task type
    pageNum        page number
    pageSize       page size (max 500 per page)

Response: {total: N, pageSize: 500, rwList: {list: [course_items]}}
"""

import sys
from pathlib import Path as _Path

SKILL_ROOT = _Path(__file__).resolve().parent.parent.parent.parent
from sustech_survival.sso import TISAuth


def get_campus_schedule(xn=None, xq=None, page_size=500, page_num=1, full=False, **kwargs):
    """Fetch campus course schedule (one page).

    Args:
        xn: Academic year, e.g. "2025-2026" (default: live term)
        xq: Semester — "1" (Fall) or "2" (Spring) (default: live term)
        page_size: Results per page (max 500)
        page_num: Page number (default 1)
        full: If True, ignore page_num and return ALL courses paginated
        **kwargs: Additional filters:
            p_xiaoqu, p_kkyx, p_kclb, p_kcxz, p_gjz, p_rwlx,
            p_chaxunpylx ('' | '1' | '2' | '3')

    Returns:
        dict with keys: total, pageSize, rwList (list of course dicts)
    """
    if xn is None or xq is None:
        from sustech_survival.semester import Semester
        current = Semester.current()
        xn = xn or current.xn
        xq = xq or current.xq

    auth = TISAuth(skill_dir=str(SKILL_ROOT))
    ok, reason = auth.ensure()
    if not ok:
        raise RuntimeError(f"TIS auth failed: {reason}")

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
        "p_chaxunpylx": "",  # ''=default, '1'=undergrad, '2'=grad, '3'=full campus
        "pageNum": str(page_num),
        "pageSize": str(page_size),
    }
    params.update(kwargs)

    if full:
        # Paginate through all pages
        all_items = []
        for pg in range(1, 100):
            params["pageNum"] = str(pg)
            r = auth.post(
                "/Xsxktz/queryRwxxcxList",
                data=params, timeout=30,
            )
            r.raise_for_status()
            d = r.json()
            items = d.get("rwList", {}).get("list", [])
            all_items.extend(items)
            if len(items) < page_size:
                break
        d["rwList"]["list"] = all_items
        return d

    r = auth.post(
        "/Xsxktz/queryRwxxcxList",
        data=params, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def get_semester_courses(semester=None, full=False):
    """Get all courses for a semester as a flat list.

    Args:
        semester: "2025-2026-1" (Fall 2025) or "2025-2026-2" (Spring 2026)
                  Defaults to the live term.
        full: If True, uses p_chaxunpylx='3' (full campus list)
              If False, uses default filtered view
    Returns:
        List of course dicts with full details.
    """
    if semester is None:
        from sustech_survival.semester import Semester
        current = Semester.current()
        xn, xq = current.xn, current.xq
    else:
        parts = semester.split("-")
        xn = parts[0] + "-" + parts[1]
        xq = parts[2]

    extra = {"p_chaxunpylx": "3"} if full else {}
    data = get_campus_schedule(xn=xn, xq=xq, full=True, **extra)
    return data.get("rwList", {}).get("list", [])

# NOTE: the standalone argparse CLI was removed 2026-08-10 during the
# CLI unification. Use `sustech tis campus-schedule` (defined inline
# in sustech_survival/tis/cli.py) — it wraps `get_campus_schedule`
# / `get_semester_courses` from this module.

