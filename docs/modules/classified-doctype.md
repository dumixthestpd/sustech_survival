# Classified Documentation

The `docs/` tree is intentionally split into **usage/user docs** and
**developer/internal docs**. This page explains the classification so new
files land in the right place.

## Doc types

| Type | Purpose | Example files |
|---|---|---|
| **User guide** | How to use a module from the CLI/Python. | `docs/en/webui.md`, `docs/en/selectcourse.md`, `docs/en/bb.md` |
| **Architecture / internal** | How a module is implemented, its file layout, contracts, and invariants. | `docs/en/webui-architecture.md`, `docs/en/context.md` |
| **Reference** | Stable links, resources, or external database notes. | `docs/en/resources.md`, `docs/en/cnki.md`, `docs/en/rsc.md`, `docs/en/wos.md` |
| **Dev instructions** | How to contribute or extend the project (skins, new modules, docs). | `docs/dev-instructions/` |
| **Classified index** | This page: where to look for a given doc type. | `docs/modules/classified-doctype.md` |

## How to classify new docs

- If it answers **“how do I use this?”** → put it in `docs/en/` (or `docs/zh/`).
- If it answers **“how does this work internally?”** → use an
  `-architecture.md` suffix or place it under a developer-focused directory.
- If it is a **contribution guide** → put it under `docs/dev-instructions/`.
- If it is a **cross-cutting index/taxonomy** → put it under
  `docs/classified-doctype/`.

## Current mapping

| Doc | Classification |
|---|---|
| `docs/en/webui.md` | User guide — run/serve the web UI |
| `docs/en/webui-architecture.md` | Internal — skin-loader architecture |
| `docs/en/transit.md` | User guide — transit data and CLI |
| `docs/en/tis.md`, `courses.md`, `grades.md` | User guides — TIS workflows |
| `docs/en/sso.md` | User guide + internal auth notes |
| `docs/en/selectcourse.md` | User guide — course selection |
| `docs/en/context.md` | User guide + internal snapshot contract |
| `docs/en/resources.md` | Reference |
| `docs/en/cnki.md`, `rsc.md`, `wos.md` | External database reference |
