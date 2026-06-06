"""TIS teaching evaluation sub-package.

.. deprecated::
    TIS 评教 (teaching evaluation) window for the 2025-2026 spring
    semester closed on 2026-06-05 and the evaluation entrance is no
    longer accessible, so this module is kept dormant until the
    2026-2027 fall evaluation window — when we can re-observe the
    eval page and resume development. There is no replacement for
    now; complete evaluations manually in the TIS web UI in the
    meantime. This module will be removed after the next evaluation
    cycle if it has not been revived.
"""

import warnings as _warnings

from .semester import Season, Semester
from .questions import QuestionType, Question, RatingQuestion, TextQuestion
from .evaluation import Evaluation
from .browser import TISAuthEval, auto_fill, lazy_submit

_warnings.warn(
    "sustech_survival.tis.eval is deprecated: the TIS 评教 window closed "
    "on 2026-06-05. The module is kept dormant and will be revived when "
    "the 2026-2027 fall evaluation window opens. Complete evaluations "
    "manually in the TIS web UI in the meantime.",
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
