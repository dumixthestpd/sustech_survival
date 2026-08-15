# Changelog

All notable changes to **sustech-survival** are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed
- **`sustech ws list` / `sustech ws count` TypeErrors**: the Click options
  (`--year`, `--transit-data`) no longer collide with the callback parameters
  (`year_code`, `transit_data_dir`). The three broken unified-CLI commands
  (`sustech ws list`, `sustech ws count`, `sustech webui serve`) now run.
- **`sustech_survival.ws.programs` module-shadowing bug**: local variable
  `user_token` shadowed the module function `user_token()`, raising
  `UnboundLocalError` in `list_programs()`, `get_count()` and
  `get_program_detail()`. Renamed the local to `tok` so all three work.
- **`sustech webui serve` broken import**: `from .webui.app import run`
  resolved to the wrong package under the `cli/` subtree; now `from ..webui.app`.
- **Broken `sustech-ws` entry point**: `pyproject.toml` pointed
  `sustech-ws = "sustech_survival.ws.cli:cli"` at a non-existent module.
  Added `ws/cli.py` (the 4 `sustech ws` commands) and `ws/__main__.py` so
  `sustech-ws` and `python -m sustech_survival.ws` both work.
- **`python -m sustech_survival.webui serve` now works**: added
  `webui/__main__.py` so the documented module entry point starts the server.

### Added
- **`Semester.current()`** (+ `Season.from_months`): a canonical resolver
  for the live academic term from the current date. Callers that used to
  hardcode `xn="2025-2026", xq="2"` now default to the term active today:
  `selectcourse`, `tis.campus_schedule`, `tis.classroom`, `context.slot_times`,
  `webui` TIS defaults, and the `sustech tis campus-schedule` CLI.
- **Security hardening**: anonymized real account/card values in tests and
  docstrings (`76727`→`100001`, `EED73C02`→`DEADBEEF`, `2024级本科`→`2025级本科`).
- Bumped dev version to `2026.8.16.dev0220` (CST).

### Changed
- **Version scheme**: switched from plain semver (`0.1.0`) to date-based
  dev versions (`YYYY.M.D.devHHMM` in CST) for development builds.
- **`classroom` moved into `tis.classroom`**: the inquiry module (查空
  教室, room occupancy, live per-room schedule) moved from
  `sustech_survival.classroom` to `sustech_survival.tis.classroom`.
  All imports updated across `booking.py`, `selectcourse/schema.py`,
  and test files. Booking (cdjy) was already at `tis.classroom.booking`;
  both inquiry and booking now share one package.
  - Import path: `from sustech_survival.tis.classroom import ...`
  - CLI: `python -m sustech_survival.tis.classroom <command>`

### Added
- **BB REST submitter** (`bb.submit_rest`): file uploads without Playwright.
  Verified end-to-end on 2026-06-08 — a single multipart POST with
  BB's hidden form fields (extracted from the upload form) plus the
  file as `newFile_LocalFile0` and BB's file-picker field set
  (`newFile_attachmentType='L'`, `newFile_fileId='new'`, and four
  `'undefined'` strings). Returns BB's `destinationUrl` JSON.
- **SubmitResult dataclass** (`bb.result`): replaces the previous
  `(ok: bool | None, msg: str)` tuple. `ok=None` for the dup case is
  now an explicit `SubmitStatus.DUPLICATE` + `result.is_duplicate`.
  Backwards-compat shim: `result.to_tuple()` returns the legacy shape.
- **Playwright isolation** (`bb._playwright`): the one Playwright-using
  function in `bb/` (submitting via the JS form flow, scraping
  submitted-file URLs) lives in a dedicated module. `bb/download.py`
  re-exports it so existing callers don't break.
- **`fetch_next_exam` in `context`**: correlates TIS exam schedule
  with the existing `fetch_next_deadline` (BB) and `fetch_next_eval`
  (course evaluation). The `Context` class exposes `next_exam` and
  the `normal`-level dict includes it alongside the other two.
- **`Context` time-perspective**: `Context(dt=...)`, `Context(time=...)`,
  and the module-level `OVERRIDE_TIME` let you simulate any moment
  in the past or future. Tests use this to assert semester-week
  behavior without mocking the clock.

### Changed
- `HomeworkItem.submit()` and `submit_rest()` now return `SubmitResult`
  directly. The old `(ok, msg)` tuple is gone from the public API;
  `to_tuple()` is the migration path.
- `bb.submit_assignment()` and `submit_assignment_rest()` return
  `SubmitResult` instead of the legacy tuple. The CLI wrapper
  `submit_file()` keeps the tuple shape via `to_tuple()` so the
  existing CLI behavior is unchanged.

## [0.0.1] — 2026-05-XX

### Added
- Initial release to the user as an internal OpenClaw skill. All
  SUSTech systems covered: BB, TIS, library, SSO, papers, PMS,
  transit, faculty, classroom, booking, selectcourse, ws, course
  evaluation (nces), context, quickcontext (deprecated).
