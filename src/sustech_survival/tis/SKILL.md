# TIS Skill

SUSTech Teaching Information System (教学信息管理系统) automation.

## Quick Start

```bash
cd ~/.openclaw/workspace/skills/sustech_survival && ./tis/check.sh
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

## What We Have Access To

- **Course Schedule**: from TIS
- **Academic Calendar**: from TIS

Data stored in: `~/.openclaw/workspace/skills/sustech_survival/` (sessions) and `~/.openclaw/workspace/sustech/26spring/` (course data)

## Fetch Course Info

```bash
cd ~/.openclaw/workspace/skills/sustech_survival
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
