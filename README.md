[English](README.md) | [简体中文](README_cn.md)

# sustech-survival

`sustech_survival` is a Python module that allows API-level sustech service calls. it satisfies everyday needs of sustech students including bb, tis, lib, pms and more.

by connecting the services at code level, we allow a simplification of the campus systems, a shortcut to a personalized campus experience and most importantly, facilitates and invites AI-agent assistance into your campus life.

[![GitHub](https://img.shields.io/badge/github-repo-blue.svg)](https://github.com/dumixthestpd/sustech-survival)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: PolyForm Noncommercial 1.0.0](https://img.shields.io/badge/license-PolyForm--Noncommercial--1.0.0-orange.svg)](./LICENSE)

---

## Features

### Campus systems

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

## Quick start

### 1. Install

Pick the extras you actually need:

| Extra | Gives you | When to pick |
|---|---|---|
| (none) | Python module only | You write your own scripts |
| `cli` | `sustech bb`, `sustech tis`, `sustech nces`, ... unified dispatcher | You want a terminal workflow |
| `webui` | Flask SPA: TIS course selector + transit map + NCES hover cards | You want the browser UI |
| `playwright` | Legacy BB file-download scraper | You're on a headless server |
| `all` | Everything above | You don't want to think about it |

```bash
# Pick one — examples:
pip install "sustech-survival[cli]"          # CLI only
pip install "sustech-survival[webui]"        # web UI only
pip install "sustech-survival[all]"          # everything
```

### 2. Authentication (planned — not yet implemented)

> The plan is a single base class at `sustech_survival/sso/authorizer.py`
> that targets SUSTech's CAS directly:
>
> - CAS endpoint: `https://cas.sustech.edu.cn/cas/login`
> - Unified check: `sustech.sso.Authorizer().ensure()`
>
> When this lands, every per-system login (BB, TIS, NCES, ...) collapses
> into one call. Until then, each submodule has its own authorizer and
> you follow that submodule's specific setup. Track progress in the
> Todo section.

### 3. Example use

Two common workflows after setup:

**Daily snapshot for AI agents:**

```python
from sustech_survival.context import Context

ctx = Context(level="normal")   # terse / normal / verbose
print(ctx.to_str())
# → Today is [2026-07-04], [Saturday]
# → Next BB deadline: [Experiment 5] — Due in 3 days
# → Next TIS exam: [...final...]
```

**Web UI (most common workflow):**

```bash
python -m sustech_survival.webui
```

Open `http://localhost:61019` — TIS course selector with conflict-free
scheduling, transit map with live bus GPS, NCES hover cards on every course.

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
- [ ] Unified `sustech.sso.Authorizer().ensure()` — collapse per-system auth into one CAS call (`https://cas.sustech.edu.cn/cas/login`)

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