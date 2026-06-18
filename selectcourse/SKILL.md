---
name: selectcourse
description: TIS course catalog + enrollment browser — for any SUSTech semester including summer (xq=3). READ-ONLY: browse courses, view details, check your enrolled courses. The WRITE-side (clicking the actual select button) is gated behind a TIS Vue component and not yet wrapped.
owner: Faux
last_updated: 2026-06-18
---

# TIS course catalog browser (`sustech_survival.selectcourse`)

> **What this is.** The read-side of TIS 选课 — browse the public course
> catalog, view offering details, and check which courses you're enrolled
> in. Works for **all three semesters** including summer (xq=3, Jul-Aug).
>
> **What this is NOT.** The write-side (clicking the "select course"
> button) is gated behind a Vue component (`XkBcjAction`) whose endpoints
> aren't directly discoverable — they live in a hashed JS bundle, not in
> the TIS menu HTML. Until that bundle is walked, use this module for
> catalog/enrolled reads and drive the UI manually for enrollment.

## Quick start

```bash
# Browse Summer 2026 (xq=3) — 56 courses loaded
python -m sustech_survival.selectcourse list --xq 3

# Filter by keyword / college / nature
python -m sustech_survival.selectcourse list 生物学 --xq 3
python -m sustech_survival.selectcourse list --xq 3 --cultivation 本科
python -m sustech_survival.selectcourse list --xq 3 --nature 必修

# Detail for one course offering
python -m sustech_survival.selectcourse course BIO463 --group 001 --xq 3

# What you're enrolled in (summer 2026)
python -m sustech_survival.selectcourse enrolled --semester 2025-2026-3

# Force-refresh the disk cache
python -m sustech_survival.selectcourse refresh --xq 3
```

All commands support `--json` for machine-readable output.

## How semesters work

TIS uses a 3-term calendar encoded as `(xn, xq)`:

| xq | season  | dates (typical) |
|----|---------|-----------------|
| 1  | 秋季 (Fall)   | Sep – Jan |
| 2  | 春季 (Spring) | Feb – Jun |
| 3  | 夏季 (Summer) | Jul – Aug |

The 9-char TIS code combines `end_year(4) + cohort_year(4) + term(1)`:
- `2025-20261` → Fall 2026 (Sep 2026 – Jan 2027)
- `2025-20262` → Spring 2026 (Feb – Jul 2026)
- `2025-20263` → Summer 2026 (Jul – Aug 2026)

See `tis/eval/semester.py` for the `Season` enum + `Semester` class.

## Data sources

| API | Used for |
|-----|----------|
| `Xsxktz/queryRwxxcxList` | Public course catalog (any xq) |
| `xszykb/queryxszykbzong` | Your enrolled courses for a semester |

Both accept `xn` (academic year) + `xq` (1/2/3). For summer 选课, pass `xq=3`.

The catalog endpoint returns ~1499 courses for a regular semester but only
56 for summer 2026 (intensive/practicum courses — no weekly schedule).

## Pitfalls

1. **`kcxx` schedule is OPTIONAL for summer courses.** 56/56 summer offerings have NO parseable weekly schedule — they're intensive lab/research courses with irregular meetings. Regular semesters (Spring/Fall) have full schedules.
2. **`skdd`/`jsz` location fields are NEVER populated** (same as classroom). The only place room data lives is in the kcxx HTML, and only when the course has a regular weekly slot.
3. **Cache TTL is 1h.** Use `refresh` after a TIS update or to bust.
4. **Summer (xq=3) is real.** Verified 2026-06-18: TIS has 56 summer 2026 courses loaded. The system is open for enrollment.
5. **Personal schedule is empty if you're not enrolled.** Don't be surprised by `(no courses enrolled)` — it just means you haven't signed up for anything in that semester yet.
6. **`pylx` is the int code, not the label.** `1` = 本科, `2` = 研究生. We expose it as a raw string for now; if you need a label, check `cultivation` against a hardcoded map.
7. **AddCourse / DropCourse are NOT wrapped.** Use the TIS web UI for the actual selection. Once we walk the Vue bundle, this module will grow `add(course_rwh)` and `drop(course_rwh)` methods.

## Programmatic API

```python
from sustech_survival.selectcourse import selectcourse

sc = selectcourse(xn="2025-2026", xq="3")   # Summer 2026
courses = sc.list_courses(keyword="生物学")
for c in courses:
    print(f"[{c.code} {c.class_group}] {c.name}")
    print(f"   teachers: {c.teachers}")
    print(f"   schedule: {c.schedule_str}")

c = sc.by_code("BIO463", "001")
print(c.rwh, c.schedule_str)

# Currently enrolled (via xszykb)
mine = sc.my_courses("2025-2026-3")
enrolled_rwhs = sc.enrolled_rwhs("2025-2026-3")
```

## Files

- `selectcourse/__init__.py` — public API
- `selectcourse/selectcourse.py` — `SelectCourseClient` (catalog + personal)
- `selectcourse/schema.py` — `Course` dataclass (kcxx parsing reused from `classroom`)
- `selectcourse/__main__.py` — CLI
- `selectcourse/cache/` — disk-cached catalog (gitignored)
- `test/test_selectcourse_schema.py` — 13 offline tests

## Tests

`pytest test/test_selectcourse_schema.py -q` → 13 passed.

## Reference

- `tis/eval/semester.py` — `Season` enum (FALL/SPRING/SUMMER) + `Semester` parser
- `tis/campus_schedule.py` — the catalog REST endpoint
- `classroom/` — the room-centric mirror of the same data
- `references/tis-api.md` — the open question for the AddCourse endpoint
- `references/building-new-sub-skill.md` — the recipe this module follows
