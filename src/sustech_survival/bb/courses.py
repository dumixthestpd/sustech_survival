# Courses — BB course data loading and discovery via REST API
"""
Course loading, listing, finding via REST API (no Playwright).

REST-only flow:
  1. /users/me                    → current user ID
  2. /users/{uid}/courses        → enrollment records with courseId
  3. /courses/{courseId}         → course name + details
"""

import json
import re
import sys
import time
from pathlib import Path
from typing import List, Dict

BB_BASE = "https://bb.sustech.edu.cn"


from sustech_survival.exceptions import SessionExpired as _SessionExpired

BB_DIR = Path(__file__).resolve().parent
COURSES_FILE = BB_DIR / "courses.json"

SKIP_COURSE_NAMES = {
    '大学物理', '高等数学', 'college physics', 'higher mathematics',
    '微积分', '线性代数', 'calculus', 'linear algebra',
}


# ── REST-based course discovery ────────────────────────────────────────────────

def _session():
    """Return requests.Session with BB cookies from SSO auth layer."""
    from sustech_survival.sso import BBAuth
    auth = BBAuth(skill_dir=str(BB_DIR.parent.parent.parent.parent))
    raw = auth.load()
    sess = __import__('requests').Session()
    for name, value in raw.items():
        sess.cookies.set(name, value, domain=".bb.sustech.edu.cn", path="/")
    return sess


def _api(path, session=None):
    """GET BB REST endpoint. Returns JSON. Dies on auth error."""
    if session is None:
        session = _session()
    r = session.get(BB_BASE + path, timeout=15)
    if r.status_code == 401:
        raise _SessionExpired("BB session expired. Run `bb.py login` to refresh.")
    r.raise_for_status()
    return r.json()


def scrape_enrolled_courses() -> List[Dict[str, str]]:
    """
    Fetch current user's enrolled courses via REST API.

    Uses /users/me → /users/{uid}/courses → /courses/{courseId}
    to build the full course list with names — no Playwright needed.

    Returns list of dicts: [{"id": "_8343_1", "name": "Physical Chemistry...", "href": ""}, ...]
    """
    me = _api("/learn/api/public/v1/users/me")
    uid = me["id"]

    enrollments = _api(f"/learn/api/public/v1/users/{uid}/courses")
    seen_ids = set()
    courses = []

    for enrollment in enrollments.get("results", []):
        course_id = enrollment.get("courseId", "")
        if not course_id or course_id in seen_ids:
            continue

        try:
            course_data = _api(f"/learn/api/public/v1/courses/{course_id}")
            name = course_data.get("name", "")
        except Exception:
            name = ""

        if not name:
            continue
        if any(sn.lower() in name.lower() for sn in SKIP_COURSE_NAMES):
            continue

        seen_ids.add(course_id)
        courses.append({"id": course_id, "name": name, "href": ""})

    return courses


def refresh_courses_json() -> List[Dict[str, str]]:
    """Scrape live from REST API and update courses.json."""
    courses = scrape_enrolled_courses()
    COURSES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(COURSES_FILE, 'w') as f:
        json.dump({"courses": courses, "ts": __import__('time').time()}, f, indent=2, ensure_ascii=False)
    print(f"Updated {COURSES_FILE} with {len(courses)} courses.")
    for c in courses:
        print(f"  - {c['name']} ({c['id']})")
    return courses


# ── Course Data ────────────────────────────────────────────────────────────────

def _refresh_if_stale(max_age_hours=24):
    """Refresh courses.json if it is older than max_age_hours or missing."""
    if COURSES_FILE.exists():
        try:
            with open(COURSES_FILE) as f:
                data = json.load(f)
            age = (time.time() - data.get("ts", 0)) / 3600
            if age < max_age_hours:
                return  # fresh enough
        except Exception:
            pass
    refresh_courses_json()


def load_courses():
    """
    Load course list from courses.json. Auto-refreshes if stale (>24h).
    Returns list of course dicts.
    """
    _refresh_if_stale()
    if not COURSES_FILE.exists():
        return []
    with open(COURSES_FILE) as f:
        data = json.load(f)
    return data.get("courses", [])


def get_course_numeric_id(course_id_str):
    """Extract numeric part from '_8343_1' → '8343'."""
    m = re.search(r"_(\d+)_", course_id_str)
    return m.group(1) if m else course_id_str


def _extract_code(name: str) -> list:
    """Extract course codes from a name string (e.g. 'MSE202', 'MSE002-003')."""
    return re.findall(r'[A-Z]{2,6}[-_]?\d{3,4}[A-Z]?', name, re.IGNORECASE)


def _codes_normalized(codes: list) -> set:
    """Normalize codes for fuzzy comparison: strip non-alpha prefixes and trailing letter suffixes."""
    normalized = set()
    for code in codes:
        base = re.sub(r'^([A-Z]+)', r'\1', code, flags=re.IGNORECASE).lower()
        digits = re.sub(r'[^0-9]', '', base)
        if digits:
            normalized.add(digits)
    return normalized


def find_course(query):
    """
    Find courses matching query (ID, numeric ID, or name substring).

    Returns list of (course_id_str, name) tuples.
    If no local match, tries live search against all enrolled courses.
    """
    courses = load_courses()
    q = query.lower().strip()
    results = []

    for c in courses:
        cid = c["id"]
        name = c.get("name", "")

        if (q == cid.lower()
                or q in name.lower()):
            results.append((cid, name))

    if results:
        return results

    # No local match -- try live fetch across all enrolled courses
    try:
        live = _api("/learn/api/public/v1/users/me")
        uid = live["id"]
        enrollments = _api(f"/learn/api/public/v1/users/{uid}/courses")
        for e in enrollments.get("results", []):
            cid = e.get("courseId", "")
            if not cid:
                continue
            try:
                cd = _api(f"/learn/api/public/v1/courses/{cid}")
                name = cd.get("name", "")
            except Exception:
                name = ""
            if q in name.lower() or q == cid.lower():
                results.append((cid, name))
    except Exception:
        pass

    return results


def list_courses():
    """Return all courses as (course_id_str, name) tuples."""
    return [(c["id"], c.get("name", "Unknown")) for c in load_courses()]


# ── Assignment Discovery (REST-only) ─────────────────────────────────────────

def discover_assignments_for_course(course_id_str):
    """
    Discover all BB assignment slots for a course via gradebook REST API.

    Returns list of (assignment_content_id, title) tuples.
    No Playwright needed -- contentId from gradebook columns is the content ID
    used in uploadAssignment URLs.
    """
    numeric_match = re.search(r"_(\d+)_1", course_id_str)
    if not numeric_match:
        numeric_match = re.search(r"^_?(\d+)_?1?$", course_id_str)
    numeric_cid = numeric_match.group(1) if numeric_match else course_id_str

    bid = f"_{numeric_cid}_1"
    try:
        cols = _api(
            f"/learn/api/public/v1/courses/{bid}/gradebook/columns"
            f"?_fields=id,name,contentId,grading",
        )
    except Exception:
        return []

    results = []
    for col in cols.get("results", []):
        content_id = col.get("contentId", "")
        if not content_id:
            continue
        cid_numeric = content_id.lstrip("_").rstrip("_1")
        name = col.get("name", "") or f"Assignment {cid_numeric}"
        results.append((cid_numeric, name))

    return results