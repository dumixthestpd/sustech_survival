# TIS Skill

SUSTech Teaching Information System (教学信息管理系统) automation.

## Quick Start

```bash
cd ~/.openclaw/workspace/skills/sustech-survival/tis && ./check-login.sh
```

**Always use check-login.sh to verify login status** — it's more reliable than visual inspection. Both BB and TIS can show fake/placeholder content when not logged in.

### If NOT Logged In:
1. Run `./login-tis.sh` to login via CAS
2. Verify login was successful (run check-login.sh again)
3. Then proceed with your task

### If Logged In:
Proceed with your task. A TIS `/authentication/main` tab stays open to maintain session.

## Scripts

| Script | Purpose |
|--------|---------|
| `login-tis.sh` | Check status → login if needed → verify → keep TIS tab open |
| `check-login.sh` | Quick status check, returns exit code 0/1 |
| `fetch_courses.py` | Extract enrolled courses to CSV |
| `fetch_calendar.py` | Find/download academic calendar PDFs |

## What We Have Access To

- **Course Schedule**: 11 courses for 26spring semester
- **Academic Calendar**: 2026 school year calendar

Data stored in: `~/.openclaw/workspace/sustech/26spring/`

## Fetch Course Info

```bash
cd ~/.openclaw/workspace/skills/sustech-survival/tis && python3 fetch_courses.py
```

This will:
1. Check if logged in to TIS
2. Visit the course selection page (/Xsxk/query/1)
3. Extract course info (code, name, teacher, schedule with week ranges, odd/even weeks, location)
4. Save to `~/.openclaw/workspace/sustech/26spring/courses.csv`

## Fetch Academic Calendar

```bash
# List available calendars
python3 fetch_calendar.py

# Download specific year
python3 fetch_calendar.py --year 2026 --download
```

## Navigating TIS Pages

After login, navigate to specific pages:

```bash
# Schedule page
open -a "Google Chrome" "https://tis.sustech.edu.cn/student/teachingSchedule/semester/2025-2026-2"

# Grades page
open -a "Google Chrome" "https://tis.sustech.edu.cn/student/grade/semester/2025-2026-2"
```

## Download Schedule/Grades as Excel

In Chrome:
1. Navigate to schedule or grades page
2. Look for "导出Excel" or "导出" button
3. Click to download

## Tab Cleanup

Both scripts automatically clean up useless tabs:
- `/session/invalid` (expired session)
- `/user/me` (check page, not needed after verification)
- TIS home page (`tis.sustech.edu.cn/`)

Only `/authentication/main` is kept to maintain session.

## Requirements

- Chrome with saved SUSTech CAS credentials
- Python 3
- macOS with AppleScript support
