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

# Singleton auth instance to avoid repeated re-auth on every call
_auth_instance = None

def session():
    global _auth_instance
    if _auth_instance is None:
        _auth_instance = TISAuth()
    # ensure() = check() first, only refreshes if expired
    ok, reason = _auth_instance.ensure()
    if not ok:
        raise RuntimeError(f"TIS session error: {reason}")
    return _auth_instance.session


def current_semester() -> dict:
    """Return current semester info:XN, XQ, XNXQ, XNXQ_EN."""
    sess = session()
    return sess.post('https://tis.sustech.edu.cn/component/querydangqianxnxq',
                     data={}).json()


def current_week() -> int:
    """Return current week number (1-18)."""
    sess = session()
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

    sess = session()
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

    sess = session()
    url = 'https://tis.sustech.edu.cn/xszykb/queryxszykbzong'
    r = sess.post(url, data={'xn': xn, 'xq': xq})
    r.raise_for_status()
    return r.json()


def week_list() -> list[int]:
    """Return list of valid week numbers for the current semester."""
    sess = session()
    r = sess.post('https://tis.sustech.edu.cn/component/queryzclist',
                  data=current_semester())
    return [item['ZC'] for item in r.json()]

# NOTE: the standalone argparse CLI was removed 2026-08-10 during the
# CLI unification. Use `sustech tis schedule` (defined inline in
# sustech_survival/tis/cli.py) — it wraps `week_schedule` /
# `semester_schedule` / `current_week` from this module.

