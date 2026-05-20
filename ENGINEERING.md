# Engineering Log

## 2026-05-21

### BB Session — BBAuth Wrong Base Class

**Bug:** `bb/session.py` created `BBAuth` via:
```python
BBAuth = _make_bbauth(_sso.Authorizer)  # WRONG
```

`Authorizer.get_ticket_cookies()` raises `NotImplementedError`. This caused:
- `refresh()` silently failed every time it ran
- `login()` fell back to `Authorizer.login()` which opens a visible browser for manual typing
- Session cookies expired and never auto-refreshed
- Bots using BB reported login failures and submission problems

**Fix:** Change to `CASAuthorizer`:
```python
BBAuth = _make_bbauth(_sso.CASAuthorizer)  # CORRECT
```

MRO after fix: `BBAuth → CASAuthorizer → Authorizer → ABC → object`

**Verified:**
- Headless CAS login: `get_ticket_cookies()` returns `TGC + JSESSIONID + s_session_id` in ~6s
- Session stored at `credentials.txt`-adjacent `bb/session.json`
- Submit works: submitted test file to CH103 Fall 2024 (`content_id=490876`, past course) — "复查提交历史记录" confirmation page shown

**Commit:** `bfa36c7`

---

### BB Submit — Verified Working

Submission flow (`bb/submit.py`) verified end-to-end on past course CH103 General Chemistry Fall 2024 (`course_id=6361`, `content_id=490876`):

```
File in JS: test_submit.txt|169     ✓
Files via override: 1               ✓
Table rows: 1, link_titles: [...]  ✓
submit_form: True                   ✓
Result: True                        ✓
"复查提交历史记录: Homework----Chapter 3" ✓
```

**Dedup check:** Correctly caught re-submit attempt.

**BB policy note:** After a submission exists, `action=newAttempt` redirects to "复查提交历史记录" instead of showing the upload form. BB only allows one submission per assignment slot. This is BB's own behavior, not a code bug.

---

## 2026-05-20

### SSO Module Consolidation

**Problem:** `Credentials` class was a separate object duplicating what `Authorizer` already did. Every authorizer subclass had redundant property overrides for `creds_file`, `submodule_dir`, and `session_file`. `BBAuth` overrode `creds_file` to `bb/credentials.txt` instead of the shared skill-root credentials file.

**Changes:**

1. **New `sso/authorizer.py`** — canonical home for `Authorizer(ABC)`. Added `.username` and `.password` as direct convenience properties (wrappers over `read_creds()`). All credential access now lives on the authorizer itself.

2. **`sso/base.py`** — converted to a re-export shim for backwards compatibility.

3. **`sso/__init__.py`** — `Credentials = Authorizer` alias so old code doesn't break.

4. **Removed redundant overrides** from `authlib/bb.py`, `authlib/tis.py`, `authlib/lib.py`, `bb/session.py` (creds_file, submodule_dir, session_file).

5. **Updated all import paths** in 13 files: `from ..base import ...` → `from ..authorizer import ...`

**Verification:**
```
RSC:  creds_file=credentials.txt  ✓
WoS:  creds_file=credentials.txt  ✓
CNKI: creds_file=credentials.txt  ✓
Lib:  creds_file=credentials.txt  ✓
TIS:  creds_file=credentials.txt  ✓
BB:   creds_file=credentials.txt  ✓ (was bb/credentials.txt — fixed)
Authorizer.username: '12413021'   ✓
```

**Commit:** `1e98d6c`
