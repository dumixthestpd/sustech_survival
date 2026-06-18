"""
sustech_survival.selectcourse — TIS course selection helper.

Read-side of 选课: browse course offerings (any semester, including summer
xq=3), view your enrolled courses, and inspect a course's schedule and
room.

For the WRITE side (clicking the actual "select" button), see
references/tis-api.md — endpoints are gated behind Vue components and
require a JS-bundle walk to discover. Until then, this module gives you
the information you need to drive the UI manually.

Public API:
    from sustech_survival.selectcourse import selectcourse, Course

Singleton:
    selectcourse() — returns a SelectCourseClient. Logs in via TISAuth.

Schema:
    Course    — one course offering (with parsed ScheduleSlots)
"""
from __future__ import annotations

from .selectcourse import SelectCourseClient, selectcourse
from .schema import Course


__all__ = ["SelectCourseClient", "selectcourse", "Course"]
