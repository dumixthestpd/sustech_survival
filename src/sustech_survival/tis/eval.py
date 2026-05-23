"""
TIS 评教 (Teaching Evaluation) automation.

Usage::

    from sustech_survival.tis import TISAuthEval

    auth = TISAuthEval().login()
    for ev in auth.evaluations(xnxq="2025-2026-2"):
        ev.load()
        ev.questions(0).answer("bad professor")
        ev.questions(1).answer(8)
        ev.save()

    # Or bulk fill
    auth.auto_fill(xnxq="2025-2026-2", courses=["MSE213"], score=10)
"""

from __future__ import annotations

import json as _json
from enum import Enum
from typing import Optional

from ..sso import TISAuth

BASE = TISAuth.BASE_URL

__all__ = [
    "TISAuthEval",
    "Evaluation",
    "Question",
    "RatingQuestion",
    "TextQuestion",
    "QuestionType",
    "auto_fill",
]


# -----------------------------------------------------------------------
# Question type enum
# -----------------------------------------------------------------------

class QuestionType(Enum):
    RATING = "rating"
    TEXT = "text"
    CHOICE = "choice"
    UNKNOWN = "unknown"


# -----------------------------------------------------------------------
# Question classes
# -----------------------------------------------------------------------

class Question:
    """
    Represents one question in an evaluation form.

    Obtain via ``ev.questions(idx)``, then call ``.answer()``::

        ev.questions(0).answer(8)
        ev.questions(1).answer("great course")
    """

    def __init__(
        self,
        ev: Evaluation,
        idx: int,
        qid: str,
        text: str,
        qtype: QuestionType,
        options: list[str],
    ):
        self.ev = ev
        self.idx = idx
        self.qid = qid
        self.text = text
        self.type = qtype
        self.options = options

    @property
    def value(self):
        """Current answer value, or None if unanswered."""
        d = self.ev.questions_data[self.idx]
        return d["answer"] if d["answered"] else None

    def answer(self, value) -> Question:
        """Set the answer on the parent Evaluation and return self for chaining."""
        d = self.ev.questions_data[self.idx]
        d["answer"] = value
        d["answered"] = True
        return self

    def __repr__(self):
        return (
            f"<Q{self.idx} [{self.__class__.__name__}] "
            f"'{self.text[:40]}' → {self.value!r}>"
        )


class RatingQuestion(Question):
    """Likert scale question (options 0-10)."""

    def answer(self, value: int) -> Question:
        if not isinstance(value, int):
            raise TypeError(
                f"Q{self.idx} is RatingQuestion — pass an int (0-10), not {type(value).__name__}"
            )
        if not 0 <= value <= 10:
            raise ValueError(f"Q{self.idx} is RatingQuestion — pass 0-10, got {value}")
        return super().answer(value)


class TextQuestion(Question):
    """Free-text / fill-in-blank question."""

    def answer(self, value: str) -> Question:
        if not isinstance(value, str):
            raise TypeError(
                f"Q{self.idx} is TextQuestion — pass a str, not {type(value).__name__}"
            )
        return super().answer(value)


# -----------------------------------------------------------------------
# JavaScript question extraction
# -----------------------------------------------------------------------

_EXTRACT_QUESTIONS_JS = r"""
() => {
    const results = [];
    const formItems = Array.from(document.querySelectorAll('.ivu-form-item'));

    for (let fi = 0; fi < formItems.length; fi++) {
        const formItem = formItems[fi];

        // Find question text: sibling before form-item within .dft-option-m
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
            if (!questionText) {
                let prev = formItem.previousElementSibling;
                for (let d = 0; d < 5 && prev; d++) {
                    const txt = prev.innerText.trim();
                    if (txt && txt.length > 10) { questionText = txt; break; }
                    prev = prev.previousElementSibling;
                }
            }
        }
        // Fallback: text node child of .ivu-form-item
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
            });
        }

        for (const ta of Array.from(formItem.querySelectorAll('textarea'))) {
            const qid2 = ta.getAttribute('data-wjstid') || ta.getAttribute('name') || String(results.length + 1000);
            results.push({ qid: qid2, text: questionText || 'Text Q', options: [], isRating: false, isText: true });
        }
    }

    for (const ta of Array.from(document.querySelectorAll('textarea, input[type=text]'))) {
        if (!ta.closest('.ivu-form-item')) {
            results.push({
                qid: ta.getAttribute('data-wjstid') || String(results.length + 2000),
                text: ta.getAttribute('placeholder') || 'Text',
                options: [], isRating: false, isText: true,
            });
        }
    }

    return results;
}
"""


# -----------------------------------------------------------------------
# Evaluation form object
# -----------------------------------------------------------------------

class Evaluation:
    """
    One course's evaluation form.

    Created by ``TISAuthEval.open_evaluation()`` — do not instantiate directly.

    Usage::

        ev = auth.open_evaluation("CAD", xnxq="2025-2026-2")
        ev.load()
        ev.questions(0).answer("great teacher")
        ev.questions(1).answer(10)
        ev.autofill()        # fills everything else with defaults
        ev.save()
    """

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
        self.course_code = course_code
        self.course_name = course_name
        self.task_type = task_type
        self.wjid = wjid
        self.jgwid = jgwid
        self.xnxq = xnxq
        self.rwh = rwh
        self.questionnaire_uuid = questionnaire_uuid
        self.theme_uuid = theme_uuid
        self.task_rwid = task_rwid
        self._page: Optional[object] = page
        self._browser: Optional[object] = browser
        self.questions_data: list[dict] = []   # raw dicts from JS

    # ---------------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------------

    def questions(self, idx: int) -> Question:
        """
        Return a Question accessor for the question at 0-based index ``idx``.

        Raises IndexError if out of range.
        """
        if idx < 0 or idx >= len(self.questions_data):
            raise IndexError(f"Question index {idx} out of range (0-{len(self.questions_data) - 1})")
        d = self.questions_data[idx]
        qtype = d["type"]
        cls = {
            QuestionType.RATING: RatingQuestion,
            QuestionType.TEXT: TextQuestion,
        }.get(qtype, Question)
        return cls(self, idx, d["qid"], d["text"], qtype, d["options"])

    def answer(self, idx: int, value) -> Evaluation:
        """
        Set answer at 0-based index ``idx``. Validates type automatically.

        Raises IndexError, TypeError, ValueError.
        Returns self for chaining.
        """
        q = self.questions(idx)
        q.answer(value)   # raises on bad type
        return self

    def autofill(self, score: int = 10, text: str = "很好") -> Evaluation:
        """
        Auto-fill all unanswered questions with defaults.

        RATING → ``score`` (int)
        TEXT   → ``text`` (str)
        """
        for i, d in enumerate(self.questions_data):
            if d["answered"]:
                continue
            if d["type"] == QuestionType.RATING:
                self.answer(i, score)
            elif d["type"] == QuestionType.TEXT:
                self.answer(i, text)
        return self

    def load(self, timeout: int = 15000) -> Evaluation:
        """
        Extract all questions from the form (handles multi-page).

        Sets ``self.questions_data`` with type, text, options for each question.
        Returns self.
        """
        page = self._page
        assert page is not None, "Evaluation not attached to a browser page"
        self.questions_data = []
        seen_qids: set[str] = set()

        while True:
            page.wait_for_timeout(2000)
            raw: list[dict] = page.evaluate(_EXTRACT_QUESTIONS_JS)

            for d in raw:
                qid = d["qid"]
                if qid in seen_qids:
                    continue
                seen_qids.add(qid)

                opts = d.get("options", [])
                if d.get("isRating") or (opts and all(o.isdigit() for o in opts)):
                    qtype = QuestionType.RATING
                elif d.get("isText"):
                    qtype = QuestionType.TEXT
                elif opts:
                    qtype = QuestionType.CHOICE
                else:
                    qtype = QuestionType.UNKNOWN

                self.questions_data.append({
                    "qid": qid,
                    "text": d.get("text", ""),
                    "type": qtype,
                    "options": opts,
                    "answer": None,
                    "answered": False,
                })

            # Multi-page: click 下一页 if present and not disabled
            next_btn = page.query_selector("button:has-text('下一页')")
            cls = next_btn.get_attribute("class") if next_btn else ""
            disabled = "is-disabled" in (cls or "")
            if next_btn and not disabled:
                next_btn.click()
                page.wait_for_timeout(3000)
            else:
                break

        return self

    def save(self) -> Evaluation:
        """
        Submit all answers to TIS via fetch().

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

    # ---------------------------------------------------------------------------
    # Internal
    # ---------------------------------------------------------------------------

    def _build_save_body(self) -> dict:
        answered = [q for q in self.questions_data if q["answered"]]
        if not answered:
            raise ValueError("No questions answered — call autofill() or answer() first")

        pjxxlist = []
        for q in answered:
            if q["type"] == QuestionType.RATING:
                xxdalist = [{"dalx": 1, "daz": str(q["answer"])}]
                dafen = str(q["answer"])
            elif q["type"] == QuestionType.TEXT:
                xxdalist = [{"dalx": 2, "daz": str(q["answer"])}]
                dafen = "0"
            elif q["type"] == QuestionType.CHOICE:
                xxdalist = [{"dalx": 3, "daz": str(q["answer"])}]
                dafen = "0"
            else:
                xxdalist = [{"dalx": 0, "daz": str(q["answer"])}]
                dafen = "0"

            pjxxlist.append({
                "wjstid": q["qid"],
                "wjstmc": q["text"],
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

    def __repr__(self):
        n = len(self.questions_data)
        answered = sum(1 for q in self.questions_data if q["answered"])
        return (
            f"<Evaluation {self.course_code} {self.course_name!r} "
            f"[{answered}/{n}]>"
        )


# -----------------------------------------------------------------------
# TISAuthEval — evaluation methods on TISAuth
# -----------------------------------------------------------------------

class TISAuthEval(TISAuth):
    """
    TIS auth + evaluation workflow.

    Inherits all auth methods from TISAuth (login, refresh, load, session).

    Usage::

        auth = TISAuthEval().login()
        for ev in auth.evaluations(xnxq="2025-2026-2"):
            ev.load().autofill().save()
    """

    def evaluations(
        self,
        xnxq: str = "2025-2026-2",
        status: str = "all",
    ) -> list[dict]:
        """
        List evaluation tasks for a semester via REST API.

        API flow (2 steps):
          1. GET /personnelEvaluation/listObtainPersonnelEvaluationTasks
             → 3 category tasks (rwid, firstwjid, rwmc)
          2. For each category: GET /personnelEvaluation/listEcaluationRalationshipEnriry
             with wjid=<firstwjid> + rwid=<task rwid>
             → course list (kcmc, kcdm, lsjgzt, etc.)

        Args:
            xnxq:   Semester code (e.g. "2025-20262" or "2025-2026-2")
            status: "all", "pending" (lsjgzt=0), or "saved" (lsjgzt=3)

        Returns list of course dicts with keys:
            course_name, course_code, teacher, task_type, lsjgzt, status_text,
            wjid, jgwid, xnxq, rwh, questionnaire_uuid, theme_uuid, task_rwid
        """
        # Normalise xnxq — backend accepts "2025-20262" as-is
        xnxq_raw = xnxq  # e.g. "2025-20262"; do NOT strip hyphens
        sess = self.session

        # Step 1: get 3 category tasks
        tasks_resp = sess.get(
            f"{BASE}/personnelEvaluation/listObtainPersonnelEvaluationTasks",
            params={"yhdm": "12413021", "rwmc": "", "sfyp": "0",
                    "pageNum": "1", "pageSize": "20"},
            timeout=15,
        )
        if tasks_resp.status_code != 200:
            raise RuntimeError(f"Task list API returned {tasks_resp.status_code}")
        tasks = tasks_resp.json()["result"]["list"]

        all_courses: list[dict] = []

        # Step 2: per-category course list
        for task in tasks:
            rwid = task["rwid"]          # category task rwid
            firstwjid = task["firstwjid"]  # wjid for course list query
            rwmc = task["rwmc"]          # e.g. "学生评价（理论类 Theoretical courses）"

            # Determine task_type from label
            if "理论" in rwmc:
                task_type = "理论类"
            elif "体育" in rwmc:
                task_type = "体育类"
            elif "实验" in rwmc or "实践" in rwmc:
                task_type = "实验实践类"
            else:
                task_type = rwmc

            courses_resp = sess.get(
                f"{BASE}/personnelEvaluation/listEcaluationRalationshipEnriry",
                params={
                    "pjrdm": "12413021",
                    "wjid": firstwjid,
                    "bpmc": "", "sfyp": "0", "xnxq": xnxq_raw,
                    "pageNum": "1", "pageSize": "50",
                    "zc": "", "xqj": "", "jc": "", "skdd": "",
                    "kkyxdm": "", "bpssyxdm": "", "kcmc": "", "sfcxqbwj": "0",
                    "rwid": rwid,
                    "lsjgzt": "",
                },
                timeout=15,
            )
            data = courses_resp.json()
            if data.get("code") != "200":
                # Skip failed categories (e.g. empty categories)
                continue

            for c in data["result"]["list"]:
                status_text = "已保存" if c.get("lsjgzt") == "3" else "未保存"
                all_courses.append({
                    "course_name": c.get("kcmc", ""),
                    "course_code": c.get("kcdm", ""),
                    "teacher": c.get("bpdm", ""),      # department code = teacher dept
                    "task_type": task_type,
                    "department": c.get("yxmc", ""),    # school name
                    "class_info": c.get("bj", ""),
                    "lsjgzt": c.get("lsjgzt", "0"),
                    "status_text": status_text,
                    "xnxq": xnxq_raw,
                    "wjid": c.get("wjid", ""),
                    "jgwid": c.get("jgwid", ""),
                    "rwh": c.get("rwh", ""),
                    "questionnaire_uuid": c.get("sxz", ""),  # encrypted form id
                    "theme_uuid": "",
                    "task_rwid": rwid,
                })

        # Filter by status
        result: list[dict] = []
        for c in all_courses:
            lsjgzt = c["lsjgzt"]
            if status == "pending" and lsjgzt != "0":
                continue
            if status == "saved" and lsjgzt != "3":
                continue
            result.append(c)

        return result

    def open_evaluation(self, course_name: str, xnxq: str = "2025-2026-2") -> Evaluation:
        """
        Open the evaluation form for a course by name.

        Args:
            course_name: Course name (e.g. "CAD" or "材料力学")
            xnxq: Semester code

        Returns an Evaluation object. Call ``ev.load()`` then ``ev.save()``.
        """
        from playwright.sync_api import sync_playwright

        # Get user ID
        r = self.session.get(f"{BASE}/user/me")
        r.raise_for_status()
        yhdm = r.json().get("yhdm", "")
        if not yhdm:
            raise RuntimeError("Could not determine user ID from TIS session")

        # Find the course in pending list
        pending = self.evaluations(xnxq=xnxq, status="pending")
        target = None
        for c in pending:
            if course_name.upper() in c["course_name"].upper():
                target = c
                break
        if not target:
            raise ValueError(f"Course '{course_name}' not found in pending evaluations")

        # Launch Playwright
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
        raw = self.load()
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        for name, value in raw.items():
            ctx.add_cookies([{"name": name, "value": value,
                              "domain": "tis.sustech.edu.cn", "path": "/"}])
        page = ctx.new_page()

        # Navigate to task page
        url = (
            f"{BASE}/studentAssess/studentEvaluationObjectPage"
            f"?yhdm={yhdm}&wjid={target['wjid']}&sfyp=0&xnxq={xnxq}"
        )
        page.goto(url, wait_until="commit", timeout=30000)
        page.wait_for_timeout(4000)

        # Click 查询 if button present
        qbtn = page.query_selector("button:has-text('查询')")
        if qbtn:
            qbtn.click()
            page.wait_for_timeout(5000)

        # Click the correct 去评价 button
        for _ in range(8):
            rows = page.query_selector_all("table tbody tr")
            if rows:
                break
            page.wait_for_timeout(1000)

        btns = page.query_selector_all("button:has-text('去评价')")
        for b in btns:
            row_text = b.evaluate(
                "el => { let r = el.closest('tr'); return r ? r.innerText : ''; }"
            )
            if course_name.upper() in row_text.upper():
                b.click()
                break
        page.wait_for_timeout(8000)

        ev = Evaluation(
            course_code=target["course_code"],
            course_name=target["course_name"],
            task_type=target["task_type"],
            wjid=target["wjid"],
            jgwid=target["jgwid"],
            xnxq=xnxq,
            rwh=target["rwh"],
            questionnaire_uuid=target["questionnaire_uuid"],
            theme_uuid=target["theme_uuid"],
            task_rwid=target["task_rwid"],
            page=page,
            browser=browser,
        )
        ev._playwright = pw   # keep alive
        return ev

    def auto_fill(
        self,
        xnxq: str = "2025-2026-2",
        courses: Optional[list[str]] = None,
        score: int = 10,
        text: str = "很好",
    ) -> dict:
        """
        Auto-fill (and save) all pending evaluations for a semester.

        Args:
            xnxq:     Semester code
            courses:  Optional list of course names to process. All pending if None.
            score:    Numeric score for RATING questions (default 10)
            text:     Answer for TEXT questions (default "很好")

        Returns dict: {total, saved, skipped, errors}
        """
        from playwright.sync_api import sync_playwright

        pending = self.evaluations(xnxq=xnxq, status="pending")
        if courses:
            pending = [
                c for c in pending
                if c["course_name"].upper() in [x.upper() for x in courses]
                or c["course_code"].upper() in [x.upper() for x in courses]
            ]

        results = {"total": len(pending), "saved": 0, "skipped": 0, "errors": []}

        if not pending:
            results["errors"].append("No pending evaluations found")
            return results

        # Get cookies for Playwright
        raw = self.load()

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(viewport={"width": 1280, "height": 900})
            for name, value in raw.items():
                ctx.add_cookies([{"name": name, "value": value,
                                  "domain": "tis.sustech.edu.cn", "path": "/"}])
            page = ctx.new_page()

            for c in pending:
                kcmc = c["course_name"]
                kcdm = c["course_code"]
                wjid = c["wjid"]

                print(f"[AUTO-FILL] {kcmc} ({kcdm})")

                # Navigate
                r = self.session.get(f"{BASE}/user/me")
                yhdm = r.json().get("yhdm", "")
                page.goto(
                    f"{BASE}/studentAssess/studentEvaluationObjectPage"
                    f"?yhdm={yhdm}&wjid={wjid}&sfyp=0&xnxq={xnxq}",
                    wait_until="commit", timeout=30000,
                )
                page.wait_for_timeout(4000)

                qbtn = page.query_selector("button:has-text('查询')")
                if qbtn:
                    qbtn.click()
                    page.wait_for_timeout(4000)

                # Click 去评价 for this course
                btns = page.query_selector_all("button:has-text('去评价')")
                target_btn = None
                for b in btns:
                    row_text = b.evaluate(
                        "el => { let r = el.closest('tr'); return r ? r.innerText : ''; }"
                    )
                    if kcdm.upper() in row_text.upper() or kcmc.upper() in row_text.upper():
                        target_btn = b
                        break
                if not target_btn:
                    results["errors"].append(f"No button for {kcmc}")
                    results["skipped"] += 1
                    continue

                target_btn.click()
                page.wait_for_timeout(8000)

                # Multi-page fill
                while True:
                    n = page.evaluate("""() => {
                        const formItems = Array.from(document.querySelectorAll('.ivu-form-item'));
                        let clicked = 0;
                        for (const fi of formItems) {
                            const grids = Array.from(fi.querySelectorAll('.grid'));
                            for (const g of grids) {
                                if (g.innerText.trim() === '10') { g.click(); clicked++; break; }
                            }
                        }
                        return clicked;
                    }""")
                    if n == 0:
                        break
                    next_btn = page.query_selector("button:has-text('下一页')")
                    cls = next_btn.get_attribute("class") if next_btn else ""
                    if next_btn and "is-disabled" not in (cls or ""):
                        next_btn.click()
                        page.wait_for_timeout(3000)
                    else:
                        break

                # Save
                save_btn = page.query_selector("button:has-text('保存')")
                if save_btn:
                    save_btn.click()
                    page.wait_for_timeout(3000)
                    results["saved"] += 1
                else:
                    results["errors"].append(f"Save button not found for {kcmc}")
                    results["skipped"] += 1

        return results


# -----------------------------------------------------------------------
# auto_fill functional API (backwards compat)
# -----------------------------------------------------------------------

def auto_fill(
    xnxq: str = "2025-2026-2",
    courses: Optional[list[str]] = None,
    score: int = 10,
    text: str = "很好",
) -> dict:
    """
    Auto-fill all pending evaluations. Uses TISAuthEval internally.

    Returns dict: {total, saved, skipped, errors}
    """
    auth = TISAuthEval()
    auth.refresh()
    return auth.auto_fill(xnxq=xnxq, courses=courses, score=score, text=text)
