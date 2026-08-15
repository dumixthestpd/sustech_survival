"""
sustech_survival.webui.utilities — head-independent rendering helpers.

Tools here are UI-independent building blocks a skin/mod/head can reuse: they
turn ``sustech_survival`` data into renderable output (ICS, HTML grids), with
no Flask and no assumption about which skin is active.

This satisfies the "webui = utilities + skin loader" split: ``utilities/`` is
the code side (draw/generate), ``skins/`` is the presentation side.
"""
from __future__ import annotations

# Re-export the existing schedule -> iCal emitter (head-independent).
from sustech_survival.selectcourse.ical import courses_to_ical
from sustech_survival.semester import Semester

__all__ = ["courses_to_ical", "Semester", "schedule_grid_html"]


def schedule_grid_html(semester: Semester, courses) -> str:
    """Render a simple weekly schedule grid as HTML (no external JS).

    ``courses``: iterable of items with ``.schedule_str`` and ``.name`` /
    ``.code``/``.rwh`` (Course objects or plain dicts). This is a tiny
    fallback grid; a skin can render its own fancier grid from the raw
    ``/api/tis/courses`` data instead.
    """
    rows = []
    for c in courses:
        name = (c.get("name") if isinstance(c, dict) else c.name) or "?"
        code = (c.get("code") if isinstance(c, dict) else c.code) or ""
        rwh = (c.get("rwh") if isinstance(c, dict) else c.rwh) or ""
        sched = (c.get("schedule") if isinstance(c, dict) else c.schedule_str) or ""
        rows.append(
            f"<tr><td>{code} {name} <code>{rwh}</code></td><td>{sched}</td></tr>")
    return ("<table class='schedule-grid'><thead>"
            "<tr><th>Course</th><th>Schedule</th></tr></thead><tbody>"
            + "".join(rows) + "</tbody></table>")
