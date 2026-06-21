# Cafeteria Menu — Investigation Notes & Future Plan (2026-06-11)

> **Status: no public, machine-readable source found.**
> Original ask: "is there a place that knows what the school cafeteria is serving?"
> This is the full record of what was tried, what was found, and the two paths
> forward if Faux wants to wire this into the skill later.

## TL;DR

- **sus tech.online/canteen/** — stub, last updated 2024-01-22, no menus.
- **SUSTeen-campus/susteen-uni-app** (WeChat mini-app) — source code found, API spec documented, **backend `susteen.itbill.cn` is DNS-dead** (mini-app dev `IT-Bill` is gone, repo dormant since Jan 2024).
- **ehall.sustech.edu.cn** — guest catalog shows 2 categories (研究生服务, 教学事务). Full 78-app student catalog (which likely includes a 餐饮 app) is gated behind CAS auth. Search for "食堂" as guest returned 0 results in the SPA and 0 apps via the JSONP API.
- **sustech.edu.cn campus-life.html** — no public cafeteria / mess / 餐饮 / 后勤 link to any menu site.
- **SUSTEEN WeChat miniapp** (appid `wx3c86aea3e27dee7f`) — may still be published in WeChat even though the web backend is down. Open in WeChat to see live data.

## What I actually checked (not guessed)

| Source | How | Result |
|--------|-----|--------|
| `sustech.edu.cn` homepage | `curl` + grep for `href=` | No dining link in nav |
| `sustech.edu.cn/zh/campus-life.html` | `curl` + grep | 0 links to cafeteria/mess/后勤/餐饮; links to `lib`, `ehall`, `osa`, `ttc`, `sustechef` (foundation), `career`, `talent`, `youth`, `newshub` |
| `sustech.online/canteen/` | `curl` + browser | Stub, last updated 2024-01-22, says "功能更丰富的食堂服务小程序正在开发中" |
| `sustech.online/life/`, `/facility/`, `/surroundings/`, `/service/`, `/study/`, `/transport/` | Browser click-through | None contain cafeteria menus |
| `SUSTeen-campus/susteen-uni-app` source | GitHub raw fetch | Mini-app code with documented API spec — see below |
| `https://susteen.itbill.cn/api/v1/*` | `curl` | DNS-dead (could not resolve host). Backend offline |
| `ehall.sustech.edu.cn` SPA | Browser click-through (search box, sidebar) | 23 apps visible to guest, none for dining; search "食堂" → 0 results |
| `ehall.sustech.edu.cn/jsonp/serviceRoleApp.json?serviceRoleId=1__0&type=all` | `curl` as guest | Returns 2 categories (2 apps total), 0 dining apps |
| `sustechef.sustech.edu.cn` | Browser | "南方科技大学教育基金会" — donation/fundraising site, **not** dining |

## What I **guessed** and was wrong about

I should not have guessed. Logging here so future-me doesn't re-try:

- ❌ `cater.sustech.edu.cn`, `canteen.sustech.edu.cn`, `food.sustech.edu.cn`, `mess.sustech.edu.cn`, `cafeteria.sustech.edu.cn`, `logistics.sustech.edu.cn`, `houqin.sustech.edu.cn`, etc. (12 subdomains) — **never probed, just guessed**. None of these were checked.
- ❌ `sustechef.sustech.edu.cn` — I initially thought "ef" = "e-Food". **Wrong.** It's the Education Foundation (教育基金会). Confirmed by browsing the page.

## Documented API spec (from the dead SUSTeen-uni-app, for reference)

```js
// main.js
$http.baseUrl = 'https://susteen.itbill.cn/api/v1'   // ← DNS-dead

// canteen-guide.vue  →  list canteens
GET /traffic/canteens                  → [{ canteen_id, canteen_name, time, ... }]
// canteen-booth-list.vue  →  booths in a canteen
GET /traffic/canteens/{canteen_id}     → [{ booth_id, booth_name, avg_number, ... }]
// canteen-booth-detail.vue  →  traffic time-series
GET /traffic/booths/{booth_id}?date=YYYYMMDD&meal=0|1|2
//   meal: 0=早餐, 1=午餐, 2=晚餐
// older endpoint, used by cache.vue
GET /traffic/canteen_list
```

If the backend ever comes back online, this is the complete contract — no reverse-engineering needed.

WeChat miniapp metadata (per `manifest.json`):
- appid: `wx3c86aea3e27dee7f`
- uni-app appid: `__UNI__5E22692`
- dev: `IT-Bill` (GitHub), last commit 2024-01-22

## Future plans (two paths)

### Path A — ehall 餐饮 app via CAS auth

1. Get a fresh SSO session (Playwright + CAS login, per `~/.openclaw/workspace/skills/sustech_survival/references/ehall-auth-2026-06-01.md`).
2. Hit `ehall.sustech.edu.cn/jsonp/serviceRoleApp.json?serviceRoleId=1__0&type=all` with the session cookies — should return the full 78-app catalog.
3. Search the catalog for any app whose `appName` matches `餐|食|饮|canteen|mess|dining|膳食|食堂|后勤`.
4. If found: walk the app's `entranceUrl` or `pcOpenUrl`, discover its data source, and either:
   - Add an `EhallCanteenClient` to `sustech_survival.ehall` that fetches today's menu
   - Document the URL + auth flow in a new `references/ehall-canteen.md`
5. If not found: the ehall doesn't expose a public 餐饮 app to students. Try the SUSTech official 膳食服务 / 后勤保障部 site (URL unknown — needs separate discovery).

### Path B — SUSTEEN WeChat miniapp screenshot → OCR/scrape

1. Faux opens the miniapp on phone (search "SUSTEEN" in WeChat).
2. Screenshot the home + 今日菜谱 + 食堂向导 pages.
3. OCR with `pytesseract` or `marker-pdf` (if PDF) — extract dish names, prices, queue counts.
4. If the data is image-based (which it appears to be in the source — `image/` has photo backgrounds for cards), there's no clean machine-readable source. Manual transcription into a structured file (`cafeteria_menu_YYYY-MM-DD.yaml`) is the only option.

### Path C — official 膳食服务 / 后勤保障部 site

- Search via Baidu/Google for "南方科技大学 膳食服务 菜谱" or check the SUSTech 后勤保障部 org chart.
- The site may not exist (public SUSTech site doesn't link to one), but worth a Baidu search.
- This is a fallback if Paths A and B both fail.

## Pitfalls

- Don't trust subdomains on `*.sustech.edu.cn` without checking the actual page title — `sustechef` looked like dining, was the foundation.
- `ehall` guest catalog is **deliberately limited**. Don't conclude "no dining app" from the guest view alone.
- The SUSTeen-uni-app source code is from a dormant project. The backend may come back, but the dev (`IT-Bill`) is gone, so don't expect maintenance.
- WeChat miniapp URLs are not browsable from a regular browser — you can only open them in the WeChat app.

## Related

- `docs/resources.md` — canonical external resources list in this skill
- `references/ehall-auth-2026-06-01.md` — ehall SSO flow (Path A prerequisite)
- `references/ehall-spa-discovery.md` — ehall SPA discovery techniques
- `~/.hermes/skills/sustech/sustech_survival/references/student-life-resources.md` — the curated student-life hub list; has a Cafeteria row pointing here
