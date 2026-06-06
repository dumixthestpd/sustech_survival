from __future__ import annotations

from enum import Enum


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

