# WS (SUSTech Global)

Student exchange / abroad programs — search, details, application info.

**Auth:** `WSAuth` — CAS-based, subclass of `WSProvider`.

---

## CLI

```bash
sustech ws list                   # list exchange programs
sustech ws search "MIT"           # keyword search
sustech ws detail <program_id>    # program details
```

---

## Python API

```python
from sustech_survival.ws.programs import list_programs, search_programs, get_program_detail

programs = list_programs(page=1, page_size=20)
results = search_programs("MIT", page=1, page_size=10)
detail = get_program_detail(program_id="...")