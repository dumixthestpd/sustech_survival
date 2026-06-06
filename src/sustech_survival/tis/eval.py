"""Backward-compat re-export from eval/ package.

.. deprecated::
    TIS 评教 (teaching evaluation) window for the 2025-2026 spring
    semester closed on 2026-06-05. This shim is kept dormant until
    the 2026-2027 fall evaluation window when the eval page can be
    re-observed. There is no replacement for now.
"""

import warnings as _warnings

from sustech_survival.tis.eval import (
    Season,
    Semester,
    QuestionType,
    Question,
    RatingQuestion,
    TextQuestion,
    Evaluation,
    TISAuthEval,
    auto_fill,
    lazy_submit,
)

_warnings.warn(
    "sustech_survival.tis.eval module shim is deprecated: the TIS 评教 "
    "window closed on 2026-06-05. Kept dormant until the 2026-2027 fall "
    "evaluation window. Complete evaluations manually in the TIS web UI "
    "in the meantime.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "Season",
    "Semester",
    "QuestionType",
    "Question",
    "RatingQuestion",
    "TextQuestion",
    "Evaluation",
    "TISAuthEval",
    "auto_fill",
    "lazy_submit",
]
