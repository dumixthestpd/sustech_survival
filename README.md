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

When the install is complete, run

```bash
where sustech
# or
sustech --version
```

to see if it is added to PATH.

### 2. Authentication

Shared CAS auth backbone lives in `sustech_survival/sso/authorizer.py`.
Every per-system login (BB, TIS, Library, WS, PMS, NCES, Booking, ...) is
just an `Authorizer` subclass — the abstract base defines how to check a
session, refresh when expired, and detect a stale response, while each
subclass only sets a few parameters (`BASE_URL`, `SERVICE_URL`) to point at
a specific system. Pick one and call `ensure()`:

```python
from sustech_survival.sso import TISAuth      # any auth subclass works

auth = TISAuth()                       # singleton-per-class
ok, reason = auth.ensure()             # check session, auto-refresh if expired
auth.session.get("/xszykb/querydangqianxnxq")   # use the authenticated session

# Or with a decorator:
from sustech_survival.sso import require_auth

@require_auth(TISAuth)
def my_function(auth=None):
    r = auth.session.get(...)
```

The module accepts credentials in three ways:

1. `sustech_survival.sso.cred_set(sid=..., pwd=...)` — a temporary override at
   the root level; the auth instances use these in-memory credentials from that
   line onward.
2. `./credentials.txt` in the current working directory — the reference used in
   the absence of an override. Format: `sid:password`.
3. `SUSTECH_CREDENTIALS` environmental variable — the path to a `sid:password`
   file.


```python
from sustech_survival import sso
sso.cred_set(sid="12410000", pwd="your-password-here")   # in-memory, wins
```

The following command writes `./credentials.txt` in the working directory:

```bash
sustech sso creds set --sid 12410000 --pass 'your-password-here'
# (omit --pass to prompt, hidden; --password also works)
```

Already installed and want to confirm the creds work before a real call:

```bash
sustech sso check                        # validate against CAS
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
sustech webui serve
```

Starts the web UI on its default head at port `20129`. (`sustech webui`
alone just prints help — the server only starts with an explicit `serve`.)
Use `sustech webui serve --skin <name>` to pick a different installed head
(see [Installing Different webui Heads](#installing-different-webui-heads)).

---


## Installing Different webui Heads

The web UI is a *head* — a self-contained skin folder (with a `manifest.json`)
that the `webui` serves. The module ships only the `default` fallback head;
every other head is **installed into `~/.sustech_survival/skins/`** and served
from there — that home dot-directory is the real skin store.

```bash
# 1. Copy the built-in head into your home skins dir so you can edit/skin it
sustech webui install default

# 2. Install your own head (a directory that has a manifest.json)
sustech webui install --path /path/to/my-head

# 3. See what's installed (name + version; the on-disk location is an
#    implementation detail and is not shown)
sustech webui skins

# 3b. Persist the default skin — saved to ~/.sustech_survival/config.json
#     (webui.skin) and used by `sustech webui serve` when no --skin is given
sustech webui set-skin my-head

# 4. Serve a specific installed head (or the configured default)
sustech webui serve --skin my-head

# 4b. OR serve a head straight from its directory — no install/copy
sustech webui serve --skin-path /path/to/my-head
```

Installed heads are copied into `~/.sustech_survival/skins/` (override the
whole tree with `$SUSTECH_HOME`). `--skin-path <dir>` serves a head directly
from its own directory without copying (e.g. one under version control).

The `sustech_survival.api` Flask-free JSON contract is what a custom head
consumes — see [Web UI](docs/en/webui.md) and the loader
(`src/sustech_survival/webui/loader.py`).

---

## On-disk storage (one home dot-directory)

Everything `sustech_survival` persists outside the package lives in ONE
user dot-directory, `~/.sustech_survival/` (managed by
`sustech_survival._cache`):

```
~/.sustech_survival/
├── cache/<module>/      # disposable caches + per-module working files
│                        #   (calendar, bb, classroom, selectcourse, ...)
├── skins/               # user-installed webui heads
├── credentials.txt      # default shared credentials (sid:password)
└── config.json          # the one user-editable settings file
```

- **Changeable home root**: set `$SUSTECH_HOME` to relocate the whole tree
  (e.g. `SUSTECH_HOME=D:/data` → everything under `D:/data/.sustech_survival/`).
  `$SUSTECH_CONFIG_DIR` overrides the dot-directory directly;
  `$SUSTECH_CACHE_DIR` relocates only the cache.
- **Module caches** are uniformly created via
  `sustech_survival._cache.cache_path("<module>", ...)` and land under
  `cache/<module>/` — no module hand-rolls its own location. Per-module
  working files (e.g. BB upload staging) live in the same tree, so
  `_cache.clear_cache("<module>")` clears exactly that module's cache —
  there is no separate scratch/tmp dir.
- **`config.json`** is read with `_cache.load_config()`. Example:
  ```json
  {
    "downloads_dir": "D:/bb-downloads",
    "webui": { "skin": "sustech_neon" }
  }
  ```
  `webui.skin` is the default web-ui skin (set with `sustech webui set-skin`);
  `downloads_dir` (or `bb.downloads_dir`) is the BB download output (else
  `~/.sustech_survival/downloads/BB-content|BB-submissions`), never the OS
  Downloads folder. Explicit `--output` / `out_dir` paths still win.

## Related projects

- **[sustech-calendar](https://github.com/dumixthestpd/sustech-calendar)** — SUSTech academic calendar (semesters, workdays, holidays). The `calendar` module loads its JSON at runtime; online is the canonical source.

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
├── webui/        We built: Flask SPA (TIS + transit + NCES + iCal)
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