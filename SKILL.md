---
name: sustech-survival
description: SUSTech academic systems — TIS schedule, Blackboard, Google Calendar sync, library search. Use for anything related to SUSTech courses, BB, TIS, or academic tasks. A toolkit for SUSTech survival, supports CLI commands and Python API.
---

# SUSTech Survival

A toolkit for SUSTech survival, supports CLI commands and Python API

SUSTech academic systems: TIS, Blackboard, calendar sync, library search.

## Sub-Skills

Each has two files:
- **README.md** — setup guide for human users
- **SKILL.md** — AI-facing quick reference

```
sustech-survival/
├── bb/              # Blackboard (course materials, assignments)
│   ├── bb.py        # Main CLI — use this
│   ├── README.md
│   └── SKILL.md
├── tis/             # TIS (schedule, grades)
│   ├── README.md
│   └── SKILL.md
├── schedule2gog/    # TIS → Google Calendar sync
│   ├── README.md
│   └── SKILL.md
├── sustech-lib-search/  # Library research
│   ├── README.md
│   └── SKILL.md
└── docs/            # (deprecated, ignore)
```

## Quick Commands

```bash
# BB: login → scrape → view
python3 bb/bb.py login
python3 bb/bb.py scrape
python3 bb/bb.py courses

# TIS: check → fetch courses
./tis/check-login.sh
python3 tis/fetch_courses.py

# Calendar: sync or clear
./schedule2gog/sync.sh
./schedule2gog/clear.sh

# Library: login headless
python3 sustech-lib-search/login-lib.py
```

## Architecture

- **BB + TIS**: CAS-based auth (POST login)
- **schedule2gog**: reads `courses.csv` → creates Google Calendar events via gog
- **sustech-lib-search**: browser relay or direct CAS for login, then 4-step research method

## Data Locations (Canonical)

| Data | Location |
|------|----------|
| Course CSV | `~/.openclaw/workspace/sustech/26spring/courses.csv` |
| BB structure | `/tmp/bb_structure.json` |
| BB courses | `bb/bb-courses.json` |
| Calendar | Google Calendar (via gog) |

**Course-specific resources** (templates, EAP, per-course data): see `personal.md` — gitignored, contains real paths on this device.

## Credentials

See `personal.md` for credentials file locations. `bb/creds.txt` format: `username:password`
