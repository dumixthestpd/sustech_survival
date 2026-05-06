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
sys.path.insert(0, '/Users/dumix/.openclaw/workspace/skills/sustech-survival')
import bb

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

## Architecture

```
bb/
├── __init__.py    # Public Python API (bb.courses, bb.items, bb.search, ...)
├── cli.py         # CLI implementation
├── bb.py          # CLI entry point shim
├── items.py       # Item class hierarchy (FileItem, HomeworkItem, ...)
├── pages.py       # Page scraping (discover_course_pages, preview_page)
├── courses.py     # Course loading from courses.json
├── download.py    # Content/attempt download functions
├── session.py     # CAS auth (login, refresh, session check)
└── query.py       # Search and type statistics (fully dynamic)
```

## Session

- Session cookies: `bb/session.json`
- `bb.login()` / `bb.py login` creates it; `refresh` renews when expired
- `check` verifies status (requires GUI Chrome)
- Credentials: `creds.txt` in `bb/` dir (format: `username:password`)

## BB Quirks

- **Portal "课程" tab URL**: `?tab_tab_group_id=_1_1` (NOT `?tabType=2` — that redirects to wrong tab)
- **Cookie popup** — BB sometimes shows a dialog; handled automatically with retries
- **DDLs in body text** — deadlines appear in page content, not sidebar labels
- **Stale content** — BB occasionally serves wrong course data for a page
- **PhysChem schedule** — experimental arrangement page has non-standard structure
- **Image comments** — BB stores picture comments as `<img>` tags in comment HTML; `scrape_attempt_files()` extracts these automatically
