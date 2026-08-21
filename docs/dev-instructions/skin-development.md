# Developing Web UI Skins

A **skin** (also called a web UI head) is a self-contained directory that the
`webui` loader serves. The shipped default skin lives at:

```
src/sustech_survival/webui/skins/default/
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

## Localization

Skins can ship localized page variants. The loader checks, in order:

1. `index.zh.html` / `index_zh.html`
2. `index.html`

The same pattern applies to `tis.html`, `transit/index.html`, etc.

Users select a language with:

```bash
sustech webui serve --lang zh
sustech webui set-lang zh
# or per-request: /any/page?lang=zh
```

## Static assets

Each skin serves **only its own** static assets from `static/`. There is no
shared package JS fallback. A skin that needs TIS JavaScript must ship:

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

# Delete a user-installed skin
sustech webui skin delete my-skin

# Serve it
sustech webui serve --skin my-skin
```

## Rules for a clean skin

- Do not depend on files outside the skin directory.
- Ship your own `static/tis/tis.js` if you render `/tis`.
- Ship `index.zh.html` only if you actually provide Chinese content.
- Keep `manifest.json` valid; the loader validates the entry page exists.
