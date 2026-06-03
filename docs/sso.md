# SSO — Auth Infrastructure

**What:** Base classes for authenticated access to SUSTech systems. Handles CAS tickets (headless) and Shibboleth/CARSI (browser-based).

**Use for:** When building new integrations with SUSTech systems. Do not use directly — use the auth class for your target system.

---

## Auth Rules (Non-Negotiable for Agents)

### ✅ Always Do
- Use `@bb_auth.ensured` (or `ensure()` before any sequence of operations) as the **first line of defense**
- Call `ensure()` before any HTTP request to a protected endpoint
- For multi-call sequences: call `ensure()` once at the start, then use `auth.requests_session` or `auth.cookies`
- For CLI tools: login once per session; the in-memory session persists for the process lifetime

### ❌ Never Do
- **Do not navigate to `cas.sustech.edu.cn` manually in a browser** — it has a hidden reCAPTCHA that blocks automation
- **Do not use `load()` without calling `ensure()` first** — it returns stale disk cache
- **Do not store session cookies to disk** — in-memory only, no `session.json` writes
- **Do not ask the user for credentials in plaintext** — always read from `credentials.txt`
- **Do not try to automate the CAS login page with Playwright** — the captcha will silently block you

### 🔑 Quick Reference

```python
# GOOD — @ensured decorator auto-injects session
from sustech_survival.sso import BBAuth
bb_auth = BBAuth()

@bb_auth.ensured
def download_content(content_id, session=None, **kwargs):
    r = requests.get(url, cookies=session)

# GOOD — explicit ensure + in-memory cookies
ok, reason = bb_auth.ensure()
if not ok:
    raise AuthorizerError(reason)
r = bb_auth.requests_session.get(url)  # in-memory session, no disk

# GOOD — refresh when needed (headless, no captcha)
ok = bb_auth.refresh()  # CAS grinding via requests

# BAD — never do this
cookies = bb_auth.load()  # deprecated, reads stale disk cache
session = bb_auth.session  # deprecated property
```

---

## Credentials

```python
from sustech_survival.sso import Credentials
c = Credentials()
c.username   # '12413021'
c.password   # wifi password
```

Reads `credentials.txt` at skill root. Format: `sid:password`

## `Authorizer` (ABC)

```python
auth.check()       # (bool, str) — verify session, auto-refresh if expired
auth.refresh()     # bool — headless re-auth (subclasses may not implement)
auth.ensure()      # (bool, str) — check + auto-refresh
auth.login()       # headful Playwright browser login
```

Session stored **in-memory only** (as of 2026-06-03). No `session.json` writes. Call `ensure()` first.

## `CASAuthorizer`

Adds CAS ticket-grinding via `requests`. Inherit with `get_ticket_cookies()` override for headless auth.

Inheritors: `BBAuth`, `LibAuth`

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

| Class | Session | Auth Method | Status (2026-05-30) |
|-------|---------|-------------|----------------------|
| `BBAuth` | `bb/session.json` | CAS tickets (headless) | ✅ Works |
| `LibAuth` | `lib/session.json` | CAS tickets (headless) | ✅ Fixed — SSL + poolmanager |
| `RSCAuthorizer` | None | Shibboleth/CARSI (Playwright) | ✅ Works |
| `WoSAuth` | None | Shibboleth/CARSI (Playwright) | ✅ Works |
| `CNKIAuth` | None | FSSO/Shibboleth (Playwright) | ✅ Works |

### LibAuth SSL Fix (2026-05-30)

`LibAuth` had two SSL bugs blocking headless access to Primo:

1. **`ssl.OP_LEGACY_SERVER_CONNECT`** — only exists in Python 3.12+. Fix: `getattr(ssl, 'OP_LEGACY_SERVER_CONNECT', 0x4)`.
2. **`_urllib3_request_context()` signature** — urllib3 2.6+ requires a 4th `poolmanager` arg. Fix: add `poolmanager=None` param and pass `self.poolmanager`.

Both fixes applied to `providers/cas.py` (`_build_session()`), `authorizer.py` (`check()`), and `sso/__init__.py` (`LibAuth.session` override).

All browser-based logins expose `auth.page`, `auth.browser`, `auth.ctx` after `login()` returns `True`. Caller must `browser.close()`.

## Off-Campus Trap

Direct `requests` calls to SUSTech services fail off-campus (timeout). Cloudscraper also fails off-campus. Use CARSI/Shibboleth SSO — it works from anywhere.
