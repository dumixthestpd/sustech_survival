"""
TIS 评教 (Teaching Evaluation) automation.

Workflow:
  1. Authenticate via SSO layer
  2. List pending evaluation tasks for a semester
  3. For each course with "待评价" status:
     a. Navigate to evaluation form (Playwright)
     b. Auto-score all numeric scale questions (default: max score)
     c. Auto-fill text questions with default "很好"
     d. Save (not submit) — leaves lsjgzt=3 so user can review/edit later
  4. Support multi-page forms (click 下一页 until disabled)
  5. Class-based API: Evaluation + EvaluationSession for full control

Usage (functional API):
  from sustech_survival.sso import TISAuth
  from sustech_survival.tis.eval import auto_fill

  auth = TISAuth()
  auth.refresh()
  raw = auth.load()
  sess = requests.Session()
  auth._apply_cookies(sess, raw)
  auto_fill(sess)  # auto-detects yhdm, all pending courses
  auto_fill(sess, courses=["CAD与工程制图"], score=10)
  auto_fill(sess, dry_run=True)

Usage (class-based API):
  from sustech_survival.tis.eval import EvaluationSession

  session = EvaluationSession()
  for eval_obj in session.list_pending(yhdm="12413021"):
      eval_obj.load()           # extract questions from form
      eval_obj.autofill(score=10)
      eval_obj.tweak(q0="great teacher", q3=7)
      eval_obj.answer(2, "needs improvement")
      eval_obj.save()
"""

from __future__ import annotations

import base64
import json as _json
import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from sustech_survival.sso import TISAuth

BASE = TISAuth.BASE_URL

__all__ = [
    # New class-based API
    "Evaluation", "EvaluationSession", "QuestionType", "Question",
    # Old functional API
    "auto_fill", "save_all", "list_courses", "list_tasks", "get_user_id",
    "build_navigate_params",
]


# -----------------------------------------------------------------------
# AES encryption for form navigation
# -----------------------------------------------------------------------

AES_KEY = b"inco_NKDpJXT_12$"
AES_IV  = b"INCO_16_NKDpJXT#"

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import padding as _pad
    from cryptography.hazmat.backends import default_backend
    _HAS_AES = True
except ImportError:
    _HAS_AES = False


def aes_encrypt(data: dict) -> str:
    """Return base64-encoded AES/CBC/PKCS7 ciphertext of a dict."""
    if not _HAS_AES:
        raise RuntimeError("pip install cryptography")
    plaintext = _json.dumps(data, ensure_ascii=False).encode("utf-8")
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
        xn = xnxq[:9]
        xq = xnxq[-1]
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


# -----------------------------------------------------------------------
# REST helpers
# -----------------------------------------------------------------------

def list_courses(sess, yhdm: str, wjid: str = "", xnxq: str = "2025-20262",
                 task_rwid: str = "") -> list[dict]:
    """
    List all evaluation courses for a semester and task.

    Returns list of dicts with keys:
      kcdm, kcmc, kclx, pjrdm, pjrxm, pjsx, pjzt, rwh, sxz, wjid, yhdm, zsx,
      kkyxdm, lsjgdm, sfhkpj, sfyp, wjstid, wjstmc

    Filter by status (lsjgzt):
      "0" → 待评价 (pending)
      "3" → 已保存 (saved, already done)

    Args:
        sess:       requests.Session
        yhdm:       Student ID
        wjid:       Activity ID (optional, can be empty if task_rwid provided)
        xnxq:       Semester code
        task_rwid:  Task record ID (optional — auto-discovers if not provided)
    """
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
    """Return the current user's student ID (yhdm) from the TIS session."""
    r = sess.get(f"{BASE}/user/me")
    r.raise_for_status()
    return r.json().get("yhdm", "")


def list_tasks(sess, xnxq: str = "2025-20262") -> list[dict]:
    """
    List all evaluation tasks for a semester.

    Returns list of dicts with keys:
      rwid, rwmc, rwxnxq, xnxqmc, rwpjxs, pjsl, ypsl, firstwjid, sfyp
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


# -----------------------------------------------------------------------
# Playwright helpers
# -----------------------------------------------------------------------

def _get_playwright_session(sess) -> tuple:
    """
    Create a Playwright browser context authenticated with TIS session cookies.
    Returns (page, browser, playwright).
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
        ctx.add_cookies([{"name": name, "value": value,
                          "domain": "tis.sustech.edu.cn", "path": "/"}])
    page = ctx.new_page()
    return page, browser, p


def _click_all_10(page) -> int:
    """
    Click the '10' option for every rating question on the current page.
    Uses the ME102 form structure: each question is one .ivu-form-item,
    each containing 11 .grid elements (0-10).
    Returns number of questions answered.
    """
    n = page.evaluate("""() => {
        const formItems = Array.from(document.querySelectorAll('.ivu-form-item'));
        let clicked = 0;
        for (const fi of formItems) {
            const grids = Array.from(fi.querySelectorAll('.grid'));
            // Find the grid with text '10'
            for (const g of grids) {
                if (g.innerText.trim() === '10') {
                    g.click();
                    clicked++;
                    break;
                }
            }
        }
        return clicked;
    }""")
    return int(n)


# -----------------------------------------------------------------------
# Question type enum and model
# -----------------------------------------------------------------------

class QuestionType(Enum):
    RATING  = "rating"   # 1–10 Likert scale (div.grid / radio)
    TEXT    = "text"     # fill-in-blank / free-text (textarea / input)
    CHOICE  = "choice"   # multiple-choice (radio buttons, not grid)
    UNKNOWN = "unknown"


@dataclass
class Question:
    """
    A single question on an evaluation form.

    Attributes
    ----------
    idx : int
        0-based position on the form (visible order).
    qid : str
        Unique question record ID (wjstid from the form DOM).
    text : str
        Question text.
    qtype : QuestionType
        Detected question type.
    answer : Any
        The answer to submit:
          RATING → int (1-10)
          TEXT   → str (free text)
          CHOICE → str (selected option)
    answered : bool
        Whether this question has been answered.
    page : int
        1-based page number where this question appears.
    options : list[str]
        Available options (e.g. ["1",…,"10"] for rating; [] for text).
    """
    idx: int
    qid: str
    text: str
    qtype: QuestionType = QuestionType.UNKNOWN
    answer: Optional[object] = None
    answered: bool = False
    page: int = 1
    options: list[str] = field(default_factory=list)

    def fill(self, value: object) -> None:
        """Set the answer for this question."""
        self.answer = value
        self.answered = True

    def __repr__(self) -> str:
        return (f"<Q{self.idx+1} [{self.qtype.value}] "
                f"{self.text[:40]!r} → {self.answer!r}>")


# -----------------------------------------------------------------------
# JavaScript question extraction
# ── JavaScript question extraction ──────────────────────────────────────────

_EXTRACT_QUESTIONS_JS = r"""
() => {
    const results = [];
    const formItems = Array.from(document.querySelectorAll('.ivu-form-item'));

    for (let fi = 0; fi < formItems.length; fi++) {
        const formItem = formItems[fi];

        // Get question text:
        // 1. Try: sibling element BEFORE the form-item within .dft-option-m
        let questionText = '';
        const dft = formItem.closest('.dft-option-m');
        if (dft) {
            const children = Array.from(dft.querySelectorAll(':scope > *'));
            for (const child of children) {
                if (child === formItem) break;
                const txt = child.innerText.trim();
                if (txt && txt.length > 10 && txt.length < 500) {
                    questionText = txt;
                    break;
                }
            }
            // Fallback: previousElementSiblings of formItem within dft
            if (!questionText) {
                let prev = formItem.previousElementSibling;
                for (let d = 0; d < 5 && prev; d++) {
                    const txt = prev.innerText.trim();
                    if (txt && txt.length > 10) { questionText = txt; break; }
                    prev = prev.previousElementSibling;
                }
            }
        }
        // 2. Try: text node that is a direct child of .ivu-form-item
        if (!questionText) {
            for (let cn = 0; cn < formItem.childNodes.length; cn++) {
                const node = formItem.childNodes[cn];
                if (node.nodeType === Node.TEXT_NODE) {
                    const txt = node.textContent.trim();
                    if (txt && txt.length > 5 && txt.length < 500) {
                        questionText = txt;
                        break;
                    }
                }
            }
        }

        const allGrids = Array.from(formItem.querySelectorAll('.grid'));
        const options = allGrids.map(g => g.innerText.trim()).filter(t => t !== '');
        const qid = formItem.getAttribute('data-wjstid') || String(fi);

        if (options.length > 0) {
            results.push({
                qid,
                text: questionText || ('Question ' + (fi + 1)),
                options,
                isRating: options.every(o => /^\d+$/.test(o)),
                isText: false,
                _count: options.length,
            });
        }

        // Text questions within this form-item
        for (const ta of Array.from(formItem.querySelectorAll('textarea'))) {
            const qid2 = ta.getAttribute('data-wjstid') || ta.getAttribute('name') || String(results.length + 1000);
            results.push({ qid: qid2, text: questionText || 'Text Q', options: [], isRating: false, isText: true, _count: 1 });
        }
    }

    // Text areas outside the rating grid structure
    for (const ta of Array.from(document.querySelectorAll('textarea, input[type=text]'))) {
        if (!ta.closest('.ivu-form-item')) {
            results.push({
                qid: ta.getAttribute('data-wjstid') || String(results.length + 2000),
                text: ta.getAttribute('placeholder') || 'Text',
                options: [], isRating: false, isText: true, _count: 1,
            });
        }
    }

    return results;
}
"""


# -----------------------------------------------------------------------
# Evaluation class
# -----------------------------------------------------------------------

class Evaluation:
    """
    One course evaluation form.  Tracks all questions and their answers.

    Parameters
    ----------
    course_code : str
        Course code, e.g. "MSE213".
    course_name : str
        Course name in Chinese.
    task_type : str
        Task type label, e.g. "理论类".
    wjid : str
        Activity ID for this evaluation task.
    jgwid : str
        Organization/workgroup ID (from task).
    xnxq : str
        Semester code, e.g. "2025-2026-1".
    rwh : str
        Record ID for this evaluation instance.
    page, browser : playwright objects
        Set by ``EvaluationSession.open()``.
    questions : list[Question]
        Built by ``load()``.
    """

    DEFAULT_TEXT_ANSWER = "很好"

    def __init__(
        self,
        course_code: str,
        course_name: str,
        task_type: str,
        wjid: str,
        jgwid: str,
        xnxq: str,
        rwh: str,
        questionnaire_uuid: str = "",
        theme_uuid: str = "",
        task_rwid: str = "",
        page: Optional[object] = None,
        browser: Optional[object] = None,
    ):
        self.course_code  = course_code
        self.course_name  = course_name
        self.task_type    = task_type
        self.wjid         = wjid
        self.jgwid        = jgwid
        self.xnxq         = xnxq
        self.rwh          = rwh
        self.questionnaire_uuid = questionnaire_uuid
        self.theme_uuid   = theme_uuid
        self.task_rwid    = task_rwid
        self._page: Optional[object] = page
        self._browser: Optional[object] = browser
        self.questions: list[Question] = []

    def load(self, timeout: int = 15000) -> "Evaluation":
        """
        Navigate to this course's evaluation form and extract all questions.

        Handles multi-page forms by clicking "下一页" until disabled.
        Sets ``self.questions`` with type, text, and options for each question.

        Returns self.
        """
        page = self._page
        assert page is not None, "Evaluation not attached to a browser page"
        self.questions = []
        page_idx = 1
        seen_qids: set[str] = set()

        while True:
            page.wait_for_timeout(2000)
            page_questions: list[dict] = page.evaluate(_EXTRACT_QUESTIONS_JS)

            for pq in page_questions:
                qid = pq["qid"]
                if qid in seen_qids:
                    continue
                seen_qids.add(qid)
                opts = pq.get("options", [])
                is_rating = pq.get("isRating", False)
                is_text = pq.get("isText", False)
                if is_rating or (opts and all(o.isdigit() for o in opts)):
                    qtype = QuestionType.RATING
                elif is_text:
                    qtype = QuestionType.TEXT
                elif opts:
                    qtype = QuestionType.CHOICE
                else:
                    qtype = QuestionType.UNKNOWN

                self.questions.append(Question(
                    idx=len(self.questions),
                    qid=qid,
                    text=pq.get("text", ""),
                    qtype=qtype,
                    page=page_idx,
                    options=opts,
                ))

            next_btn = page.query_selector("button:has-text('下一页')")
            disabled = (
                next_btn is not None and
                "is-disabled" in (next_btn.get_attribute("class") or "")
            )
            if next_btn and not disabled:
                next_btn.click()
                page.wait_for_timeout(3000)
                page_idx += 1
            else:
                break

        return self

    def autofill(self, score: int = 10, text: str | None = None) -> "Evaluation":
        """
        Auto-fill all auto-detectable questions with sensible defaults.

        Parameters
        ----------
        score : int
            Score to assign to all RATING questions (default 10).
        text : str
            Text to assign to all TEXT questions.
            None → use DEFAULT_TEXT_ANSWER ("很好").

        Returns self for chaining.
        """
        text = text or self.DEFAULT_TEXT_ANSWER
        for q in self.questions:
            if q.qtype == QuestionType.RATING:
                q.fill(score)
            elif q.qtype == QuestionType.TEXT:
                q.fill(text)
        return self

    def answer(self, idx: int, value: object) -> "Evaluation":
        """
        Set the answer for question at 0-based index ``idx``.

        Raises IndexError if out of range.
        Raises TypeError if value type doesn't match question type
        (e.g. str for a RATING question).
        Returns self for chaining.
        """
        q = self.questions[idx]
        if q.qtype == QuestionType.RATING and not isinstance(value, int):
            raise TypeError(
                f"Q{idx+1} is RATING (1-10) — pass an int, not {type(value).__name__!r}. "
                f"Use tweak(q{idx}=<int>) or autofill(score=<int>)."
            )
        self.questions[idx].fill(value)
        return self

    def tweak(self, **kwargs: object) -> "Evaluation":
        """
        Override answers by question index (0-based).

        Example::

            eval.tweak(q0="terrible professor", q3=8)

        Unknown keys are silently ignored.
        Raises TypeError if a value type doesn't match question type.
        Returns self for chaining.
        """
        for key, value in kwargs.items():
            if key.startswith("q"):
                try:
                    self.answer(int(key[1:]), value)
                except (ValueError, IndexError):
                    pass
        return self

    def save(self) -> "Evaluation":
        """
        Submit all collected answers to TIS via fetch.

        The form must have been loaded via ``load()`` first.

        Returns self.
        """
        page = self._page
        assert page is not None, "Form not loaded"
        body = self._build_save_body()
        page.evaluate(
            f"""
            fetch('{BASE}/personnelEvaluation/submitSaveEvaluation', {{
                method: 'POST',
                headers: {{
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest'
                }},
                body: {self._json_dumps(body)}
            }}).then(r => r.json()).then(d => {{ window._save_result = d; }})
            """
        )
        page.wait_for_timeout(3000)
        return self

    def _build_save_body(self) -> dict:
        """Build the save request body from collected answers."""
        answered = [q for q in self.questions if q.answered]
        if not answered:
            raise ValueError("No questions answered — call autofill() or answer() first")

        pjxxlist = []
        for q in answered:
            if q.qtype == QuestionType.RATING:
                xxdalist = [{"dalx": 1, "daz": str(q.answer)}]
                dafen = str(q.answer)
            elif q.qtype == QuestionType.TEXT:
                xxdalist = [{"dalx": 2, "daz": str(q.answer)}]
                dafen = "0"
            elif q.qtype == QuestionType.CHOICE:
                xxdalist = [{"dalx": 3, "daz": str(q.answer)}]
                dafen = "0"
            else:
                xxdalist = [{"dalx": 0, "daz": str(q.answer)}]
                dafen = "0"

            pjxxlist.append({
                "wjstid": q.qid,
                "wjstmc": q.text,
                "xxdalist": xxdalist,
                "dafen": dafen,
            })

        return {
            "xnxq": self.xnxq,
            "wjid": self.wjid,
            "jgwid": self.jgwid,
            "sfyp": "0",
            "questionniareUuid": self.questionnaire_uuid,
            "questionnaireThemeUuid": self.theme_uuid,
            "questions": [{
                "wjid": self.wjid,
                "jgwid": self.jgwid,
                "wjmxid": self.rwh,
                "pjjglist": [{
                    "kcmc": self.course_name,
                    "kcdm": self.course_code,
                    "pjxxlist": pjxxlist,
                }],
            }],
        }

    @staticmethod
    def _json_dumps(obj) -> str:
        return _json.dumps(obj, ensure_ascii=False, separators=(",", ":"))

    def __repr__(self) -> str:
        n = len(self.questions)
        answered = sum(1 for q in self.questions if q.answered)
        return (f"<Evaluation {self.course_code} {self.course_name!r} "
                f"({answered}/{n} answered)>")


# -----------------------------------------------------------------------
# EvaluationSession
# -----------------------------------------------------------------------

class EvaluationSession:
    """
    Manage the TIS evaluation workflow for a semester.

    Parameters
    ----------
    skill_dir : str
        Path to skill root. ``None`` → auto-detect.
    auth : TISAuth, optional
        Pre-configured auth object. Created if omitted.
    """

    def __init__(self, skill_dir: str | None = None, auth: TISAuth | None = None):
        if skill_dir is None:
            from pathlib import Path
            skill_dir = str(Path(__file__).resolve().parent.parent.parent.parent)
        self._skill_dir = skill_dir
        if auth is None:
            auth = TISAuth(skill_dir=skill_dir)
            auth.refresh()
        self._auth = auth
        self._raw_cookies: Optional[dict] = None

    @property
    def cookies(self) -> dict:
        if self._raw_cookies is None:
            self._raw_cookies = self._auth.load()
        return self._raw_cookies

    def _new_page(self, wjid: str, yhdm: str, xnxq: str, timeout: int = 15000):
        raw = self.cookies
        from playwright.sync_api import sync_playwright
        p = sync_playwright().start()
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        for name, value in raw.items():
            ctx.add_cookies([{"name": name, "value": value,
                              "domain": "tis.sustech.edu.cn", "path": "/"}])
        page = ctx.new_page()
        url = (f"{BASE}/studentAssess/studentEvaluationObjectPage"
               f"?yhdm={yhdm}&wjid={wjid}&sfyp=0&xnxq={xnxq}")
        page.goto(url, wait_until="commit", timeout=timeout)
        page.wait_for_timeout(4000)
        qbtn = page.query_selector("button:has-text('查询')")
        if qbtn:
            qbtn.click()
            page.wait_for_timeout(5000)
        return page, browser, p

    def _navigate_to_form(self, page, browser, pw, kcmc: str, timeout: int = 15000) -> bool:
        for _ in range(8):
            rows = page.query_selector_all("table tbody tr")
            if rows:
                break
            page.wait_for_timeout(1000)

        btns = page.query_selector_all("button:has-text('去评价')")
        target = None
        for b in btns:
            row_text = b.evaluate(
                "el => { let r = el.closest('tr'); return r ? r.innerText : ''; }"
            )
            if kcmc.upper() in row_text.upper():
                target = b
                break
        target = target or (btns[0] if btns else None)
        if not target:
            return False
        target.click()
        page.wait_for_timeout(timeout)
        return True

    def list_all(self, yhdm: str, xnxq: str = "2025-2026-1",
                 status_filter: str = "all") -> list[dict]:
        """
        List all evaluation courses for this semester.

        Returns list of dicts with keys:
          course_code, course_name, task_type, wjid, jgwid, xnxq,
          rwh, questionnaire_uuid, theme_uuid, task_rwid, status
        """
        sess = self._make_requests_session()
        tasks = list_tasks(sess, xnxq)
        courses: list[dict] = []

        for task in tasks:
            task_rwid = task.get("rwid", "")
            task_wjid = task.get("firstwjid", "")
            task_type = task.get("rwmc", "")
            page, browser, pw = self._new_page(task_wjid, yhdm, xnxq)

            rows = page.query_selector_all("table tbody tr")
            for row in rows:
                tds = row.query_selector_all("td")
                if len(tds) < 6:
                    continue
                txts = [td.inner_text().strip() for td in tds]
                if not txts[0] or txts[0] == "暂无数据":
                    continue

                status = txts[-2] if len(txts) >= 2 else ""
                btn = row.query_selector("button")
                btn_text = btn.inner_text().strip() if btn else ""

                course = {
                    "course_name":  txts[1] if len(txts) > 1 else "",
                    "course_code":  "",
                    "task_type":    task_type,
                    "wjid":         task_wjid,
                    "jgwid":        "",
                    "xnxq":         xnxq,
                    "rwh":          "",
                    "questionnaire_uuid": "",
                    "theme_uuid":   "",
                    "task_rwid":    task_rwid,
                    "status":       status,
                    "btn_text":     btn_text,
                    "row_text":     " | ".join(txts),
                }

                if (status_filter == "all" or
                    status_filter == "pending" and "去评价" in btn_text or
                    status_filter == "saved" and "已完成" in status):
                    courses.append(course)

            browser.close()
            pw.stop()

        return courses

    def list_pending(self, yhdm: str, xnxq: str = "2025-2026-1") -> list[dict]:
        """Shortcut: list_all with status_filter='pending'."""
        return self.list_all(yhdm, xnxq, status_filter="pending")

    def open(self, course_info: dict) -> Evaluation:
        """
        Open the evaluation form for a course and return an Evaluation object.

        Call ``eval.load()`` next to extract questions, then
        ``eval.autofill()``, ``eval.tweak()``, ``eval.save()``.
        """
        yhdm   = course_info.get("yhdm", "12413021")
        xnxq   = course_info.get("xnxq", "2025-2026-1")
        wjid   = course_info.get("wjid", "")
        kcmc   = course_info.get("course_name", "")

        page, browser, pw = self._new_page(wjid, yhdm, xnxq)
        self._navigate_to_form(page, browser, pw, kcmc)

        return Evaluation(
            course_code    = course_info.get("course_code", ""),
            course_name    = kcmc,
            task_type      = course_info.get("task_type", ""),
            wjid           = wjid,
            jgwid          = course_info.get("jgwid", ""),
            xnxq           = xnxq,
            rwh            = course_info.get("rwh", ""),
            questionnaire_uuid = course_info.get("questionnaire_uuid", ""),
            theme_uuid     = course_info.get("theme_uuid", ""),
            task_rwid      = course_info.get("task_rwid", ""),
            page           = page,
            browser        = browser,
        )

    def _make_requests_session(self):
        import requests
        raw = self.cookies
        sess = requests.Session()
        sess.headers["User-Agent"] = "Mozilla/5.0"
        sess.headers["X-Requested-With"] = "XMLHttpRequest"
        for name, value in raw.items():
            sess.cookies.set(name, value, domain="tis.sustech.edu.cn", path="/")
        return sess


# -----------------------------------------------------------------------
# auto_fill: updated with multi-page support
# -----------------------------------------------------------------------

def auto_fill(sess, yhdm: str = None, xnxq: str = "2025-20262",
              courses: Optional[list[str]] = None,
              score: int = 10,
              dry_run: bool = False) -> dict:
    """
    Auto-fill and save all pending evaluations for a semester.

    Multi-page aware: fills ALL pages of questions before saving.

    Args:
        sess:     requests.Session with TIS auth
        yhdm:     Student ID. Auto-detected from session if omitted.
        xnxq:     Semester code (e.g. "2025-20262")
        courses:  Optional list of course codes/names to process.
                  If None, processes all "待评价" (lsjgzt=0) courses.
        score:    Numeric score to assign to all scale questions (default 10).
        dry_run:  If True, only list courses without saving.

    Returns:
        Dict with keys: total, saved, skipped, errors
    """
    from playwright.sync_api import sync_playwright
    from pathlib import Path as _Path

    _SKILL = str(_Path(__file__).resolve().parent.parent.parent.parent)
    auth = TISAuth(skill_dir=_SKILL)

    if not yhdm:
        yhdm = get_user_id(sess)
        if not yhdm:
            return {"total": 0, "saved": 0, "skipped": 0,
                    "errors": ["Could not auto-detect student ID. Pass yhdm explicitly."]}

    auth.refresh()
    raw = auth.load()

    tasks = list_tasks(sess, xnxq)
    if not tasks:
        return {"total": 0, "saved": 0, "skipped": 0, "errors": ["No evaluation tasks found"]}

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
            if "submitSaveEvaluation" in req.url:
                captured["post"] = req.post_data

        page.on("request", on_request)

        for c in all_pending:
            kcmc   = c.get("kcmc", "?")
            kcdm   = c.get("kcdm", "?")
            wjid   = c.get("_task_wjid", "")

            print(f"[{'DRY-RUN' if dry_run else 'SAVE'}] {kcmc} ({kcdm}) — {c.get('_task_name', '?')}")

            if dry_run:
                results["skipped"] += 1
                continue

            try:
                page.goto(
                    f"{BASE}/studentAssess/studentEvaluationObjectPage"
                    f"?yhdm={yhdm}&wjid={wjid}&sfyp=0&xnxq={xnxq}",
                    wait_until="commit", timeout=30000,
                )
                page.wait_for_timeout(4000)

                qbtn = page.query_selector("button:has-text('查询')")
                if qbtn:
                    qbtn.click()
                    for _ in range(10):
                        page.wait_for_timeout(1000)
                        if "去评价" in page.inner_text("body"):
                            break

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

                target_btn = target_btn or (btns[0] if btns else None)
                if not target_btn:
                    print(f"  WARNING: No 去评价 button found for {kcmc}")
                    results["errors"].append(f"No button for {kcmc}")
                    results["skipped"] += 1
                    continue

                target_btn.click()
                page.wait_for_timeout(6000)

                # ── Multi-page fill loop ─────────────────────────────────────
                total_answered = 0
                while True:
                    n = _click_all_10(page)
                    total_answered += n

                    next_btn = page.query_selector("button:has-text('下一页')")
                    disabled = next_btn and "is-disabled" in (next_btn.get_attribute("class") or "")
                    if next_btn and not disabled:
                        next_btn.click()
                        page.wait_for_timeout(3000)
                    else:
                        break

                print(f"  Total answered: {total_answered} questions with score={score}")
                page.wait_for_timeout(300)

                save_btn = page.query_selector("button:has-text('保存')")
                if save_btn:
                    save_btn.click()
                    page.wait_for_timeout(3000)

                if captured.get("post"):
                    body = _json.loads(captured["post"])
                    for pjjg in body.get("pjjglist", []):
                        answered = sum(1 for q in pjjg["pjxxlist"] if q.get("xxdalist"))
                        total_q = len(pjjg["pjxxlist"])
                        print(f"  Saved: {answered}/{total_q} questions")
                    captured.clear()

                results["saved"] += 1

            except Exception as e:
                print(f"  ERROR: {e}")
                results["errors"].append(f"{kcmc}: {e}")
                results["skipped"] += 1

        browser.close()

    return results


def save_all(sess, yhdm: str, xnxq: str = "2025-20262",
             courses: Optional[list[str]] = None,
             score: int = 10) -> dict:
    """Alias for auto_fill with dry_run=False."""
    return auto_fill(sess, yhdm, xnxq, courses, score, dry_run=False)
