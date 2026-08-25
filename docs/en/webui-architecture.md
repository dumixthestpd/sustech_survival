# Web UI Architecture

> How the skin-loader head is put together. Pure facts — what the code is,
> what it does, where each piece lives.

## The model

One Flask app, one port (`:20129`). The active **skin** is a self-contained
directory that owns every page and static asset the app serves. The shipped
skins carry the full TIS course-selector engine (the 5-step workflow:
search → pick → conflict-free schedule → compare → bid & sync) plus the
transit map frontend. The head itself stays thin: it picks the skin, serves
its files, and mounts the `/api/*` endpoints the skin's manifest declares.

```
browser ──> skin pages (HTML/CSS/JS — the course-selector engine, transit map)
      \        |
       \       v
        └──> /api/*  (JSON contract, mounted per module)
                  |
                  v
         sustech_survival.api (Flask-free data functions)
                  |
                  v
         clients (SelectCourseClient, TransitClient, NCES…)
```

The browser never talks to SUSTech directly: every `/api/*` route calls the
existing Python clients server-side, so credentials never leave the process.

## Files

| Path | Role |
|---|---|
| `webui/loader.py` | Skin discovery/validation: `installed_skins()`, `find_skin()`, `install_skin()`, manifest parsing |
| `webui/app.py` | `create_app()` — resolves the active skin, serves its pages + static, mounts its declared APIs |
| `webui/api_registry.py` | The skin-driven API exposure: each module's `api.py` declares endpoints; the skin's `manifest.api` picks which get mounted |
| `webui/skins/<name>/` | One skin: `manifest.json`, entry page, own pages + static |
| `webui/skins/default/` | English skin: landing + full course-selector engine (`tis.html` + `static/tis/tis.js`) + transit |
| `webui/skins/default_zh/` | Chinese skin — same engine, Chinese page shells |
| `docs/dev-instructions/skin-development.md` | How to author and install skins |

## Skin resolution

Explicit `--skin-path` > explicit `--skin` name > `webui.skin` saved in
`config.json` > first installed skin > shipped `default`. `create_app()`
works with zero installed skins (in-package default head). A user-installed
skin of the same name shadows the shipped one (that's how
`sustech webui install default` gives you a moddable copy).

## Pages and language

Each skin ships its pages in **one language** — `default` is English,
`default_zh` is Chinese. There is no locale machinery in the loader: no
`?lang=`, no `--lang`, no `.zh.html` lookup. The Chinese skin's `tis.html`
hardcodes its Chinese page shell (the engine's dynamic messages stay
English; see the localization note at the bottom of `default_zh/tis.html`).

- `/` — the skin's manifest `entry` (default `index.html`).
- `/static/<path>` — the skin's own `static/`, then the skin's transit
  assets. No cross-skin fallback; path traversal is rejected (safe-joined
  to the skin root).
- `/<page>` — a catch-all serves `<skin>/<page>.html` or
  `<skin>/<page>/index.html`, so a skin can ship new pages without the head
  knowing about them.
- `/tis`, `/transit` — module routes (`selectcourse/api.py`,
  `transit/api.py`) resolve the *skin's* `tis.html` / transit `index.html`
  and 404 when the skin drops the feature.

## API exposure

Each submodule that wants web endpoints declares them in its own `api.py`
(no central route table to drift). The active skin's `manifest.api` lists
what it needs — a bare `"tis"` pulls in every `tis.*` endpoint, a dotted
`"tis.info"` pulls exactly one. Endpoints the skin didn't ask for are not
mounted. A manifest name no module provides logs a startup warning instead
of a runtime 404.

## The course-selector engine

The engine (`default/static/tis/tis.js`, ~6k lines) is an IIFE that owns
state (`PICKED`, catalog caches, NCES eval cache, bid values), renders the
5-step workflow, and talks to `/api/tis/*` + `/api/nces/*`. Each skin ships
its own copy of the engine under `static/tis/tis.js` — there is no shared
package JS fallback.
