"""
bb ddl — Assignment deadlines from Blackboard.

Uses BB REST API exclusively (no Playwright):
  1. /users/me                 → current user ID
  2. /users/{uid}/courses      → enrolled courses for current term
  3. /courses/{id}/gradebook/columns  → assignment names + ISO due dates
  4. /courses/{id}/gradebook/users/{uid}  → all grades + status for user

Due dates come as ISO timestamps directly from BB — no regex parsing needed.
Scores and NeedsGrading status come from the users endpoint — no per-column
attempt API calls needed.
"""

import re
import sys
from datetime import datetime, timedelta

import requests

# ── session via SSO auth layer ─────────────────────────────────────────────────

BB_BASE = "https://bb.sustech.edu.cn"


def _session():
    """Return requests.Session with BB CAS cookies from SSO auth layer."""
    from sustech_survival.sso.authorizer import get_auth

    auth = get_auth("bb")
    raw = auth.load()
    sess = requests.Session()
    for name, value in raw.items():
        sess.cookies.set(name, value, domain=".bb.sustech.edu.cn", path="/")
    return sess


def _api(path: str, session=None):
    """GET BB REST API endpoint. Returns JSON dict or dies."""
    if session is None:
        session = _session()
    url = BB_BASE + path
    r = session.get(url, timeout=15)
    if r.status_code == 401:
        print("❌ BB session expired. Run `bb.py login` to refresh.")
        sys.exit(1)
    r.raise_for_status()
    return r.json()


# ── user + course list ─────────────────────────────────────────────────────────

def _get_user_id(session=None) -> str:
    """Return current user ID string (e.g. '_70745_1')."""
    data = _api("/learn/api/public/v1/users/me", session)
    return data["id"]


def _get_enrolled_courses(session=None, term_id="_57_1"):
    """
    Return list of (course_id, course_name) for given termId.

    Uses /users/{uid}/courses (enrollments) which gives ALL enrolled courses
    regardless of pagination — more reliable than /courses?termId= which can
    miss courses at certain offsets.
    """
    uid = _get_user_id(session)
    data = _api(f"/learn/api/public/v1/users/{uid}/courses", session)
    courses = []
    seen_ids = set()
    for enrollment in data.get("results", []):
        cid = enrollment.get("id", "")   # e.g. "_551150_1" — enrollment record id
        course_id = enrollment.get("courseId", "")  # e.g. "_8343_1"
        if not course_id or course_id in seen_ids:
            continue
        seen_ids.add(course_id)
        # Fetch course name
        try:
            course_data = _api(f"/learn/api/public/v1/courses/{course_id}", session)
            name = course_data.get("name", "")
        except Exception:
            name = ""
        if name:
            courses.append((course_id, name))
    return courses


# ── gradebook ──────────────────────────────────────────────────────────────────

def _get_gradebook_columns(course_id, session=None):
    """Return dict mapping columnId → {name, due} for assignments with due dates."""
    cols = _api(
        f"/learn/api/public/v1/courses/{course_id}/gradebook/columns"
        f"?_fields=id,name,contentId,grading",
        session,
    )
    result = {}
    for col in cols.get("results", []):
        grading = col.get("grading", {})
        if grading.get("type") != "Attempts":
            continue
        col_id = col.get("id", "")
        if not col_id:
            continue
        result[col_id] = {
            "name": col.get("name", ""),
            "content_id": col.get("contentId", ""),
            "due": grading.get("due", "") or "",
        }
    return result


def _get_user_grades(course_id, user_id, session=None):
    """
    Return dict mapping columnId → {score, status} for all grade columns
    in a course for the current user.

    One API call replaces N per-column attempt calls.
    Status values: 'Graded', 'NeedsGrading', 'In Progress', 'Not Attempted'.
    """
    data = _api(
        f"/learn/api/public/v1/courses/{course_id}/gradebook/users/{user_id}",
        session,
    )
    result = {}
    for entry in data.get("results", []):
        col_id = entry.get("columnId", "")
        if not col_id:
            continue
        result[col_id] = {
            "score": entry.get("score"),
            "status": entry.get("status", ""),
        }
    return result


# ── date helpers ──────────────────────────────────────────────────────────────

def _parse_iso(iso: str):
    """Parse BB ISO timestamp → datetime. Returns None if unparseable."""
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _format_due(iso: str):
    """Human-readable due date from ISO string."""
    dt = _parse_iso(iso)
    if not dt:
        return "无截止日"
    return dt.strftime("%m-%d %H:%M")


# ── main ──────────────────────────────────────────────────────────────────────

def run(days: int = 7, course_id: str = None):
    """Print upcoming BB assignment deadlines. See docs/bb.md."""
    session = _session()
    now = datetime.now()
    cutoff = now + timedelta(days=days)

    # 1. Get enrolled courses
    courses = _get_enrolled_courses(session, term_id="_57_1")
    if not courses:
        print("❌ 无法获取课程列表，请重新登录")
        return

    # 2. Filter to active courses if no specific course requested
    if course_id:
        courses = [(c, n) for c, n in courses if c == course_id]
    else:
        active_ids = {"_8053_1", "_8157_1", "_8221_1", "_8328_1", "_8343_1"}
        courses = [
            (c, n) for c, n in courses
            if "2026" in n or c in active_ids
        ]
        if not courses:
            courses = _get_enrolled_courses(session, term_id="_57_1")

    # 3. Get current user ID (for grade lookup)
    uid = _get_user_id(session)

    all_items = []  # (course_name, name, due_iso, status, score_str)

    for cid, cname in courses:
        try:
            # Columns: gives us name + ISO due date
            cols = _get_gradebook_columns(cid, session)
        except Exception:
            continue

        if not cols:
            continue

        try:
            # All user grades in one call: gives score + NeedsGrading status
            grades = _get_user_grades(cid, uid, session)
        except Exception:
            grades = {}

        for col_id, col in cols.items():
            name = col["name"]
            if not name:
                continue

            due_iso = col["due"]
            due_dt = _parse_iso(due_iso)
            due_str = _format_due(due_iso)

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

            # Grade info from users endpoint (no extra API calls)
            grade_info = grades.get(col_id, {})
            score = grade_info.get("score")
            grade_status = grade_info.get("status", "")

            score_str = ""
            if grade_status == "Graded" and score is not None:
                score_str = f" {score}"
            elif grade_status == "NeedsGrading":
                score_str = " 待评分"

            all_items.append({
                "course": cname,
                "name": name,
                "due_iso": due_iso,
                "due_str": due_str,
                "status": status,
                "score": score_str,
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
