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


def get_campus_schedule(xn="2025-2026", xq="2", page_size=500, page_num=1, full=False, **kwargs):
    """Fetch campus course schedule (one page).

    Args:
        xn: Academic year, e.g. "2025-2026"
        xq: Semester — "1" (Fall) or "2" (Spring)
        page_size: Results per page (max 500)
        page_num: Page number (default 1)
        full: If True, ignore page_num and return ALL courses paginated
        **kwargs: Additional filters:
            p_xiaoqu, p_kkyx, p_kclb, p_kcxz, p_gjz, p_rwlx,
            p_chaxunpylx ('' | '1' | '2' | '3')

    Returns:
        dict with keys: total, pageSize, rwList (list of course dicts)
    """
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
                  Defaults to Spring 2026.
        full: If True, uses p_chaxunpylx='3' (full campus list, 1488 for Spr2026)
              If False, uses default filtered view (~188 courses)
    Returns:
        List of course dicts with full details.
    """
    if semester is None:
        xn, xq = "2025-2026", "2"
    else:
        parts = semester.split("-")
        xn = parts[0] + "-" + parts[1]
        xq = parts[2]

    extra = {"p_chaxunpylx": "3"} if full else {}
    data = get_campus_schedule(xn=xn, xq=xq, full=True, **extra)
    return data.get("rwList", {}).get("list", [])


# ── CLI ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import json, argparse

    parser = argparse.ArgumentParser(description="TIS Campus Schedule")
    parser.add_argument("--semester", default="2025-2026-2",
                        help="e.g. 2025-2026-2 (Spring 2026)")
    parser.add_argument("--full", action="store_true",
                        help="Use full campus list (p_chaxunpylx=3, ~1488 courses)")
    parser.add_argument("--json", action="store_true", help="Output JSON to stdout")
    parser.add_argument("--csv", action="store_true", help="Output CSV to stdout")
    args = parser.parse_args()

    parts = args.semester.split("-")
    xn = parts[0] + "-" + parts[1]
    xq = parts[2]

    print(f"Fetching {args.semester} campus schedule (full={args.full})...")
    extra = {"p_chaxunpylx": "3"} if args.full else {}
    data = get_campus_schedule(xn=xn, xq=xq, full=True, **extra)
    items = data.get("rwList", {}).get("list", [])
    print(f"Total: {data.get('total')} | Collected: {len(items)}")

    if args.json:
        print(json.dumps(items, ensure_ascii=False, indent=2))
    elif args.csv:
        import csv, io
        if items:
            out = io.StringIO()
            w = csv.DictWriter(out, fieldnames=["kcmc","kcdm","kkyxmc","dgjsmc","xf","kclbmc","kcxzmc","xiaoqumc","pylx"])
            w.writeheader()
            for it in items:
                w.writerow({k: it.get(k, "") for k in ["kcmc","kcdm","kkyxmc","dgjsmc","xf","kclbmc","kcxzmc","xiaoqumc","pylx"]})
            print(out.getvalue())
    else:
        for course in items[:5]:
            print(f"\n  {course.get('kcmc')} ({course.get('kcdm')})")
            print(f"  {course.get('kkyxmc')} | {course.get('dgjsmc', 'TBA')} | {course.get('xf')}学分")
            print(f"  {course.get('kclbmc')} / {course.get('kcxzmc')} | pylx={'本科' if course.get('pylx')=='1' else '研究生'}")
        print(f"\n  ... +{len(items)-5} more")
