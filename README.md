[English](README.md) | [简体中文](README_cn.md)

# sustech_survival

<p align="center">
  <img src="src/sustech_survival/resources/logo-full-transparent.svg"
       alt="sustech_survival" width="360">
</p>

`sustech_survival` is a Python module that allows API-level SUSTech service calls. It satisfies everyday needs of SUSTech students including BB, TIS, library, PMS, and more.

By connecting the services at the code level, we simplify the campus systems, offer a shortcut to a personalized campus experience, and — most importantly — welcome AI agents into your campus life.

[![GitHub](https://img.shields.io/badge/github-repo-blue.svg)](https://github.com/dumixthestpd/sustech_survival)
[![Docs](https://img.shields.io/badge/docs-site-blue.svg)](https://dumixthestpd.github.io/sustech_survival/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: PolyForm Noncommercial 1.0.0](https://img.shields.io/badge/license-PolyForm--Noncommercial--1.0.0-orange.svg)](./LICENSE)

---

## Features

### Campus systems

- **Blackboard Learn** (`bb`)
- **Teaching Information System (TIS)** (`tis`)
- **SUSTech Library** (`lib`)
- **Single Sign-On (SSO)** (`sso`)
- **Campus Printing System** (`pms`)
- **SUSTech Global** (`ws`)
- **E-Hall** (`booking`)
- **Niuwa Curriculum Evaluation System (NCES)** (`nces`)

### We built

- **selectcourse**
  - TIS course selection: browse offerings, add/drop, and manage the cart.
- **faculty**
  - Faculty directory: list by department, full-text search, and profile lookup.
- **transit**
  - Campus bus and walking navigation: schedules, live GPS, and route planning.
- **calendar**
  - SUSTech academic calendar with date intelligence: load JSON from the GitHub-hosted `sustech-calendar` repo, resolve (week, weekday) → dates, apply compensatory-day transfer. Online is the canonical source; local override available for in-progress edits.
- **ical**
  - `.ics` export of an enrolled semester. Lives in `selectcourse.ical` and is wired through the webui at `GET /api/tis/ical`.
- **webui**
  - Skin-based Flask web UI. Two skins ship with the package — `default` (English) and `default_zh` (Chinese) — each with the full TIS course selector (search → pick → conflict-free schedule → compare → bid & sync), the transit map, and NCES evals. Skins are self-contained and single-language (no language switching). Start with `python -m sustech_survival.webui serve`.
- **context**
  - Daily-use snapshot for AI agents: date, week, next deadlines, exams, class-now, weather, AQI.
- **papers**
  - Academic paper search and fetch across CrossRef, CNKI, WoS, and RSC.

---

## Quick start

### 1. Install

Extras add heavier optional capabilities:

- `webui` — Flask web UI: `default`/`default_zh` skins with the full TIS course selector + transit map + NCES evals
- `nces` — Anubis PoW solver for NCES listing scrape
- `papers` — cloudscraper for publisher sites that block plain requests
- `playwright` — browser-backed BB download / submit (for UIs that only render in JS)
- `all` — Everything above

This project is **not published to PyPI**. Install directly from GitHub:

```bash
pip install "sustech_survival @ git+https://github.com/dumixthestpd/sustech_survival.git"               # API + CLI only
pip install "sustech_survival[webui] @ git+https://github.com/dumixthestpd/sustech_survival.git"        # + web UI
pip install "sustech_survival[all] @ git+https://github.com/dumixthestpd/sustech_survival.git"          # everything
```

When the install is complete, run

```bash
where sustech
# or
sustech --version
```

to see if it is added to PATH.

### 2. (Optional) Set $SUSTECH_HOME Environmental Variable

`SUSTECH_HOME` holds the value to the home of the module. During the run of the `sustech_survival`, the module creates directory `$SUSTECH_HOME/.sustech_survival/` to hold credentials, webui skins, `config.json`, cache, etc.

```bash
set SUSTECH_HOME=path/to/sustech/home
```

### 3. Authentication

```bash
sustech sso creds set --sid 12410000 --password your-password-here
```



The module accepts credentials in this order:

1. `sustech_survival.sso.cred_set(sid=..., pwd=...)` — a temporary override at
   the root level; the auth instances use these in-memory credentials from that
   line onward.
2. `SUSTECH_CREDENTIALS` environmental variable — the path to a `sid:password`
   file.
3. `~/.sustech_survival/credentials.txt` — the project’s home dot-directory
   default. Format: `sid:password`.

There is **no** automatic `./credentials.txt` lookup in the current working
directory anymore; the home dot-directory is the single on-disk default.


```python
from sustech_survival import sso
sso.cred_set(sid="12410000", pwd="your-password-here")   # in-memory
```

The following command writes the default credentials file
(`~/.sustech_survival/credentials.txt`, or the `SUSTECH_CREDENTIALS` path if
that environment variable is set):

```bash
sustech sso creds set --sid 12410000 --pass 'your-password-here'
# (omit --pass to prompt, hidden; --password also works)
```

Already installed and want to confirm the creds work before a real call:

```bash
sustech sso check                        # validate against CAS
```

### 4. Example use

Two common workflows after setup:

#### Python Example

**Daily snapshot for AI agents:**
,
```python
from sustech_survival.context import Context

ctx = Context(level="normal")   # terse / normal / verbose
print(ctx.to_str())
# → Today is [2026-07-04], [Saturday]
# → Next BB deadline: [Experiment 5] — Due in 3 days
# → Next TIS exam: [...final...]
```

#### CLI Example

**Web UI for human use:**

```bash
sustech webui serve
```

Starts the web UI on its default head at port `20129`.

Use `sustech webui serve --skin <name>` to pick a different installed head.


**Installing Different webui Heads:**

Web UI heads, or skins, are installed into `~/.sustech_survival/skins/`.

```bash
# Copy the built-in head into your home skins dir so you can edit/skin it
sustech webui install default

# Install your own head (a directory that has a manifest.json)
sustech webui install --path /path/to/my-head

# See what's installed
sustech webui skins

# Persist the default skin to my-head in config.json
sustech webui skin set my-head

# Delete a user-installed skin (not the packaged default)
sustech webui skin delete my-head

# Serve a specific installed head by skin name
sustech webui serve --skin my-head

# OR serve a head straight from its directory
sustech webui serve --skin-path /path/to/my-head
```


## Related projects

- **[sustech-calendar](https://github.com/dumixthestpd/sustech-calendar)** — SUSTech academic calendar (semesters, workdays, holidays). The `calendar` module loads its JSON at runtime; online is the canonical source.

- **[sustech-cli](https://github.com/wormforce/sustech-cli)** — TypeScript rewrite of this module's behavioral surface (TIS / Blackboard / WS / PMS / library-booking / eHall booking / papers / NCES). Our repo remains the Python behavioral reference; their `docs/MIGRATION.md` tracks the port.

---

## Architecture

```
sustech_survival/
├── sso/          Official: shared SSO / authorizer backbone (CAS, Shibboleth)
├── bb/           Official: Blackboard Learn
├── tis/          Official: Teaching Information System (TIS)
│   └── classroom/    TIS classroom inquiry + venue-borrow (cdjy)
├── lib/          Official: SUSTech Library (Primo)
│   └── booking/      IC library booking (research rooms)
├── pms/          Official: Campus Printing System
├── ws/           Official: SUSTech Global (international programs)
├── booking/      Official: E-Hall (ehall.sustech.edu.cn)
├── nces/         Official: Niuwa Curriculum Evaluation System
├── transit/      Official: bus schedule + live GPS + campus map data
│
├── selectcourse/ We built: TIS choice helper (browse / add / drop / cart)
│   └── ical.py       .ics export of an enrolled semester
├── faculty/      We built: faculty directory (list / search / profile)
├── context/      We built: daily-use snapshot (date, deadlines, class-now, weather, AQI)
├── calendar.py   We built: academic calendar + date intelligence
├── papers/       We built: scholarly search / fetch (CrossRef, CNKI, WoS, RSC)
├── webui/        We built: skin loader — default/default_zh skins with the full course-selector engine
└── api/          We built: Flask-free JSON contract the webui / a custom skin consumes
```

The `sso` layer is the shared auth backbone: `Authorizer` is the abstract
base, and each service's login is just an `Authorizer` subclass. See the
[Quick start](#2-authentication) for how one handles credentials.

---

## Debugging

The fastest way to iterate on the codebase is to install in dev mode against a working tree and run pytest with live credentials.

```bash
git clone https://github.com/dumixthestpd/sustech_survival
cd sustech_survival
pip install -e ".[all]"

# Unit tests (mocked, fast)
python -m pytest src/test/ -v

# Clear the local on-disk cache (keeps credentials, skins, and config)
sustech cache clear
# or clear one module's cache
sustech cache clear --module tis

# Live tests (require real BB/TIS auth — see tests/ for setup)
python -m pytest src/test/ -v --live
```

## Dev

- [Skin development instructions](docs/dev-instructions/skin-development.md)
- [Documentation layout](docs/README.md)

---

## Todo

- [x] Unified `sustech.sso.Authorizer().ensure()` — collapsed per-system auth into one CAS call.
- [ ] Campus canteen daily food notice
- [ ] NCES comment summarization (when an API key is configured; also achievable via a skill doc)

---

## About the dev

This module is developed by **dumixthestpd**, a non-CS undergraduate student at SUSTech, who only controls the macroscopic design. 99% of this module is agent-written and we're aware of the problematic code quality. We welcome more students to join us and contribute — open an issue to start the conversation. PRs are also welcome. If you'd like to join us, our QQ discussion group is at **980133038**.

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