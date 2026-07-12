[English](README.md) | [简体中文](README_cn.md)

# sustech-survival

`sustech_survival` is a Python module that allows API-level SUSTech service calls. It satisfies everyday needs of SUSTech students including BB, TIS, library, PMS, and more.

By connecting the services at the code level, we simplify the campus systems, offer a shortcut to a personalized campus experience, and — most importantly — welcome AI agents into your campus life.

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
- **calendar** — SUSTech academic calendar with date intelligence: load JSON from the GitHub-hosted `sustech-calendar` repo, resolve (week, weekday) → dates, apply compensatory-day transfer. Online is the canonical source; local override available for in-progress edits.
- **ical** — `.ics` export of an enrolled semester. Lives in `selectcourse.ical` and is wired through the webui at `GET /api/tis/ical`.
- **webui** — Flask SPA combining the TIS course selector, transit map, NCES hover cards, and iCal export. Start with `python -m sustech_survival.webui serve`.
- **context** — Daily-use snapshot for AI agents: date, week, next deadlines, exams, class-now, weather, AQI.
- **papers** — Academic paper search and fetch across CrossRef, CNKI, WoS, and RSC.

---

## Quick start

### 1. Install

The CLI (`click`) is in core deps — `pip install sustech-survival` gives you both the Python API and the `sustech` command.

Extras add heavier optional capabilities:

- `webui` — Flask SPA: TIS course selector + transit map + NCES hover cards
- `playwright` — Legacy BB file-download scraper
- `nces` — Anubis PoW solver for NCES listing scrape
- `papers` — cloudscraper for publisher sites that block plain requests
- `all` — Everything above

```bash
# Pick one — examples:
pip install "sustech-survival"               # API + CLI only
pip install "sustech-survival[webui]"        # + web UI
pip install "sustech-survival[all]"          # everything
```

### 2. Authentication

Shared CAS auth backbone lives in `sustech_survival/sso/authorizer.py`.
Every per-system login (BB, TIS, Library, WS, PMS, NCES, Booking, ...) is
just an `Authorizer` subclass — pick one and call `ensure()`:

```python
from sustech_survival.sso import TISAuth

auth = TISAuth()                       # singleton-per-class
ok, reason = auth.ensure()             # check session, auto-refresh if expired
auth.session.get("/xszykb/querydangqianxnxq")   # use the authenticated session

# Or with a decorator:
from sustech_survival.sso import require_auth

@require_auth(TISAuth)
def my_function(auth=None):
    r = auth.session.get(...)
```

Credentials are resolved in this order (first match wins):

1. `SUSTECH_CREDENTIALS` env var — explicit path to a credentials file
2. `~/.config/sustech-survival/credentials.txt` — XDG-style user config
3. `./credentials.txt` — current working directory
4. Walk-up from package source — dev/editable installs

Format: `sid:password`. Sessions are kept **in memory only** — no `session.json` on disk.

Each module's CLI exposes `session login | check | refresh`:

```bash
sustech bb session login
sustech tis session refresh
python -m sustech_survival.lib.login   # Library Primo
```

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

- **[sustech-calendar](https://github.com/dumixthestpd/sustech-calendar)** — SUSTech academic calendar (semesters, workdays, holidays). The `calendar` module loads its JSON at runtime; online is the canonical source.

---

## Architecture

```
sustech_survival/
├── bb/                ← Blackboard Learn
├── tis/               ← Teaching Information System (TIS)
│   └── classroom/     ← TIS classroom inquiry + venue-borrow (cdjy)
├── lib/               ← SUSTech Library (Primo)
│   └── booking/       ← IC library booking (research rooms, etc.)
├── sso/               ← Shared auth backbone (CAS + Shibboleth)
├── pms/               ← Campus Printing System
├── transit/           ← Bus + campus map (we built)
├── faculty/           ← Faculty directory (we built)
├── selectcourse/      ← TIS course selection helper (we built)
│   └── ical.py        ← .ics export (we built)
├── booking/           ← E-Hall (ehall.sustech.edu.cn)
├── ws/                ← SUSTech Global (international programs)
├── context/           ← Daily-use snapshot (we built)
├── nces/              ← Niuwa Curriculum Evaluation System
├── papers/            ← CrossRef / CNKI / WoS / RSC (we built)
├── calendar.py        ← Academic calendar + date intelligence (we built)
├── exceptions.py
└── webui/             ← Flask SPA (we built): TIS + transit + NCES + iCal
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
python -m pytest src/test/ -v

# Live tests (require real BB/TIS auth — see tests/ for setup)
python -m pytest src/test/ -v --live
```

---

## Todo

- [x] Unified `sustech.sso.Authorizer().ensure()` — collapsed per-system auth into one CAS call.
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