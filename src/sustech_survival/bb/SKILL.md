---
name: bb
description: Interact with SUSTech Blackboard (bb.sustech.edu.cn). Use when user asks to open Blackboard, check BB, login to bb, check assignments, get course materials, or any Blackboard-related tasks.
---

# Blackboard (BB)

> ⚠️  CRITICAL — NEVER submit to BB without explicit permission.
> Every test run creates a REAL submission on Blackboard and counts as an attempt.
> Before ANY submission: (1) ask dumix first, (2) check session is valid, (3) confirm no prior submission exists.
> UUID suffixes on filenames (e.g. `---cf8274ec...`) must be stripped before submitting.
> **submit.py requires a `y` confirmation before submitting** (or `--yes` flag).

## Python API

```python
import sys
sys.path.insert(0, '/Users/dumix/.openclaw/workspace/skills/sustech_survival/src')
import sustech_survival.bb as bb

# Session
bb.credentials('creds.txt')              # set credentials file (username:password)
ok, reason = bb.session()                # check session: (bool, reason)
bb.login()                               # CAS login via headless Playwright

# Browse
bb.courses()                             # [(id, name), ...] — all enrolled courses (from cache)
bb.courses(refresh=True)                 # re-scrape from BB portal "课程" tab → updates cache
bb.pages('8157')                        # [(content_id, title, section), ...]
bb.items('598333', '8157')               # [Item, ...] — items in a page

# Search (live scrape — scans all pages)
bb.search(text='week')                   # items with "week" in title
bb.search(type_filter=['homework'])      # all homework items
bb.search(course='EAP', text='ppt')    # EAP course + "ppt" in title
bb.search(has_attachments=True)          # items with files

# Stats (live scrape)
bb.types()                               # {item_types, course_counts, total_items, ...}
bb.types(course='EAP')                   # stats for one course

# Download
bb.download('612447')                   # download all files to ~/Downloads/bb/
bb.preview(attempt_id, course_id='8343') # {filename, size, type} — file metadata before downloading

# Submit (DANGEROUS — real submission)
bb.submit('612447', '/path/to/file.pdf', course_id='8157')
```

## CLI

```bash
# Entry point — run from sustech-survival/ directory
python3 run_bb.py <command>

# Session
python3 run_bb.py courses                   # list enrolled courses
python3 run_bb.py search                    # all items (live scrape)
python3 run_bb.py search --course EAP       # filter by course
python3 run_bb.py search --type homework    # filter by type
python3 run_bb.py search --text week        # text in title
python3 run_bb.py search --has-attachments # items with files
python3 run_bb.py search -o json           # JSON output
python3 run_bb.py types                    # item type statistics
python3 run_bb.py page 598333 -c 8157      # items in a specific page
python3 run_bb.py page 598333 -c 8157 -v   # verbose (show descriptions)
```

### `bb search` — Search & Filter Items

```bash
# Filter by course name
python3 run_bb.py search --course EAP

# Filter by item type: file | video | homework | folder | inline | link | text
python3 run_bb.py search --type homework
python3 run_bb.py search --type file

# Text search in titles
python3 run_bb.py search --text experiment
python3 run_bb.py search --text week --type file

# Only items with attachments
python3 run_bb.py search --has-attachments

# Hide/show specific types
python3 run_bb.py search --hide homework
python3 run_bb.py search --show file

# Sort
python3 run_bb.py search --sort title       # alphabetical
python3 run_bb.py search --sort type        # by type
python3 run_bb.py search --sort course      # by course (default)

# Verbose — show description + attachments per item
python3 run_bb.py search --type homework -v

# JSON output
python3 run_bb.py search -o json
```

### `bb types` — Statistics

```bash
python3 run_bb.py types             # live scrape — all courses
python3 run_bb.py types --course EAP  # single course
```

### `bb page` — Items Inside a Page

```bash
# By content_id (auto-resolves course_id)
python3 run_bb.py page 598333 -c 8157

# Verbose: show files, video URL, description, deadline
python3 run_bb.py page 598333 -c 8157 -v
```

### `bb submit` — Submit Assignment

```bash
# Submit a file (requires y confirmation or --yes)
python3 run_bb.py submit <content_id> <file_path> [-c course_id] [--comment "..."]

# Example
python3 run_bb.py submit 622821 /tmp/hw.pdf
python3 run_bb.py submit 622821 /tmp/hw.pdf -c 8221 --yes
```

## Item Types

Each item inside a BB page has a specific type:

| Icon | Type | Description |
|------|------|-------------|
| 📄 | `file` | Downloadable file (PDF, doc, etc.) |
| 🎬 | `video` | Embedded video (BB TX player iframe) |
| 📝 | `homework` | Assignment with upload submission |
| 📁 | `folder` | Link to another BB content page |
| 🖼 | `inline` | Inline images (not downloadable) |
| 🔗 | `link` | External URL reference |
| 📃 | `text` | Description text only |
| ❓ | `unknown` | Could not classify |

## Submit

```bash
# Check attempts (no submission)
python3 bb.py submit --course 8328 --content 610812 --list

# Submit (requires y confirmation or --yes)
python3 bb.py submit --course 8328 --content 610812 --files report.pdf
```

## Submit — BB Assignment Submission

> ⚠️  CRITICAL — NEVER submit to BB without explicit permission. Every test run creates a REAL submission and counts as an attempt.
> Before submission: (1) ask dumix first, (2) confirm no prior submission exists.
> **Naming format:** `12413021+姓名+作业N` (e.g. `12413021段斯宸作业10.pdf`)

### Python API (via __main__.py)

```python
import sys
sys.path.insert(0, '/Users/dumix/.openclaw/workspace/skills/sustech_survival/src')
from sustech_survival.bb import submit, check_attempts, find_assignment, list_upcoming

# Check attempts (before submitting)
count, name = check_attempts('623874', '8053')
print(f'{name}: {count} prior attempt(s), next would be #{count+1}')

# Submit a file
ok, msg = submit('623874', '/tmp/12413021段斯宸作业10.pdf', '8053')
print(f'Success: {ok} — {msg}')

# Find assignment by keyword
results = find_assignment('尺规')
for r in results:
    print(f'[{r["course"]}] {r["title"]} (c={r["content_id"]}) due={r["due"]} submitted={r["submitted"]}')

# List upcoming assignments
upcoming = list_upcoming(limit=20)
for course, title, cid, coid, due, *_ in upcoming:
    print(f'[{due}] {course} | {title}')
```

### CLI

```bash
# Check attempt count
python3 -m sustech_survival.bb check <content_id> [course_id]

# Submit
python3 -m sustech_survival.bb submit <content_id> <file_path> [course_id]

# Find by keyword
python3 -m sustech_survival.bb find "尺规"

# List upcoming
python3 -m sustech_survival.bb list-due --limit 20
```

### Known Assignment IDs (CAD 2026 Spring)

| Assignment | Content ID | Course ID | Due |
|-----------|-----------|-----------|-----|
| 第十周作业 (Assignment for Lecture 10) | 623874 | 8053 | 2026年5月10日 星期日 上午8:00 |
| 第十周实验作业 | 624232 | 8053 | 2026年5月16日 星期六 |
| 第九次实验作业 | 623434 | 8053 | 2026年5月9日 星期六 |

### Submission Flow

1. **Confirm with dumix** before any submission
2. **Check attempts** — `check_attempts(content_id, course_id)` → if count > 0, confirm again
3. **Rename file** to `12413021段斯宸作业N.pdf` (strip any OpenClaw UUID suffix)
4. **Submit** — `submit(content_id, file_path, course_id)` → returns (ok, message)
5. **Verify** — re-run check_attempts to confirm attempt count increased

## Architecture

```
bb/
├── __init__.py      # Public Python API
├── cli.py           # CLI — courses, search, types
├── items.py         # Item class hierarchy
├── pages.py         # Page scraping
├── courses.py       # Course loading
├── download.py      # Content/attempt download + submit_homework()
├── submit.py        # Submission logic + submit/check/find/list-upcoming CLI
└── session.py       # CAS auth
```

## Session

- Session cookies: `bb/session.json`
- `bb.login()` / `sustech bb session login` creates it; `refresh` renews when expired
- Credentials: `creds.txt` in `bb/` dir (format: `username:password`)

## BB Quirks

- **DDLs in body text** — deadlines appear in page content, not sidebar labels
- **DDLs on the uploadAssignment page** — the deadline for a homework item
  is on the `uploadAssignment` page itself, NOT in the description body
  (which is the teacher's freeform text). Teachers often leave the body
  empty and put the deadline only on the submission page. Use
  `HomeworkItem.from_submission_page(course_id, content_id)` to extract
  the deadline safely — never set `deadline` manually.
- **Don't construct HomeworkItem manually** — use
  `HomeworkItem.from_submission_page(course_id, content_id)` which extracts
  `title` and `deadline` from the live page. Manual construction is fragile
  (wrong title, missing deadline).
- **Image comments** — BB stores picture comments as `<img>` tags in comment HTML
- **PhysChem schedule** — experimental arrangement page has non-standard structure

## Late-submission safety

`HomeworkItem.submit()` emits a `UserWarning` if `self.deadline` is in the
past (relative to current China time). This catches the "I think I'm
resubmitting but it's actually past the deadline" mistake.

Suppress with `hw.submit(..., force_late=True)` if you've explicitly
decided a late attempt is OK. The warning does NOT fire on `dry_run=True`
(since no real attempt is made).

```python
from sustech_survival.bb.items import HomeworkItem

# Safe pattern: extract from the live page
hw = HomeworkItem.from_submission_page("8328", "610821")
print(hw.deadline)  # "2026年5月12日 23:59"

# If deadline is past, this warns but still submits:
ok, msg = hw.submit("/path/to/report.pdf", target_name="...", dry_run=False)

# To suppress the warning when you're sure:
ok, msg = hw.submit("/path/to/report.pdf", force_late=True)
```
