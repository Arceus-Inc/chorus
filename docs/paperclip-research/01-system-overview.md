# 01 — System overview

## What Paperclip is

A **control plane for AI-agent companies** (`doc/GOAL.md`, `doc/PRODUCT.md`): one
instance runs many companies; every "employee" is an AI agent that runs externally
and phones home. The control plane owns org-as-data, the task DAG, goals, budgets,
governance, approvals, secrets, and routines. Its self-description:

> "It looks like a task manager. Under the hood: org charts, budgets, governance,
> goal alignment, and agent coordination."

The product is built around a **two-layer model** (`doc/GOAL.md` §Architecture):

1. **Control plane** (this software) — the nervous system: agent registry + org
   chart, task assignment + status, budget/spend tracking, comments/documents/work
   products, the goal hierarchy, and heartbeat monitoring. It enforces
   execution-control semantics (single-assignee issues, atomic checkout, execution
   locks, blockers, recovery, workspace controls).
2. **Execution services (adapters)** — agents run externally and report in. *"The
   control plane doesn't run agents. It orchestrates them. Agents run wherever they
   run and phone home."*

## Monorepo shape

pnpm workspace (`pnpm-workspace.yaml`). Languages: ~1600 `.ts`, ~480 `.tsx`.

```
server/         Express REST API + WebSocket + 146 orchestration services
ui/             React + Vite board UI (the human control surface)
packages/
  db/           Drizzle schema (~90 tables), migrations, Postgres/PGlite clients
  shared/       Zod schemas + constants + validators — the contract spine
  adapters/*    one package per agent runtime (claude-local, codex, cursor, …)
  adapter-utils/  shared adapter plumbing (process spawn, kill, transcript types)
  mcp-server/   a stdio MCP server that fronts the REST API for agents
  plugins/      the plugin SDK + examples + sandbox providers
  skills-catalog/  installable markdown skill packs
  teams-catalog/   reusable company/team templates
cli/            the `paperclipai` CLI (instance setup + control-plane client)
doc/            design docs (SPEC, SPEC-implementation, execution-semantics, …)
evals/          promptfoo behavior evals for the heartbeat skill
```

`packages/shared` is the dependency root — the MCP server, CLI, plugins, server, and
UI all import the same Zod/constant contracts.

## One process, in-process scheduler

The entire backend runs in **one Node process** (`server/src/index.ts:startServer`).
The spec is explicit: *"A lightweight scheduler/worker in the server process handles
heartbeat trigger checks, stuck run detection, budget threshold checks. Separate queue
infrastructure is not required for V1."* (`doc/SPEC-implementation.md` §6.3).

Boot sequence (`server/src/index.ts`):

1. Await OTel instrumentation (`instrumentation.ts`, no-op unless
   `OTEL_EXPORTER_OTLP_ENDPOINT` is set).
2. Create DB — embedded PostgreSQL (PGlite) under `~/.paperclip/instances/default/db`
   when `DATABASE_URL` is unset; apply pending Drizzle migrations.
3. `createApp(db, …)` builds the Express app (`server/src/app.ts`).
4. `setupLiveEventsWebSocketServer(...)` mounts the WebSocket realtime server on the
   raw HTTP server's `upgrade` handler.
5. Boot services: `heartbeatService` (the scheduler), `routineService`,
   `pluginWorkerManager`, `adapter-registry-bootstrap` (`reconcileAdapterAvailability`),
   storage service, telemetry.
6. **Startup crash-reconciliation**: `reconcileCloudUpstreamRunsOnStartup`,
   `reconcilePersistedRuntimeServicesOnStartup`, plus the recovery loop's startup pass
   (reap orphaned runs → resume queued runs → reconcile stranded work → scan silent
   runs → sweep stale locks) — see [05-liveness-and-recovery.md](05-liveness-and-recovery.md).

So a single process hosts: the REST API, the WebSocket fan-out, the heartbeat
scheduler (a `setInterval`), the plugin workers, and (in dev) the Vite UI middleware.
There is **no external queue, no Redis, no separate worker tier** in V1. The realtime
event bus is an in-process Node `EventEmitter` keyed by `companyId`
(`server/src/services/live-events.ts`), which is the one explicit single-process
scaling seam.

## The request pipeline (`server/src/app.ts`)

Middleware order: raw-body capture → `express.json` → `httpLogger` →
`private-hostname-guard` (SSRF defense) → `board-mutation-guard` (CSRF for session
writes) → `actorMiddleware` (normalizes auth into `req.actor`) → `/api/auth` (BetterAuth)
→ the `/api` router. The `/api` router mounts ~40 route factories (each a
`(db) => Router`), then static UI serving, then the error handler. Company-scoping is
**checked per-handler** via `assertCompanyAccess`, not by a path middleware — see
[07-api-realtime-auth-mcp.md](07-api-realtime-auth-mcp.md).

## Data stores

- **Primary:** PostgreSQL. Local default = embedded PGlite; optional Docker Postgres
  or hosted Supabase via `DATABASE_URL`. Drizzle migrations are the source of truth.
- **Object storage:** local disk (`~/.paperclip/.../storage`) or S3-compatible, behind
  a `storageService` abstraction (`server/src/storage/`). Assets are content-addressed
  (sha256 + `object_key`).
- **Git** is the agent's *workspace* substrate (execution workspaces are branches /
  worktrees), not the control-plane store.

## The decisive seam: control plane ⟂ execution

This is the architectural keystone and the reason chorus exists separately. The
adapter interface is **`execute(ctx) → result`** (awaited to completion) +
`testEnvironment` + `cancel`. Per run, the control plane:

1. enqueues a **wakeup row** → a `queued` `heartbeat_runs` row,
2. the scheduler tick **claims** it (concurrency-capped), auto-checks-out the issue,
   mints a per-run JWT,
3. **spawns the agent CLI as an OS child process** in a resolved git workspace,
   injecting `PAPERCLIP_API_KEY` + a stdio MCP server,
4. tails stdout via an `onLog` callback → persists to `heartbeat_run_events` →
   publishes `heartbeat.run.log` over WebSocket,
5. receives **one** `AdapterExecutionResult` at process exit.

The agent does the work and reports back by calling `paperclip*` MCP tools (thin
wrappers over the REST API). **During the run the control plane sees only an opaque
byte stream + its own lifecycle markers — never structured tool calls.** This single
fact drives the entire liveness/recovery design ([05](05-liveness-and-recovery.md))
and is the central contrast with dream-native chorus
([10](10-implications-for-chorus.md)).

## Key entry-point files

- Boot/wiring: `server/src/index.ts`, `server/src/app.ts`
- The orchestration engine: `server/src/services/heartbeat.ts` (~11k lines / 424KB)
- The issue state machine + checkout: `server/src/services/issues.ts` (244KB)
- Recovery/liveness: `server/src/services/recovery/service.ts` (147KB)
- Realtime: `server/src/realtime/live-events-ws.ts`, `server/src/services/live-events.ts`
- The contract spine: `packages/shared/src/{constants.ts,api.ts,types/}`
