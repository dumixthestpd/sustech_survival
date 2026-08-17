[English](README.md) | [简体中文](README_cn.md)

# sustech_survival

<p align="center">
  <img src="src/sustech_survival/resources/logo-full-transparent.svg"
       alt="sustech_survival" width="360">
</p>

`sustech_survival` is a Python module that allows API-level SUSTech service calls. It satisfies everyday needs of SUSTech students including BB, TIS, library, PMS, and more.

By connecting the services at the code level, we simplify the campus systems, offer a shortcut to a personalized campus experience, and — most importantly — welcome AI agents into your campus life.

[![GitHub](https://img.shields.io/badge/github-repo-blue.svg)](https://github.com/dumixthestpd/sustech_survival)
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

The CLI (`click`) is in core deps — `pip install git+https://github.com/dumixthestpd/sustech_survival.git` gives you both the Python API and the `sustech` command.

Extras add heavier optional capabilities:

- `webui` — Flask SPA: TIS course selector + transit map + NCES hover cards
- `nces` — Anubis PoW solver for NCES listing scrape
- `papers` — cloudscraper for publisher sites that block plain requests
- `playwright` — browser-backed BB download / submit (for UIs that only render in JS)
- `all` — Everything above

```bash
pip install "sustech_survival @ git+https://github.com/dumixthestpd/sustech_survival.git"               # API + CLI only
pip install "sustech_survival[webui] @ git+https://github.com/dumixthestpd/sustech_survival.git"        # + web UI
pip install "sustech_survival[all] @ git+https://github.com/dumixthestpd/sustech_survival.git"          # everything
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

**Credentials are resolved with three-way precedence (later wins):**

1. `sustech_survival.sso.cred_set(sid=..., pwd=...)` — in-memory, highest
2. `./credentials.txt` — current working directory
3. `SUSTECH_CREDENTIALS` env var — explicit path to a credentials file

Format: `sid:password`. Sessions are kept **in memory only** — no `session.json` on disk.

```python
from sustech_survival import sso
sso.cred_set(sid="12410000", pwd="your-password-here")   # in-memory, wins
```

**After a plain `pip install`, credentials do NOT ship with the package** — the
package never bundles a `credentials.txt`. Set them with one command
(writes `./credentials.txt` in the working directory, mode 600):

```bash
sustech sso creds set --sid 12410000 --pass 'your-password-here'
# (omit --pass to prompt, hidden; --password also works)
```

Already installed and want to confirm the creds work before a real call:

```bash
sustech sso check                        # validate against CAS, no service binding
python -m sustech_survival.lib.login   # Library Primo (headless CAS login)
sustech pms check                      # verify PMS auth
```

> Note: there is currently NO `sustech <svc> session login|check|refresh`
> subcommand — those shown here historically were not implemented. Use
> `ensure()` / `auth.check()` in Python, or the per-module read commands above.

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

Open `http://localhost:20129` — TIS course selector with conflict-free
scheduling, transit map with live bus GPS, NCES hover cards on every course.

---

## Related projects

- **[sustech-calendar](https://github.com/dumixthestpd/sustech-calendar)** — SUSTech academic calendar (semesters, workdays, holidays). The `calendar` module loads its JSON at runtime; online is the canonical source.

---

## Architecture

```
# Row 1 — OFFICIAL systems (provided by SUSTech; we authenticate against / query them)
sustech_survival/
├── sso/      ← Shared SSO backbone (CAS / Shibboleth; the authorizer layer)
├── bb/       ← Blackboard Learn
├── tis/      ← Teaching Information System (TIS)
│   └── classroom/  ← TIS classroom inquiry + venue-borrow (cdjy)
├── lib/      ← SUSTech Library (Primo)
│   └── booking/   ← IC library booking (research rooms)
├── pms/      ← Campus Printing System
├── ws/       ← SUSTech Global (international programs)
├── booking/  ← E-Hall (ehall.sustech.edu.cn)
├── nces/     ← Niuwa Curriculum Evaluation System
└── transit/  ← official bus schedule + live GPS + campus map data

# Row 2 — WE BUILT (our own modules on top of those systems)
│
├── selectcourse/   ← TIS choice helper (browse / add / drop / cart)
│   └── ical.py     ← .ics export of an enrolled semester
├── faculty/        ← Faculty directory (list / search / profile)
├── context/        ← Daily-use snapshot (date, deadlines, class-now, weather, AQI)
├── calendar.py     ← Academic calendar + date intelligence
├── papers/         ← scholarly search / fetch (CrossRef, CNKI, WoS, RSC)
├── webui/          ← Flask SPA (TIS + transit + NCES + iCal)
└── api/            ← Flask-free JSON contract the webui / a custom skin consumes

# sso / authorizer — simplified inheritance
Authorizer                      (abstract base: ensure/check/refresh, in-memory session, stale detection)
 ├── CASAuthorizer              (CAS 3.0 handshake: fetch execution token → POST creds → exchange ticket)
 │     ├── TISAuth              BASE_URL + SERVICE_URL = TIS
 │     ├── BBAuth               BASE_URL + SERVICE_URL = Blackboard
 │     ├── LibAuth              BASE_URL + SERVICE_URL = Library Primo
 │     ├── WiFiAuth             BASE_URL + SERVICE_URL = campus Wi-Fi gateway
 │     └── NCESAuth             CAS via Keycloak OIDC + cas-proxy (not a plain ticket)
 ├── ShibbolethAuthorizer       (Shibboleth: CNKIAuth, WoSAuth)
 ├── BookingAuth                (ehall authcenter, not plain CAS)
 ├── PMSAuth, ACSAuth, JSTORAuth, IEEEAuth, SpringerAuth, WileyAuth, ScopusAuth, PubMedAuth (direct Authorizer)
 └── WSAuth                     (via WSProvider)
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

This module is developed by **dumixthestpd**, a non-CS undergraduate student at SUSTech, who only controls the macroscopic design. 99% of this module is agent-written and we're aware of the problematic code quality. We welcome more students to join us and contribute — open an issue to start the conversation. PRs are also welcome.

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