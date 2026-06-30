# Changelog

All notable changes to **sustech-survival** are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

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
