# 08 — Frontend (the board UI)

`ui/` is a React + Vite SPA — a **control plane for watching a company of AI agents
work**. The primary object is the **issue/task** (called "Issue" in code, "Task" in UI
copy); agents, the org chart, runs, and costs orbit the task board. The most
product-distinctive part is **how a human sees whether the company is working or stuck.**

Core files: `ui/src/App.tsx` (routing), `ui/src/api/*` (REST client), `ui/src/context/*`
+ `ui/src/hooks/*` (state/realtime), `ui/src/components/*`, `ui/src/plugins/*` +
`ui/src/adapters/*` (extension registries).

---

## 1. Page inventory & information architecture

Routing is a single file (`App.tsx`, React Router). Almost everything nests under a company-prefixed
shell `/:companyPrefix → <Layout> → boardRoutes()`. IA = **company → board → object**.

| Page | What a human does |
|---|---|
| **Dashboard** | Landing: a live "Agents" panel of running runs, metric cards (agents enabled/running/paused/error, tasks in-progress/blocked, month spend, pending approvals), 14-day charts, activity feed, budget-incident banner. |
| **DashboardLive** | A wide "Live agent runs" wall — up to 50 active+recent run cards. |
| **Issues (board)** | Kanban/list of tasks by status. |
| **IssueDetail** (179KB — the heart) | One task: chat thread with the assignee, live runs, run ledger, **recovery cards**, monitor card, attachments, documents, child issues, continuation handoffs. Where a human steers one task. |
| **Agents / AgentDetail** | Roster (polls runs every 15s to mark who's running); per-agent config, runtime state, task sessions, skills, run transcripts. |
| **OrgChart** | Pan/zoom SVG of the `reportsTo` tree; each card a status dot + adapter type. |
| **Goals / Costs / Inbox / Approvals / Routines** | Goal tree; budgets/spend/incidents; the human's triage queue (incl. a **blocked** tab); governance gates; scheduled runs. |
| Settings family | Company/access/secrets/plugins/adapters/instance admin. |
| Onboarding | Create company + first agent + seed task. |

---

## 2. How a human SEES working vs stuck (the key product question)

There is no single "inspector" — a **layered liveness system** at three altitudes:

**(a) The live run surface — "what is it doing right now."** `ActiveAgentsPanel` (dashboard) and
`LiveRunWidget` (IssueDetail) render run cards backed by `RunChatSurface`, which renders the agent's
**actual streamed stdout as a chat transcript**. Active run → animated cyan "ping" dot + "Live now";
finished → grey dot. The streaming engine `useLiveRunTranscripts.ts` **dual-sources**: polls the
run-log endpoint (~2s for active runs) **and** opens a WebSocket for `heartbeat.run.log/.event/.status`
frames, deduping chunks; output runs through `getUIAdapter(type).parseStdoutLine` to build
`TranscriptEntry[]`. *(So the structured tool-call transcript is reconstructed **here**, in the UI, from
raw stdout — not by the server; see [04](04-execution-and-adapters.md).)*

**(b) Liveness / silence classification — "actually progressing or just spinning."** The backend
classifies every run; the UI renders the vocabulary in `IssueRunLedger` (`LIVENESS_COPY`):
- working: `advanced` ("concrete evidence of progress"), `completed`, `needs_followup`
- stuck-ish: `plan_only` ("described future work without action evidence"), `empty_response`,
  `blocked`, `failed`

Active runs also carry an `outputSilence` signal — the literal "is it hung" indicator:
`suspicious → "Silence watch"` (amber), `critical → "Stale run"` (red ← a hung agent),
`snoozed → "Silence snoozed"`.

**(c) Recovery actions — "stuck, and here's the decision you owe me."** When the system decides a task
lost its live path, it surfaces an `IssueRecoveryActionCard` — the clearest "stuck" representation.
Five tonal states (`needed`/`in_progress`/`observe_only`/`escalated`/`resolved`) and plain-English
kinds: `missing_disposition` ("run finished, no next step chosen"), `stranded_assigned_issue`
("retried, still no live path"), `workspace_validation`, `active_run_watchdog` ("the active run has
been silent"), `issue_graph_liveness`. The card shows owner/evidence/next-action/wake-policy/attempt
count and a **Resolve…** menu (try again / mark done / send for review / dismiss false-positive).

**(d) The triage queue.** Inbox → **"blocked" tab** is where a human finds everything stuck
company-wide, bucketed by reason (`needs_decision`, `stalled`, `needs_attention`, `recovery_required`,
`external_wait`, `owner_paused`), ranked by severity.

> **Net:** working = streaming chat + "Live now" + `advanced`; idle = grey dot; **stuck** = a graduated,
> explicit vocabulary ("Silence watch" → "Stale run" → a recovery card demanding a decision → the
> blocked Inbox). The product deliberately distinguishes "producing tokens" from "making real progress"
> — *because the server can't tell the difference, only timing + evidence.*

---

## 3. State & realtime

- **Server cache: TanStack React Query** everywhere, with a single hierarchical key factory
  (`lib/queryKeys.ts`). No Redux/Zustand for server state.
- **Realtime: one shared WebSocket per company**, owned by `context/LiveUpdatesProvider.tsx`
  (`/api/companies/:id/events/ws`, exponential-backoff reconnect). It holds no state — it translates
  server `LiveEvent`s into **React Query cache invalidations** + toasts, and is route-aware (suppresses
  redundant toasts, surgically patches the cache, even hydrating a single new comment).
- **A second WebSocket** is opened by `useLiveRunTranscripts` for active-run log streaming (closed when
  no run is live).
- **Polling fills the gaps**: live-run queries `refetchInterval` 3000ms; Agents roster 15s; quotas
  ~5min. Model = **WS push for low-latency log/status + React Query polling as a safety net + cache
  invalidation as the glue.**

---

## 4. The API client (`ui/src/api/`)

A thin, hand-written typed REST client (not generated). `client.ts` is the whole transport: a
`request<T>()` over `fetch` (base `/api`, `credentials: "include"`, typed `ApiError`). One module per
domain (`issues.ts`, `agents.ts`, `heartbeats.ts`, …) exporting a `<domain>Api` object of typed
wrappers, typed against `@paperclipai/shared`. Components call `issuesApi.list(...)` inside React Query
`queryFn`s; the client layer has zero caching of its own.

---

## 5. Plugin UI injection & adapter UI registry

Two dynamic-extension systems:

- **Plugins** (`ui/src/plugins/`) — a slot system (`slots.tsx`): the host `import()`s each plugin's ESM
  bundle and **rewrites its bare imports (`react`, `@paperclipai/plugin-sdk/ui`) to blob-URL shims** that
  re-export the host's own React/SDK off `globalThis.__paperclipPluginBridge__` — so plugins share the
  host's single React instance (context works across the boundary). Rendered via `<PluginSlotOutlet>`,
  each in a per-plugin error boundary + a `PluginBridgeScope`. ~16 slot types (`page`, `dashboardWidget`,
  `detailTab`, `taskDetailView`, `commentAnnotation`, …). The bridge (`bridge.ts`) gives plugin code
  `usePluginData`/`usePluginAction`/`usePluginStream` (SSE)/`useHostContext`/`usePluginToast`.
- **Adapters** (`ui/src/adapters/`) — the per-runtime stdout parsers. A `UIAdapterModule` mainly knows
  `parseStdoutLine` + config form fields. `registry.ts` registers ~13 builtins; external/dynamic adapters
  get a bridge that falls back to the generic `process` parser then lazy-loads the real one, and can
  override builtins (generation-counter to discard stale loads).

So: **plugins inject UI surfaces + data/actions; adapters inject runtime-specific log parsing + config.**
Both registry-driven, lazy-loaded, gracefully degrading.
