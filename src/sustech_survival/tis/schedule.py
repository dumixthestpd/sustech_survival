"""Personal weekly course schedule — xszykb API.

API: POST /xszykb/queryxszykbzhou  (xn, xq, zc)
     POST /xszykb/queryxszykbzong  (xn, xq)  — full semester
     POST /component/querydangqianxnxq  — current semester
     POST /component/querydangqianzc  — current week

No browser/Playwright needed — pure requests.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from sustech_survival.sso import TISAuth


def _session():
    auth = TISAuth()
    auth.refresh()
    return auth.session


def current_semester() -> dict:
    """Return current semester info:XN, XQ, XNXQ, XNXQ_EN."""
    sess = _session()
    return sess.post('https://tis.sustech.edu.cn/component/querydangqianxnxq',
                     data={}).json()


def current_week() -> int:
    """Return current week number (1-18)."""
    sess = _session()
    return int(sess.post('https://tis.sustech.edu.cn/component/querydangqianzc',
                          data={}).text)


def week_schedule(zc: int, xn: str | None = None, xq: str | None = None) -> list[dict]:
    """Return personal course schedule for week zc.

    Args:
        zc: Week number (1-18). Pass None to use current week.
        xn: Academic year e.g. "2025-2026". Auto-detected if omitted.
        xq: Semester number (1 or 2). Auto-detected if omitted.

    Returns:
        List of course-entry dicts with keys: SKSJ, SKSJ_EN, KEY, KSJC, JSJC,
        RWH, XB, PYLX, ZC, KCWZSM, SKFS, SFFXEXW, FILEURL.
        KEY is "xq{day}_jc{period}" e.g. "xq2_jc3" = Tuesday period 3.
        ZC is a 36-char bitmap "011111..." indicating which weeks the course runs.
    """
    if xn is None or xq is None:
        sem = current_semester()
        xn = xn or sem['XN']
        xq = xq or sem['XQ']

    sess = _session()
    url = 'https://tis.sustech.edu.cn/xszykb/queryxszykbzhou'
    r = sess.post(url, data={'xn': xn, 'xq': xq, 'zc': str(zc)})
    r.raise_for_status()
    return r.json()


def semester_schedule(xn: str | None = None, xq: str | None = None) -> list[dict]:
    """Return full semester schedule (all weeks, all courses).

    Returns: Same dict shape as week_schedule() plus ZC bitmap field.
    """
    if xn is None or xq is None:
        sem = current_semester()
        xn = xn or sem['XN']
        xq = xq or sem['XQ']

    sess = _session()
    url = 'https://tis.sustech.edu.cn/xszykb/queryxszykbzong'
    r = sess.post(url, data={'xn': xn, 'xq': xq})
    r.raise_for_status()
    return r.json()


def week_list() -> list[int]:
    """Return list of valid week numbers for the current semester."""
    sess = _session()
    r = sess.post('https://tis.sustech.edu.cn/component/queryzclist',
                  data=current_semester())
    return [item['ZC'] for item in r.json()]


def main():
    import argparse, json

    parser = argparse.ArgumentParser(description='Personal course schedule (TIS xszykb)')
    parser.add_argument('--zc', type=int, default=None,
                        help='Week number (default: current week)')
    parser.add_argument('--xn', default=None, help='Academic year e.g. 2025-2026')
    parser.add_argument('--xq', default=None, help='Semester 1 or 2')
    parser.add_argument('--all', action='store_true',
                        help='Fetch full semester instead of single week')
    args = parser.parse_args()

    if args.all:
        data = semester_schedule(args.xn, args.xq)
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        zc = args.zc if args.zc is not None else current_week()
        data = week_schedule(zc, args.xn, args.xq)
        print(f'=== Week {zc} ===')
        for entry in data:
            print(f"  [{entry['KEY']}] {entry['SKSJ']}")


if __name__ == '__main__':
    main()