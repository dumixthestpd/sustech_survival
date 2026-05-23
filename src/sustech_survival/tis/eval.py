"""
TIS 评教 (Teaching Evaluation) automation.

Workflow:
  1. Authenticate via SSO layer
  2. List pending evaluation tasks for a semester
  3. For each course with "待评价" status:
     a. Navigate to evaluation form (AES-encrypted URL)
     b. Auto-score all numeric scale questions (default: max score)
     c. Save (not submit) — leaves pjzt=2 so user can review/edit later
  4. Support save-only mode so user can manually review before final submit

Usage:
  from sustech_survival.sso import TISAuth
  from sustech_survival.tis.eval import auto_fill
  from pathlib import Path

  skill = str(Path(__file__).resolve().parent.parent.parent.parent)
  auth = TISAuth(skill_dir=skill)
  auth.refresh()  # always refresh — check() doesn't detect TIS expiry reliably
  raw = auth.load()
  sess = requests.Session()
  auth._apply_cookies(sess, raw)
  auto_fill(sess)  # auto-detects yhdm, all pending courses
  auto_fill(sess, courses=["CAD与工程制图"], score=10)  # specific courses
  auto_fill(sess, dry_run=True)  # list only, no saves
"""

import base64
import json
import sys
from typing import Optional

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import padding as _pad
    from cryptography.hazmat.backends import default_backend
    _HAS_AES = True
except ImportError:
    _HAS_AES = False

from sustech_survival.sso import TISAuth
BASE = TISAuth.BASE_URL

__all__ = ["auto_fill", "save_all", "list_courses", "list_tasks", "build_navigate_params"]


# ---------------------------------------------------------------------------
# AES encryption for form navigation
# ---------------------------------------------------------------------------

AES_KEY = b"inco_NKDpJXT_12$"
AES_IV  = b"INCO_16_NKDpJXT#"


def aes_encrypt(data: dict) -> str:
    """Return base64-encoded AES/CBC/PKCS7 ciphertext of a dict."""
    if not _HAS_AES:
        raise RuntimeError("pip install cryptography")
    plaintext = json.dumps(data, ensure_ascii=False).encode("utf-8")
    padder = _pad.PKCS7(128).padder()
    padded = padder.update(plaintext) + padder.finalize()
    cipher = Cipher(algorithms.AES(AES_KEY), modes.CBC(AES_IV), backend=default_backend())
    enc = cipher.encryptor().update(padded) + cipher.encryptor().finalize()
    return base64.b64encode(enc).decode("ascii")


def build_navigate_params(rwid: str, wjid: str, yhdm: str, xnxq: str,
                           wjmxdx: str = "", pjlxid: str = "", pjfs: str = "1",
                           xn: str = "", xq: str = "") -> str:
    """
    Build AES-encrypted jsonobj for evaluation form navigation.

    Args:
        rwid:  Evaluation task record ID (from list_courses)
        wjid:  Evaluation activity ID (from list_courses)
        yhdm:  User ID (student ID)
        xnxq:  Semester code, e.g. "2025-20262"
        wjmxdx: Evaluation target code (usually same as rwid)
        pjlxid: Evaluation type ID (usually "1" for student-evaluate-course)
        pjfs:   Evaluation mode ("1" = score-based)
        xn:     Academic year (auto-parsed from xnxq if empty)
        xq:     Semester (auto-parsed from xnxq if empty)
    """
    if not xn and not xq and len(xnxq) >= 9:
        xn = xnxq[:9]   # "2025-2026"
        xq = xnxq[-1]   # "2"
    if not wjmxdx:
        wjmxdx = rwid

    params = {
        "rwid":   rwid,
        "wjid":   wjid,
        "pjrdm":  yhdm,
        "xn":     xn,
        "xq":     xq,
        "xnxq":   xnxq,
        "pjlxid": pjlxid or "1",
        "pjfs":   pjfs,
    }
    return aes_encrypt(params)


# ---------------------------------------------------------------------------
# Course listing
# ---------------------------------------------------------------------------

def list_courses(sess, yhdm: str, wjid: str = "", xnxq: str = "2025-20262",
                 task_rwid: str = "") -> list[dict]:
    """
    List all evaluation courses for a semester and task.

    Returns list of dicts with keys:
      kcdm, kcmc, kclx, pjrdm, pjrxm, pjsx, pjzt, rwh, sxz, wjid, yhdm, zsx,
      kkyxdm, lsjgdm, sfhkpj, sfyp, wjstid, wjstmc

    Filter by status:
      pjzt == "2" → 已保存 (saved, already done)
      pjzt == "1" → 待评价 (pending)
      pjzt == "0" → 未开始

    Args:
        sess:       requests.Session
        yhdm:       Student ID
        wjid:       Activity ID (optional, can be empty if task_rwid provided)
        xnxq:       Semester code
        task_rwid:  Task record ID (optional — auto-discovers if not provided)
    """
    # Auto-discover task rwid if not given
    if not task_rwid:
        tasks = list_tasks(sess, xnxq)
        if tasks:
            task_rwid = tasks[0]["rwid"]
            wjid = tasks[0].get("firstwjid") or wjid

    params = {
        "pjrdm": yhdm,
        "wjid":  wjid or "",
        "xnxq":  xnxq,
        "pageNum":  1,
        "pageSize": 100,
    }
    if task_rwid:
        params["rwid"] = task_rwid

    r = sess.get(f"{BASE}/personnelEvaluation/listEcaluationRalationshipEnriry", params=params)
    r.raise_for_status()
    data = r.json()
    result = data.get("result", {})
    if isinstance(result, dict):
        return result.get("list", [])
    return []


def get_user_id(sess) -> str:
    """
    Return the current user's student ID (yhdm) from the TIS session.
    Makes a lightweight /user/me API call.
    """
    r = sess.get(f"{BASE}/user/me")
    r.raise_for_status()
    return r.json().get("yhdm", "")


def list_tasks(sess, xnxq: str = "2025-20262") -> list[dict]:
    """
    List all evaluation tasks for a semester.

    Returns list of dicts with keys:
      rwid, rwmc, rwxnxq, xnxqmc, rwpjxs, pjsl, ypsl, firstwjid, sfyp

    Use firstwjid as the wjid for list_courses().
    """
    params = {
        "xnxq":    xnxq,
        "pageNum": 1,
        "pageSize": 10,
    }
    r = sess.get(f"{BASE}/personnelEvaluation/listObtainPersonnelEvaluationTasks", params=params)
    r.raise_for_status()
    data = r.json()
    result = data.get("result", {})
    if isinstance(result, dict):
        return result.get("list", [])
    return []


# ---------------------------------------------------------------------------
# Playwright helpers
# ---------------------------------------------------------------------------

def _get_playwright_session(sess) -> tuple:
    """
    Create a Playwright browser context authenticated with TIS session cookies.
    Returns (page, browser, context).
    Caller must browser.close() when done.
    """
    from pathlib import Path as _Path
    _SKILL = str(_Path(__file__).resolve().parent.parent.parent.parent)
    auth = TISAuth(skill_dir=_SKILL)
    auth.refresh()
    raw = auth.load()

    from playwright.sync_api import sync_playwright
    p = sync_playwright().start()
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    for name, value in raw.items():
        ctx.add_cookies([{
            "name": name, "value": value,
            "domain": "tis.sustech.edu.cn", "path": "/"
        }])
    page = ctx.new_page()
    return page, browser, p


def _click_all_10(page) -> int:
    """
    Click div.grid containing '10' for every question group on the form.
    Returns number of questions answered.
    """
    n = page.evaluate("""() => {
        const allGrids = Array.from(document.querySelectorAll('div.grid'));
        // Group grids by question (new group when we see '不同意' in ancestor)
        const groups = [];
        let currentGroup = [];
        for (const grid of allGrids) {
            let parent = grid.parentElement;
            let hasDisagree = false;
            let depth = 0;
            while (parent && depth < 5) {
                if (parent.innerText && parent.innerText.includes('不同意')) {
                    hasDisagree = true;
                    break;
                }
                parent = parent.parentElement;
                depth++;
            }
            if (hasDisagree && currentGroup.length > 0) {
                groups.push(currentGroup);
                currentGroup = [];
            }
            currentGroup.push(grid);
        }
        if (currentGroup.length > 0) groups.push(currentGroup);

        let clicked = 0;
        for (const group of groups) {
            for (const grid of group) {
                if (grid.innerText.trim() === '10') {
                    grid.click();
                    clicked++;
                    break;
                }
            }
        }
        return clicked;
    }""")
    return int(n)


# ---------------------------------------------------------------------------
# Main automation functions
# ---------------------------------------------------------------------------

def auto_fill(sess, yhdm: str = None, xnxq: str = "2025-20262",
              courses: Optional[list[str]] = None,
              score: int = 10,
              dry_run: bool = False) -> dict:
    """
    Auto-fill and save all pending evaluations for a semester.

    Args:
        sess:   requests.Session with TIS auth
        yhdm:   Student ID. Auto-detected from session if omitted.
        xnxq:   Semester code (e.g. "2025-20262")
        courses: Optional list of course codes/names to process.
                 If None, processes all "待评价" (lsjgzt=0) courses.
        score:  Numeric score to assign to all scale questions (default 10).
        dry_run: If True, only list courses without saving.

    Returns:
        Dict with keys: total, saved, skipped, errors
    """
    from playwright.sync_api import sync_playwright
    from sustech_survival.sso import TISAuth
    from pathlib import Path as _Path

    _SKILL = str(_Path(__file__).resolve().parent.parent.parent.parent)
    auth = TISAuth(skill_dir=_SKILL)
    if not yhdm:
        yhdm = get_user_id(sess)
        if not yhdm:
            return {"total": 0, "saved": 0, "skipped": 0,
                    "errors": ["Could not auto-detect student ID. Pass yhdm explicitly."]}

    auth = TISAuth(skill_dir=_SKILL)
    auth.refresh()
    raw = auth.load()

    # Get all tasks for the semester
    tasks = list_tasks(sess, xnxq)
    if not tasks:
        return {"total": 0, "saved": 0, "skipped": 0, "errors": ["No evaluation tasks found"]}

    # Collect all pending courses across all tasks
    all_pending = []
    for task in tasks:
        task_rwid = task.get("rwid", "")
        task_wjid  = task.get("firstwjid", "")
        task_name  = task.get("rwmc", task_rwid[:8])
        task_courses = list_courses(sess, yhdm, task_wjid, xnxq, task_rwid)
        pending = [c for c in task_courses if str(c.get("lsjgzt", "")) == "0"]
        for c in pending:
            c["_task_rwid"] = task_rwid
            c["_task_wjid"]  = task_wjid
            c["_task_name"]  = task_name
        all_pending.extend(pending)

    # Filter by course list if provided
    if courses:
        all_pending = [
            c for c in all_pending
            if c.get("kcdm", "").upper() in [x.upper() for x in courses]
            or c.get("kcmc", "").upper() in [x.upper() for x in courses]
        ]

    results = {"total": len(all_pending), "saved": 0, "skipped": 0, "errors": []}

    if not all_pending:
        results["errors"].append("No pending evaluations found")
        return results

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        for name, value in raw.items():
            ctx.add_cookies([{"name": name, "value": value,
                               "domain": "tis.sustech.edu.cn", "path": "/"}])
        page = ctx.new_page()
        captured = {}

        def on_request(req):
            if 'submitSaveEvaluation' in req.url:
                captured['post'] = req.post_data

        page.on("request", on_request)

        for c in all_pending:
            kcmc   = c.get("kcmc", "?")
            kcdm   = c.get("kcdm", "?")
            rwh    = c.get("rwh", "")
            wjid   = c.get("_task_wjid", "")
            xnxq_c = c.get("xnxq", xnxq)

            print(f"[{'DRY-RUN' if dry_run else 'SAVE'}] {kcmc} ({kcdm}) — {c.get('_task_name', '?')}")

            if dry_run:
                results["skipped"] += 1
                continue

            try:
                # Navigate to object page for this task
                page.goto(
                    f"{BASE}/studentAssess/studentEvaluationObjectPage"
                    f"?yhdm={yhdm}&wjid={wjid}&sfyp=0&xnxq={xnxq}",
                    wait_until="commit", timeout=30000,
                )
                page.wait_for_timeout(4000)

                # Click 查询
                qbtn = page.query_selector("button:has-text('查询')")
                if qbtn:
                    qbtn.click()
                    for _ in range(10):
                        page.wait_for_timeout(1000)
                        if "去评价" in page.inner_text("body"):
                            break

                # Find the matching 去评价 button by course name in row
                btns = page.query_selector_all("button:has-text('去评价')")
                target_btn = None
                for b in btns:
                    row_text = b.evaluate("""
                        el => {
                            let row = el.closest('tr');
                            return row ? row.innerText : '';
                        }
                    """)
                    if kcdm.upper() in row_text.upper() or kcmc.upper() in row_text.upper():
                        target_btn = b
                        break

                if not target_btn:
                    target_btn = btns[0] if btns else None

                if not target_btn:
                    print(f"  WARNING: No 去评价 button found for {kcmc}")
                    results["errors"].append(f"No button for {kcmc}")
                    results["skipped"] += 1
                    continue

                target_btn.click()
                page.wait_for_timeout(6000)

                # Auto-score all questions
                n_answered = _click_all_10(page)
                print(f"  Answered {n_answered} questions with score={score}")
                page.wait_for_timeout(300)

                # Save
                save_btn = page.query_selector("button:has-text('保存')")
                if save_btn:
                    save_btn.click()
                    page.wait_for_timeout(3000)

                if captured.get('post'):
                    body = json.loads(captured['post'])
                    for pjjg in body.get('pjjglist', []):
                        answered = sum(1 for q in pjjg['pjxxlist'] if q.get('xxdalist'))
                        total = len(pjjg['pjxxlist'])
                        print(f"  Saved: {answered}/{total} questions")
                    captured.clear()

                results["saved"] += 1

            except Exception as e:
                print(f"  ERROR: {e}")
                results["errors"].append(f"{kcmc}: {e}")
                results["skipped"] += 1

        browser.close()

    return results


# Alias for save_all
def save_all(sess, yhdm: str, xnxq: str = "2025-20262",
             courses: Optional[list[str]] = None,
             score: int = 10) -> dict:
    """Alias for auto_fill with dry_run=False."""
    return auto_fill(sess, yhdm, xnxq, courses, score, dry_run=False)
