# Developing Web UI Skins

A **skin** (also called a web UI head) is a self-contained directory that the
`webui` loader serves. The shipped default skins live at:

```
src/sustech_survival/webui/skins/default/       # English
src/sustech_survival/webui/skins/default_zh/    # Chinese
```

User-installed skins live in:

```
~/.sustech_survival/skins/<skin-name>/
```

## Minimum skin layout

```
my-skin/
  manifest.json      # required
  index.html         # required entry page
  static/            # optional, served under /static/
  tis.html           # optional TIS page
  transit/           # optional transit frontend
```

### manifest.json

```json
{
  "name": "my-skin",
  "version": "1.0.0",
  "requires": "2026.8.0",
  "entry": "index.html",
  "api": []
}
```

- `name` is the unique skin name used by `sustech webui skin set <name>`.
- `requires` is the minimum `sustech_survival` version.
- `entry` defaults to `index.html`.
- `api` lists the `/api/*` endpoints (or whole module namespaces like
  `"tis"`) the skin's pages call. Only the listed endpoints are mounted —
  anything else stays cold (and a name no module provides produces a
  startup warning).

## One language per skin

Skins are single-language — there is **no language switching** in the
loader: no `?lang=`, no `--lang`, no `.zh.html` lookup. A Chinese skin is
simply its own skin (`default_zh`) shipping its own pages. The two shipped
skins carry the same full TIS course-selector engine; only the page shells
differ.

## Static assets

Each skin serves **only its own** static assets from `static/`. There is no
shared package JS fallback. A skin that renders `/tis` ships the engine
itself:

```
my-skin/static/tis/tis.js
```

## Transit

A skin can ship transit in either of these layouts:

```
my-skin/transit/index.html
my-skin/transit/static/...

# or

my-skin/static/transit/index.html
my-skin/static/transit/static/...
```

The loader accepts both. If a skin ships no transit directory, `/transit`
returns 404.

## CLI workflow

```bash
# Install a skin from a directory
sustech webui install --path /path/to/my-skin

# List skins
sustech webui skins

# Set the default skin
sustech webui skin set my-skin
sustech webui skin set default_zh        # switch the default to the Chinese skin

# Delete a user-installed skin
sustech webui skin delete my-skin

# Serve it
sustech webui serve --skin my-skin
```

## Rules for a clean skin

- Do not depend on files outside the skin directory.
- Pick one language per skin and ship its pages in that language.
- Keep `manifest.json` valid; the loader validates the entry page exists.
- List in `manifest.api` exactly the endpoints your pages call.
