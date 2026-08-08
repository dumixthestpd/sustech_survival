"""
sustech_survival.selectcourse — TIS course selection helper.

Read-side of 选课: browse course offerings (any semester, including summer
xq=3), view your enrolled courses, and inspect a course's schedule and
room.

Write-side: `add_course()` / `drop_course()` / `add_to_cart()` /
`remove_from_cart()` — all default to `dry_run=True` and only mutate TIS
when explicitly opted in. Endpoints discovered by walking the
`/pub/xkgl/xsxk/xsxk-*.js` bundle — see `references/tis-api.md`.

Public API:
    from sustech_survival.selectcourse import (
        selectcourse, Course, EnrollmentError,
        TIS_ADD_XUANKE_URL, TIS_TUIKE_URL,
    )

Singleton:
    selectcourse() — returns a SelectCourseClient. Logs in via TISAuth.

Schema:
    Course              — one course offering (with parsed ScheduleSlots)
    EnrollmentError     — raised when a write call returns jg != '1'

Naming note
-----------
Our public API uses Pythonic names (`round_code` for the selection round,
`category` for course category, `category_name_to_code` for the
display-name → code translator). TIS's internal short codes (`xkfsdm`,
`kclbdm`, `kclbmc`) appear ONLY on the wire inside `build_queryform`
— the function that builds the form payload TIS expects. The
KCLBDM_MAP / kclbmc_to_code aliases remain for any external code that
imported them.

Module layout (split 2026-08-08):
    selectcourse.py     — read-side client orchestrator + write-method mixins
    course.py           — Course dataclass + slot helpers
    maps.py             — CATEGORY_MAP, language_to_code (pure data)
    endpoints.py        — TIS URL constants + XKTJZ_*
    queryform.py        — TIS wire-format payload builder
    errors.py           — EnrollmentError
    writes.py           — 5 write methods + _post_xsxk helper
    ical.py             — ICS calendar export (unchanged)
    __main__.py         — CLI entry (unchanged)
"""
from __future__ import annotations

from .selectcourse import (
    SelectCourseClient, selectcourse, EnrollmentError,
)
from .course import Course
from .endpoints import (
    TIS_ADD_XUANKE_URL, TIS_TUIKE_URL,
    TIS_ADD_GOUWUCHE_URL, TIS_DEL_GOUWUCHE_URL,
    TIS_UPD_XKXS_BY_YX, TIS_UPD_XKXS_BY_GWC,
    XKTJZ_CART_TO_ENROLLED, XKTJZ_TASK_TO_ENROLLED,
    XKTJZ_TASK_TO_CART,  # back-compat alias (same value as TASK_TO_ENROLLED)
)
from .maps import (
    CATEGORY_MAP, CATEGORY_REVERSE,
    category_name_to_code, LANGUAGE_MAP, language_to_code,
    # Back-compat aliases — same object, old TIS-jargon name.
    KCLBDM_MAP, KCLBDM_REVERSE, kclbmc_to_code,
)


__all__ = [
    "SelectCourseClient", "selectcourse", "Course", "EnrollmentError",
    "TIS_ADD_XUANKE_URL", "TIS_TUIKE_URL",
    "TIS_ADD_GOUWUCHE_URL", "TIS_DEL_GOUWUCHE_URL",
    "TIS_UPD_XKXS_BY_YX", "TIS_UPD_XKXS_BY_GWC",
    "XKTJZ_CART_TO_ENROLLED", "XKTJZ_TASK_TO_ENROLLED",
    "CATEGORY_MAP", "CATEGORY_REVERSE", "category_name_to_code",
    "LANGUAGE_MAP", "language_to_code",
    # Back-compat (kept so old imports don't break).
    "KCLBDM_MAP", "KCLBDM_REVERSE", "kclbmc_to_code", "XKTJZ_TASK_TO_CART",
]