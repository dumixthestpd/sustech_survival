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

## Data Locations

| Data | Location |
|------|----------|
| Course CSV | `~/.openclaw/workspace/sustech/26spring/courses.csv` |
| BB structure | `/tmp/bb_structure.json` |
| BB courses | `bb/bb-courses.json` |
| Calendar | Google Calendar (via gog) |
| EAP research | `~/.openclaw/workspace/sustech/26spring/eap/research/` |

## SUSTech Lab Report Template

**Template:** `~/.openclaw/workspace/sustech/26spring/实验报告模板_物理化学.docx`

Used for: Physical Chemistry Experiments (SE03), Basic Experiments for Organic Chemistry.

**Formatting spec:** Times New Roman 12pt, 2.5cm margins, 1.5 line spacing, hanging indent ~0.64cm.

**Workflow:**
1. `conda activate docx_env`
2. Fill placeholder paragraphs ONLY (don't touch styles)
3. `soffice --headless --convert-to pdf input.docx --outdir /tmp/`
4. `openclaw message send --media /tmp/input.pdf --channel telegram --target 7680374260`

Skill: `skills/docx-env/SKILL.md`

## Credentials

`~/.openclaw/workspace/credentials.txt` — format: `username:password`
