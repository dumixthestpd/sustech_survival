# Blackboard (BB) — SUSTech

Quick login and course content scraping for SUSTech Blackboard.

## Setup

1. **Save your credentials:**
   ```bash
   echo "12413021:your_cas_password" > ~/.openclaw/workspace/creds.txt
   ```

2. **Install playwright:**
   ```bash
   playwright install chromium
   ```

## Usage

```bash
cd ~/.openclaw/workspace/skills/sustech-survival/bb

# Login once (saves session)
python3 bb.py login

# Scrape all courses
python3 bb.py scrape

# List enrolled courses
python3 bb.py courses

# Quick peek at a page
python3 bb.py peek "https://bb.sustech.edu.cn/..."

# Check login status
python3 bb.py check

# Refresh expired session
python3 bb.py refresh
```

## Output

- `scrape` saves to `courses.json` (hierarchical view)
- Raw data at `/tmp/structure.json`

## Courses

Spring 2026 enrolled:
- CAD与工程制图（2026春）
- EAP Spring 2026
- Physical Chemistry Experiments
- 基础有机化学实验
- 材料力学B
