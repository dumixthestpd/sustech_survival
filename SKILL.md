---
name: sustech_survival
description: SUSTech academic systems — TIS, BB, paper databases.
---

See [docs/](docs/) for full reference.

## Auth — Critical Rules for All Agents

Session is **in-memory only** (2026-06-03). No disk persistence.

### ✅ Always
- Call `ensure()` before any HTTP request to a protected endpoint
- For CLI: `python3 sustech_survival/tis/cli.py session check` before running commands
- Use `@auth.ensured` decorator for functions that need a validated session
- For multi-call sequences: `ensure()` once → `auth.requests_session` for all calls

### ❌ Never
- **Do not navigate to CAS login page manually** — hidden reCAPTCHA silently blocks automation
- **Do not use `load()` or `save()`** — deprecated, disk-based, returns stale cookies
- **Do not store session cookies to disk** — in-memory only
- **Do not ask user for credentials in plaintext** — read from `credentials.txt`
- **Do not try to automate CAS login with Playwright** — captcha blocks it

### Quick Reference

```python
# CLI first — no auth management needed
python3 sustech_survival/tis/cli.py evals --pending
python3 sustech_survival/tis/cli.py grades --semester 2025-20262 --export grades.csv

# Python — explicit ensure
from sustech_survival.sso import TISAuth
auth = TISAuth()
ok, reason = auth.ensure()
if not ok:
    raise AuthorizerError(reason)
r = auth.requests_session.get(url)  # in-memory session, pre-loaded

# @ensured decorator — auto-injects session
@auth.ensured
def do_work(session=None, **kwargs):
    return auth.requests_session.get(url)
```

### TIS Auth Classes
- `TISAuth` → `auth.requests_session` (requests.Session with cookies)
- `BBAuth` → `auth.requests_session` (Blackboard session)
- `LibAuth` → `auth.requests_session` (Library session)

### Credentials
Format: `sid:password` in `credentials.txt` at skill root.