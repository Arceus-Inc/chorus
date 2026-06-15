# chorus — enriched specs

Buildable, code-level specs for **chorus**, grounded in a fresh deep assessment of the
Paperclip codebase (clone `412a04c`, 2026-06-12 — current), the dream SDK, and our
core beliefs.

These are the self-contained *implementation* specs — the beliefs, the dream/Paperclip
assessment, and the design thinking are folded directly into them. Background research lives
in [paperclip-research/](../../paperclip-research/).

## The spec set

One chorus spec per Paperclip research dimension — so coverage is at parity, not lopsided.

| # | Spec | Paperclip counterpart | What it fixes |
|---|---|---|---|
| [00](00-architecture.md) | **Architecture & scope** | `01-system-overview` | what chorus is, the layering, the repo shape, the boundary, non-goals, the dream-native thesis |
| [01](01-data-model.md) | **Data model** | `02-data-model` | the ledger — tasks, two-lock checkout, decomposition, dependencies, wakes, routines, runs, recovery, workforce, goals, budgets — with the verbatim partial-unique-index crash-safety contracts |
| [02](02-lifecycle-and-recovery.md) | **Lifecycle & recovery** | `03` + `05` + execution-semantics | the status FSM, the liveness-as-visibility contract, exact-once decomposition, the three-tier recovery ladder, monitors |
| [03](03-scheduler.md) | **Scheduler (heartbeat + cron)** | `03-task-lifecycle` | the tick (kernel pulse), the wake model, cron/routines, the beat |
| [04](04-outcomes-and-governance.md) | **Outcomes, DoD & governance** | `06-governance` | the evaluator-verified DoD (the differentiator), the artifact model, two-gate budgets, fail-closed trust |
| [05](05-dream-seam.md) | **The dream seam (execution)** | `04-execution-and-adapters` | how a beat invokes `run_task`, witnessing the event stream, the DoD pass-down, the deleted adapter/MCP stack |
| [06](06-roles-and-workforce.md) | **Roles & workforce** | `02` (agents) + `09` (skills) | employee = replayable identity, role = toolset+DoD+outcome, the org tree, assignment, the thin role `.md` |
| [07](07-memory.md) | **Memory** | `memory-landscape.md` | scopes, read-at-start, append-only writer, provenance, the lattice seam |
| [08](08-observability.md) | **Observability & inspection** | `08-frontend` + `observability.md` | the event taxonomy, working-vs-stuck *witnessed* not guessed, the inspector, opt-in tracing |
| [09](09-extensibility-and-portability.md) | **Extensibility & portability** | `09-extensibility` | role plugins, skills, the slug-portable company package, the contract layer |
| [10](10-public-api-and-cli.md) | **Public API & CLI** | `07-api-realtime-auth-mcp` | the `Chorus` facade, the CLI, the public-API pin, why there's no REST/MCP |
| [11](11-build-plan.md) | **Build plan (M1→M4)** | `10-implications` | per-milestone goal, tables, dream APIs, new code, acceptance, deferrals |
| [12](12-storage.md) | **Storage architecture** | `DATABASE.md` | store→backend routing, SQLite-now-vs-Postgres-later, the portable-intersection rules, the `Ledger` conformance test |

## The frame these specs assume (from the beliefs)

- **dream-native.** chorus calls `dream.run_task` in-process and witnesses its structured
  event stream. There is **no subprocess adapter, no MCP phone-home, no output-silence
  watchdog** — the three things that bloat Paperclip. (B2.2)
- **Four repos.** dream · chorus · horizon · lattice (strict bottom-up; siblings never import each
  other). chorus *stubs* intake until **horizon** ships (horizon then owns direction/what-to-do-next),
  and writes **raw sprint memory** while **lattice** owns consolidation. Both seams are reserved,
  neither sibling is absorbed. (see chorus-on-dream.md)
- **Storage.** SQLite-WAL is the SDK default; Postgres is the Arceus driver. The schema
  stays in the SQLite ∩ Postgres intersection. Partial-unique indexes work in both. (B2.1)
- **Reuse dream's coordination.** The two-lock atomic checkout + lease live on dream's
  `coordination` board (`board.sqlite`); chorus does **not** rebuild them.
- **The differentiator.** Paperclip's ROADMAP still lists **Enforced Outcomes**, **Memory**,
  and **Artifacts** as ⚪ open. chorus closes Enforced Outcomes at M1 because dream's
  evaluator verifies the real artifact against a typed DoD. (B3.1)

## What each Paperclip table becomes

| Paperclip | chorus | Note |
|---|---|---|
| `issues` (+ 2 locks) | `task` | locks delegated to dream coordination board |
| `issue_relations type=blocks` | `task_dependency` | `depends_on` edges |
| `issue_plan_decompositions` | `decomposition_claim` | exact-once fan-out |
| `issue_recovery_actions` | `recovery_action` | liveness-as-visibility |
| `agent_wakeup_requests` | `wake` | coalescing push inbox |
| `heartbeat_runs` | `run` | **thin** — no PID/stdout/silence cols |
| `routines`/`routine_triggers`/`routine_runs` | `routine`/`routine_trigger`/`routine_run` | cron |
| `agents` (`reportsTo`) | `employee` | the Workforce |
| `goals` | `goal` | alignment tree |
| `budget_*`/`cost_events` | `budget_policy`/`budget_incident`/`cost_event` | two-gate |
| `documents`/work-products | `artifact` | outcome landing |
| — *(absent in PC)* | `dod` (typed verifier) | the differentiator |
