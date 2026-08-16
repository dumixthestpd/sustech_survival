[English](README.md) | [绠€浣撲腑鏂嘳(README_cn.md)

# sustech_survival

<p align="center">
  <img src="src/sustech_survival/resources/logo-full-transparent.svg"
       alt="sustech_survival" width="360">
</p>

`sustech_survival` is a Python module that allows API-level SUSTech service calls. It satisfies everyday needs of SUSTech students including BB, TIS, library, PMS, and more.

By connecting the services at the code level, we simplify the campus systems, offer a shortcut to a personalized campus experience, and 鈥?most importantly 鈥?welcome AI agents into your campus life.

[![GitHub](https://img.shields.io/badge/github-repo-blue.svg)](https://github.com/dumixthestpd/sustech_survival)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: PolyForm Noncommercial 1.0.0](https://img.shields.io/badge/license-PolyForm--Noncommercial--1.0.0-orange.svg)](./LICENSE)

---

## Features

### Campus systems

- **Blackboard Learn** (`bb`)
- **Teaching Information System (TIS)** (`tis`)
- **SUSTech Library** (`lib`)
- **Single Sign-On (SSO)** (`sso`) 鈥?shared auth backbone
- **Campus Printing System** (`pms`)
- **SUSTech Global** (`ws`)
- **E-Hall** (`booking`)
- **Niuwa Curriculum Evaluation System (NCES)** (`nces`)

### We built

- **selectcourse** 鈥?TIS course selection: browse offerings, add/drop, and manage the cart.
- **faculty** 鈥?Faculty directory: list by department, full-text search, and profile lookup.
- **transit** 鈥?Campus bus and walking navigation: schedules, live GPS, and route planning.
- **calendar** 鈥?SUSTech academic calendar with date intelligence: load JSON from the GitHub-hosted `sustech-calendar` repo, resolve (week, weekday) 鈫?dates, apply compensatory-day transfer. Online is the canonical source; local override available for in-progress edits.
- **ical** 鈥?`.ics` export of an enrolled semester. Lives in `selectcourse.ical` and is wired through the webui at `GET /api/tis/ical`.
- **webui** 鈥?Flask SPA combining the TIS course selector, transit map, NCES hover cards, and iCal export. Start with `python -m sustech_survival.webui serve`.
- **context** 鈥?Daily-use snapshot for AI agents: date, week, next deadlines, exams, class-now, weather, AQI.
- **papers** 鈥?Academic paper search and fetch across CrossRef, CNKI, WoS, and RSC.

---

## Quick start

### 1. Install

The CLI (`click`) is in core deps 鈥?`pip install git+https://github.com/dumixthestpd/sustech_survival.git` gives you both the Python API and the `sustech` command.

Extras add heavier optional capabilities:

- `webui` 鈥?Flask SPA: TIS course selector + transit map + NCES hover cards
- `nces` 鈥?Anubis PoW solver for NCES listing scrape
- `papers` 鈥?cloudscraper for publisher sites that block plain requests
- `playwright` 鈥?browser-backed BB download / submit (for UIs that only render in JS)
- `all` 鈥?Everything above

```bash
pip install "sustech_survival @ git+https://github.com/dumixthestpd/sustech_survival.git"               # API + CLI only
pip install "sustech_survival[webui] @ git+https://github.com/dumixthestpd/sustech_survival.git"        # + web UI
pip install "sustech_survival[all] @ git+https://github.com/dumixthestpd/sustech_survival.git"          # everything
```

### 2. Authentication

Shared CAS auth backbone lives in `sustech_survival/sso/authorizer.py`.
Every per-system login (BB, TIS, Library, WS, PMS, NCES, Booking, ...) is
just an `Authorizer` subclass 鈥?pick one and call `ensure()`:

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

1. `SUSTECH_CREDENTIALS` env var 鈥?explicit path to a credentials file
2. `~/.config/sustech_survival/credentials.txt` 鈥?XDG-style user config
3. `./credentials.txt` 鈥?current working directory
4. Walk-up from package source 鈥?dev/editable installs

Format: `sid:password`. Sessions are kept **in memory only** 鈥?no `session.json` on disk.

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
# 鈫?Today is [2026-07-04], [Saturday]
# 鈫?Next BB deadline: [Experiment 5] 鈥?Due in 3 days
# 鈫?Next TIS exam: [...final...]
```

**Web UI (most common workflow):**

```bash
python -m sustech_survival.webui
```

Open `http://localhost:61019` 鈥?TIS course selector with conflict-free
scheduling, transit map with live bus GPS, NCES hover cards on every course.

---

## Related projects

- **[sustech-calendar](https://github.com/dumixthestpd/sustech-calendar)** 鈥?SUSTech academic calendar (semesters, workdays, holidays). The `calendar` module loads its JSON at runtime; online is the canonical source.

---

## Architecture

```
sustech_survival/
鈹溾攢鈹€ bb/                鈫?Blackboard Learn
鈹溾攢鈹€ tis/               鈫?Teaching Information System (TIS)
鈹?  鈹斺攢鈹€ classroom/     鈫?TIS classroom inquiry + venue-borrow (cdjy)
鈹溾攢鈹€ lib/               鈫?SUSTech Library (Primo)
鈹?  鈹斺攢鈹€ booking/       鈫?IC library booking (research rooms, etc.)
鈹溾攢鈹€ sso/               鈫?Shared auth backbone (CAS + Shibboleth)
鈹溾攢鈹€ pms/               鈫?Campus Printing System
鈹溾攢鈹€ transit/           鈫?Bus + campus map (we built)
鈹溾攢鈹€ faculty/           鈫?Faculty directory (we built)
鈹溾攢鈹€ selectcourse/      鈫?TIS course selection helper (we built)
鈹?  鈹斺攢鈹€ ical.py        鈫?.ics export (we built)
鈹溾攢鈹€ booking/           鈫?E-Hall (ehall.sustech.edu.cn)
鈹溾攢鈹€ ws/                鈫?SUSTech Global (international programs)
鈹溾攢鈹€ context/           鈫?Daily-use snapshot (we built)
鈹溾攢鈹€ nces/              鈫?Niuwa Curriculum Evaluation System
鈹溾攢鈹€ papers/            鈫?CrossRef / CNKI / WoS / RSC (we built)
鈹溾攢鈹€ calendar.py        鈫?Academic calendar + date intelligence (we built)
鈹溾攢鈹€ exceptions.py
鈹斺攢鈹€ webui/             鈫?Flask SPA (we built): TIS + transit + NCES + iCal
```

---

## Debugging

The fastest way to iterate on the codebase is to install in dev mode against a working tree and run pytest with live credentials.

```bash
git clone https://github.com/dumixthestpd/sustech_survival
cd sustech_survival
pip install -e ".[all]"

# Unit tests (mocked, fast)
python -m pytest src/test/ -v

# Live tests (require real BB/TIS auth 鈥?see tests/ for setup)
python -m pytest src/test/ -v --live
```

---

## Todo

- [x] Unified `sustech.sso.Authorizer().ensure()` 鈥?collapsed per-system auth into one CAS call.
- [ ] Better localization (cleanly differentiate EN vs CN)
- [ ] Campus canteen daily food notice
- [ ] NCES comment summarization (when an API key is configured; also achievable via a skill doc)

---

## About the dev

This module is developed by **dumixthestpd**, a non-CS undergraduate student at SUSTech, who only controls the macroscopic design. 99% of this module is agent-written and we're aware of the problematic code quality. We welcome more students to join us and contribute 鈥?open an issue to start the conversation. PRs are also welcome.

---

## Credits

Standing on the shoulders of:

- **[xCipHanD/SUSTech_AutoScheduler](https://github.com/xCipHanD/SUSTech_AutoScheduler)** 鈥?primary reference for the TIS course data model and time code parsing; their bug list taught us what to fix in our own scheduler.
- **[lethal233/sustech-tis-converter](https://github.com/lethal233/sustech-tis-converter)** 鈥?early exploration of TIS REST endpoints.
- **[Fros1er/SUSTechTISHelper](https://github.com/Fros1er/SUSTechTISHelper)** 鈥?TIS helper utilities.
- **[SUSTech-CRA/awesome-sustech-service-tools](https://github.com/SUSTech-CRA/awesome-sustech-service-tools)** 鈥?curated list of SUSTech service tools and API references.

See [CREDITS.md](./CREDITS.md) for the full list and known-bug catalog.

---

## License

[PolyForm Noncommercial License 1.0.0](./LICENSE) 鈥?non-commercial use only, share-alike, preserve attribution.