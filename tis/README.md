# TIS — SUSTech Teaching Information System

Course schedule, grades, and academic information.

## Quick Start

```bash
cd ~/.openclaw/workspace/skills/sustech-survival/tis

# Check login status
./check-login.sh

# Login if needed
./login-tis.sh

# Fetch courses
python3 fetch_courses.py
```

## Scripts

| Script | What it does |
|--------|-------------|
| `check-login.sh` | Verify login (exit 0 = logged in) |
| `login-tis.sh` | Login via CAS → keep session tab open |
| `fetch_courses.py` | Extract enrolled courses to CSV |
| `fetch_calendar.py` | Find/download academic calendar PDFs |

## Course Data

Output: `~/.openclaw/workspace/sustech/26spring/courses.csv`

Your 11 courses (Spring 2026):
- 物理化学 / 物理化学实验
- 材料力学B
- 高分子材料
- 体育IV
- 非物质文化遗产保护与应用
- EAP
- 基础有机化学实验 / 基础有机化学
- 材料测试分析技术
- CAD与工程制图

## Academic Calendar

```bash
python3 fetch_calendar.py --year 2026 --download
```

## Important

**Always check login first** with `./check-login.sh` before running any other TIS action.

Chrome must have your CAS credentials saved for autofill to work.

## Requirements

- Chrome with saved CAS credentials
- Python 3
- macOS with AppleScript (for GUI scripts)
