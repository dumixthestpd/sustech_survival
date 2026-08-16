# SSO — Auth Infrastructure

**What:** Base classes for authenticated access to SUSTech systems. Handles CAS tickets (headless) and Shibboleth/CARSI (browser-based).

**Use for:** When building new integrations with SUSTech systems. Do not use directly — use the auth class for your target system.

---

## Auth Rules (Non-Negotiable for Agents)

### ✅ Always Do
- Use `@require_auth(AuthorizerClass)` (or call `ensure()` before any sequence of operations) as the **first line of defense**
- Call `ensure()` before any HTTP request to a protected endpoint
- For multi-call sequences: call `ensure()` once at the start, then use `auth.session` to get a `requests.Session` with cookies + headers already set
- For CLI tools: login once per session; the in-memory session persists for the process lifetime

### ❌ Never Do
- **Do not navigate to `cas.sustech.edu.cn` manually in a browser** — it has a hidden reCAPTCHA that blocks automation
- **Do not store session cookies to disk** — in-memory only, no `session.json` writes
- **Do not ask the user for credentials in plaintext** — always read from `credentials.txt`
- **Do not try to automate the CAS login page with Playwright** — the captcha will silently block you

### 🔑 Quick Reference

```python
# GOOD — @require_auth decorator auto-injects the Authorizer
from sustech_survival.sso import require_auth, TISAuth

@require_auth(TISAuth)
def my_endpoint(auth=None):
    r = auth.session.get("/xszykb/querydangqianxnxq")  # cookies + headers pre-set

# GOOD — explicit ensure() + in-memory session
ok, reason = auth.ensure()
if not ok:
    raise AuthorizerError(reason)
r = auth.session.get(url)

# GOOD — check vs. force-refresh
ok, reason = auth.check()        # (ok, reason) — auto-refreshes if expired
auth.refresh()                   # bool — force a fresh CAS login when needed

# BAD — never do this
ok = auth._refresh()             # private — use the public auth.refresh() instead
cookies = auth.load()            # REMOVED — disk cache is gone
session = auth.requests_session  # REMOVED — use auth.session
```

---

## Credentials

```python
from sustech_survival.sso import TISAuth
auth = TISAuth()
auth.username   # your SUSTech student ID
auth.password   # CAS password
```

Reads credentials via `auth.username` / `auth.password` properties, which call `_read_creds()` internally. Resolution order: `SUSTECH_CREDENTIALS` env var → `~/.config/sustech_survival/credentials.txt` → `./credentials.txt` → walk-up from package source. Format: `sid:password`

## Setting Up Credentials

Create a `credentials.txt` file with one line:

```
YOUR_SID:your_password
```

Pick any of these locations (first match wins):

| # | Location | When to use |
|---|----------|-------------|
| 1 | `$SUSTECH_CREDENTIALS` env var (path to file) | CI, containers, agents |
| 2 | `~/.config/sustech_survival/credentials.txt` | Shared across projects (recommended) |
| 3 | `./credentials.txt` (current working directory) | Quick local dev |
| 4 | Walk-up from package source | Editable/development installs |

A template is provided as `credentials.example.txt` in the repo root:

```bash
cp credentials.example.txt credentials.txt
# Edit credentials.txt — replace YOUR_PASSWORD with your CAS password
```

`credentials.txt` is in `.gitignore` — it will never be committed. Sessions are kept **in memory only** — no session data is written to disk.

### Verifying credentials

```bash
# CLI — check if auth works
sustech tis session check
sustech bb session check

# Python — ensure() returns (ok: bool, reason: str)
from sustech_survival.sso import TISAuth
ok, reason = TISAuth().ensure()
print(ok, reason)  # True "Logged in as <your name>" or False "..."
```

## `Authorizer` (ABC)

```python
auth.check()       # (bool, str) — verify session, auto-refresh if expired
auth.ensure()      # (bool, str) — check + auto-refresh (recommended)
auth.refresh()     # bool — force a fresh CAS login
auth.login()       # headful Playwright browser login (last-resort fallback)

# Property
auth.session       # requests.Session with cookies + headers already set
```

Sessions are stored **in memory only**. No `session.json` writes. Call `ensure()` before any HTTP request — it will auto-refresh if the session is missing or expired.

## `CASAuthorizer`

Adds CAS ticket-grinding via `requests`. Inherit with `_get_ticket_cookies()` for custom CAS flows (or use the existing `TISAuth`, `BBAuth`, `LibAuth`, `PMSAuth`, etc. directly).

Inheritors: `TISAuth`, `BBAuth`, `LibAuth`, `PMSAuth`, `WSAuth`

## `ShibbolethAuthorizer`

Adds Shibboleth WAYF/DS flow. Navigates to SP-initiated URL → institution dropdown → CARSI WAYF → SUSTech CAS → IdP consent → SP ACS.

## CARSI Wayf Login

```python
from sustech_survival.sso.providers.carsi import login_via_carsi

login_via_carsi(page, wayf_url)
# Searches for '南方科技大学' in WAYF, clicks result,
# calls selectidp() with correct entityID, returns on SP ACS redirect
```

## Authlib Classes

The `sso.authlib` subpackage provides Authorizer subclasses for the
research-database providers. All use Shibboleth/CARSI Playwright login
(except `PMSAuthorizer`, which is CAS-based).

| Class | Auth Method | Status (2026-07-11) |
|-------|-------------|---------------------|
| `RSCAuthorizer` | Shibboleth/CARSI (Playwright) | ✅ Works |
| `WoSAuth` | Shibboleth/CARSI (Playwright) | ✅ Works |
| `CNKIAuth` | FSSO/Shibboleth (Playwright) | ✅ Works |
| `PMSAuth` | CAS tickets (headless) | ✅ Works |
| `IEEEAuth`, `SpringerAuth`, `WileyAuth`, `ScopusAuth`, `JSTORAuth`, `ACSAuth`, `PubMedAuth` | Shibboleth/CARSI | ✅ Available |

### LibAuth SSL Fix (2026-05-30)

`LibAuth` had two SSL bugs blocking headless access to Primo:

1. **`ssl.OP_LEGACY_SERVER_CONNECT`** — only exists in Python 3.12+. Fix: `getattr(ssl, 'OP_LEGACY_SERVER_CONNECT', 0x4)`.
2. **`_urllib3_request_context()` signature** — urllib3 2.6+ requires a 4th `poolmanager` arg. Fix: add `poolmanager=None` param and pass `self.poolmanager`.

Both fixes applied to `providers/cas.py` (`_build_session()`), `authorizer.py` (`check()`), and `sso/__init__.py` (`LibAuth.session` override).

All browser-based logins expose `auth.page`, `auth.browser`, `auth.ctx` after `login()` returns `True`. Caller must `browser.close()`.

## Off-Campus Trap

Direct `requests` calls to SUSTech services fail off-campus (timeout). Cloudscraper also fails off-campus. Use CARSI/Shibboleth SSO — it works from anywhere.
