"""BB — Blackboard Learn.

Usage:
    from sustech_survival.bb import ddl
    ddl.run()        → print upcoming BB assignment deadlines
    ddl.run(days=7)  → deadlines within N days

REST-based modules (no Playwright):
    from sustech_survival.bb import query, download, submit
    query.discover_courses()   → list of (course_id, name)
    query.discover_pages(cid) → list of (content_id, title, section)
    query.resolve_course(cid) → course_id string
    download.scrape_content_files(cid) → (title, [(name, url)])
    download.download_content(cid) → list of saved paths
    submit.submit_file(content_id, file_path) → (ok, message)
    submit.submit_assignment_rest(course_id, content_id, file_path) → SubmitResult
"""

import sys
from pathlib import Path as _Path

_SKILL_ROOT = _Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_SKILL_ROOT / "src"))

__all__ = [
    "ddl", "query", "download",
    "submit_file", "submit_assignment", "submit_assignment_rest", "check_attempts",
]

from sustech_survival.bb import query, download, ddl

# submit is pure REST now (no Playwright; the legacy Playwright submitter and
# the bb._playwright module were removed). Lazy-import so the package loads
# cheaply — the functions resolve on first attribute access.
def __getattr__(name):
    if name in ("submit_file", "submit_assignment", "submit_assignment_rest",
                "check_attempts"):
        from sustech_survival.bb import submit as _submit
        return getattr(_submit, name)
    raise AttributeError(name)

# Note (2026-06-08): we used to do `from .submit import submit, ...` here,
# but that bound the `submit` function to the `bb` package namespace and
# shadowed the `sustech_survival.bb.submit` SUBMODULE. Anyone doing
# `import sustech_survival.bb.submit as m` got the function, not the
# module, breaking monkeypatching and any code that needed the module.
# Renamed the function to `submit_file` to break the collision.
#
# ddl had the same flaw: a package-level `ddl()` function shadowed the
# `sustech_survival.bb.ddl` SUBMODULE (fixed 2026-09-04 the same way). The
# submodule now owns the `ddl` name; the old deadline convenience is
# `ddl.run(...)`.
