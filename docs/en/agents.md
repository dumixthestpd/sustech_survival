# Agents (AI)

How AI agents integrate with `sustech_survival`.

**Strategy — differentiate, don't align.** The TypeScript port
([`wormforce/sustech-cli`](https://github.com/wormforce/sustech-cli)) already
owns the "agent-ready CLI + MCP server" lane (`sustech` / `sustech-mcp`).
This module deliberately does **not** clone that with a Python MCP server.
Python's edge here is different and deeper:

- an **in-process API** — agents that run Python get the full library, not a CLI text stream;
- a **language-neutral HTTP contract** (`/api/*`) — any-language agents can use our data without our command name;
- a **consequence-rich write safety layer** — every mutating operation is tagged with severity/risk and a confirmation gate.

There is no single "right" surface; pick per agent. The three are equivalent views of the same module.

---

## 1. In-process Python API (Python agents — richest)

```python
import sustech_survival
from sustech_survival import Context

# Daily snapshot: date, week, deadlines, exams, class-now, weather, AQI.
snapshot = Context(level=Context.Level.NORMAL).to_dict()

# Flask-free data contract (sustech_survival.api — tis / nces / transit).
from sustech_survival import api
courses = api.tis.courses(...)      # enrolled courses, grades, etc.
rating  = api.nces.ratings([{"code": "BIO103", "teacher": "..."}])
```

### Risk-aware writes (`sustech_survival.consequence`)

Every operation that changes real student state (drop, bid, booking,
submission, eval, PMS upload) carries a structured `Consequence` descriptor.
**Surface it to the user before acting** — this is our agent-safety
differentiator:

```python
from sustech_survival.consequence import consequence_by_name, require_confirmation

desc = consequence_by_name("selectcourse.drop_course")
print(desc.severity, desc.irreversible)   # Severity.HIGH, True
print(desc.what_changes)                  # "Drops this course section on TIS"
print(desc.risk)                          # human-readable risk note

# The CLI enforces the gate: consequence-rich ops raise
# ConfirmationRequired unless dry_run or explicitly confirmed (--yes/--commit).
```

See `sustech_survival/consequence.py` for the full contract (`Severity`,
`Consequence`, `consequence_rich`, `consequence_of`, `require_confirmation`).

---

## 2. HTTP `/api/*` (any language)

Run the webui head and use its JSON endpoints — the same skin-driven contract
the web UI consumes (see [webui-architecture](webui-architecture.md)):

```bash
sustech webui serve --port 20129
# GET  http://127.0.0.1:20129/api/tis/courses?...
# POST http://127.0.0.1:20129/api/nces/ratings   {"items": [...]}
# GET  http://127.0.0.1:20129/api/transit/live
```

Language-neutral — agents in any language can use our data without our
command name.

---

## 3. CLI

```bash
sustech context --json
sustech tis courses
sustech bb session check
```

The `sustech` command comes from this package. If the TypeScript port
(`wormforce/sustech-cli`) is also installed, `where sustech` shows which one
wins on this machine — invoke by full path to disambiguate.

---

## Credentials

Agents authenticate via the `$SUSTECH_CREDENTIALS` env var (path to a
`sid:password` file) — see [SSO](sso.md), "Auth Rules (Non-Negotiable for
Agents)".
