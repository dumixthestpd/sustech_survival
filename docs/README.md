# Documentation Layout

The docs are classified by **module/system**, not by document type.

```
docs/
  en/                  English source pages
  zh/                  Chinese source pages
  tis/                 TIS-related docs
  bb/                  Blackboard-related docs
  webui/               Web UI docs
  transit/             Transit docs
  ...                  one directory per module/system
  dev-instructions/    contribution / extension guides
```

Each module directory contains a `README.md` landing page that links to the
relevant English and Chinese pages, plus any architecture or dev notes for
that module.

## Why module directories?

- It is easy to find everything about one system in one place.
- `webui.md` (user guide) and `webui-architecture.md` (internal design) both
  belong under `webui/`, not in two unrelated top-level categories.
- New contributors can look at `dev-instructions/` for how to build/extend a
  module, while users can look at `en/` or `zh/`.
