"""
bb ddl — Assignment deadlines from Blackboard.

Uses BB REST API exclusively (no Playwright):
  1. /users/{uid}/courses?termId=_57_1  → enrolled courses (user's actual enrollments)
  2. /courses/{id}/gradebook/columns   → assignments + ISO due dates + scores

Due dates come as ISO timestamps directly from BB — no regex parsing needed.
"""

from sustech_survival.exceptions import SessionExpired as _SessionExpired
from sustech_survival.sso import BBAuth
from sustech_survival.sso.authorizer import AuthorizerError as _AuthorizerError
import re
import sys
from datetime import datetime, timedelta, timezone

import requests

# -- auth singleton -------------------------------------------------------------
# No hardcoded path — BBAuth().skill_root auto-discovers skill root via
# credentials.txt search, so this works from any install location.
bb_auth = BBAuth()


def session():
    """Return requests.Session with BB CAS cookies.

    Uses BBAuth.ensure() which auto-refreshes via CAS if the session is expired.
    Raises _SessionExpired on auth failure (including when refresh fails).
    """
    ok, reason = bb_auth.ensure()
    if not ok:
        raise _SessionExpired(f"BB auth failed: {reason}")
    return bb_auth.session


def api(path: str, session=None):
    """GET BB REST API endpoint. Returns JSON dict or dies."""
    if session is None:
        session = session()
    url = "https://bb.sustech.edu.cn" + path
    r = session.get(url, timeout=15)
    if r.status_code == 401:
        raise _SessionExpired("BB session expired after refresh — run `bb session login` manually")
    r.raise_for_status()
    return r.json()


# -- user ID (cached) ----------------------------------------------------------

_uid_cache = None


def get_uid(session):
    """Return current user ID (cached)."""
    global _uid_cache
    if _uid_cache:
        return _uid_cache
    me = session.get(
        "https://bb.sustech.edu.cn/learn/api/public/v1/users/me", timeout=10
    )
    _uid_cache = me.json()["id"]
    return _uid_cache


# -- course list --------------------------------------------------------------

def get_courses(session=None, term_id="_57_1"):
    """Return list of (course_id, course_name) for the current user's enrollments.

    Uses /users/{uid}/courses to get ONLY enrolled courses — not all courses
    in a term. Then fetches course names in parallel for speed.

    course_id format: "_8157_1" (with underscores, as BB uses them).
    """
    uid = get_uid(session)
    data = api(f"/learn/api/public/v1/users/{uid}/courses?termId={term_id}", session)
    entries = data.get("results", [])
    if not entries:
        return []

    # Fetch course names in parallel via threading
    import concurrent.futures

    def fetch_name(entry):
        cid = entry["courseId"]
        try:
            details = session.get(
                f"https://bb.sustech.edu.cn/learn/api/public/v1/courses/{cid}",
                timeout=10,
            )
            name = details.json().get("name", "?")
        except Exception:
            name = "?"
        return (cid, name)

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        futures = {ex.submit(fetch_name, e): e for e in entries}
        courses = []
        for fut in concurrent.futures.as_completed(futures):
            try:
                cid, name = fut.result()
                if name and name != "?":
                    courses.append((cid, name))
            except Exception:
                pass

    return courses


# -- gradebook ----------------------------------------------------------------

def get_gradebook_columns(course_id, session=None):
    """Return list of grade-column dicts for a course.

    Each dict:
      id           — column ID (e.g. "_413533_1")
      name         — assignment name
      content_id   — maps to content item
      due          — ISO datetime string or "" if none
      possible     — max score (float)
      scoring_type — "Attempts" / "Calculated"
    """
    cols = api(
        f"/learn/api/public/v1/courses/{course_id}/gradebook/columns"
        f"?_fields=id,name,contentId,score,grading",
        session,
    )
    results = []
    for col in cols.get("results", []):
        grading = col.get("grading", {})
        due_raw = grading.get("due", "") or ""
        results.append({
            "id": col.get("id", ""),
            "name": col.get("name", ""),
            "content_id": col.get("contentId", ""),
            "possible": col.get("score", {}).get("possible", 0),
            "due": due_raw,
            "scoring_type": grading.get("type", ""),
        })
    return results


def get_user_attempts(course_id, column_id, session=None):
    """Return list of attempt dicts for current user on one column."""
    try:
        data = api(
            f"/learn/api/public/v1/courses/{course_id}/gradebook/columns/{column_id}/attempts",
            session,
        )
        return data.get("results", [])
    except Exception:
        return []


# -- date helpers -------------------------------------------------------------

def parse_iso(iso: str):
    """Parse BB ISO timestamp → naive local datetime (CST/UTC+8).

    BB returns UTC (Z-suffix). The user is in Shenzhen (UTC+8).
    We convert to local time so the due date shows the correct wall-clock hour.
    """
    if not iso:
        return None
    try:
        # "2026-03-25T15:59:00.000Z" → aware UTC → convert to CST (+8)
        dt_utc = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        dt_local = dt_utc.astimezone(timezone(timedelta(hours=8)))
        return dt_local.replace(tzinfo=None)  # naive for consistent comparison
    except ValueError:
        return None


def format_due(iso: str):
    """Human-readable due date from ISO string."""
    dt = parse_iso(iso)
    if not dt:
        return "无截止日"
    return dt.strftime("%m-%d %H:%M")


# -- main --------------------------------------------------------------------

def upcoming_deadlines(days: int = 30) -> list[dict]:
    """Return upcoming BB assignment deadlines within ``days`` as list of dicts.

    Each dict: {name, course, due, due_str, days_left, due_dt}
    Returns [] if none found. Raises _SessionExpired on auth failure.
    """
    session = session()
    now = datetime.now()
    cutoff = now + timedelta(days=days)

    courses = get_courses(session, term_id="_57_1")
    if not courses:
        raise _SessionExpired("无法获取课程列表，请重新登录")

    results = []
    for cid, cname in courses:
        try:
            cols = get_gradebook_columns(cid, session)
        except Exception:
            continue
        for col in cols:
            if col["scoring_type"] != "Attempts" or not col["name"]:
                continue
            due_iso = col["due"]
            due_dt = parse_iso(due_iso)
            if due_dt is None:
                continue
            if due_dt < now or due_dt > cutoff:
                continue
            days_left = (due_dt - now).days
            results.append({
                "name": col["name"],
                "course": cname,
                "due": due_iso,
                "due_str": format_due(due_iso),
                "days_left": days_left,
                "due_dt": due_dt,
            })

    results.sort(key=lambda x: x["due_dt"])
    return results


def run(days: int = 7, course_id: str = None):
    """See docs/bb.md."""
    session = session()
    now = datetime.now()
    cutoff = now + timedelta(days=days)

    # 1. Get enrolled courses for current term
    courses = get_courses(session, term_id="_57_1")
    if not courses:
        print("❌ 无法获取课程列表，请重新登录")
        raise _SessionExpired("无法获取课程列表，请重新登录")

    # 2. Filter
    if course_id:
        courses = [(c, n) for c, n in courses if c == course_id]

    all_items = []  # (course_name, name, due_iso, status, score, feedback)

    for cid, cname in courses:
        try:
            cols = get_gradebook_columns(cid, session)
        except Exception as e:
            continue

        for col in cols:
            if col["scoring_type"] != "Attempts":
                continue   # skip Total, averages, etc.
            if not col["name"]:
                continue

            due_iso = col["due"]
            due_dt = parse_iso(due_iso)
            due_str = format_due(due_iso)

            # Status relative to now
            if due_dt:
                if due_dt < now:
                    status = "已截止"
                elif due_dt <= cutoff:
                    delta = (due_dt - now).days
                    status = f"还有 {delta} 天"
                else:
                    status = f"{days} 天后"
            else:
                status = ""

            # Attempt info
            attempts = get_user_attempts(cid, col["id"], session)
            score_str = ""
            feedback_str = ""
            has_score = False
            if attempts:
                latest = attempts[-1]
                s = latest.get("score")
                if s is not None:
                    has_score = True
                    score_str = f" {s}"
                    fb = latest.get("feedback", "") or ""
                    if fb:
                        fb_clean = re.sub(r"<[^>]+>", "", fb)
                        feedback_str = f" 评语: {fb_clean[:50]}"
                else:
                    score_str = " 未评分"

            # Hide: submitted+graded (has score), OR past-due with no submission
            # (likely old/irrelevant BB columns — not real pending work),
            # OR no due date at all (BB placeholder items with no deadline)
            if has_score:
                continue
            if due_dt and due_dt < now:
                continue
            if not due_dt:
                continue

            all_items.append({
                "course": cname,
                "name": col["name"],
                "due_iso": due_iso,
                "due_str": due_str,
                "status": status,
                "score": score_str,
                "feedback": feedback_str,
                "due_dt": due_dt,
            })

    if not all_items:
        print("📭 暂无作业信息")
        return

    # Sort: upcoming first, then by date
    def sort_key(item):
        dt = item["due_dt"]
        if dt is None:
            return (1, datetime.max)
        if dt < now:
            return (2, dt)
        return (0, dt)

    all_items.sort(key=sort_key)

    # Print
    print(f"📚 作业列表 ({len(all_items)} 项)\n")
    current_course = None
    for item in all_items:
        if item["course"] != current_course:
            current_course = item["course"]
            print(f"\n{'='*50}")
            print(f"  {current_course[:50]}")
            print(f"{'='*50}")
        delta = item["status"]
        print(f"  • {item['name'][:45]}")
        parts = [f"截止: {item['due_str']}"]
        if delta:
            parts.append(delta)
        if item["score"]:
            parts.append(item["score"])
        print(f"    {' | '.join(parts)}")
        if item["feedback"]:
            print(f"    {item['feedback']}")
