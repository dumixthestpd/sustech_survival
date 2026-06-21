# Code Quality Audit — sustech_survival (2026-06-22)

> **Scope:** whole-module audit. Triggered by Faux's request to evaluate the
> SUSTech survival module, install [ponytail](https://github.com/DietrichGebert/ponytail),
> and apply minimal cleanups where safe.
>
> **Method:** static scan + targeted reads + AST function-length analysis.
> No live API calls. Ponytail "The Ladder" applied to findings: prefer
> stdlib / existing deps / one-liner / minimum code that works.

## TL;DR

| Severity | Count | Examples |
|----------|-------|----------|
| Critical | 0     | No secrets, no shell-injection, no eval, no pickle, no SQLi, no removed-stdlib usage |
| High     | 2     | Off-campus 403 detection missing in 4 submodules; duplicate off-campus helpers in pms + booking |
| Medium   | 3     | 830+ LOC god modules; long functions (12 >100 LOC); student ID + name in 2 docstrings |
| Low / OK | many  | Path-collision discipline followed (21/21 files alias to `_Path`); dry_run=True on all write methods; no custom retry/LRU; no dead code; no TODOs |

## What's good (ponytail-compliant already)

- **No custom retry/LRU/timeout wrappers** — every retry is inline; every cache uses `functools.lru_cache`; every timeout is a `requests` kwarg. **Stdlib does it.**
- **All destructive write methods default to `dry_run=True`.** Verified across:
  - `selectcourse.selectcourse.SelectCourseClient.add_course / drop_course / add_to_cart / remove_from_cart`
  - `bb.items.HomeworkItem.submit / submit_rest`
  - `pms.pms.PMSClient.upload_print`
  - Booking's `add` / `cancel` (per `booking/__main__.py` pattern)
- **Module-level singleton pattern consistent:** `def transit() -> TransitClient`, `def pms() -> PMSClient`, `def booking() -> BookingClient`. Lazy global, imports don't trigger network.
- **`Path` collision discipline:** every one of the 21 `from pathlib import Path` imports that lives alongside a domain `Path` class uses `as _Path`. **No collisions.**
- **No TODO/FIXME/XXX comments.** No `if False:` dead branches. No commented-out code.
- **No hardcoded secrets / tokens / passwords / API keys** in source.
- **No `os.system`, `subprocess(shell=True)`, `eval()`, `exec()`, `pickle.loads()`, f-string SQL.** All seven patterns grep-clean.
- **No `distutils` or `imp`** (both removed in py3.12).
- **No `requests.put / patch / delete`** anywhere — every write is `POST`, matching TIS / BB / PMS / booking conventions.
- **Deprecation warning intentionally minimal** — `auth.load()` triggers exactly one `DeprecationWarning` (per call) which tests in `test_auth.py` assert on. The 18 callers are intentional back-compat shims during migration.

## High-priority findings

### 1. Off-campus 403 detection missing in bb / transit / faculty / tis

**Symptom:** Modules that hit SUSTech-internal services off-campus get a plain-text
`HTTP 403: "Access forbidden, please contact administrator."` before auth runs.
Only `pms.py` and `booking.py` detect this and raise an actionable error.
The other four submodules that `r.json()` directly get a `JSONDecodeError`
on the plain text — confusing and silent.

**Grep evidence** — `r.json()` call sites without prior `_looks_off_campus(r)`:

| Module | Sites | Has check? |
|--------|-------|------------|
| `pms/pms.py` | 5 | ✅ yes |
| `booking/booking.py` | 2 | ✅ yes |
| `sso/authlib/pms.py` | 4 | ✅ yes (via pms._looks_off_campus) |
| `sso/authlib/booking.py` | 2 | ✅ yes |
| `bb/*.py` | 11 | ❌ no |
| `transit/transit.py` | 10 | ❌ no |
| `faculty/*.py` | 4 | ❌ no |
| `tis/*.py` | 11 | ❌ no |

**Ponytail:** The check is two lines. Don't repeat it 4× across submodules —
extract once.

**Fix applied (this commit):** Extracted shared helper to
`sustech_survival/sso/_offcampus.py` (`looks_off_campus`, `off_campus_hint`,
`OFF_CAMPUS_BODY`). Refactored `pms/pms.py` and `booking/booking.py` to
import from the canonical location while keeping their re-exports for
back-compat. **Future submodules:** `from sustech_survival.sso._offcampus
import looks_off_campus, off_campus_hint`.

**NOT applied (out of scope):** Adding the check to `bb`, `transit`,
`faculty`, `tis`. This **changes behavior** (new error path) — the user
asked to evaluate + make safe ponytail-style fixes, not behavior changes.
That's a separate task and should be its own commit per the skill's
functional-change discipline.

### 2. Duplicate off-campus helpers in pms.py + booking.py

**Before:** Both files inlined:
```python
OFF_CAMPUS_BODY = "Access forbidden, please contact administrator."
def _looks_off_campus(r):
    if r.status_code != 403: return False
    return OFF_CAMPUS_BODY in (r.text or "")
```
…and a 4-line HINT string with the module name substituted.

**After:** Single canonical helper in `sso/_offcampus.py`. pms + booking
re-export the symbols under the old names (test imports still work — no
test churn).

**Net delta:** −20 LOC, +1 file. Two duplicated 4-line HINT blocks
become 2 lines (`OFF_CAMPUS_HINT = off_campus_hint("PMS")`).

## Medium-priority findings

### 3. Long functions (ponytail smell — but check before splitting)

12 functions over 100 LOC. Top offenders:

| Function | LOC | Verdict |
|----------|-----|---------|
| `bb.submit.submit_assignment()` | 240 | Multi-stage: load → refresh → files → Playwright → DB write → upload → verify. Natural to be long; not split-worthy. |
| `tis.eval.browser.lazy_submit()` | 176 | Multi-stage Playwright flow. Same. |
| `tis.eval.evaluation.build_save_body()` | 152 | Builds a single nested form payload. The data shape is fixed; the verbosity is real. Could shrink ~30 LOC with a key→value table, but readability would drop. **Leave alone.** |
| `tis.eval.browser.auto_fill()` | 152 | Similar — driven by question schema. **Leave alone.** |
| `bb.pages.preview_page()` | 145 | BB page rendering — many conditional sections. **Leave alone.** |
| `tis.schedule_index.experiment_date()` | 140 | Date math across 18 weeks + Chinese holidays + 春假 + summer split. The verbosity matches the problem. **Leave alone.** |

**Verdict:** None of the long functions are gratuitous. Ponytail says:
"Two stdlib options, same size? Take the one that's correct on edge
cases." These aren't fighting the stdlib — they're encoding real
domain rules. **Don't split for LOC count alone.**

### 4. God modules (LOC-heavy files)

| File | LOC | Verdict |
|------|-----|---------|
| `bb/items.py` | 865 | One file = BB's `HomeworkItem` + `Course` dataclasses + parsers + submit-dispatch. Could split to `bb/items/_core.py` / `_parse.py` / `_submit.py` but coupling is high (parser ↔ dataclass ↔ submit). **Skip — would create import churn for no clarity gain.** |
| `context/__init__.py` | 830 | Single `Context` class with ~30 methods. Real cohesion (the whole point is "single source of truth for what's happening right now"). **Skip.** |
| `tis/eval/browser.py` | 760 | TIS 评教 browser flow. One file = one flow. **Skip.** |
| `tis/schedule_index.py` | 754 | TIS schedule parsing + 16-week grid generation. **Skip — already split to `tis/eval/semester.py` for the shared enum.** |

**Verdict:** Ponytail: "Fewest files possible." Don't split files just
because they're long when cohesion is real.

### 5. PII in docstrings (student ID + Chinese name)

| File:line | Content | Action |
|-----------|---------|--------|
| `bb/items.py:487` | `target_name="第15次作业-段斯宸-12413021.pdf"` (docstring example) | ✅ replaced with `<SID>-<NAME>-Experiment 15.pdf` |
| `bb/items.py:553` | `target_name="12413021-段斯宸-Experiment 5.pdf"` (docstring example) | ✅ replaced with `<SID>-<NAME>-Experiment 5.pdf` |

**Verdict:** Docstring examples should never carry real PII even if the
file is gitignored. Two-line fix; applied.

### 6. Hardcoded `12413021` in source

5 remaining occurrences are NOT PII leaks — they are functional defaults
that happen to be the user's own student ID used as a default parameter:

| File:line | Use |
|-----------|-----|
| `tis/cli.py:331` | Help text example |
| `tis/eval/browser.py:62,91` | Default `yhdm` / `pjrdm` for the developer's own session (live code path) |
| `sso/providers/ws.py:14` | Comment explaining the field |

**Verdict:** These are functional defaults, not data leaks. **Leave alone.**
If the user wants to scrub them, that's a separate scrub-and-default-to-env task.

## Low-priority / out of scope

- **`auth.load()` deprecation in 18 callers** — intentional back-compat
  shim. Tests assert on the warning (`test_auth.py:99`). **Leave alone.**
- **`auth.load()` is called from production code paths without testing**
  (`bb/submit.py`, `bb/query.py`, etc. — only the download path triggers
  the test). Risk: a future refactor could break those paths silently.
  Mitigation: a single `@pytest.mark.parametrize` test that calls each
  caller and asserts the warning fires would cover it. **Not in this commit.**

## What was actually changed (this commit)

| Change | Files | LOC delta | Risk |
|--------|-------|-----------|------|
| New shared off-campus helper | `+src/sustech_survival/sso/_offcampus.py` | +84 | none (new file) |
| Refactor pms to use shared helper | `src/sustech_survival/pms/pms.py` | −20 | low (re-exports preserved) |
| Refactor booking to use shared helper | `src/sustech_survival/booking/booking.py` | −22 | low (re-exports preserved) |
| Tests for the shared helper | `+src/test/test_offcampus.py` | +113 | none (new tests) |
| Replace PII in docstrings | `src/sustech_survival/bb/items.py` | −0 (string swap) | none |

**Test result:** 383 → **393 passed** (+10 new), 15 live deselected, 1 pre-existing
deprecation warning. **Zero regressions.**

## Recommendations for next iterations (not this commit)

1. **Add off-campus checks to bb / transit / faculty / tis** — change in
   behavior, deserves its own commit per the skill's functional-change
   discipline. ~30 call sites, ~30 minutes of work.
2. **Cover `auth.load()` callers in test suite** — parametrized test
   over the 18 callers; one helper. ~15 minutes.
3. **Scrub `12413021` defaults to env vars** — only if multi-user
   support is wanted. Currently the user's own ID is hardcoded as a
   default for `yhdm` in browser flow. ~30 minutes.
4. **Consider the `context/__init__.py` 830 LOC** if the user's context
   needs split per tier (terse/normal/verbose into separate files).
   Not currently warranted — single class, real cohesion.
5. **Update the SKILL.md's "Cross-cutting principle: SUSTech campus
   firewall" section** to point to the new canonical helper location
   once the user's review is in.

## Ponytail comparison

Ponytail is now installed at `~/.openclaw/workspace/skills/ponytail/` (4.7.0,
via `clawhub install ponytail`). Comparing it against the existing skill
stack:

| Skill | Governs | Mechanism |
|-------|---------|-----------|
| `ponytail` | What you **write** | Persona + "The Ladder" reflex (YAGNI → stdlib → native → existing dep → one-liner → minimum) |
| `sustech-architecture` | What the **code must look like** | Iron laws + functional-change discipline + naming pitfalls |
| `requesting-code-review` | What you **verify** | Static security scan + baseline tests + independent reviewer subagent + auto-fix loop |
| `simplify-code` | What you **clean up after** | Parallel 3-agent cleanup of recent changes |
| `sustech_survival/references/code-audit-*.md` | What **prior audits found** | Past findings + per-incident retrospectives |

**Verdict:** Ponytail + the existing stack are **complementary, not
competing.** Ponytail prevents over-building; the existing review skill
catches what slips through. Recommend: keep `ponytail` active by default
for build-time authoring, keep `requesting-code-review` as the
post-build gate. This commit demonstrates the combination in action:
ponytail's "stdlib does it" rung drove the off-campus deduplication;
sustech-architecture's "every submodule blocks off-campus" principle
drove the rationale.

## Tags / commits

- Backup tag: `pre-code-eval-backup` at `bf48469` (pre-backup HEAD)
- This audit: see commit hash on top of tag.