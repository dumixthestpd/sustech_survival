---
name: sustech_survival
description: SUSTech academic systems — TIS schedule, Blackboard, Google Calendar sync, library search. Use for anything related to SUSTech courses, BB, TIS, or academic tasks.
publish: personal
---

# SUSTech Survival

A toolkit for SUSTech survival, supports CLI commands and Python API

SUSTech academic systems: TIS, Blackboard, calendar sync, library search.

## Python Package

```python
import sustech_survival as sustech

# Auth is fully automatic — never call session functions manually
sustech.bb.courses()          # enrolled courses (auto-authenticates as needed)
sustech.bb.search(text='hw')  # search BB items (auto-authenticates as needed)
sustech.bb.ddl(days=14)       # upcoming deadlines across all enrolled courses
sustech.lib.login()            # Library CAS login
sustech.lib.check()            # check session validity
sustech.tis.courses()         # TIS course schedule
sustech.tis.grades()          # TIS grades + GPA (official SUSTech 4.0 scale)

# Paper research — search academic papers and download PDFs
sustech.papers.search_and_fetch(
    queries=["electrochromic polymer WPU", "solid state electrochromic device"],
    dest_dir="papers/",
    fetch_pdfs=True,
    openaccess_only=False,
    min_year=2020,
)
```

**Auth (`sso.py`):** `Authorizer` base class with `check()`, `refresh()`, `login()`, `ensure()`. All BB operations auto-refresh the session via CAS when needed — agents never call session functions manually.

## CLI

```bash
# TIS — grades and schedule
python3 -c "from sustech_survival.tis.grades import run; run()"
python3 -c "from sustech_survival.tis.courses import run; run()"

# BB — deadlines and course materials
python3 -c "from sustech_survival.bb import ddl; ddl(days=14)"

# Auth check
python3 sustech.py bb session check
python3 sustech.py lib login
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
├── rsc/                        # RSC publishing via CARSI/Shibboleth SSO
├── sso/                        # SSO auth infrastructure (CAS, Shibboleth, cloudscraper)
├── schedule2gog/               # TIS -> Google Calendar sync
└── resources/                  # External SUSTech resources (handbooks, maps, portals)
    └── SKILL.md
```

## Architecture

- **SSO (`sso/`):** `Authorizer` base class, `CASAuthorizer` mixin. `check()`, `refresh()`, `login()`, `ensure()`.
  - Credentials: `from sustech_survival.sso import Credentials` — reads `credentials.txt` at skill root
  - Public attributes after `login()`: `auth.browser`, `auth.page`, `auth.ctx`
- **BB (`bb/`):** `BBAuth` inherits `CASAuthorizer`. Session at `bb/session.json`. Auto-refresh on 401.
- **TIS (`tis/`):** Same CAS auth pattern. Grades API: `POST https://tis.sustech.edu.cn/cjgl/grcjcx/grcjcx`
- **Lib (`lib/`):** CAS auth for Primo. Session at `lib/session.json`
- **RSC/WoS/CNKI (`sso/authlib/`):** `*Authorizer` classes with Playwright headless login. CARSI/Shibboleth SSO. No session file — login each time.

## RSC Shibboleth SSO (2026-05-19)

**RSC (Royal Society of Chemistry) supports CARSI/Shibboleth federated SSO.** Works without VPN or cloudscraper.

### Login Flow
RSC WAYF → China (CARSI) Federation → Southern University of Science and Technology → SUSTech CAS login → IdP consent → RSC

### Direct Login URL (bypasses WAYF)
```
https://www.rsc.org/rsc-id/account/checkfederatedaccess?instituteurl=https%3A%2F%2Fidp.sustech.edu.cn%2Fidp%2Fshibboleth&returnurl=https%3A%2F%2Fpubs.rsc.org&platformID=1c576962-b994-4139-a186-8120433be7b7
```

### Key Entity IDs
- RSC SP: `https://shib.rsc.org/shibboleth`
- SUSTech IdP: `https://idp.sustech.edu.cn/idp/shibboleth`
- SUSTech CAS: `https://cas.sustech.edu.cn/cas/login`

### Usage
```python
from sustech_survival.sso.authlib.rsc import RSCAuthorizer
from sustech_survival.sso import Credentials  # reads credentials.txt

auth = RSCAuthorizer()
ok = auth.login()          # reads credentials automatically, headless=True
# or: ok = auth.login(username="12413021", password="pass", headless=True)
if ok:
    auth.page.goto("https://pubs.rsc.org/en/search?q=electrochromic")
    # ... browse ...
    auth.browser.close()
```

### No Session File — Login Every Time
Unlike BB/TIS/Lib, RSC auth does NOT save cookies to disk. Each session requires fresh login. This is intentional (simpler, more secure).

### ACS/Wiley/Nature — Try the Same Pattern
Most publishers support CARSI/Shibboleth. The flow is identical:
1. Find "Log in via your home institution" / Shibboleth WAYF on the publisher site
2. Navigate directly to their Shibboleth check URL with SUSTech IdP entityID
3. CAS login → IdP consent → publisher session

ACS CARSI/Shibboleth URL: `https://pubs.acs.org/action/ssoRequest?applications=...

## Web of Science — CARSI/Shibboleth ✅

WoS uses Clarivate's access portal → CARSI DS WAYF → SUSTech CAS. Flow handled by `WoSAuth`.

### Login Flow
`webofscience.com` → select "CHINA CERNET Federation" → CARSI DS WAYF → search SUSTech → SUSTech CAS → IdP consent → WoS

### CARSI Provider — `sso/providers/carsi.py`
Reusable CARSI DS WAYF handler. Used by `WoSAuth`, adaptable for other CARSI participants.

Key: `login_via_carsi(page, idp_entity_id, idp_display_name, ...)`
- Fills search input, clicks institution `<li>`, submits form
- Waits for redirect to IdP

### Usage
```python
from sustech_survival.sso.authlib.wos import WoSAuth

auth = WoSAuth()
ok = auth.login()   # headless, reads credentials.txt
if ok:
    auth.page.goto("https://www.webofscience.com")
    auth.browser.close()
```

## CNKI — FSSO/Shibboleth ✅

CNKI (中国知网) uses its own FSSO Shibboleth system. SUSTech entityID is the same as the general IdP.

### Login Flow
`fsso.cnki.net/Shibboleth.sso/Login?entityID=...` → SUSTech CAS → IdP consent → CNKI

### Usage
```python
from sustech_survival.sso.authlib.cnki import CNKIAuth

auth = CNKIAuth()
ok = auth.login()   # headless, reads credentials.txt
if ok:
    auth.page.goto("https://navi.cnki.net/")
    auth.browser.close()
```

## Principles

**The skill is a shared tool for all SUSTech students.**
- Personal data (credentials, session files) is gitignored, never committed
- Course-specific content stays in your workspace, not in the skill
- The skill ships only generic infrastructure that any SUSTech student can use

## Course Materials

Course-specific materials (papers, assignments, notes) live in your **workspace**, not in the skill.

```
~/.openclaw/workspace/
```

This separation ensures the skill is reusable across all SUSTech students regardless of major or courses.

## Database Access Summary

| Database | Status | Method |
|---|---|---|
| **RSC** | ✅ Works | Shibboleth direct |
| **WoS** | ✅ Works | CARSI → SUSTech CAS |
| **CNKI** | ✅ Works | FSSO/Shibboleth |
| arXiv | ✅ Works | Direct download |
| **ScienceDirect** | ❌ Blocked | Cloudflare |
| **Wiley** | ❌ Blocked | Cloudflare |
| **IEEE Xplore** | ❌ Blocked | Error 418 |
| **Scopus** | ❌ Blocked | Cloudflare |
| **Nature** | ❌ Blocked | No Shibboleth |
| **IOP** | ❌ Blocked | Radware Bot Manager |
| **APS** | ❌ Blocked | Cloudflare |
| **T&F** | ❌ Blocked | Cloudflare |
| **Emerald** | ❌ Blocked | Cloudflare |
| **Springer** | ❌ Likely blocked | Cloudflare |

Western publishers (Elsevier, Wiley, Springer Nature, IEEE, etc.) all use Cloudflare or custom bot detection that blocks headless browsers. Only databases with standard Shibboleth/CARSI without Cloudflare work.

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
- [x] ~~**Assignment deadline tracker**~~ — done: `sustech_survival/bb/_ddl.py` — REST API (fast) + BB portal page fallback for course IDs. Finds "我的作业" content per course, parses due dates including recurring (每周六晚12点).
- [x] ~~**TIS grade + course companion**~~ — done: `tis/grades.py` (grades + GPA) and `tis/courses.py` (schedule). Uses official SUSTech GPA table.

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