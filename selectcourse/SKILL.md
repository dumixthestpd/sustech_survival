---
name: selectcourse
description: TIS course catalog + enrollment browser — for any SUSTech semester including summer (xq=3). READ + WRITE: browse courses, view details, check your enrolled courses, AND add/drop courses (write-side defaults to dry_run=True for safety). All 18 TIS Xsxk/* endpoints are documented in references/tis-api.md.
owner: Faux
last_updated: 2026-06-19
---

# TIS course catalog browser (`sustech_survival.selectcourse`)

> **What this is.** Full surface for TIS 选课 — browse the public course
> catalog, view offering details, check which courses you're enrolled
> in, AND add/drop courses. Works for **all three semesters** including
> summer (xq=3, Jul-Aug).
>
> **Write-side safety.** All write methods default to `dry_run=True`.
> They return the exact payload that would be POSTed to TIS without
> sending any HTTP request. Pass `dry_run=False` to actually fire.

## Quick start

```bash
# Browse Summer 2026 (xq=3)
python -m sustech_survival.selectcourse list --xq 3

# Filter by keyword / college / nature
python -m sustech_survival.selectcourse list 生物学 --xq 3
python -m sustech_survival.selectcourse list --xq 3 --cultivation 本科
python -m sustech_survival.selectcourse list --xq 3 --nature 必修

# Detail for one course offering
python -m sustech_survival.selectcourse course BIO463 --group 001 --xq 3

# What you're enrolled in
python -m sustech_survival.selectcourse enrolled --semester 2025-2026-3

# Force-refresh the disk cache
python -m sustech_survival.selectcourse refresh --xq 3

# Add a course (dry-run; shows payload, no mutation)
python -m sustech_survival.selectcourse add 2025-2026-2-BIO101-001

# Actually add it (mutates enrollment — be sure)
python -m sustech_survival.selectcourse add 2025-2026-2-BIO101-001 --no-dry-run

# Drop a course (dry-run by default)
python -m sustech_survival.selectcourse drop 2025-2026-2-BIO101-001

# Shopping cart flow
python -m sustech_survival.selectcourse add-to-cart 2025-2026-2-BIO101-001
python -m sustech_survival.selectcourse remove-from-cart 2025-2026-2-BIO101-001
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

All 18 TIS endpoints (read + write) are documented in
[`references/tis-api.md`](references/tis-api.md). Summary:

| API | Used for |
|-----|----------|
| `Xsxktz/queryRwxxcxList` | Public course catalog (any xq) |
| `xszykb/queryxszykbzong` | Your enrolled courses for a semester |
| `Xsxk/addXuanke` | **Add** course (cart → enrolled) |
| `Xsxk/tuike` | **Drop** course |
| `Xsxk/addGouwuche` | Add to shopping cart |
| `Xsxk/delGouwuche` | Remove from shopping cart |
| `Xsxk/updXuefeijiaofei` | Tuition payment (not wrapped) |
| ... | 11 more read endpoints — see ref doc |

The write-side endpoints were discovered 2026-06-19 by walking the
`/pub/xkgl/xsxk/xsxk-*.js` JS bundle on the catalog page
(`/Xsxk/query/1`). Full discovery walkthrough + bundle hashes in
`references/tis-api.md`.

## Pitfalls

1. **`kcxx` schedule is OPTIONAL for summer courses.** 56/56 summer offerings have NO parseable weekly schedule — they're intensive lab/research courses with irregular meetings. Regular semesters (Spring/Fall) have full schedules.
2. **`skdd`/`jsz` location fields are NEVER populated** (same as classroom). The only place room data lives is in the kcxx HTML, and only when the course has a regular weekly slot.
3. **Cache TTL is 1h.** Use `refresh` after a TIS update or to bust.
4. **Summer (xq=3) is real.** Verified 2026-06-18: TIS has 56 summer 2026 courses loaded.
5. **Personal schedule is empty if you're not enrolled.** Don't be surprised by `(no courses enrolled)` — it just means you haven't signed up for anything in that semester yet.
6. **`pylx` is the int code, not the label.** `1` = 本科, `2` = 研究生.
7. **Write-side defaults to dry-run.** Course enrollment is a state-mutating operation — the methods print what they'd POST but never actually fire unless you pass `--no-dry-run` / `dry_run=False`. Be sure before flipping.
8. **`p_id` may not equal `rwh`.** We assume the catalog's `rwh` (任务号) maps to TIS's `p_id` for add/drop. If TIS rejects with `jg='0'` saying the id is invalid, see open-question #3 in `references/tis-api.md`.

## Programmatic API

```python
from sustech_survival.selectcourse import (
    selectcourse, Course, EnrollmentError,
)

sc = selectcourse(xn="2025-2026", xq="3")   # Summer 2026
courses = sc.list_courses(keyword="生物学")
for c in courses:
    print(f"[{c.code} {c.class_group}] {c.name}")
    print(f"   teachers: {c.teachers}")
    print(f"   schedule: {c.schedule_str}")

c = sc.by_code("BIO463", "001")
print(c.rwh, c.schedule_str)

# Currently enrolled
mine = sc.my_courses("2025-2026-3")
enrolled_rwhs = sc.enrolled_rwhs("2025-2026-3")

# Add a course (dry-run; inspect payload, don't fire)
res = sc.add_course("2025-2026-2-BIO101-001")
print(res["would_post"])

# Actually add it (will raise EnrollmentError if jg != '1')
res = sc.add_course("2025-2026-2-BIO101-001", dry_run=False)

# Drop
res = sc.drop_course("2025-2026-2-BIO101-001", dry_run=False)

# Cart flow
sc.add_to_cart("2025-2026-2-BIO101-001", dry_run=False)
sc.remove_from_cart("2025-2026-2-BIO101-001", dry_run=False)
```

## Files

- `selectcourse/__init__.py` — public API
- `selectcourse/selectcourse.py` — `SelectCourseClient` (catalog + enrolled + add/drop)
- `selectcourse/schema.py` — `Course` dataclass (kcxx parsing reused from `classroom`)
- `selectcourse/__main__.py` — CLI
- `selectcourse/cache/` — disk-cached catalog (gitignored)
- `test/test_selectcourse_schema.py` — 13 offline tests (catalog parser)
- `test/test_selectcourse_write.py` — 19 offline tests (write-side + dry-run + EnrollmentError)
- `references/tis-api.md` — full TIS endpoint reference

## Tests

```
pytest test/test_selectcourse_schema.py test/test_selectcourse_write.py -q
→ 32 passed
```
