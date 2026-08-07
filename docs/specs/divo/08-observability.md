# 08 — Observability & inspection

How a human (and the system) sees whether the company is working or stuck. chorus's equivalent of
Paperclip's [`08-frontend`](../../paperclip-research/08-frontend.md) + `doc/observability.md` — but
the central product question ("working vs stuck") is *answered structurally*, because chorus
witnesses dream's event stream instead of reconstructing from stdout.

---

## 1. The event stream (the spine)

Every meaningful transition is published to an in-process event bus and appended to a durable
event log (`events.jsonl` per workforce). This is dream's `engine` events + chorus's org events.
The bus is the one thing the inspector, audit, and (in Arceus) the realtime board consume.

**Event taxonomy:**

| Group | Events | Source |
|---|---|---|
| **task** | `task.created`, `task.assigned`, `task.status` (→in_progress/blocked/done/…), `task.dependency_resolved`, `task.children_done` | ledger mutations |
| **wake** | `wake.enqueued`, `wake.coalesced`, `wake.claimed` | scheduler |
| **run (beat)** | `run.queued`, `run.started`, `run.text`, `run.tool_use`, `run.tool_result`, `run.turn`, `run.evaluated` (outcome+score), `run.done` | **dream event stream** |
| **cron** | `routine.fired`, `routine.suppressed` | tick |
| **recovery** | `recovery.opened`, `recovery.escalated`, `recovery.resolved`, `monitor.due` | recovery |
| **budget** | `budget.soft_threshold`, `budget.hard_stop`, `budget.resumed` | budgets |
| **org** | `employee.hired`, `employee.paused`, `employee.terminated`, `approval.decided` | governance |

The `run.*` events are **structured** — `run.tool_use` carries the tool name + input, `run.evaluated`
carries the evaluator's verdict + score. chorus never parses prose to learn these; dream emits them.

---

## 2. Working vs stuck — witnessed, not guessed

This is *the* product question, and chorus answers it from typed state, where Paperclip could only
estimate from byte-silence (research [08 §2](../../paperclip-research/08-frontend.md)):

| Signal | Paperclip (reconstructed) | chorus (witnessed) |
|---|---|---|
| **working** | streaming stdout + "Live now" dot | `run.started` + ongoing `run.tool_use`/`run.turn` events |
| **progress quality** | `classifyRunLiveness` regex over final stdout | `run.evaluated` verdict from the evaluator (`advanced`/`completed`/`plan_only`/`blocked`) |
| **hung** | output-silence thresholds (60min/4h) | **`run.lease_expires_at` passed** (the beat stopped renewing) — a fact, not a guess |
| **stuck** | recovery card inferred from silence + evidence | `recovery.opened` from the liveness contract (spec 02 §3) — a non-terminal task with *no action-path primitive* |

So chorus's "stuck" vocabulary is **derived from the ledger's liveness contract + the evaluator**,
not from timing. A task is stuck iff it is non-terminal and has none of the action-path primitives
(spec 02 §3) — a query, not a heuristic.

---

## 3. The inspector (read-only projection)

The inspector (CLI `chorus inspect`, and in Arceus the web board) is a **pure read model** over the
ledger + event log. It holds no state. The surfaces (Paperclip's layered liveness UI, adapted):

- **the live beat surface** — active runs rendered from the `run.*` event stream (already structured;
  no per-adapter `parse-stdout` needed).
- **the liveness vocabulary** — `advanced / completed / needs_followup` (working) vs
  `plan_only / empty / blocked / failed` (stuck-ish), straight from `run.evaluated`.
- **recovery cards** — one per open `recovery_action`: owner, cause, evidence, next-action, the
  decision the human owes ("try again / mark done / send for review / dismiss").
- **the blocked inbox** — every stalled task company-wide, bucketed by reason (needs_decision /
  stalled / external_wait / recovery_required), ranked by severity.

> Net: working = live `run.*` events; stuck = a recovery card or a blocked-inbox row, both *derived
> from durable state*. chorus deliberately distinguishes "producing tokens" from "making progress"
> the same way Paperclip does — but it **knows** the difference (the evaluator), where Paperclip
> guessed.

---

## 4. Tracing (default-on OTLP)

Distributed tracing is **on by default**. Chorus always fans the EventBus to an
`OtelSpanSink` (OTLP/HTTP + `BatchSpanProcessor`) unless `OTEL_SDK_DISABLED=true`.
Endpoint defaults to `http://localhost:4318`; override with
`OTEL_EXPORTER_OTLP_ENDPOINT`. Every span carries `service.name`/`service.version`
(also via `OTEL_SERVICE_NAME` / `OTEL_SERVICE_VERSION`).

**Span tree** keyed by `task_id`:

| Event | Span |
|---|---|
| `run.started` → `run.done` | root `beat.{task_id}` |
| `run.tool_use` → `run.tool_result` | child `tool.{name}` |
| `llm.call` | child `llm.call` (`gen_ai.*` attrs) |
| `run.subagent_*` | child `subagent.{name}` |
| `run.evaluated` | root attrs `chorus.eval.outcome` / `chorus.eval.score` |

Point the endpoint at any OTLP collector (Jaeger, Tempo, Langfuse OTLP, SigNoz, …).
Ledger-op spans and full `trace_id` correlation (08 §6) remain follow-ups.

---

## 5. Audit

Every mutation appends to an `activity` log (`actor_type/actor_id`, `action`, `entity_type/entity_id`,
`run_id`, `details`) — append-only, the universal "who did what" (Paperclip's `activity_log`). The
event log is for *liveness/realtime*; the audit log is for *accountability*. They overlap but serve
different readers.

### Retention — the event log rotates, the audit trail does not

`events.jsonl` is an unbounded firehose, so it **rotates**: at a size/age threshold (default 64 MB /
7 days) the active file is sealed to `events-{seq}.jsonl.gz` and a fresh file opened. Rotation is
safe because the event log is *derived* telemetry — nothing reads it to reconstruct state (the ledger
is the source of truth, spec 00 B2.2), so old segments can be compacted or shipped off-box without
affecting correctness. The **`activity` table never rotates**: it is the durable accountability
record and is bounded by being the *audited subset* of events, not the firehose. The inspector reads
live state from the ledger + the active segment; historical replay reads sealed segments on demand.

---

## 6. Correlation — one id from tick to cost

A single `trace_id` threads an entire causal chain so a human can follow "this dollar came from that
tick": the tick that dispatches a wake **mints a `trace_id`**, the beat inherits it onto every
`run.*` event, the evaluator verdict carries it, each `cost_event` the beat produces stores it (spec
01 Cluster E), and the `activity` row for the disposition carries it too. So
`tick → wake → run → tool_use… → evaluated → cost_event → activity` all share one id — the inspector's
"why did this task cost $4" and "what did this tick set in motion" are both a single `trace_id` filter
across the event log, the cost ledger, and the audit trail. dream's OTel spans (§4) use the same id
as their trace root when tracing is on, so external traces stitch to internal events for free.

---

## 7. What chorus does NOT build (vs Paperclip's frontend)

- no **per-adapter stdout parsers** (`parse-stdout.ts`) — the stream is already structured;
- no **WebSocket fan-out infrastructure in the SDK** — the bus is in-process (Arceus adds the WS);
- no **React board in the SDK** — `chorus inspect` (CLI) is enough; the board is Arceus.
