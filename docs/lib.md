# Library (Primo)

SUSTech library book search via Primo (Ex Libris).

**Auth:** `LibAuth` — CAS with custom SSL context for Primo's legacy TLS.

---

## Python API

```python
from sustech_survival import lib

lib.ensure()                   # check + auto-refresh auth session
lib.login(headless=False)      # headful Playwright login (fallback)
```