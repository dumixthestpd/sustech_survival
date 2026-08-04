# TIS Page

> The TIS (Teaching Information System) course-selector SPA at `/tis`.
> Pure facts: what the code is, what it does, where each piece lives.
> No workflow. No "how to use this". No priority lists.

## Files

| Path | Role |
|---|---|
| `src/sustech_survival/webui/templates/tis.html` | Page markup, inline CSS, button labels |
| `src/sustech_survival/webui/static/tis/tis.js` | 4171-line IIFE: state, render, cascade, persistence |
| `src/sustech_survival/webui/blueprints/tis.py` | HTTP routes (13 endpoints) |

## Sections of `tis.js`

The `// ──` headers are the index. Each header marks a region of the
file. The regions are:

```
DOM refs · State · Loading bar · HTTP helpers · Semester helpers ·
Color/time helpers · Catalog loaders · Results render · NCES brief ·
NCES eval page · Picked list + mutators · ICS export · Flash/utils ·
Drag-to-reorder picked · Solve tab · Weekly grid · Tabs · Bid panel ·
DOMContentLoaded
```

## State

The single source of truth. All declared in `tis.js` lines 62-82.

| Var | Type | Role |
|---|---|---|
| `PICKED` | `{rwh: courseDict}` | The user's chosen sections. Canonical. |
| `PICKED_BIDS` | `{rwh: int}` | Bid value per pick. Mirrors `PICKED`. |
| `PICKED_CONFLICTS` | `{rwh: bool}` | Per-pick conflict flag. |
| `ENROLLED_RWH` | `Set<rwh>` | What's on TIS right now. |
| `EXISTING_BIDS` | `{rwh: int}` | Server-side bids for enrolled/cart. |
| `BLOCKED` | `{"day:period": true}` | User's unavailable slots. |
| `CAT` / `ALL_CAT` | `Course[]` | Cached catalog. |
| `EVAL_CACHE` | `{code: evalResponse}` | NCES cache. |
| `COLORS_CACHE` | `{code: hex}` | Stable color per code. |
| `ROUND_INFO` | object | Bid-round metadata. |
| `MODE` | `'personal' \| 'campus'` | Search mode (Selection vs Catalog). |

## Cascade contract

`PICKED` is mutated by exactly three functions:

1. `addPicked(course)` — `tis.js` line 1678
2. `removePicked(rwh)` — `tis.js` line 1698
3. `applyPicksFromData(data)` — used by localStorage restore + file Load

All three MUST call, in order:

```
savePicks()              ← localStorage auto-save
renderPicked()           ← #pick-list + action buttons
updateResultsHeader()    ← select-all + count in search results
renderGrid()             ← weekly grid (clear #grid-legend if empty)
renderBidPanel()         ← bid boxes + bar + totals
updateBidStat()          ← right-column "Bids: X/150 pts" summary
updateSolveCodes()       ← solver "Codes to solve:" chip
```

This contract is also written at the top of `tis.js` (lines 15-25).
Both locations describe the same contract; the code is authoritative.

## HTTP routes (in `tis.py`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/tis/info` | Semester + filter options |
| GET | `/api/tis/courses?mode=personal\|campus` | Catalog or personal search |
| POST | `/api/tis/refresh` | Force re-fetch from TIS |
| GET | `/api/tis/course/<rwh>` | One section |
| GET | `/api/tis/enrolled` | What's on file |
| POST | `/api/tis/solve` | Conflict-free combinations |
| POST | `/api/tis/add` | Add (dry-run by default) |
| POST | `/api/tis/drop` | Drop (dry-run by default) |
| POST | `/api/tis/add-to-cart` | Cart add |
| POST | `/api/tis/remove-from-cart` | Cart remove |
| GET | `/api/tis/round` | Bid-round info + 剩余积分 |
| POST | `/api/tis/bids` | Submit bid values |
| GET | `/api/tis/course-types` | xkfsdm tab options (personal mode) |

## Page layout

Three-column CSS grid (`grid-template-columns: 380px 1fr 300px`).

```
+--------------------+--------------------------+------------------------+
| LEFT  (380px)      | CENTER (1fr)             | RIGHT (300px)          |
|--------------------|--------------------------|------------------------|
| Mode toggle        | Tabs: grid · solve ·     | pick-stat header       |
| Selection/Catalog  |       eval · bids        | bid-stat link          |
| Search + filters   |  TAB CONTENT             | #pick-list             |
| #filter-pills      |                          | "Safe" actions:        |
| #results-header    |                          |  Export ICS · Save ·   |
|   ◻ select all     |                          |  Load                  |
| #results (cards)   |                          | ── "Real actions" ──   |
|                    |                          |  Sync to TIS · Drop    |
|                    |                          | Enrollment status      |
+--------------------+--------------------------+------------------------+
```

## Tabs

| Tab | DOM id | Default | Purpose |
|---|---|---|---|
| grid | `#tab-grid` | yes | Weekly grid (odd + even), legend, 🎯 Solve |
| solve | `#tab-solve` | | Conflict-free scheduler + blocked-time editor |
| eval | `#tab-eval` | | NCES community eval browse + detail + brief |
| bids | `#tab-bids` | | Bid management (积分选课) + sync to TIS |

Tab switching: `switchTab(name)` at `tis.js` line 2946.

## Persistence

| Layer | Key / format | Restored at |
|---|---|---|
| localStorage | key `tis-picks-v1`, shape `{version:1, picks:[...], savedAt:ISO}` | `DOMContentLoaded` via `loadPicksFromStorage()` |
| File export | `tis-picks-YYYY-MM-DD_HH-MM-SS.json`, same shape | user-triggered Load |
| TIS server | `EXISTING_BIDS` from `/api/tis/enrolled` | `loadEnrolled()` |

## Errors and flash messages

`flash(msg, kind)` at `tis.js` line 1773 surfaces all errors as a
fixed-position banner. `kind` ∈ `'ok' \| 'warn' \| 'err'`. `getJSON`
and `postJSON` (lines 118, 126) have no timeout — TIS over VPN is
slow, and a timeout was a footgun. Callers own error handling via
`.catch()`.
