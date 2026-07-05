# NCES in the unified web UI — plan

## Context

User asked: *"can we continue to build nces to satisfy the need of community
course eval?"*

This is feature (2) of the course-selector web UI (alongside course search
and solver). The current state already has a placeholder endpoint
`GET /api/tis/nces?code=X` that just returns a `direct_url` linking out to
`ncesnext.com/search?q=<code>`.

## What the live system actually allows

I probed `ncesnext.com` directly today (2026-07-05):

| Path | Result |
|---|---|
| `GET /` | HTTP 200, but body is **Anubis PoW challenge page** (4.4KB), not real content |
| `GET /search?q=MSE306` | Same — Anubis challenge, no data |
| `GET /course/8721/` | Same |
| `GET /api/*` | Routes exist in `robots.txt` but every request returns the Anubis challenge page (HTTP 200, body=HTML) |
| `GET /sitemap.xml` | 172KB, real sitemap with `/course/<id>/#review-<id>` URLs |
| `GET /robots.txt` | Disallows `/api/*` and `/course/*/material/`, `/vote`, `/follow`, etc. |
| `web_extract` on ncesnext.com | Times out (parallel extractor can't pass Anubis either) |
| Response headers | No `Content-Security-Policy`, no `X-Frame-Options` → **iframe embedding will work** |

**Conclusion:** ncesnext.com is behind **Anubis** (Proof-of-Work challenge
via `/.within.website/x/cmd/anubis/`). The page only renders after the
client solves a SHA256 PoW. This blocks all four server-side options:

- ❌ `requests` / `curl` — can't solve PoW
- ❌ `cloudscraper` / `flaresolverr` — Anubis isn't Cloudflare
- ❌ `web_extract` (Hermes parallel extractor) — also blocked
- ✅ User's browser — solves PoW in JS automatically
- ✅ Iframe — works because no `frame-ancestors` CSP

## Option survey

I considered five approaches. **Scraping-by-Anubis-solver is a 200+ line
undertaking with ongoing arms-race risk** — I rejected it as not worth the
maintenance burden. The three viable options are below.

### Option A — Direct URL only (status quo) ⭐ minimal
**What:** keep `/api/tis/nces?code=X` returning a `direct_url`.
**UX:** "View evaluations on NCES ↗" link opens in new tab.
**Pros:** zero new code, zero deps, no breakage.
**Cons:** user leaves the app, no in-context summary.

### Option B — In-app iframe (recommended) ⭐⭐⭐
**What:** render NCES in an `<iframe>` inside the eval tab. The
browser solves Anubis automatically; once user is on ncesnext.com
with cookies set, search/filters update via URL params.
**UX:** full NCES inside the course selector; back button returns
to TIS.
**Pros:** in-context, all NCES features work, no maintenance burden,
zero server cost, no extra deps.
**Cons:** iframe is `~600px` wide on the eval pane (small but workable).
The user's session to ncesnext.com is shared with normal browser tabs.

**Implementation cost:** ~25 lines. New route
`/tis/nces-embed?code=X` returns a tiny HTML wrapper:

```html
<!doctype html>
<html><body style="margin:0;padding:0;overflow:hidden">
  <iframe src="https://ncesnext.com/search?q={{code}}"
          style="width:100vw;height:100vh;border:0"></iframe>
</body></html>
```

Frontend replaces `renderEval`'s "View on NCES ↗" with an iframe
panel. Width auto-fits the eval pane.

### Option C — Playwright solver (heavy) ⭐⭐
**What:** add `[playwright]` extra to webui deps, launch headless
Chromium per request, let it solve Anubis, scrape `__NEXT_DATA__`,
return JSON to frontend.
**UX:** structured data rendered inline (no iframe).
**Pros:** works headless server-side, clean data.
**Cons:**
- 200MB+ Chromium download per install
- ~3-5s per request (cold launch) — kills interactive UX
- Anubis version can change; maintenance burden
- Likely violates ncesnext.com ToS
- Re-introduces the "we already removed this" chromium dep

### Option D — Anubis PoW solver in pure Python
**What:** reimplement Anubis's challenge in Python (the algorithm is
documented; difficulty=2 takes ~5-15s of SHA256 mining). Then pass
the cookie through a normal request.
**Pros:** no Chromium dep.
**Cons:**
- Server-side PoW mining violates ncesnext.com's stated anti-AI-scraping
  policy ("Anubis is a compromise … make scraping much more expensive")
- Arms race — they will raise difficulty
- Slow first request (~10s); subsequent requests OK while cookie lives
- Ethical grey area (the Anubis page explicitly calls out "AI companies
  aggressively scraping websites")

**Not recommended.** The ToS signal is loud and clear.

### Option E — Hybrid: cache results
Combine B (iframe for live data) with a small server-side cache of
manually-imported JSON snapshots (user pastes the eval JSON from
their own browser session once, we serve it to everyone else).
**Pros:** zero scraping, community-sourced data.
**Cons:** needs a place to store + share the cache.

## Recommendation

**Option B (iframe embed)** for the web UI — gives users a real
in-app experience with zero new dependencies and respects
ncesnext.com's anti-scraping posture.

**Option A (direct URL)** stays as a fallback for users who prefer
opening in a new tab, and for when the iframe is blocked.

**Skipped:** C, D (heavy/maintenance burden + ToS). E is interesting
but out of scope for this round.

## Proposed file set

```
src/sustech_survival/webui/
├── blueprints/tis.py                 # MOD: extend /api/tis/nces to return
│                                       #      embed_url alongside direct_url
├── templates/tis.html                # MOD: eval tab gets a top-bar with
│                                       #      "Open in new tab" + iframe
├── templates/nces_embed.html         # NEW: 9-line HTML wrapper

src/sustech_survival/nces/
└── __init__.py                        # No changes (lazy stub stays)

~/.hermes/skills/sustech/nces/SKILL.md  # MOD: add "iframe strategy" section
~/.hermes/skills/sustech-dev/SKILL.md   # MOD: add ncesnext catalog entry
                                         #      noting Anubis + iframe
```

No new dependencies. No Python changes. No CLI changes.

## Verification bar

Before declaring done:
1. Open the web UI in browser, click an MSE306 card → eval tab shows
   iframe loading ncesnext.com search for MSE306
2. Iframe renders, user can solve Anubis once, then full NCES search
   is visible inside the course selector
3. "Open in new tab ↗" button still works as fallback
4. All 4 Python versions (3.10/3.11/3.12/3.14) still pass unified CLI
   smoke test (no regressions)
5. Existing endpoints (`/api/tis/courses`, `/api/tis/solve`) still work
6. Build clean: `python -m build` produces wheel + tar.gz without errors

## Open questions for you

1. **Embed height**: full viewport-height iframe vs. fixed ~600px
   scrolling region? (Default plan: 600px, scrolls inside the pane)
2. **Anubis on first load**: the iframe shows Anubis once; subsequent
   visits (cookie cached) skip it. Want me to add a hint "First time?
   Click 'I'm not a bot' — solved once, cached forever after" tooltip?
3. **Other NCES sources**: c.x-d.fun might have its own eval data — do
   you want me to investigate, or stick to ncesnext.com only?