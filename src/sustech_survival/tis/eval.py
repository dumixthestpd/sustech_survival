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

    // Get the current page's wjid from window.myVue (set before each page navigation)
    // Fall back to the first wjlist entry's wjid
    let page_wjid = null;
    try {
        const vm = window.myVue;
        if (vm && vm.wjlist && vm.wjlist[0]) {
            // For page 2 (teacher), wjid is in pjjg[1].wjid; for page 1 (course), pjjg[0].wjid
            const pjjgList = vm.wjlist[0].pjxtPjjgPjjgckb || [];
            if (pjjgList.length >= 2) {
                page_wjid = pjjgList[1].wjid;  // teacher wjid (page 2)
            }
            if (!page_wjid && pjjgList.length >= 1) {
                page_wjid = pjjgList[0].wjid;  // course wjid (page 1)
            }
        }
    } catch(e) {}

    for (let fi = 0; fi < formItems.length; fi++) {
        const formItem = formItems[fi];
        let questionText = '';

        // Walk UP to .modular-zs-main → .xzt-ms-head h5 (works for BOTH page 1 and page 2)
        const modularZsMain = formItem.closest('.modular-zs-main');
        if (modularZsMain) {
            const xztHead = modularZsMain.querySelector('.xzt-ms-head h5');
            if (xztHead) questionText = xztHead.innerText.trim();
        }

        // Get the REAL backend wjstid from the Vue component data
        let qid = String(fi);  // fallback
        let vue_datas = null;
        if (modularZsMain && modularZsMain.__vue__) {
            try {
                const vueData = modularZsMain.__vue__.$data;
                if (vueData && vueData.datas) {
                    vue_datas = vueData.datas;
                    if (vueData.datas.tmid) qid = String(vueData.datas.tmid);
                }
            } catch(e) {}
        }

        // Collect all .grid options within this form item
        const allGrids = Array.from(formItem.querySelectorAll('.grid'));
        const options = allGrids.map(g => g.innerText.trim()).filter(t => t !== '');
        const isRating = options.length > 0 && options.every(o => /^\d+$/.test(o));

        // Also get the marks map from Vue (maps grid value to answer)
        let marks = null;
        if (modularZsMain && modularZsMain.__vue__) {
            try {
                const vueData = modularZsMain.__vue__.$data;
                if (vueData && vueData.marks) marks = vueData.marks;
            } catch(e) {}
        }

        if (options.length > 0) {
            results.push({
                qid,
                text: questionText || ('Question ' + (fi + 1)),
                options,
                isRating,
                isText: false,
                marks,
                vue_datas,  // pass full datas for save body
                q_wjid: page_wjid,  // wjid for this page's evaluation layer
            });
        }

        for (const ta of Array.from(formItem.querySelectorAll('textarea'))) {
            const qid2 = ta.getAttribute('data-wjstid') || ta.getAttribute('name') || String(results.length + 1000);
            results.push({ qid: qid2, text: questionText || 'Text Q', options: [], isRating: false, isText: true, q_wjid: page_wjid });
        }
    }

    for (const ta of Array.from(document.querySelectorAll('textarea, input[type=text]'))) {
        if (!ta.closest('.ivu-form-item')) {
            results.push({
                qid: ta.getAttribute('data-wjstid') || String(results.length + 2000),
                text: ta.getAttribute('placeholder') || 'Text',
                options: [], isRating: false, isText: true,
                q_wjid: page_wjid,
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
        self._jsonobj: dict = {}
        self._pjmap: dict = {}
        self._wjlist: list = []
        self._question_blocks: list = []

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
        Also captures Vue state (headobj, wjlist) for save body construction.
        Sets ``self.questions_data`` with type, text, options for each question.
        Returns self.
        """
        page = self._page
        assert page is not None, "Evaluation not attached to a browser page"
        self.questions_data = []
        self._seen_qids: set[str] = set()

        while True:
            page.wait_for_timeout(2000)

            # Read Vue state ONCE per page before extracting questions
            self._read_vue_state(page)

            raw: list[dict] = page.evaluate(_EXTRACT_QUESTIONS_JS)

            for d in raw:
                qid = d["qid"]
                if qid in self._seen_qids:
                    continue
                self._seen_qids.add(qid)

                opts = d.get("options", [])
                if d.get("isRating") or (opts and all(o.isdigit() for o in opts)):
                    qtype = QuestionType.RATING
                elif d.get("isText"):
                    qtype = QuestionType.TEXT
                elif opts:
                    qtype = QuestionType.CHOICE
                else:
                    qtype = QuestionType.UNKNOWN

                vue_datas = d.get("vue_datas") or {}
                self.questions_data.append({
                    "qid": qid,
                    "text": d.get("text", ""),
                    "type": qtype,
                    "options": opts,
                    "answer": None,
                    "answered": False,
                    "_vue_datas": vue_datas,
                    "_q_wjid": d.get("q_wjid") or None,
                })

            # Multi-page: click 下一步 to advance to next page
            # Break if: no questions extracted (n=0) OR we have ALL questions for this form
            # We detect "last page" by checking if the 下一步 button has text "下一步"
            # (the LAST page has NO 下一步 button — it shows "保存" instead)
            next_btn = page.query_selector("button:has-text('下一步')")
            if next_btn is None:
                break  # last page — no more navigation
            cls = next_btn.get_attribute("class") or ""
            if "is-disabled" in cls:
                break
            next_btn.click()
            page.wait_for_timeout(4000)  # wait for page transition + new content

        return self

    def _read_vue_state(self, page) -> None:
        """Read jsonobj, pjmap, wjlist from Vue and cache on self."""
        result = page.evaluate("""() => {
            try {
                const vue = window.myVue;
                if (!vue) return null;
                const data = vue.$data;
                const jsonobj = data.jsonobj;
                const pjmap = data.pjmap && Object.keys(data.pjmap).length > 0
                    ? data.pjmap
                    : data.wjlist?.[0]?.pjmap;
                const wjlist = data.wjlist;
                let question_blocks = [];
                if (wjlist && wjlist[0] && wjlist[0].pjxtWjWjbReturnEntity) {
                    const wjEntity = wjlist[0].pjxtWjWjbReturnEntity;
                    question_blocks = (wjEntity.wjzblist || []).map(zb => ({
                        zmc: zb.zmc,
                        zxssx: zb.zxssx,
                        questions: (zb.tklist || []).map(tm => ({
                            tmid: tm.tmid,
                            tgmc: tm.tgmc,
                            tmlx: tm.tmlx,
                            tmfz: tm.tmfz,
                            jsonContent: tm.jsonContent,
                        }))
                    }));
                }
                // Capture per-page wjid from pjjg list (pjjg[0]=course page1, pjjg[1]=teacher page2)
                const pjjgList = (wjlist && wjlist[0] && wjlist[0].pjxtPjjgPjjgckb) || [];
                return {
                    jsonobj: jsonobj ? JSON.parse(JSON.stringify(jsonobj)) : null,
                    pjmap: pjmap ? JSON.parse(JSON.stringify(pjmap)) : null,
                    wjlist: wjlist ? JSON.parse(JSON.stringify(wjlist)) : [],
                    question_blocks,
                    // Expose per-page wjid for page1 (course) and page2 (teacher)
                    course_wjid: pjjgList[0]?.wjid || null,
                    teacher_wjid: pjjgList[1]?.wjid || null,
                };
            } catch(e) { return null; }
        }""")
        if result:
            self._jsonobj = result.get("jsonobj") or {}
            self._pjmap = result.get("pjmap") or {}
            self._wjlist = result.get("wjlist") or []
            self._question_blocks = result.get("question_blocks") or []
            # Store per-page wjid for correct pjlx routing in save
            self._course_wjid = result.get("course_wjid") or ""
            self._teacher_wjid = result.get("teacher_wjid") or ""
        else:
            self._jsonobj = {}
            self._pjmap = {}
            self._wjlist = []
            self._question_blocks = []
            self._course_wjid = ""
            self._teacher_wjid = ""

    def save(self) -> Evaluation:
        """
        Two-pass save matching the browser's actual flow:
          Call 1: pjlx=1 (course questions) → server returns a new pjid
          Call 2: pjlx=2 (teacher/TA questions) → uses Call 1's pjid in pjidlist
        """
        from sustech_survival.sso import TISAuth
        auth = TISAuth()
        auth.refresh()
        sess = auth.session

        # Pass 1: course questions (pjlx=1)
        body1 = self._build_save_body(pjlx="1")
        r1 = sess.post(
            f"{BASE}/personnelEvaluation/submitSaveEvaluation",
            json=body1,
            timeout=15,
        )
        result1 = r1.json()
        self._last_save_result = result1

        # Extract pjid from result 1 for use in result 2
        new_pjid = ""
        if result1.get("code") == 200:
            # pjid is in pjjglist[0].pjid or at top level
            new_pjid = (
                result1.get("result", {}).get("pjjglist", [{}])[0].get("pjid", "")
                or result1.get("result", {}).get("pjid", "")
                or ""
            )

        if not new_pjid:
            # Fall back: use the id from jsonobj as the new pjid
            new_pjid = getattr(self, "_jsonobj", {}).get("id", "") or ""

        # Pass 2: teacher/TA questions (pjlx=2) — only if we have pjlx=2 questions
        body2 = self._build_save_body(pjlx="2", prior_pjid=new_pjid)
        if body2["pjjglist"][0]["pjxxlist"]:
            r2 = sess.post(
                f"{BASE}/personnelEvaluation/submitSaveEvaluation",
                json=body2,
                timeout=15,
            )
            self._last_save_result = r2.json()

        return self

    # ---------------------------------------------------------------------------
    # Internal
    # ---------------------------------------------------------------------------

    def _build_save_body(self, pjlx: str = "1", prior_pjid: str = "") -> dict:
        """
        Build save body for one pjlx layer.

        pjlx="1": course questions (qid 25868-25878), pjidlist=[], wjid=jsonobj.wjid
        pjlx="2": teacher/TA questions (qid 25879+), pjidlist=[{prior_pjid}], wjid=from vue_datas
        """
        answered = [q for q in self.questions_data if q["answered"]]
        if not answered:
            raise ValueError("No questions answered — call autofill() or answer() first")

        jsonobj = getattr(self, "_jsonobj", None) or {}
        pjmap = getattr(self, "_pjmap", None) or {}

        # pjlx detection: _q_wjid differs from course wjid = pjlx=2; else pjlx=1
        course_wjid = jsonobj.get("wjid", "") or ""
        def get_q_pjlx(q: dict) -> str:
            q_wjid = q.get("_q_wjid") or ""
            if q_wjid and q_wjid != course_wjid:
                return "2"
            return "1"

        layer_answered = [q for q in answered if get_q_pjlx(q) == pjlx]
        if not layer_answered:
            layer_answered = []  # empty list — caller checks this

        # wjid for pjjglist: default to course wjid, override from first layer_answered if available
        wjid = jsonobj.get("wjid", "") or ""
        if pjlx == "2" and layer_answered:
            for _q in layer_answered:
                _qw = _q.get("_q_wjid") or ""
                if _qw:
                    wjid = _qw
                    break
            # Fallback: use stored teacher_wjid from page 2 vue state
            if not wjid or wjid == jsonobj.get("wjid", ""):
                wjid = getattr(self, "_teacher_wjid", "") or wjid

        pjxxlist = []
        for q in layer_answered:
            qid = str(q["qid"])
            vue_datas = q.get("_vue_datas") or {}

            # marks are at vue_datas.datas.marks for page 1 components
            marks = None
            if vue_datas:
                marks = vue_datas.get("marks") or vue_datas.get("datas", {}).get("marks") if isinstance(vue_datas, dict) else None

            # xxdalist: send the raw answer value for ratings (0-10 scale)
            # The marks map (from Vue component's internal state) maps grid positions to
            # internal values but we should send the actual score the user selected.
            # E.g. if answer=10 (user selected "10" grid), xxdalist=[10].
            if q["type"] == QuestionType.RATING:
                xxdalist = [int(q["answer"])]
                dalx, daz = 1, str(q["answer"])
            elif q["type"] == QuestionType.TEXT:
                ans_str = str(q["answer"])
                xxdalist = [ans_str]
                dalx, daz = 2, ans_str
            else:
                ans_str = str(q["answer"])
                xxdalist = [ans_str]
                dalx, daz = 3, ans_str

            pjxxlist.append({
                "sjly": "1",
                "stlx": "5",
                "wjid": wjid,
                "wjssrwid": pjmap.get("RWID", "") or jsonobj.get("rwid", "") or "",
                "wjstctid": "",
                "wjstid": qid,
                "xxdalist": xxdalist,
                "dalx": dalx,
                "daz": daz,
            })

        # pjdf = avg of rating answers
        rating_answers = [q["answer"] for q in layer_answered if q["type"] == QuestionType.RATING]
        pjdf = sum(rating_answers) / len(rating_answers) if rating_answers else 0

        # bpdm/pjrjsdm: for pjlx=2 use teacher code; for pjlx=1 use course code
        bpdm_course = jsonobj.get("bpdm", "") or ""
        pjrdm = jsonobj.get("pjrdm", "") or ""
        pjsx_val = jsonobj.get("pjsx", 1)
        if pjlx == "2":
            bpdm = jsonobj.get("jszgh", "") or jsonobj.get("skzgh", "") or "30000212"  # teacher staff code
            pjrjsdm = bpdm + pjrdm + str(pjsx_val)
        else:
            bpdm = bpdm_course
            pjrjsdm = bpdm_course + pjrdm + str(pjsx_val)

        pjjgbm = pjmap.get("PJJGBM", "") or ""
        pjjgxxbm = pjmap.get("PJJGXXBM", "") or ""
        full_pjmap = {
            "PJJGBM": pjjgbm,
            "PJJGXXBM": pjjgxxbm,
            "RWID": pjmap.get("RWID", "") or jsonobj.get("rwid", "") or "",
        }

        pjrxm = jsonobj.get("pjrmc", "") or jsonobj.get("pjrxm", "") or ""

        # bprmc / kcmc: for pjlx=2 use teacher name
        bprmc = jsonobj.get("bpmc", "") or self.course_name or ""
        kcmc = jsonobj.get("kcmc", "") or self.course_name or ""
        if pjlx == "2":
            # Teacher name is in jsonobj.skjsmc
            bprmc = jsonobj.get("skjsmc", "") or bprmc
            # bprdm for teacher: try jszgh first (newer API), then skzgh, then fallback
            bpdm = jsonobj.get("jszgh", "") or jsonobj.get("skzgh", "") or bpdm

        pjidlist = []
        if pjlx == "2" and prior_pjid:
            pjidlist = [{
                "pjid": prior_pjid,
                "pjbm": pjjgbm or "",
                "sfnm": "1",
            }]

        return {
            "pjidlist": pjidlist,
            "pjjglist": [{
                "bprdm": bpdm,
                "bprmc": bprmc,
                "kcdm": jsonobj.get("kcdm", "") or self.course_code or "",
                "kcmc": kcmc,
                "pjdf": pjdf,
                "pjfs": "1",
                "pjid": jsonobj.get("id", "") or "",
                "pjlx": pjlx,
                "pjmap": full_pjmap,
                "pjrdm": pjrdm,
                "pjrjsdm": pjrjsdm,
                "pjrxm": pjrxm,
                "pjsx": 1,
                "pjxxlist": pjxxlist,
                "rwh": jsonobj.get("rwh", "") or "",
                "stzjid": "xx",
                "wjid": wjid or jsonobj.get("wjid", "") or "",
                "wjssrwid": pjmap.get("RWID", "") or jsonobj.get("rwid", "") or "",
                "wtjjy": None,
                "xhgs": None,
                "xnxq": jsonobj.get("xnxq", "") or "",
                "sfxxpj": "1",
                "sqzt": None,
                "yxfz": None,
                "sdrs": None,
                "skjc": None,
                "zsxz": pjrjsdm,
                "sfnm": "1",
            }],
            "pjzt": "2",
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

    def open_evaluation(self, course_name: str, xnxq: str = "2025-2026-2",
                        status: str = "pending") -> Evaluation:
        """
        Open the evaluation form for a course by name.

        Args:
            course_name: Course name (e.g. "CAD" or "材料力学")
            xnxq: Semester code
            status: "pending" (default) or "saved" — which evaluation list to search

        Returns an Evaluation object. Call ``ev.load()`` then ``ev.save()``.
        """
        from playwright.sync_api import sync_playwright

        # Get user ID
        r = self.session.get(f"{BASE}/user/me")
        r.raise_for_status()
        yhdm = r.json().get("yhdm", "")
        if not yhdm:
            raise RuntimeError("Could not determine user ID from TIS session")

        # Find the course in the specified list
        evals = self.evaluations(xnxq=xnxq, status=status)
        target = None
        for c in evals:
            if course_name.upper() in c["course_name"].upper():
                target = c
                break
        if not target:
            raise ValueError(f"Course '{course_name}' not found in {status} evaluations")

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
                    next_btn = page.query_selector("button:has-text('下一步')")
                    if next_btn and "is-disabled" not in (next_btn.get_attribute("class") or ""):
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
