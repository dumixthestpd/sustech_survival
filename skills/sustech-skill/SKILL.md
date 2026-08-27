---
name: sustech-skill
description: Use the installed `sustech` CLI (from the `sustech_survival` package) for SUSTech academic systems — Blackboard, TIS, course selection, library, papers, NCES, faculty, transit, WS, PMS, booking, Wi-Fi, and the unified Web UI. Prefer `sustech <service> <verb>` commands over scraping websites or reverse-engineering endpoints. Re-discover the surface with `sustech --help` and `sustech consequence list`; do not rely on memorized commands. Do not use for unrelated universities.
---

# SUSTech academic systems — CLI wrapper

The `sustech_survival` package wraps SUSTech's academic systems as a typed,
machine-friendly CLI. This skill teaches an agent to use the installed CLI
correctly: pick the right service, authenticate via the shared CAS backbone,
discover the live command surface instead of guessing, gate destructive
operations behind the documented confirmation flow, and read or mutate
state through `--json or `--confirm`.

## Install

```bash
pip install "sustech_survival @ git+https://github.com/dumixthestpd/sustech_survival.git"
```

Verify:

```bash
sustech --version            # sustech_survival <version>
sustech --help               # discover top-level subcommands
```

If `sustech` is not on `PATH`, report that. Do not assume a source
checkout is needed; do not auto-install without the user's go-ahead.

## Discover the live surface

The CLI evolves. Do not memorize the command list — query it.

```bash
sustech --help               # top-level subcommands
sustech <service> --help     # verbs under one service
sustech consequence list     # mutation ops + their risks (single source of truth)
sustech consequence show <op># one operation's risk + verification rules
```

`sustech consequence list` is the canonical map of every state-changing
operation, with a stable identifier, a risk class, and the verification
rule that proves the change took effect. Re-query it; do not paraphrase it.

## Authentication — shared CAS backbone

All authenticated services share one credential set, stored by `sustech
sso creds`:

```bash
sustech sso creds --set --sid <sid> --password-stdin   # never pass --password via argv
sustech sso check                                       # confirm credentials work
```

- `sustech sso creds --set` reads the password from stdin (never
  `argv`/shell history). When running in an agent context where the user
  pastes the password, pipe it: `printf '%s' "$pw" | sustech sso creds
  --set --sid <sid> --password-stdin`.
- Off-campus publisher flows (CNKI / RSC / WoS) layer a Shibboleth +
  CARSI federation on top of CAS; the same `sso creds` entry feeds them.
- The Shibboleth consent screen occasionally appears in English with
  `<input type="submit" name="_eventId_proceed">` as the continue button
  (no visible label). Use the `_eventId_proceed` selector.

## Route common requests

Map the user's request to a service + verb. The exact names live in
`sustech --help`; the high-value areas:

| Area | Service | Typical verbs |
|---|---|---|
| Calendar / academic year | `sustech tis` | `terms`, `today`, `week`, `day`, `evals` |
| Course catalog / schedule | `sustech tis` | `courses`, `schedule`, `courses-search`, `grades` |
| Course selection (term) | `sustech selectcourse` | `list`, `enrolled`, `export-table` |
| Blackboard | `sustech bb` | `courses`, `content`, `assignments`, `ddl`, `download`, `submit` |
| Library (Primo) | `sustech lib` | `search`, `detail` |
| Library room booking | `sustech lib-booking` | `labs`, `rooms`, `reservations`, `home-summary` |
| E-Hall facility booking | `sustech booking` | `rooms`, `my-meetings`, `create`, `cancel` |
| Paper search | `sustech papers` | `search` |
| NCES course eval | `sustech nces` | `browse`, `search`, `course` |
| Faculty directory | `sustech faculty` | `departments`, `list`, `get`, `search`, `render` |
| Campus bus / nav | `sustech transit` | `lines`, `stops`, `schedule`, `live` |
| Campus Wi-Fi | `sustech wifi` | `status`, `events` |
| WS (exchange / abroad) | `sustech ws` | `programs`, `detail` |
| Print queue (PMS) | `sustech pms` | `submit`, `status`, `history` |
| Profile (export/import) | `sustech profile` | `show`, `export`, `import` |

Context snapshot (what's happening right now):

```bash
sustech context              # week, term, holidays, current period
sustech context --json       # machine-readable
```

## Output for people vs agents

Human-readable text is the default. For agents and scripts, request JSON:

```bash
sustech tis courses search "machine learning"
sustech tis courses search "machine learning" --json
sustech tis courses search "machine learning" --json --pretty
```

Always prefer `--json` for any data the agent will post-process. Pipe the
output through `jq`; do not parse human-format text.

## Mutating operations — consequence + confirm gate

State-changing operations live behind two gates:

1. **`sustech consequence list`** documents every mutation (id, risk
   class, verification rule). Re-query it before any write.
2. **`--confirm`** is the explicit gate for irreversible operations
   (Blackboard submission, TIS enrollment, room booking creation/cancel).
   The command must echo back the target and wait for `--confirm` before
   sending.

Workflow for any mutation:

```bash
# 1. Inspect the risk
sustech consequence show <operation-id>

# 2. Preview (dry run)
sustech <service> <verb> ... --preview        # where supported

# 3. Apply with explicit confirm
sustech <service> <verb> ... --confirm

# 4. Verify the change took effect
sustech <service> <verb> --verify             # or re-read after apply
```

Never skip `--confirm` for irreversible operations. Never reuse a
confirmation from a previous command — each call's confirmation is for
that call's exact target.

## Web UI

For interactive flows (drag-drop cart, live bus map, NCES browse) the CLI
launches a local Flask app:

```bash
sustech webui serve --port 20129
# open http://localhost:20129/ in the user's browser
```

The UI is one Flask app, one port. If the user prefers a different
language, the default skin is `default` (en) or `default_zh` (zh); switch
with `sustech webui serve --skin default_zh` or `--skin-path <dir>` for a
custom skin.

## Troubleshooting

- **`401 / "session 失效"`** — credentials expired or wrong. Run
  `sustech sso creds --status`, then `sustech sso check`. If credentials
  are correct but the call still fails, the session cookie may have
  expired mid-flow — retry once with `sustech sso check` first.
- **Command not in `--help`** — re-query; the CLI added or renamed a
  verb. Do not assume an old verb still exists.
- **Off-campus paywalled resource (CNKI / RSC / WoS)** — the user must be
  routed through the SUSTech Shibboleth IdP. Trigger the SUSTech login
  flow, then CARSI WAYF (search institution → submit), then the
  publisher page. The full chain lives in the `sso` skill (not bundled
  here — the local skill pack at `~/.hermes/skills/sustech/sso/` has
  the live procedure).
- **Mutation succeeded but the user sees old state** — re-read after
  `apply`. Some services cache; the `confirm` step does not invalidate
  read caches.

## Source of truth for the CLI

This skill is a wrapper. The authoritative reference is the docs site
(per-service pages + module indexes) and the in-CLI `--help` text:

- Site: <https://dumixthestpd.github.io/sustech_survival/>
- Per-service: `sustech <service> --help`
- Live mutation map: `sustech consequence list`