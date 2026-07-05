# sustech-survival

> SUSTech academic systems toolkit — Blackboard, TIS, Library, PMS, transit, papers, course evaluation, faculty, classroom booking, and SSO for the entire `sustech.edu.cn` ecosystem.

```text
$ pip install sustech-survival
```

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](./LICENSE)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

---

## Why

SUSTech runs a stack of academic systems (Blackboard, TIS, the SSO gateway, the library catalogue, transit, course evaluations, faculty lookup, classroom booking, paper databases). Most are reachable from the terminal but each has its own auth handshake, its own quirks, and its own "this is what the form actually does" discovery cost. `sustech-survival` is the unified toolkit that knows all of that.

Use it from Python or from the CLI. The same authentication, the same request session, the same result types — across every system.

---

## Features

- **Blackboard** — assignment deadlines, course/contents tree, file upload (REST *and* legacy Playwright paths), gradebook + attempt history, course material download.
- **TIS (教学信息服务)** — exam schedule, course schedule + section solver, grades, evaluations, schedule index for the SPA backend.
- **Library (lib.sustech.edu.cn)** — book + room search (form-POST based, no JavaScript required).
- **SSO (CAS + Shibboleth)** — one auth framework, per-system authorizers. Headless CAS re-auth works around the py3.12 `LegacyAdapter` regression.
- **Papers** — CNKI, Web of Science, RSC search/fetch wrappers with the per-database auth handshakes.
- **PMS (联创打印)** — campus print queue (write + status + history).
- **Transit** — bus schedule, live bus GPS, campus map web UI (MapLibre + PMTiles, port 61019).
- **Faculty / Classroom / Booking / Selectcourse** — the SUSTech admin sub-apps, all driven by the same SSO + REST pattern.
- **Context** — single object that surfaces "what's happening right now": date/week/holiday, next BB deadline, next TIS exam, next course evaluation, class-in-session, library open/closed, weather, AQI. Time-perspective via `Context(dt=...)` for testing or "what would I have seen last week".
- **Course evaluation (NCES)** — student-built community evaluation platform integration.

---

## Installation

```bash
# Directly from GitHub (latest)
pip install git+https://github.com/dumixthestpd/sustech-survival.git

# Or from PyPI
pip install sustech-survival

# With the legacy BB Playwright submitter + file downloader
pip install "sustech-survival[playwright]"
playwright install chromium

# With the TIS course-grid SPA backend
pip install "sustech-survival[flask]"

# With everything
pip install "sustech-survival[all]"
```

The package is **one module** by design. Submodules (bb, tis, lib, sso, papers, pms, transit, faculty, classroom, booking, selectcourse, ws, context, nces, quickcontext) are *equal* in priority — none is more important. Pick the ones you need; ignore the rest.

---

## Quick start

### From Python

```python
import sustech_survival as sustech

# Auth (auto-refreshes on first call)
sustech.sso.BBAuth().ensure()

# BB: list your courses + upcoming deadlines
for cid, name in sustech.bb.courses.list_courses():
    print(f"  {name}  ({cid})")
sustech.bb.ddl(days=14)   # prints the upcoming-deadlines table

# Submit a homework file (REST, no Playwright)
from pathlib import Path
result = sustech.bb.submit_assignment_rest(
    "8328",                              # course_id
    "610821",                            # content_id
    Path("/tmp/12413021-段斯宸-Experiment 5 (Aspirin).pdf"),
    name_override="12413021-段斯宸-Experiment 5 (Aspirin).pdf",
    dry_run=True,                        # set False to actually submit
)
print(result.message)                    # SubmitResult: .ok, .is_duplicate, .destination_url, .message
```

### From the CLI

```bash
# Course/contents + upcoming deadlines
sustech-bb courses
sustech-bb deadlines --days 7

# Submit a file (dry-run by default; pass --yes to go live)
sustech-bb submit 610821 /tmp/hw.pdf --course 8328 --yes

# TIS exam schedule
sustech-tis exams
sustech-tis exams --export csv

# Context — "what's happening right now" in three tiers
sustech-context --level terse       # ≤1ms, no I/O
sustech-context --level normal      # adds next deadline + eval + exam
sustech-context --level verbose     # + weather, AQI, library
sustech-context --level normal --dt 2026-05-12T10:00:00  # time-travel for testing
```

### Time-perspective (testing & "what if?")

The `Context` class lets you simulate any moment. Useful for tests in summer holiday (no live data) and for asking "what would I see in week 14?":

```python
from datetime import datetime
from zoneinfo import ZoneInfo
from sustech_survival.context import Context

# "What was my context on 2026-05-29?"
ctx = Context(level="normal", dt=datetime(2026, 5, 29, 14, 30, tzinfo=ZoneInfo("Asia/Shanghai")))
print(ctx.to_str())
# → "Today is [2026-05-29], [Friday]"
# → "According to SUSTech academic calendar, this is [Week 14 of 2026 Spring]"
# → "Next BB deadline: [...] — Due in 3 days"
# → "Next TIS exam: [...]"
```

The module-level `OVERRIDE_TIME` does the same globally for the lifetime of the process.

---

## API reference (selected)

All submodules expose a flat namespace. The 80/20 surface:

| Function | Purpose | Returns |
|---|---|---|
| `bb.courses.list_courses()` | List enrolled courses | `[(course_id, name), ...]` |
| `bb.ddl(days=7, course_id=None)` | Print upcoming deadlines | prints table |
| `bb.submit_assignment_rest(course_id, content_id, file_path, ...)` | REST submit (no Playwright) | `SubmitResult` |
| `bb.submit_assignment(course_id, content_id, file_paths, ...)` | Legacy Playwright submit | `SubmitResult` |
| `bb.download.download_content(content_id, out_dir=...)` | Download course materials | `[path, ...]` |
| `tis.exams.run(export=None)` | Print or export exam schedule | prints / writes CSV |
| `tis.schedule.week_schedule(week)` | TIS section data for a week | `[entry, ...]` |
| `sso.BBAuth().ensure()` | Validate or refresh BB session | `(ok: bool, reason: str)` |
| `sso.TISAuth().ensure()` | Validate or refresh TIS session | `(ok: bool, reason: str)` |
| `context.Context(level="normal")` | The "right now" snapshot | `Context` object with `.date`, `.week`, `.class_now`, `.next_deadline`, `.next_exam`, `.next_eval`, `.weather`, `.aqi`, `.library_status`, ... |
| `papers.search.search_and_fetch(queries=[...])` | Cross-database paper search | `SearchResult` |

### `SubmitResult` (replaces the old `(ok, msg)` tuple)

```python
from sustech_survival.bb.result import SubmitResult, SubmitStatus, success, failure, duplicate, dry_run

# Construct
r = success(
    "Submitted OK. destinationUrl: ...",
    destination_url="/webapps/assignment/.../mode=DEFAULT",
    staged_path=Path("/var/folders/.../bb_submits/x.pdf"),
)

# Check status
if r:                                 # True for SUCCESS and DRY_RUN
    print(r.message)
elif r.is_duplicate:                  # explicit property for the dedup case
    print("Already submitted")
else:                                 # FAILURE
    print(f"Failed: {r.message}, reason={r.diagnostics.get('reason')}")

# Match for exhaustive handling
match r.status:
    case SubmitStatus.SUCCESS:  ...
    case SubmitStatus.FAILURE:  ...
    case SubmitStatus.DUPLICATE: ...
    case SubmitStatus.LATE_BLOCKED: ...
    case SubmitStatus.DRY_RUN: ...
```

`result.to_tuple()` is the backwards-compat shim that returns the legacy `(ok, msg)` shape. New code should use the dataclass fields directly.

---

## Architecture

The package is **one module by design** — never split into separate pip packages. The reason: every submodule shares the SSO + session + cookie cache, and splitting them creates real problems (auth drift, duplicate cookies, dependency hell).

```
sustech_survival/
├── __init__.py        ← public API: from . import bb, tis, lib, sso, papers
├── bb/                ← Blackboard
├── tis/               ← TIS (教学信息服务)
├── lib/               ← Library
├── sso/               ← CAS + Shibboleth (auth backbone, shared)
├── papers/            ← CNKI / WoS / RSC
├── pms/               ← 联创打印
├── transit/           ← Bus + campus map
├── faculty/           ← 教师信息
├── classroom/         ← 教室借用
├── booking/           ← 预约
├── selectcourse/      ← 选课
├── ws/                ← 外事 programs
├── context/           ← "What's happening right now" (daily-use snapshot)
├── nces/              ← Course evaluation (student-built)
├── quickcontext/      ← DEPRECATED shim → use context
├── exceptions.py      ← Single exception hierarchy (APIError, SessionExpired, NotFound, ...)
└── _version.py
```

The `bb._playwright` module is the only place in the package that imports Playwright. Everything else is pure REST + the headless CAS handshake.

---

## Error model

One exception hierarchy lives in `sustech_survival.exceptions`:

| Class | When |
|---|---|
| `APIError` | Base class. |
| `SessionExpired` | Auth session expired or was revoked. Re-authenticate. |
| `NotFound` | Resource not found (HTTP 404). |
| `NetworkError` | Connection failure (timeout, DNS, refused). |
| `InvalidCredentials` | Login rejected. |
| `PermissionDenied` | Authenticated but not authorized for this resource. |

The BB CLI returns `SubmitResult` (not exceptions) for submission flows — see "When to use exceptions vs SubmitResult" in `docs/bb.md` for the rationale.

---

## Testing

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

Tests in `src/test/` use the **time-perspective feature** of `Context` to simulate semester weeks without depending on live data. The 76+ unit tests pass without network access.

---

## Contributing

PRs welcome. The two ground rules:

1. **The module stays together.** Don't propose extracting a submodule into its own pip package. SSO is shared; splitting it is a regression.
2. **Don't alter live endpoint behavior without real verification.** The URLs, field names, and CSRF patterns in this code are reverse-engineered against live SUSTech systems. If you change a URL, a form field, a header, or a parser, you must run the test against the live system first and document the date. See the `sustech-dev` skill for the endpoint catalog where new findings go.

Code style: black + isort, 100-column. `pyproject.toml` is the source of truth.

---

## License

MIT — see [LICENSE](./LICENSE).
