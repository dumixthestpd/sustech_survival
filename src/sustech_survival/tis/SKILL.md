# TIS Skill

SUSTech Teaching Information System (教学信息管理系统) automation.

## Quick Start

```bash
cd ~/.openclaw/code/sustech_survival && ./tis/check.sh
```

**Always use check.sh to verify login status** — TIS can show placeholder content when not logged in.

### If NOT Logged In:
1. Run `python3 tis/login.py` to login via CAS
2. Verify login was successful (run check.sh again)
3. Then proceed with your task

### If Logged In:
Proceed with your task.

## Scripts

| Script | Purpose |
|--------|---------|
| `login.py` | Headless CAS login via requests |
| `check.sh` | Quick status check, returns exit code 0/1 |
| `courses.py` | Extract enrolled courses to CSV |

## Teaching Evaluation (评教)

> **⚠️ DEPRECATED — 2026-06-06 (dormant until next eval window).** The
> TIS 评教 window for the 2025-2026 spring semester closed on 2026-06-05
> and the evaluation entrance is no longer accessible, so the `tis.eval`
> module is kept dormant until the 2026-2027 fall evaluation window —
> when we can re-observe the eval page and resume development.
>
> Importing `sustech_survival.tis.eval` emits a `DeprecationWarning`.
> No replacement for now — complete evaluations manually in the TIS
> web UI. The branch `feat/eval-submit` is preserved as the development
> archive for next semester's revival.

### Quick Start

```python
from sustech_survival.tis.eval import TISAuthEval

auth = TISAuthEval()
auth.login()

ev = auth.open_evaluation("EAP", xnxq="2025-20262")
ev.load()        # navigate all pages, collect questions
ev.autofill()    # fill all questions with rating=10
ev.save()        # submit both pjlx=1 (course) and pjlx=2 (teacher)
```

### How it works

TIS evaluations have two layers, each requiring its own save:

- **pjlx=1** — course questions (page 1)
- **pjlx=2** — teacher questions (page 2, if present)

`load()` uses Playwright to navigate pages via the `下一步` button and extracts questions from the DOM. `save()` builds the API body and submits twice.

### Per-question wjid

Questions on different pages use different wjids — page 1 uses the course wjid, page 2 uses the teacher wjid. Both are read from Vue state during `load()`.

## What We Have Access To

- **Course Schedule**: from TIS
- **Academic Calendar**: from TIS

Data stored in: `~/.openclaw/code/sustech_survival/` (sessions) and `~/.openclaw/workspace/sustech/26spring/` (course data)

## Fetch Course Info

```bash
cd ~/.openclaw/code/sustech_survival
python3 tis/courses.py
```

## Python API

```python
from sustech_survival import tis
tis.login()       # headless CAS login
tis.courses()     # scrape courses → CSV
```

## Navigating TIS Pages

After login:
- Schedule: `https://tis.sustech.edu.cn/student/teachingSchedule/semester/2025-2026-2`
- Grades: `https://tis.sustech.edu.cn/student/grade/semester/2025-2026-2`

## Tab Cleanup

`check.sh` and `login.py` automatically clean up useless tabs:
- `/session/invalid` (expired session)
- TIS home page

Only `/authentication/main` is kept to maintain session.

## Venue Borrowing (场地借用 / cdjy)

Located at `sustech_survival.tis.classroom.booking` — NOT under `classroom/`.

Minimal client (no CRUD bloat — write-once, wait-for-approval):

```python
from sustech_survival.tis.classroom.booking import venue_borrow
from sustech_survival.tis.classroom.booking_schema import (
    BorrowApplication, BorrowDetail, BorrowTimeSlot,
)

c = venue_borrow()
c.ensure_session()

# Check permission first
perm = c.check_permission("2025-2026", "2")
if perm.allowed:
    # Build the application
    form = BorrowApplication(
        applicant_name="段斯宸", applicant_phone="13908478929",
        user_name="段斯宸", user_phone="13908478929",
        xn="2025-2026", xq="2", semester="2025-2026-2",
        weeks="5-8", headcount=30, purpose="学术讲座",
        details=[BorrowDetail(
            room_code="YJ-123", room_name="一教123",
            time_slots=[BorrowTimeSlot(
                weekday=2, period_start=3, period_end=4, week_pattern="5-8"
            )],
        )],
    )
    # Dry-run first (default, no network call)
    c.create_borrow_application(form, dry_run=True)
    # Then commit
    saved = c.create_borrow_application(form, dry_run=False)
```

Client methods:
- `check_permission(xn, xq)` → `PermissionResult`
- `list_audit_statuses()` → `[AuditStatus]` (workflow reference)
- `query_venue_occupancy(xn, xq, room_codes=...)` → `[VenueOccupancySlot]`
- `create_borrow_application(form, dry_run=True)` → `BorrowApplication`

Endpoints: `/cdjy/*` and `/gzlshywlc/*`. Auth via `LiveOccupancyClient` (TIS CAS).
