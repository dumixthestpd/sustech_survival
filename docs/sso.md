# SSO — Auth Infrastructure

**What:** Base classes for authenticated access to SUSTech systems. Handles CAS tickets (headless) and Shibboleth/CARSI (browser-based).

**Use for:** When building new integrations with SUSTech systems. Do not use directly — use the auth class for your target system.

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

Session file at `<module>/session.json`.

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
