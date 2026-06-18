---
name: classroom
description: TIS 全校课表 reverse view — find which classroom is occupied at what time, and which classrooms are free when. Works for all three SUSTech semesters (Fall, Spring, Summer) by changing `--xq`.
owner: Faux
last_updated: 2026-06-18
---

# TIS 全校课表 reverse view (`sustech_survival.classroom`)

> **What this is.** The "room-centric" mirror of the campus course schedule.
> TIS shows you "what course is in room X at time Y" — this module flips
> the view: given a room, when is it occupied? given a timeslot, which
> rooms are free?
>
> **Works for all three semesters** — set `--xq 1` (Fall), `--xq 2`
> (Spring), `--xq 3` (Summer/Jul-Aug). Same API, different term code.

## The trick

`Xsxktz/queryRwxxcxList` returns ~1499 courses per semester. The API's
`skdd` (上课地点) and `jsz` (教室) fields are **never populated** —
verified 2026-06-18 across all 500 fetched items: 0/500.

The real schedule is embedded as HTML inside `kcxx`:

```html
<span class="ivu-tag-text"><p>1-15周,星期一第3-4节 一教324</p></span>
<span class="ivu-tag-text"><p>3,7,9,13周,星期日第1-4节 校外活动场所</p></span>
<span class="ivu-tag-text"><p>1-9,11-15周,星期二第3-4节 一教326</p></span>
```

We regex-parse these into structured `(weeks, day, period-range, room)`
tuples — see `schema.py:parse_kcxx` and `_SLOT_RE`.

## Quick start

```bash
# List all rooms (with slot counts and capacity)
python -m sustech_survival.classroom rooms
python -m sustech_survival.classroom rooms --min-cap 100

# All slots in one room
python -m sustech_survival.classroom room 一教324

# What's in this room on week 5 Monday?
python -m sustech_survival.classroom occupancy 一教324 --week 5 --day 1

# What rooms are free Tue 3-4 week 5?
python -m sustech_survival.classroom free --week 5 --day 2 --period 3 4

# Same with capacity filter
python -m sustech_survival.classroom free --week 5 --day 2 --period 3 4 \
    --capacity-min 50

# Summer semester (xq=3) — same API, different term
python -m sustech_survival.classroom rooms --xq 3 --xn 2025-2026
python -m sustech_survival.classroom occupancy 一教324 --xq 3 \
    --week 2 --day 3

# Force-refresh the disk cache (TTL = 1h)
python -m sustech_survival.classroom refresh
```

All commands support `--json` for machine-readable output.

## Day / period numbers

- `day`: 1 = Mon, 2 = Tue, ..., 7 = Sun
- `period`: 1-12 (4 morning, 4 afternoon, 4 evening — see `PERIOD_TIMES`)

| Period | Time |
|--------|------|
| 1      | 08:00-08:45 |
| 2      | 08:55-09:40 |
| 3      | 10:00-10:45 |
| 4      | 10:55-11:40 |
| 5      | 14:00-14:45 |
| 6      | 14:55-15:40 |
| 7      | 16:00-16:45 |
| 8      | 16:55-17:40 |
| 9      | 19:00-19:45 |
| 10     | 19:55-20:40 |
| 11     | 20:50-21:35 |
| 12     | 21:45-22:30 |

## Programmatic API

```python
from sustech_survival.classroom import classroom

c = classroom()                       # default: 2025-2026 Spring
rooms = c.rooms()                     # List[Room]
r = c.room_by_name("一教324")         # fuzzy match
slots = c.slots_for_room("一教324")   # List[ScheduleSlot]
occ = c.occupancy("一教324", week=5, day=1)
free = c.free(week=5, day=2, period_start=3, period_end=4)
```

## Cache

Disk-cached at `<skill_root>/classroom/cache/schedule_<xn>_<xq>.json`.
TTL: 3600s (1h). Use `c.refresh()` or `python -m ... refresh` to bust.

The cache survives process restarts. Without cache, the first call takes
~30s (paginated through 3 pages × 500 courses).

## Pitfalls

1. **`skdd` and `jsz` are NEVER populated.** Don't try to read them — only `kcxx` has the data.
2. **`jszws` (capacity) is populated 93% of the time.** Some rooms show `cap=?` in the rooms list — that's a course that didn't expose its capacity in the API.
3. **Multiple parallel sections may share a room.** e.g. `SME308 001` / `001A` / `001B` all meet in 一教324 on Mon 5-6. This is real — different lab groups booking the same physical room at the same time.
4. **Off-campus venues appear as "校外..."**. They're real schedule slots but not queryable for occupancy (no room to enter).
5. **`day` 0 / invalid is treated as "never active"**. If a parsed slot has `day=0` (parse failure on an unknown Chinese day char), it's effectively hidden from occupancy queries.
6. **Week 10 is often skipped** (spring festival). Patterns like `1-9,11-15周` correctly skip it.
7. **Manual TIS CAS login** — `classroom.py:_tis_login()` hand-rolls the CAS POST to avoid the `LegacyAdapter` urllib3 bug. Don't replace it with `TISAuth.ensure()` until that bug is fixed.

## Files

- `classroom/__init__.py` — public API
- `classroom/classroom.py` — `ClassroomOccupancy` client (one client, all queries)
- `classroom/schema.py` — `Room`, `ScheduleSlot`, kcxx parser
- `classroom/__main__.py` — CLI
- `classroom/cache/` — disk-cached parsed schedule (gitignored)
- `test/test_classroom_schema.py` — 34 offline tests

## Tests

`pytest test/test_classroom_schema.py -q` → 34 passed.

## Reference

- `tis/campus_schedule.py` — the underlying REST endpoint (`Xsxktz/queryRwxxcxList`)
- `tis/eval/semester.py` — `Season.FALL/SPRING/SUMMER` enum + `Semester` class (TIS code structure)
- `references/tis-personal-schedule-discovery-2026-05-28.md` — how the personal schedule API was discovered
- `references/building-new-sub-skill.md` — the recipe this module follows
