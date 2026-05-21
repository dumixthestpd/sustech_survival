"""
bb ddl — Assignment deadlines from Blackboard.

Uses BB REST API exclusively (no Playwright):
  1. /courses?termId=_57_1  → enrolled courses
  2. /courses/{id}/gradebook/columns → assignments + ISO due dates + scores

Due dates come as ISO timestamps directly from BB — no regex parsing needed.
"""

import re
import sys
from datetime import datetime, timedelta

import requests

# ── session ──────────────────────────────────────────────────────────────────

BB_BASE = "https://bb.sustech.edu.cn"
SESSION_FILE = None  # resolved at runtime


def _session():
    """Return requests.Session with BB CAS cookies."""
    from pathlib import Path
    skill_root = Path(__file__).resolve().parent.parent.parent.parent
    session_file = skill_root / "bb" / "session.json"

    import json
    with open(session_file) as f:
        raw = json.load(f)

    sess = requests.Session()
    # BB expects these cookies on .bb.sustech.edu.cn
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


# ── course list ──────────────────────────────────────────────────────────────

def _get_courses(session=None, term_id="_57_1"):
    """Return list of (course_id, course_name) for given termId.

    course_id format: "_8157_1" (with underscores, as BB uses them)
    """
    data = _api(f"/learn/api/public/v1/courses?termId={term_id}", session)
    courses = []
    for c in data.get("results", []):
        cid = c["id"]           # already in "_xxx_1" format
        name = c.get("name", "")
        if name:
            courses.append((cid, name))
    return courses


# ── gradebook ────────────────────────────────────────────────────────────────

def _get_gradebook_columns(course_id, session=None):
    """Return list of grade-column dicts for a course.

    Each dict:
      id           — column ID (e.g. "_413533_1")
      name         — assignment name
      content_id   — maps to content item
      due          — ISO datetime string or "" if none
      possible     — max score (float)
      scoring_type — "Attempts" / "Calculated"
    """
    cols = _api(
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


def _get_user_attempts(course_id, column_id, session=None):
    """Return list of attempt dicts for current user on one column."""
    try:
        data = _api(
            f"/learn/api/public/v1/courses/{course_id}/gradebook/columns/{column_id}/attempts",
            session,
        )
        return data.get("results", [])
    except Exception:
        return []


# ── date helpers ─────────────────────────────────────────────────────────────

def _parse_iso(iso: str):
    """Parse BB ISO timestamp → datetime. Returns None if unparseable."""
    if not iso:
        return None
    try:
        # "2026-03-25T15:59:00.000Z"
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _format_due(iso: str):
    """Human-readable due date from ISO string."""
    dt = _parse_iso(iso)
    if not dt:
        return "无截止日"
    return dt.strftime("%m-%d %H:%M")


# ── main ────────────────────────────────────────────────────────────────────

def run(days: int = 7, course_id: str = None):
    """See docs/bb.md."""
    session = _session()
    now = datetime.now()
    cutoff = now + timedelta(days=days)

    # 1. Get enrolled courses for current term
    courses = _get_courses(session, term_id="_57_1")
    if not courses:
        print("❌ 无法获取课程列表，请重新登录")
        return

    # 2. Filter
    if course_id:
        courses = [(c, n) for c, n in courses if c == course_id]
    else:
        active_ids = {"_8053_1", "_8157_1", "_8221_1", "_8328_1", "_8343_1"}
        courses = [
            (c, n) for c, n in courses
            if "2026" in n or c in active_ids
        ]
        if not courses:
            courses = _get_courses(session, term_id="_57_1")

    all_items = []  # (course_name, name, due_iso, status, score, feedback)

    for cid, cname in courses:
        try:
            cols = _get_gradebook_columns(cid, session)
        except Exception as e:
            continue

        for col in cols:
            if col["scoring_type"] != "Attempts":
                continue   # skip Total, averages, etc.
            if not col["name"]:
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

            # Attempt info
            attempts = _get_user_attempts(cid, col["id"], session)
            score_str = ""
            feedback_str = ""
            if attempts:
                latest = attempts[-1]
                s = latest.get("score")
                score_str = f" {s}" if s is not None else " 未评分"
                fb = latest.get("feedback", "") or ""
                if fb:
                    # strip HTML tags
                    fb_clean = re.sub(r"<[^>]+>", "", fb)
                    feedback_str = f" 评语: {fb_clean[:50]}"

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
