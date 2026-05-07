---
name: sustech_survival
description: SUSTech academic systems — TIS schedule, Blackboard, Google Calendar sync, library search. Use for anything related to SUSTech courses, BB, TIS, or academic tasks.
---

# SUSTech Survival

A toolkit for SUSTech survival, supports CLI commands and Python API

SUSTech academic systems: TIS, Blackboard, calendar sync, library search.

## Python Package

```python
import sustech_survival as sustech

sustech.bb.check_session()    # (bool, reason)
sustech.bb.login()            # Playwright headful CAS login
sustech.bb.courses()          # enrolled courses
sustech.lib.login()           # Library CAS login
sustech.lib.check()           # check session validity
sustech.tis.courses()         # TIS schedule
```

**Auth (`sso.py`):** `Authorizer` base class with `check()`, `refresh()`, `login()`, `ensure()`. Decorator: `@require_auth("bb")`.

## CLI

```bash
python3 sustech.py bb session check
python3 sustech.py bb courses
python3 sustech.py bb search "homework"
python3 sustech.py tis courses
python3 sustech.py lib login
python3 sustech.py lib check
```

Run `python3 sustech.py --help` for all commands.

## Sub-Skills

Each has two files:
- **README.md** — setup guide for human users
- **SKILL.md** — AI-facing quick reference

```
sustech_survival/               <- Skill root (ClawHub publishes this)
├── SKILL.md                    # This file
├── personal.example.md          # Template — copy to personal.md
├── personal.md                  # Gitignored: student info + credentials
├── credentials.example.txt
├── sustech.py                   # Unified CLI entry point
├── bb/                         # Blackboard (course materials, assignments)
├── tis/                        # TIS (schedule, grades)
├── lib/                        # Library Primo search
├── schedule2gog/               # TIS -> Google Calendar sync
└── resources/                  # External SUSTech resources (handbooks, maps, portals)
    └── SKILL.md
```

## Architecture

- **Shared Auth (`sso.py`)**: `Authorizer` + `@require_auth("bb")` decorator
  - `check()` -> (bool, reason) — verify session
  - `refresh()` -> bool — re-auth via CAS requests
  - `login()` -> bool — Playwright headful login
  - `ensure()` -> (bool, reason) — check + auto-refresh
  - Decorator: `@require_auth("bb")` gates any function needing auth
- **BB**: CAS auth, session at `bb/session.json`
- **TIS**: CAS auth via `tis/login.py`
- **Lib**: CAS auth for Primo, session at `lib/session.json`
- **schedule2gog**: reads `courses.csv` -> Google Calendar via gog

## Data Locations (Canonical)

| Data | Location |
|------|----------|
| Course CSV | `~/.openclaw/workspace/sustech/26spring/courses.csv` |
| BB session | `bb/session.json` |
| Lib session | `lib/session.json` |
| BB courses | `bb/courses.json` |
| Calendar | Google Calendar (via gog) |

**Course-specific resources** (templates, per-course data): see `personal.md` — gitignored, contains real paths on this device.

## Resources

For external SUSTech resources (student handbooks, portal links, maps, course reviews), see `resources/SKILL.md`.

**Notable:** [sustech.online](https://sustech.online/) (南科手册) — community student handbook with useful sub-pages we may build skills around later (bus tracker, campus map, talks, freshman guides).

---

## Todo List — Ideas & Future Work

Inspired by [SUSTech-CRA/awesome-sustech-service-tools](https://github.com/SUSTech-CRA/awesome-sustech-service-tools). Listed here to track what could be built.

### High Priority

- [ ] **BB grade scraper** — pull grades from Blackboard beyond what TIS exposes. [sustech.online resources/SKILL.md](../resources/SKILL.md) has BB + Sakai links; BB has gradebook but no official API
- [ ] **Course review skill** — integrate with [NCES (ncesnext.com)](https://ncesnext.com/) API or scrape course reviews. Auth: SUSTech email required
- [ ] **LaTeX template manager** — fetch from [SUSTC/latex-template](https://github.com/SUSTC/latex-template), auto-select template by course. Templates include lab reports, thesis, recommendation letters

### Medium Priority

- [ ] **sustech.online bus tracker skill** — scrape or API `sustech.online/transport/bustimer` for live bus schedules + vehicle positions
- [ ] **sustech.online campus map skill** — serve the interactive street view `/facility/` as a reference
- [ ] **TIS auto-enroll watcher** — notify when a full course opens up (watchdog on enrollment status). Based on [SUSTechTISHelper](https://github.com/Fros1er/SUSTechTISHelper) patterns
- [ ] **Grade exporter** — convert TIS/BB grade data to CSV/Excel. Based on [sustech-tis-converter](https://github.com/lethal233/sustech-tis-converter)

### Low Priority / Exploratory

- [ ] **IPTV live skill** — stream campus live TV via [liziwl/iptv-panel-react](https://github.com/liziwl/iptv-panel-react)
- [ ] **SUSTown integration** — community platform with [WeChat/QQ mini-program](https://github.com/SUSTech-CRA/SUSTown); could surface announcements
- [ ] **ShareLaTeX project sync** — open/edit LaTeX projects on CRA's [ShareLaTeX instance](https://sharelatex.cra.ac.cn/) via their API
- [ ] **c.x-d.fun auto-scheduler** — [xCipHanD's TIS auto-scheduler](https://c.x-d.fun/) as an alternative to manual enrollment

### References

- Full community projects list: [awesome-sustech-service-tools](https://github.com/SUSTech-CRA/awesome-sustech-service-tools)
- SUSTech LaTeX templates: [SUSTC/latex-template](https://github.com/SUSTC/latex-template)
- CRA service dashboard: [monitor.cra.moe](https://monitor.cra.moe)

## Credentials

All services read from `credentials.txt` at skill root.
Format: `username:password` (e.g. `12413021:yourpass`)