# PMS (Campus Print)

Read printer status and the upload queue, and upload documents to the campus PMS.

## Authentication

Install the `[pms]` extra, which includes the legacy RSA login dependency.

```python
from sustech_survival.sso import PMSAuth

auth = PMSAuth()
ok, reason = auth.ensure()
if not ok:
    raise RuntimeError(reason)
```

`ensure()` follows the site's `Auth/SSoPage` entry, discovers the current CAS
service callback, and reuses the same in-memory cookie jar through authcenter,
CAS and PMS. It verifies the resulting session with `Auth/Check`. No browser
is required. Interactive authentication challenges stop the flow.

`login_via_cas()` uses this same flow (`headless` is retained for compatibility).
`login_password()` is an explicit legacy RSA print-account login requiring the
`[pms]` extra. It is not the default CAS path, and an invalid-session response
from it does not establish that the campus password is wrong. No automatic
fallback to that endpoint occurs.

## CLI

```bash
sustech pms check
sustech pms jobs --json
sustech pms stations --json
```

Authentication/read failures exit nonzero. Authentication diagnostics go to
stderr so JSON output remains parseable.

## Python API and upload receipts

```python
from sustech_survival.pms import pms

client = pms()  # verifies/reuses the PMS authorizer session
jobs = client.list_print_jobs()
preview = client.upload_print("PMS_TEST.pdf", paper="A4", color="bw",
                              duplex="long", copies=1, dry_run=True)
# After reviewing the file/options and obtaining authorization:
receipt = client.upload_print("PMS_TEST.pdf", paper="A4", color="bw",
                              duplex="long", copies=1)
print(receipt.status, receipt.job_id, receipt.verification_url)
```

Dry runs perform no network calls. A real upload snapshots queue IDs, sends one
multipart POST with the correct queue page as `BackURL`, parses JSON or the
same-site result redirect, and reads the queue once. It does not automatically
follow upload redirects or repeat the POST.

- `status="confirmed"`, `ok=True`, `uploaded=True`: one new matching queue job
  was read back; `job_id` identifies it.
- `status="unknown"`, `ok=False`, `uploaded=None`: the result could not be
  confirmed, including a lost response, delayed/failed queue read or multiple
  new matches. Inspect `observed_job_ids`, `http_status`, `response_format` and
  `verification_error`, then query the queue before considering any retry.
- `status="rejected"`, `uploaded=False`: an explicit rejection and no new
  matching queue job. An unavailable initial queue snapshot sends no upload.

`ok=False` alone is never a reason to resend a file. Uploading queues a document;
this API does not trigger physical printing.

Queue verification URL: <https://pms.sustech.edu.cn/client/new/cprintPc/printDoc.html>.

## Duplex values and queue labels

The client follows the PMS queue list's long/short-edge labels:

| Option | `dwDuplex` | Queue flag | Queue label |
| --- | --- | --- | --- |
| `"single"` / `DUPLEX_SINGLE` | 1 | `single` | 单面 |
| `"long"` / `"双面长边"` / `DUPLEX_LONG_EDGE` | 2 | `vdup` | 双面长边 |
| `"short"` / `"双面短边"` / `DUPLEX_SHORT_EDGE` | 3 | `hdup` | 双面短边 |

Numeric inputs and numeric strings use the same wire value. The upload page
reverses the queue's edge labels; aliases, previews and queue records all use
the queue convention. This corrects the previous `long=3` / `short=2` alias
and constant mapping. Callers using raw numeric values keep those values.

Queue records preserve `duplex_flag` and expose `duplex_edge="long"` for `vdup`
and `"short"` for `hdup`. Missing or conflicting flags remain unknown
(`is_duplex=None`, `duplex_edge=None`).

Other client methods: `list_server_groups()`, `list_stations(group_sn=None)`,
`list_scan_jobs()`, `history(begin=..., end=...)`, `delete_print_job(job_id)` and
`delete_scan_job(job_id)`. Deletion changes the account and needs authorization.
