[English](README.md) | [简体中文](README_cn.md)

# sustech-survival

`sustech_survival` is a python module that allows api-level sustech service calls. it satisfies everyday needs of sustech students including bb, tis, lib, pms and more.

by connecting the services at code level, we allow a simplification on the campus systems, a short cut to a personalized campus experience and most importantly, facilitates and invites ai-agent assistance into your campus life.

```bash
pip install git+https://github.com/dumixthestpd/sustech-survival.git
```

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: PolyForm Noncommercial 1.0.0](https://img.shields.io/badge/license-PolyForm--Noncommercial--1.0.0-orange.svg)](./LICENSE)

---

## Features

### Campus systems

These wrap SUSTech's existing services. For the Chinese name, see [README_cn.md](./README_cn.md).

- **Blackboard Learn** (`bb`)
- **Teaching Information System (TIS)** (`tis`)
- **SUSTech Library** (`lib`)
- **Single Sign-On (SSO)** (`sso`) — shared auth backbone
- **Campus Printing System** (`pms`)
- **SUSTech Global** (`ws`)
- **E-Hall** (`booking`)
- **Niuwa Curriculum Evaluation System (NCES)** (`nces`)

### We built

- **selectcourse** — TIS course selection: browse offerings, add/drop, and manage the cart.
- **faculty** — Faculty directory: list by department, full-text search, and profile lookup.
- **transit** — Campus bus and walking navigation: schedules, live GPS, and route planning.
- **webui** — Flask SPA combining the TIS course selector, transit map, and NCES hover cards. Start with `python -m sustech_survival.webui`.
- **context** — Daily-use snapshot for AI agents: date, week, next deadlines, exams, class-now, weather, AQI.
- **papers** — Academic paper search and fetch across CrossRef, CNKI, WoS, and RSC.

---

## Installation

```bash
pip install git+https://github.com/dumixthestpd/sustech-survival.git
```

Optional extras:

```bash
pip install "sustech-survival[cli]"        # `sustech` unified CLI dispatcher
pip install "sustech-survival[webui]"      # Flask SPA (TIS + transit + NCES)
pip install "sustech-survival[playwright]" # Legacy BB file scraper
pip install "sustech-survival[all]"         # Everything
```

---

## Quick start

### 1. Install

```bash
pip install "sustech-survival[webui]"
```

### 2. First import — verify auth

```python
import sustech_survival as sustech

sustech.sso.BBAuth().ensure()   # prompts for credentials on first run
print("Blackboard session OK")
```

### 3. Daily-use snapshot (built for AI agents)

```python
from sustech_survival.context import Context

ctx = Context(level="normal")   # terse / normal / verbose
print(ctx.to_str())
# → Today is [2026-07-04], [Saturday]
# → Next BB deadline: [Experiment 5] — Due in 3 days
# → Next TIS exam: [...final...]
```

### 4. Start the web UI

```bash
python -m sustech_survival.webui
```

Open `http://localhost:61019` in your browser. You get:
- TIS course selector with conflict-free scheduling
- Transit map with live bus GPS
- NCES hover cards on every course

---

## Related projects

- **[sustech-calendar](https://github.com/dumixthestpd/sustech-calendar)** — SUSTech academic calendar (semesters, workdays, holidays). Planned as a dependency of `tis`, `context`, and other time-aware modules.

---

## Architecture

```
sustech_survival/
├── bb/                ← Blackboard Learn
├── tis/               ← Teaching Information System (TIS)
│   └── classroom/     ← TIS classroom inquiry + venue-borrow (cdjy)
├── lib/               ← SUSTech Library (Primo)
├── sso/               ← Shared auth backbone (CAS + Shibboleth)
├── pms/               ← Campus Printing System
├── transit/           ← Bus + campus map (we built)
├── faculty/           ← Faculty directory (we built)
├── selectcourse/      ← TIS course selection helper (we built)
├── booking/           ← E-Hall (ehall.sustech.edu.cn)
├── ws/                ← SUSTech Global (international programs)
├── context/           ← Daily-use snapshot (we built)
├── nces/              ← Niuwa Curriculum Evaluation System
├── papers/            ← CrossRef / CNKI / WoS / RSC (we built)
├── exceptions.py
└── webui/             ← Flask SPA (we built): TIS + transit + NCES
```

---

## Debugging

The fastest way to iterate on the codebase is to install in dev mode against a working tree and run pytest with live credentials.

```bash
git clone https://github.com/dumixthestpd/sustech-survival
cd sustech-survival
pip install -e ".[all,playwright]"
playwright install chromium

# Unit tests (mocked, fast)
python -m pytest tests/ -v

# Live tests (require real BB/TIS auth — see tests/ for setup)
python -m pytest tests/ -v --live
```

---

## Todo

- [ ] Better localization (cleanly differentiate EN vs CN)
- [ ] Campus canteen daily food notice
- [ ] NCES comment summarization (when an API key is configured; also achievable via a skill doc)

---

## About the dev

This module is developed by **dumixthestpd**, a non-CS undergraduate student (ID 12413021) at SUSTech, who only controls the macroscopic design. 99% of this module is agent-written and we're aware of the problematic code quality. We welcome more students to join us and contribute — contact me via SUSTech edu mail, and further info on joining the dev will be provided. PRs are also welcome.

---

## Credits

Standing on the shoulders of:

- **[xCipHanD/SUSTech_AutoScheduler](https://github.com/xCipHanD/SUSTech_AutoScheduler)** — primary reference for the TIS course data model and time code parsing; their bug list taught us what to fix in our own scheduler.
- **[lethal233/sustech-tis-converter](https://github.com/lethal233/sustech-tis-converter)** — early exploration of TIS REST endpoints.
- **[Fros1er/SUSTechTISHelper](https://github.com/Fros1er/SUSTechTISHelper)** — TIS helper utilities.
- **[SUSTech-CRA/awesome-sustech-service-tools](https://github.com/SUSTech-CRA/awesome-sustech-service-tools)** — curated list of SUSTech service tools and API references.

See [CREDITS.md](./CREDITS.md) for the full list and known-bug catalog.

---

## License

[PolyForm Noncommercial License 1.0.0](./LICENSE) — non-commercial use only, share-alike, preserve attribution.