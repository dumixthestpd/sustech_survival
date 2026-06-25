---
name: pms
description: SUSTech 联创 PMS cloud print — list campus printers, query usage records, upload print jobs, manage scans. Live client, no cache. Sub-skill of sustech_survival.
owner: Faux
category: sustech
last_updated: 2026-06-12
parent: sustech_survival
---

> **Canonical code lives in the OpenClaw workspace**, not here.
> Real implementation: `~/.openclaw/code/sustech_survival/src/sustech_survival/pms/`
> Auth (custom RSA flow, NOT standard CAS): `~/.openclaw/code/sustech_survival/src/sustech_survival/sso/authlib/pms.py`

# PMS — SUSTech 联创 Cloud Print (sub-skill)

ONE client class, FIVE record types, ZERO local data. Every call hits the
live `pms.sustech.edu.cn` API.

## What is PMS?

The SUSTech campus print/copy/scan system by 杭州联创信息技术有限公司
(Unifound). Log in with your SUSTech credentials and you can:

- Pick up print jobs at any of ~26 stations across campus (慧园, 荔园,
  琳恩图书馆, 书院, etc.)
- See your usage history (per-page costs, subsidy used)
- Manage scanned documents

The system uses a **custom RSA-encrypted login** (not standard CAS):
1. `POST /api/client/Auth/GetAuthToken` → `{szToken}`
2. `GET  /api/client/Auth/PublicKey` → `{publicKey, nonceStr}`
3. RSA-encrypt `password + ";" + nonceStr` → ciphertext
4. `POST /api/client/Auth/Login` with `{szLogonName, szPassword, szToken}`

Cookies (OSESSIONID) are set on success.

## Quick start

```python
import sys
sys.path.insert(0, '/Users/dumix/.openclaw/code/sustech_survival/src')

from sustech_survival.pms import pms, PMSClient

# Singleton — auto-auths on first call
c = pms()

# 26 campus printers, with status + features
for s in c.list_stations():
    flag = "🟢" if s.is_idle else "🟡" if s.is_busy else "🔴"
    print(f"{flag} {s.sz_name} | {','.join(s.papers)} | {s.functions_text}")

# Last 30 days of print history
from datetime import date, timedelta
records, total_pages = c.history(
    begin=date.today() - timedelta(days=30),
    end=date.today(),
    type=1,  # 1=print, 2=scan, 3=copy
    page=1, page_size=20,
)
for r in records:
    print(f"  {r.datetime_str} | {r.paper};{r.dw_pages}页 | ¥{r.money_total:.2f}")

# Upload a file for printing (dry-run first!)
result = c.upload_print(
    "/Users/dumix/hw.pdf",
    color="bw", paper="A4", duplex="single", copies=2,
    dry_run=True,
)
print(result.to_markdown())

# Real upload (creates a job you pick up at any printer)
result = c.upload_print("/Users/dumix/hw.pdf", color="bw", copies=1)
```

## CLI

```bash
cd ~/.openclaw/code/sustech_survival
PYTHONPATH=src python -m sustech_survival.pms <command>

Commands:
  check                Verify the session is alive
  stations [GROUP]     List campus printers (--json for machine-readable)
  groups               List server groups (dropdown on the page)
  jobs                 List uploaded-but-not-printed documents
  job-delete ID        Delete a print job
  scans                List scanned documents
  scan-delete ID       Delete a scan
  history              Usage records (打印/扫描/复印)
        --type print|scan|copy   (default: print)
        --from YYYY-MM-DD        (default: 3 years ago)
        --to   YYYY-MM-DD        (default: today)
        --page N --size N
  upload FILE          Upload a file for printing at any station
        --color bw|color
        --paper A4|A3|none
        --duplex single|short|long
        --copies N
        --from-page N --to-page N
        --dry-run                prepare form but don't POST

Global:
  --json                machine-readable JSON output (one record per line)
```

Examples:

```bash
# Show idle printers in markdown table format
PYTHONPATH=src python -m sustech_survival.pms stations

# Last week's print history as JSON
PYTHONPATH=src python -m sustech_survival.pms --json history \
    --from 2026-06-05 --to 2026-06-12

# Dry-run an upload (no actual upload)
PYTHONPATH=src python -m sustech_survival.pms upload ~/hw.pdf \
    --color bw --paper A4 --copies 2 --dry-run

# Real upload (creates job on PMS, you pick it up at any printer)
PYTHONPATH=src python -m sustech_survival.pms upload ~/hw.pdf \
    --color bw --paper A4 --copies 1
```

## API surface

### `PMSClient(session)` — one client, all the methods

| Method | Endpoint | Description |
|--------|----------|-------------|
| `list_server_groups()` | GET `/client/Station/GetSrvList` | The dropdown filter groups |
| `list_stations(group_sn=None)` | GET `/client/Station/GetList` | All printers/copiers/scanners (optional group filter) |
| `list_print_jobs()` | GET `/client/PrintJob/Get` | Uploaded-but-not-printed docs |
| `delete_print_job(id)` | POST `/client/PrintJob/Del` | Delete a print job (`{dwJobId, dwOldJobId}`) |
| `list_scan_jobs()` | GET `/client/Scan/Get` | Scanned documents |
| `delete_scan_job(id)` | POST `/client/Scan/Del` | Delete a scan (`{dwJobId}`) |
| `history(begin, end, type, page, page_size)` | POST `/client/Report/DetailPage` | Paginated usage records |
| `upload_print(file_path, color, paper, duplex, copies, page_from, page_to, dry_run)` | POST `/client/CloudPrint/Upload` | Upload file for printing (multipart) |

### Module-level singleton

```python
from sustech_survival.pms import pms
client = pms()  # auto-auths via PMSAuth on first call
```

### Schema classes (in `sustech_survival.pms.schema`)

| Class | Parses | Key fields |
|-------|--------|-----------|
| `Station` | `/client/Station/GetList` | `sz_name`, `is_idle`, `papers`, `can_print/copy/scan/color`, `state_text`, `server_group` |
| `ServerGroup` | `/client/Station/GetSrvList` | `dw_sn`, `sz_name` |
| `PrintJob` | `/client/PrintJob/Get` | `dw_job_id`, `file_name`, `paper`, `dw_total_pages`, `is_color`, `duplex_label`, `datetime_str` |
| `ScanJob` | `/client/Scan/Get` | `dw_job_id`, `file_name`, `file_size_kb`, `datetime_str` |
| `UsageRecord` | `/client/Report/DetailPage` | `dw_sid`, `datetime_str`, `paper`, `dw_pages`, `money_total`, `settle_label`, `dw_mfp_sn` |

All have `from_api(raw: dict) -> Self` classmethods and `to_markdown()` for AI-readable rendering.

### Constants (re-exported from `sustech_survival.pms`)

```python
PAPER_A4 = 9, PAPER_A3 = 8, PAPER_UNSPECIFIED = -1
COLOR_BW = 1, COLOR_COLOR = 2
DUPLEX_SINGLE = 1, DUPLEX_SHORT_EDGE = 2, DUPLEX_LONG_EDGE = 3
REPORT_TYPE_PRINT = 1, REPORT_TYPE_SCAN = 2, REPORT_TYPE_COPY = 3
```

## Architecture

```
sustech_survival/pms/
├── __init__.py       exports PMSClient + schema classes + singleton factory
├── pms.py            PMSClient (one class, all methods) + coercion helpers + PrintUploadResult
├── schema.py         Station, ServerGroup, PrintJob, ScanJob, UsageRecord
├── __main__.py       CLI (human + agent friendly, --json for LLMs)
└── SKILL.md          this file

sustech_survival/sso/authlib/pms.py
└── PMSAuth           Authorizer subclass (RSA + token login, NOT standard CAS)
```

- **One client class** (PMSClient) — all operations, no scattered functions.
- **Schema classes with classmethod parsers** (`Station.from_api`, etc.) — never `parse_*()` loose functions.
- **Module-level singleton** (`pms()`) — auto-auths.
- **Both human + CLI friendly** — markdown tables by default, `--json` for LLMs.

## Auth flow (why it's not CAS)

Standard CAS services (TIS, BB, Lib) use SUSTech CAS at `cas.sustech.edu.cn/cas/login`. PMS does NOT — it has its own RSA-encrypted login:

```
POST /api/client/Auth/GetAuthToken   →  { szToken: "..." }
GET  /api/client/Auth/PublicKey       →  { publicKey: "MIGd...", nonceStr: "..." }
RSA-encrypt( password + ";" + nonceStr, publicKey )  →  base64 ciphertext
POST /api/client/Auth/Login            { szLogonName, szPassword, szToken }
                                       →  sets OSESSIONID cookie
```

`PMSAuth.login_password()` does all 4 steps. Cookies are persisted to `<skill_root>/pms/session.json` so subsequent calls don't re-auth. Session TTL is 25 min on the server.

If your print account hasn't been activated yet, `/Auth/Check` returns the error
"云打印系统内没有您的账号信息，请联系图书馆技术部处理". Contact library tech to
create your account — the system is keyed on your SUSTech SID.

## Picking options

| Constant | Numeric | Aliases (string) | Chinese label |
|----------|---------|------------------|---------------|
| `COLOR_BW` | 1 | `"bw"`, `"black"`, `"黑白"`, `"1"` | 黑白 |
| `COLOR_COLOR` | 2 | `"color"`, `"colour"`, `"彩色"`, `"2"` | 彩色 |
| `PAPER_UNSPECIFIED` | -1 | `""`, `"none"`, `"不指定"`, `"unspecified"` | 不指定 |
| `PAPER_A4` | 9 | `"A4"`, `"9"` | A4 |
| `PAPER_A3` | 8 | `"A3"`, `"8"` | A3 |
| `DUPLEX_SINGLE` | 1 | `"single"`, `"单面"`, `"1"` | 单面 |
| `DUPLEX_SHORT_EDGE` | 2 | `"short"`, `"双面短边"`, `"2"` | 双面短边 |
| `DUPLEX_LONG_EDGE` | 3 | `"long"`, `"双面长边"`, `"3"` | 双面长边 |

The `upload_print()` method accepts either the numeric codes or any of the
string aliases. Same for the CLI.

## Caveats

- **No local cache.** Every call hits the live site — explicit design choice.
  ~3s for a single API call, ~30-60s for paginated history.
- **SUSTech IP not required** for the API itself (the public endpoint is
  reachable from anywhere), but the on-campus page UI does go through CAS
  if you're not already authed. Direct API login via `login_password()` works
  from any IP with valid credentials.
- **Print account must exist.** New students may need to ask library tech to
  activate their print account. The auth flow succeeds (returns szTrueName)
  even without an active print account, but `upload_print()` and `history()`
  will return empty results.
- **Upload cost is free.** Money is only deducted when you actually pick up
  the file at a physical printer. But uploaded jobs clutter your queue — use
  `job-delete` to clean up.
- **`upload_print()` is state-mutating.** Always pass `dry_run=True` first
  to verify the form data, then re-run without it.
- **Field names are quirky.** The API mixes `dwJobId` (no underscore),
  `dwPaperID` (all-caps ID), `dwUsedFreeMoney` (subsidy), etc. The schema
  classes normalize these — but raw API responses won't.

## Testing

```bash
cd ~/.openclaw/code/sustech_survival
./venv/bin/python -m pytest src/test/test_pms_*.py -v
```

Three test files:

- `test_pms_schema.py` — offline parser tests using fixture dicts
- `test_pms_module.py` — module surface + coercion helpers + PrintUploadResult
- `test_pms_auth.py` — RSA encrypt (deterministic key/nonce → base64) +
  live auth tests (`@pytest.mark.live`)

The live tests auto-run by default (they're fast). Skip with `pytest -m "not live"`.

## See also

- `sustech_survival` — parent skill (TIS, BB, faculty, etc.)
- `sso` — authorizer framework; `PMSAuth` is a custom (non-CAS) subclass
- `references/pms-flow-analysis-2026-06-12.md` — the API reverse-engineering
  that built this module (TODO: write after first real use)