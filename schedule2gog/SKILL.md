---
name: schedule2gog
description: Sync SUSTech TIS class schedule to Google Calendar. Use when dumix wants to sync, export, or clear class schedule from Google Calendar, or check which week it is.
---

# Schedule → Google Calendar

## Quick Commands

```bash
cd ~/.openclaw/workspace/skills/sustech-survival/schedule2gog

# ── Calendar (academic calendar from sustech.edu.cn) ─────────────
python3 fetch_calendar.py              # Check updates, download if new
python3 fetch_calendar.py --parse     # Download + parse → semester.json
python3 fetch_calendar.py --check      # Just check for updates
python3 fetch_calendar.py --year 2026 # Target specific year

# ── Schedule sync (TIS personal course schedule → Google Calendar) ──
./sync.sh            # Full sync (keeps existing events, skips duplicates)
./sync.sh --clear    # Clear ALL SUSTech events first, then full sync (recommended)
./dry-run.sh         # Preview only
./clear.sh           # Remove all schedule events from calendar
./clear.sh --course "CourseName"  # Remove specific course only
```

**Important:** Always use `--clear` first if you're syncing fresh — otherwise duplicates may accumulate if you run sync multiple times before the duplicate detection catches up.

## Semester Week Calculator

```bash
python3 semester_week.py                    # today's week
python3 semester_week.py 2026-04-20         # specific date
python3 semester_week.py next monday        # natural language
python3 semester_week.py -h                 # help
```

**Can also be imported as a module:**

```python
from semester_week import get_week, week_number

info = get_week("2026-04-20")
# info["week"] → 8
# info["parity"] → "even"
# info["is_class_day"] → False  (Sunday)
# info["is_holiday"] → False

wn = week_number(datetime.date(2026, 4, 20), datetime.date(2026, 2, 23))
# wn → 8
```

**Data source:** `~/.openclaw/workspace/sustech/semester.json`
Update this single file to change semester dates — both `sync.py` and `semester_week.py` read from it.

## Prerequisites

1. TIS logged in: `tis/login-tis.sh`
2. Courses fetched: `python3 tis/fetch_courses.py`
3. gog calendar auth: `gog auth list`

## Known Courses (Spring 2026)

| Course | Teacher | Schedule |
|--------|---------|----------|
| 物理化学 | 田雷蕾 | Mon 3-4 + Wed 3-4 (even) |
| 物理化学实验 | 李艳艳, 章剑波, 王海鸥 | Thu 1-4 (odd) |
| 材料力学B | 黄博远 | Fri 7-8 + Wed 7-8 (even) |
| 高分子材料 | 孙大陟 | Tue 3-4 + Thu 3-4 (even) |
| 体育IV | 梁锡元 | Wed 1-2 |
| 非物质文化遗产保护与应用 | 王晓葵 | Thu 9-10 |
| EAP | 李卓 | Fri 3-4 |
| 基础有机化学实验 | 王海鸥, 李艳艳, 李慧丽 | Mon 5-8 (even) |
| 材料测试分析技术 | 温瑞涛 | Mon 5-6 (odd) + Wed 5-6 |
| CAD与工程制图 | 郭艺璇, 黄业绪, 肖啸川 | Mon 9-10 + Tue 5-7 |
| 基础有机化学 | 郭旭岗 | Wed 9-10 + Fri 5-6 (even) |

## Filter Warning

Course names are NOT unique. `"物理化学"` matches lecture AND experiment.

AI should use **exact course names**:
- `物理化学` — lecture only
- `物理化学实验` — experiment only
- `基础有机化学` — lecture only
- `基础有机化学实验` — lab only

## Two Data Sources — Know the Difference

| Source | What it contains | Who it applies to |
|--------|------------------|-------------------|
| **Public Academic Calendar** (fetched by `fetch_calendar.py`) | Semester start/end, holidays, compensatory days | **Everyone** — same for all students |
| **TIS Personal Schedule** (fetched by `fetch_courses.py`) | Your specific courses, times, rooms, teachers | **You only** — personalized |

**Why this matters:**
- The academic calendar PDF comes from `sustech.edu.cn` (public website) — NOT from TIS. It defines the universal semester structure: when term starts, exam periods, holidays, and makeup class days.
- TIS contains your personal course enrollments on top of that structure.
- `sync.py` combines both: `semester.json` (universal timing) × `courses.csv` (your schedule) = calendar events.

**When to update which:**
- New semester → run `fetch_calendar.py --force --parse` to regenerate `semester.json` from the official public calendar.
- Course changes mid-semester → run `fetch_courses.py` to refresh your personal schedule.

## Clear Script Logic

`clear.py` only deletes events where `description` contains `Teacher:` AND `Week:` (SUSTech course markers). It will NOT delete non-TIS calendar events. Safe to run.

## Semester

Spring 2026: **Week 1 Monday = Feb 23** | First class day = Feb 25 | End = July 5

**Config file:** `~/.openclaw/workspace/sustech/semester.json`

| Key | Value |
|-----|-------|
| `spring.week_1_monday` | Feb 23, 2026 |
| `spring.first_class_day` | Feb 25, 2026 |
| `spring.semester_end` | July 5, 2026 |
| `_notes.odd_week_days` | [0, 2, 4] → Mon, Wed, Fri |
| `_notes.even_week_days` | [1, 3] → Tue, Thu |
