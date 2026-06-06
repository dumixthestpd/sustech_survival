from __future__ import annotations

import json as _json
from typing import Optional

from .semester import Season, Semester
from .questions import QuestionType, Question, RatingQuestion, TextQuestion, _EXTRACT_QUESTIONS_JS


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
        self.page: Optional[object] = page
        self.browser: Optional[object] = browser
        self.questions_data: list[dict] = []   # raw dicts from JS
        self.jsonobj: dict = {}
        self.pjmap: dict = {}
        self.wjlist: list = []
        self.question_blocks: list = []

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
        page = self.page
        assert page is not None, "Evaluation not attached to a browser page"
        self.questions_data = []
        self.seen_qids: set[str] = set()

        while True:
            page.wait_for_timeout(2000)

            # Read Vue state ONCE per page before extracting questions
            self.read_vue_state(page)

            raw: list[dict] = page.evaluate(_EXTRACT_QUESTIONS_JS)

            for d in raw:
                qid = d["qid"]
                if qid in self.seen_qids:
                    continue
                self.seen_qids.add(qid)

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

    def read_vue_state(self, page) -> None:
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
            self.jsonobj = result.get("jsonobj") or {}
            self.pjmap = result.get("pjmap") or {}
            self.wjlist = result.get("wjlist") or []
            self.question_blocks = result.get("question_blocks") or []
            # Store per-page wjid for correct pjlx routing in save
            self.course_wjid = result.get("course_wjid") or ""
            self.teacher_wjid = result.get("teacher_wjid") or ""
        else:
            self.jsonobj = {}
            self.pjmap = {}
            self.wjlist = []
            self.question_blocks = []
            self.course_wjid = ""
            self.teacher_wjid = ""

    def save(self) -> Evaluation:
        """
        Two-pass save matching the browser's actual flow:
          Call 1: pjlx=1 (course questions) → server returns a new pjid
          Call 2: pjlx=2 (teacher/TA questions) → uses Call 1's pjid in pjidlist
        """
        from sustech_survival.sso import TISAuth
        auth = TISAuth()
        if not auth.refresh():
            raise RuntimeError("TIS auth refresh failed — run: sustech tis session refresh")
        sess = auth.session
        BASE = TISAuth.BASE_URL
        body1 = self.build_save_body(pjlx="1")
        r1 = sess.post(
            f"{BASE}/personnelEvaluation/submitSaveEvaluation",
            json=body1,
            timeout=15,
        )
        result1 = r1.json()
        self.last_save_result = result1

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
        body2 = self.build_save_body(pjlx="2", prior_pjid=new_pjid)
        if body2["pjjglist"][0]["pjxxlist"]:
            r2 = sess.post(
                f"{BASE}/personnelEvaluation/submitSaveEvaluation",
                json=body2,
                timeout=15,
            )
            self.last_save_result = r2.json()

        return self

    # ---------------------------------------------------------------------------
    # Internal
    # ---------------------------------------------------------------------------

    def build_save_body(self, pjlx: str = "1", prior_pjid: str = "") -> dict:
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
    def json_dumps(obj) -> str:
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

