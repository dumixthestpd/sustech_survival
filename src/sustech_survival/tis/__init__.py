"""
TIS subsystem: grades, courses, teaching evaluations.

Auth: use ``from sustech_survival.sso import TISAuth`` or
      ``from sustech_survival.tis import TISAuthEval`` (includes eval methods).

Usage::

    from sustech_survival.tis import TISAuthEval

    auth = TISAuthEval().login()
    for ev in auth.evaluations(xnxq="2025-2026-2"):
        ev.load()
        ev.questions(0).answer("great teacher")
        ev.save()
"""

from . import grades
from . import courses
from . import classroom

__all__ = ["grades", "courses", "TISAuthEval", "Evaluation"]

def __getattr__(name: str):
    if name == "TISAuthEval":
        from .eval import TISAuthEval
        return TISAuthEval
    if name == "Evaluation":
        from .eval import Evaluation
        return Evaluation
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
