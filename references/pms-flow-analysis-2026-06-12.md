# PMS API reverse-engineering notes — 2026-06-12

Built `sustech_survival.pms` (submodule + authorizer + CLI) by walking the
SPA's JS source rather than packet-sniffing. This doc captures the raw
findings for future reference.

## Site structure

- **Base URL**: `https://pms.sustech.edu.cn/`
- **SPA root**: `https://pms.sustech.edu.cn/client/new/cprintPc/`
- **API base**: `https://pms.sustech.edu.cn/api/`
- **Vendor**: 杭州联创信息技术有限公司 (Unifound) — product "联创云打印"
- **Auth**: Custom RSA flow (not SUSTech CAS, despite being CAS-fronted)

## Navigation map (from common.js `addCommon()`)

| Menu item | Nav class | HTML page | JS file |
|-----------|-----------|-----------|---------|
| 云打印 (Cloud print) | `nav_c1` | `cprint.html` | `cprint.js` + `cloudprint.js` |
| 打印文档 (Print jobs) | `nav_c2` | `printDoc.html` | `printDoc.js` |
| 扫描文档 (Scans) | `nav_c3` | `scanDoc.html` | `scanDoc.js` |
| 打印点 (Printers) | `nav_c4` | `printDev.html` | `printDev.js` |
| 使用记录 (History) | `nav_c5` | `footprint.html` | `footprint.js` |
| 帮助 (Help) | `nav_c6` | `help.html` | `help.js` |

## API endpoints (all under `/api/client/...`)

### Auth

| Method | Path | Body | Returns |
|--------|------|------|---------|
| POST | `/Auth/GetAuthToken` | — | `{szToken}` |
| GET | `/Auth/PublicKey` | — | `{publicKey (raw base64), nonceStr}` |
| POST | `/Auth/Login` | `{szLogonName, szPassword (RSA ciphertext), szToken}` | `{result: {szTrueName, ...}}` |
| POST | `/Auth/Check` | — | `{code: 0/!=0, result: {szTrueName}}` |
| GET | `/Auth/QrImg?szToken=...` | — | QR code image |
| GET | `/Auth/WaitUserIn` | — | Polled by QR login |
| GET | `/Auth/SSoPage?backurl=...` | — | SSO redirect URL |

### Cloud print (云打印)

| Method | Path | Notes |
|--------|------|-------|
| POST | `/CloudPrint/Upload` | multipart/form-data: `szPath` (file), `dwColor`, `dwPaperId`, `dwDuplex`, `dwFrom`, `dwTo`, `dwCopies`, `BackURL` |

### Print jobs (打印文档)

| Method | Path | Notes |
|--------|------|-------|
| GET | `/PrintJob/Get?timestamp=...` | Returns array of `{dwJobId, szJobName, szAttribe, szPaperDetail (JSON string), dwCopies, dwCreateDate, dwCreateTime}` |
| POST | `/PrintJob/Del` | Body: `{dwJobId, dwOldJobId}` (both same value) |

### Scans (扫描文档)

| Method | Path | Notes |
|--------|------|-------|
| GET | `/Scan/Get?timestamp=...` | Returns array of `{dwJobId, szDisplayName, dwFileSize, dwSubmitDate, dwSubmitTime}` |
| POST | `/Scan/Del` | Body: `{dwJobId}` |

### Printers (打印点)

| Method | Path | Notes |
|--------|------|-------|
| GET | `/Station/GetSrvList` | Returns array of `{dwSN, szName}` (dropdown options) |
| GET | `/Station/GetList?timestamp=...` | Returns array of stations |

### Usage records (使用记录)

| Method | Path | Notes |
|--------|------|-------|
| POST | `/Report/DetailPage` | Body: `{dwBeginDate, dwEndDate (YYYYMMDD), dwType (1=print/2=scan/3=copy), dwPageNo, dwRowCount}` → `{result: [...], dwTotalPage}` |

## Field-name gotchas

The PMS API mixes naming conventions — easy to miss if you're used to BB/TIS:

| Endpoint | Field | Notes |
|----------|-------|-------|
| `PrintJob/Get` | `dwJobId` | **NOT** `dwID`. Single source of truth. |
| `PrintJob/Get` | `szAttribe` | Comma-sep flags. Contains `single`, `vdup`/`hdup`/`single`, `color`, paper size letter |
| `PrintJob/Get` | `szPaperDetail` | **JSON-encoded STRING** in the response, not a nested object |
| `Scan/Get` | `szDisplayName` | NOT `szFileName` |
| `Scan/Get` | `dwSubmitDate`/`dwSubmitTime` | NOT `dwSubmitTime` only |
| `Report/DetailPage` | `dwSID` | Record ID — all-caps, no underscores |
| `Report/DetailPage` | `dwPaperID` | All-caps `ID` |
| `Report/DetailPage` | `dwPages` | **NOT** `dwTotalPages`. Just `dwPages`. |
| `Report/DetailPage` | `dwMFPSN` | Device SN |
| `Report/DetailPage` | `dwUsedFreeMoney` | Subsidy portion (in cents) |
| `Station/GetList` | `dwDevSN` | Device serial |
| `Station/GetList` | `dwProperty` | Bitmask: 1=print, 2=copy, 4=scan, 8=color |
| `Station/GetList` | `dwStatus` | Bitmask: 1=idle, 2=busy, 0x20=fault, 0x200=warning, 0x400=comm fail, 0x800=user closed, 0x1000=disuse |
| `Station/GetList` | `szStatInfo` | Human-readable status (used for fault details) |

## Crypto: RSA-encrypted password

The flow mirrors what `JSEncrypt.encrypt()` does in the browser:

1. Get `szToken` from `GetAuthToken` (cached for the login)
2. Get `publicKey` (raw base64 — no PEM headers) and `nonceStr`
3. Concatenate `password + ";" + nonceStr`
4. RSA-encrypt with PKCS#1 v1.5 (1024-bit key)
5. Base64-encode the result
6. Send as `szPassword` to `/Auth/Login`

`pycryptodome`'s `PKCS1_v1_5` produces output compatible with JSEncrypt. Tested
live against the real server (12413021 / wifipass1).

## Status interpretation (printDev.js backState logic)

```python
def state_text(dw_status, sz_stat_info):
    if dw_status == 0:
        return "未开放", 3
    if dw_status & 1:
        return "空闲", 2
    if dw_status & 2:
        return "忙碌", 1
    if (dw_status & 0x20) or (dw_status & 0x200) or (dw_status & 0x400) \
       or (dw_status & 0x800) or (dw_status & 0x1000) \
       or (dw_status & 0x2000) or (dw_status & 0x10000):
        short = sz_stat_info.split("-", 1)[0] if "-" in sz_stat_info else sz_stat_info
        return short or "不可用", 3
    return "不可用", 3
```

## Settle type interpretation (footprint.js getSettleTypeName)

```python
def settle_label(dw_settle_type):
    return "手工收费" if (dw_settle_type & 0xFF) == 4 else "自助收费"
```

## Things the SPA does that we DON'T need

- QR-code login (browser polls `/Auth/WaitUserIn` every 1s after scanning)
- Multi-language switching (`hostlang = 1` for Chinese, 2 for English)
- File preview (`/PrintJob/PreviewPage`) — we'd just download the file
- File delete confirmation modal
- Date picker UI (we just send YYYYMMDD strings)

## Things the SPA does that we DO need

- Server-group dropdown filter (`OPMServer` is the only one currently — filter
  by `dwDevSN // 1000 == group.dwSN`)
- Date format conversion (`2024-09-09` → `20240909` via `.replace(/-/g, "")`)
- Page size of 5 (matches the SPA default; we default to 20 in the API for
  agent-friendliness)
- The `szPaperDetail` JSON string parsing (the API returns it as a string,
  not an array)

## Cookies

- `OSESSIONID` — the only auth cookie that matters for API calls
- `SESSIONID` — set but cleared by the server (legacy/anti-CSRF?)
- Various `set_*` cookies for UI settings (`set_print_color`, `set_filesize`,
  `set_show_langbtn`) — irrelevant for API

## Source files captured

- `/tmp/help.html`, `/tmp/help.js` — help page (small)
- `/tmp/cprint.html`, `/tmp/cprint.js` (10.7 KB), `/tmp/cloudprint.js` (3.7 KB) — cloud print
- `/tmp/printDoc.html`, `/tmp/printDoc.js` (9.7 KB) — print job list
- `/tmp/scanDoc.html`, `/tmp/scanDoc.js` (8.5 KB) — scan list
- `/tmp/printDev.html`, `/tmp/printDev.js` (9.6 KB) — printer list
- `/tmp/footprint.html`, `/tmp/footprint.js` (9.8 KB) — usage history
- `/tmp/login.html`, `/tmp/login.js` (8.4 KB) — login page

Total SPA JS: ~70 KB. All read in 2026-06-12.