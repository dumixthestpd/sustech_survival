# CNKI (中国知网)

**What:** China's largest academic database — journals (科举网), theses/dissertations (学位论文), conference papers, yearbooks.

**Use for:** Chinese-language literature, Chinese university theses, domestic Chinese research, government reports. Essential for anything published primarily in Chinese.

**Auth:** FSSO/Shibboleth (off-campus works).

## Module

```python
from sustech_survival.sso.authlib.cnki import CNKIAuth
```

## `CNKIAuth.login()`

```python
auth = CNKIAuth()
ok = auth.login()          # headful Playwright
if ok:
    auth.page.goto('https://navi.cnki.net/')
    auth.browser.close()
```

**Flow:** CNKI FSSO Shibboleth endpoint with SUSTech entityID → SUSTech CAS → IdP consent → CNKI session.

**Session:** None. Login every time.

**Login timeout:** 120s.

**Known trap:** Cloudscraper fails off-campus. Use FSSO/Shibboleth SSO.
