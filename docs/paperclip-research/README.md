# Paperclip — architecture research

A complete, code-level architecture study of **[Paperclip](https://github.com/paperclipai/paperclip)**
(`paperclipai/paperclip`), read end to end as prior art for **chorus**.

> "If OpenClaw is an _employee_, Paperclip is the _company_." — Paperclip README

Paperclip is the chorus/horizon thesis already shipped, in TypeScript/Node + React:
a control plane that orchestrates a team of AI agents to run a business. It is the
single most relevant reference for chorus, because it solves (or explicitly leaves
open) every problem chorus will face — and because the place it draws its
architectural boundary is exactly the place chorus should draw a *different* one.

These docs were produced by reading the whole repo (all ~90 schema tables, the 146
orchestration services, adapters, routes, realtime, auth, MCP server, UI, plugins,
skills, teams, CLI, and every canonical design doc). `file:symbol` citations point
into the Paperclip repo as of the read (commit on `master`, mid-2026).

## Index

| Doc | Component |
|---|---|
| [01-system-overview.md](01-system-overview.md) | The essence, monorepo shape, one-process boot/wiring, stores, the control-plane⟂execution split |
| [02-data-model.md](02-data-model.md) | The ~90-table data model (org-as-data, DAG-as-data, runtime-as-data) |
| [03-task-lifecycle-orchestration.md](03-task-lifecycle-orchestration.md) | The work loop, push-wakes vs poll-recovery, decomposition, non-blocking re-invocation, atomic checkout, assignment |
| [04-execution-and-adapters.md](04-execution-and-adapters.md) | The adapter contract, the observability boundary, adapter types, environments/workspaces, wakeup/invocation |
| [05-liveness-and-recovery.md](05-liveness-and-recovery.md) | The silent-stall machinery: liveness-as-visibility, the watchdog, three-tier recovery, crash reconciliation |
| [06-governance-budgets-security.md](06-governance-budgets-security.md) | Budgets (two-gate hard-stop), approvals, the authorization engine, secrets, low-trust containment, routines |
| [07-api-realtime-auth-mcp.md](07-api-realtime-auth-mcp.md) | REST surface, WebSocket realtime, the auth model, and the MCP agent↔control-plane contract |
| [08-frontend.md](08-frontend.md) | The React board UI, and how a human *sees* whether the company is working or stuck |
| [09-extensibility.md](09-extensibility.md) | Plugins, skills, teams/company templates, the CLI, and the shared contract layer |
| [10-implications-for-chorus.md](10-implications-for-chorus.md) | The synthesis: what to steal, what dream-native makes unnecessary, the one differentiator |

## The one-paragraph synthesis

Paperclip is a **single-process control plane** (Express + WebSocket + an in-process
scheduler) that orchestrates coding-agent CLIs as **external subprocesses**. It owns
the company, the org chart, the task DAG, budgets, governance, and an elaborate
liveness/recovery layer — but it **never owns the agent loop**. The agent runs in its
own process; the control plane spawns it, tails its stdout, and the agent phones home
over REST/MCP. Everything durable lives in Postgres rows guarded by partial-unique
indexes; nothing important lives in process memory.

**The decisive fact:** during a run, the control plane sees an *opaque byte stream* +
its own lifecycle markers — never the agent's structured tool-calls/turns. So
"is it working or stuck?" is **not observable live** — it is *reconstructed* from
output-silence timing + durable side-effect evidence + DAG row-state. Paperclip's
~350KB liveness/watchdog/recovery subsystem exists **entirely to compensate for that
process boundary.**

**Why this matters for chorus:** chorus is dream-native — it calls `run_task`
in-process and gets dream's *structured event stream*. It **witnesses** liveness
instead of reconstructing it, so most of that subsystem evaporates. But everything
Paperclip got right that is *orthogonal* to observability — the row-based DAG,
exact-once decomposition, blocker-driven re-invocation, two-gate budgets, fail-closed
trust, slug-portable orgs — is directly transplantable. See
[10-implications-for-chorus.md](10-implications-for-chorus.md).
