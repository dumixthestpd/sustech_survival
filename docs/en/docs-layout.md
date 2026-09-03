# Documentation Layout

The docs are classified by **module/system**, not by document type.

```
docs/
  en/                  English source pages
  zh/                  Chinese source pages
  modules/             Per-module landing pages (one .md per module)
  dev-instructions/    contribution / extension guides
```

Each module landing page in `modules/` links to the relevant English and
Chinese pages, plus any architecture or dev notes for that module.

## Why modules/ instead of per-module dirs?

- Each module's landing page (`modules/tis.md`, `modules/webui.md`, ...) is a
  single file that aggregates links to its user guide, Chinese version, and
  any architecture or dev notes — easier to scan than opening a directory.
- The slug (`/modules/tis/`) is distinct from the user-guide slug
  (`/tis/`), so cross-links never collide.
- New contributors can look at `dev-instructions/` for how to build/extend a
  module, while users can look at `en/` or `zh/`.
