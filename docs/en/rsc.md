# RSC (Royal Society of Chemistry)

**What:** Peer-reviewed journals in chemistry — RSC Advances, Journal of Materials Chemistry A/B/C, Physical Chemistry Chemical Physics, Energy & Environmental Science, etc.

**Use for:** Electrochromic materials, polymer electrolytes, energy storage, catalysis, nanomaterials. High-quality review articles and primary research.

**Auth:** Shibboleth/CARSI (off-campus works).

## Module

```python
from sustech_survival.sso.authlib.rsc import RSCAuthorizer
```

## `RSCAuthorizer.login()`

```python
auth = RSCAuthorizer()
ok = auth.login()          # headful Playwright
if ok:
    auth.page.goto('https://pubs.rsc.org/en/search?q=electrochromic')
    auth.browser.close()
```

**Flow:** Direct Shibboleth URL (bypasses WAYF) → SUSTech CAS → IdP consent → RSC session.

**Login timeout:** 90s. If browser doesn't reach RSC ACS in time, `False`.

**Session:** None. Login every time.

**Known trap:** cloudscraper fails off-campus. Use CARSI SSO.
