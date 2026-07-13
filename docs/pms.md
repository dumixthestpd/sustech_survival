# PMS (Campus Print)

联创打印 — campus print queue, stations, and job upload.

**Auth:** `PMSAuth` — CAS + RSA password encryption. Requires `[pms]` extra (`pycryptodome`).

---

## Authentication

```python
from sustech_survival.sso import PMSAuth

auth = PMSAuth()
ok, reason = auth.ensure()    # RSA-encrypts password, POSTs to PMS login
```

```bash
sustech pms check             # verify PMS auth
```

---

## CLI

```bash
sustech pms stations          # list campus printers
sustech pms jobs               # list pending print jobs
```

---

## Python API

```python
from sustech_survival.pms import pms

client = pms()                # builds default client with PMSAuth
stations = client.list_stations()
jobs = client.list_print_jobs()
client.upload_print(file_path='/tmp/report.pdf', copies=1, color=False, duplex=False)
client.delete_print_job(job_id=12345)
```

### PMSClient methods

| Method | Description |
|--------|-------------|
| `list_server_groups()` | Printer groups by building |
| `list_stations(group_sn=None)` | Individual printers |
| `list_print_jobs()` | Uploaded-but-not-printed jobs |
| `delete_print_job(job_id)` | Cancel a pending job |
| `list_scan_jobs()` | Pending scan jobs |
| `delete_scan_job(job_id)` | Cancel a pending scan |
| `history(start, end)` | Print history |
| `upload_print(...)` | Upload a document for printing |