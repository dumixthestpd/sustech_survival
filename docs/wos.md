# Web of Science (WoS)

**What:** Multidisciplinary citation index — Science Citation Index, Social Sciences, Arts & Humanities. Links papers by citations.

**Use for:** Finding highly-cited papers, citation chains, reviewing the literature landscape. Good for identifying seminal works. Less full-text, more citation metadata.

**Auth:** Shibboleth/CARSI (off-campus works).

## Module

```python
from sustech_survival.sso.authlib.wos import WoSAuth
```

## `WoSAuth.login()`

```python
auth = WoSAuth()
ok = auth.login()          # headful Playwright (headless=False default)
if ok:
    auth.page.goto('https://www.webofscience.com')
    auth.browser.close()
```

**Flow:** WoS SP init → Clarivate access portal → select `CHINA CERNET Federation` → CARSI DS WAYF → search SUSTech → SUSTech CAS → IdP consent → WoS ACS.

**Institution selector:** Angular Material `mat-select` with `formcontrolname=federationName`. Must click combobox first, then select from dropdown panel.

**Go button:** English `Go to institution` in headless, Chinese `转到机构` in visible browser.

**Session:** None. Login every time.

**Login timeout:** 120s.

**Known trap:** Cloudscraper fails off-campus. Use CARSI SSO.
