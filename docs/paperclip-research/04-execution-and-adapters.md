# 04 — Execution & adapters

> **The load-bearing architectural fact of the whole system.** The control plane's
> relationship to a running agent is a thin **process/transport boundary**: it ships a
> prompt + context into `adapter.execute()`, receives an **opaque byte stream** of
> stdout/stderr back via an `onLog` callback, and gets exactly **one** structured
> `AdapterExecutionResult` when the run finishes. The control plane does **not** parse,
> observe, or react to tool calls/turns *during* a run. "Stuck vs. working" is therefore
> **not observable live** — it is reconstructed *after the fact*.

Core files: `packages/adapter-utils/src/types.ts` (the contract),
`server/src/adapters/registry.ts` (the registry), `server/src/services/heartbeat.ts`
(invocation/streaming/cancel/wakeup), `packages/adapters/*` (per-runtime adapters).

---

## 1. The adapter interface

The contract is **`ServerAdapterModule`** (`packages/adapter-utils/src/types.ts:352`).
Only two required members:

```ts
type: string;
execute(ctx: AdapterExecutionContext): Promise<AdapterExecutionResult>;
testEnvironment(ctx: AdapterEnvironmentTestContext): Promise<AdapterEnvironmentTestResult>;
```

Everything else is optional capability/metadata: `listSkills`/`syncSkills`, `sessionCodec`,
`sessionManagement`, `models`/`listModels`, `getRuntimeCommandSpec`, `getConfigSchema`,
`supportsLocalAgentJwt`, `getQuotaWindows`, `detectModel`, `onHireApproved`, capability flags.

A "heartbeat" (one agent run) == **one invocation of `execute()`, awaited to completion.** There
is no separate start/poll/stop RPC trio. Invocation: `heartbeat.ts:≈9001`
(`adapterResult = await adapter.execute({...})`).

**What the control plane sends** — `AdapterExecutionContext` (`types.ts:122`): `runId`, `agent`,
`runtime` (prior session params), `config` (resolved adapter config), `context` (the wake payload:
issueId/wakeReason/wakeCommentId/approval info/workspace hints), `executionTarget` (local/ssh/
sandbox), `runtimeCommandSpec`, `authToken` (a short-lived **local agent JWT** minted per run and
injected as `PAPERCLIP_API_KEY` so the agent can phone home), and the callbacks
`onLog(stream, chunk)` / `onMeta(meta)` / `onSpawn({pid, processGroupId, startedAt})`.

**How it's observed** — **streaming, but only raw bytes.** `onLog` (`heartbeat.ts:≈8822`) fires
per stdout/stderr data chunk (wired in `runChildProcess`, `adapter-utils/src/server-utils.ts`).
Each chunk is redacted, persisted to the run-log store, used to update `lastOutputAt`/byte
progress, and **published as a `heartbeat.run.log` live event**. **There is no polling of the
agent**; the local model is the OS child process and its pipes.

**What the agent returns** — `AdapterExecutionResult` (`types.ts:69`), returned once at exit:
`exitCode`, `signal`, `timedOut`, `errorMessage/errorCode/errorFamily/retryNotBefore`, `usage`,
`sessionId`/`sessionParams`, `provider`/`model`/`costUsd`, `resultJson`, `runtimeServices`,
`summary`, `clearSession`, optional `question`. **Separately**, agents also phone home **out of
band** over HTTP using the injected JWT (POST comments, PATCH status, create children) — that is
the *real* progress channel.

**Cancellation** — `cancelRunInternal` (`heartbeat.ts:≈11025`) → `terminateHeartbeatRunProcess`:
**SIGTERM to the process group → grace → SIGKILL** (killing `-processGroupId` so child trees die).
PID/process-group are persisted on spawn (`onSpawn`) so cancellation works after a control-plane
restart. The HTTP adapter cancels via `AbortController`. **The control plane can only cancel by
killing the process / closing the transport — it cannot tell the agent "stop the current tool."**

---

## 2. The observability boundary (THE key fact)

**During a run the control plane sees only an opaque byte stream plus its own lifecycle markers.
It does not see structured agent events (tool calls, turns, thinking) live.**

Two live channels, both via `publishLiveEvent`:
1. **`heartbeat.run.log`** (`heartbeat.ts:≈8853`) — raw, redacted stdout/stderr chunks, exactly as
   the agent CLI emitted them. The control plane treats them as **bytes**: append to the log store,
   track `lastOutputAt`/byte counts. **It does not parse them.**
2. **`heartbeat.run.event`** (`appendRunEvent`, `heartbeat.ts:≈5171`) — **control-plane-authored
   lifecycle events only**: "run started", `adapter.invoke` (command/env/prompt metrics from
   `onMeta`), "run cancelled", retry-scheduling, liveness-continuation. **Never derived from the
   agent's tool stream.**

**Where the structured transcript actually lives:** adapters run their CLIs in structured-output
mode (e.g. Claude with `--output-format stream-json --verbose`), but the adapter parses that JSON
**only at the end**, from the *complete* captured stdout, to populate `resultJson`/`usage`/
`summary`. The per-event `tool_call`/`tool_result`/`thinking`/`turn` `TranscriptEntry` types are
produced by **UI-side `parse-stdout.ts` parsers** consuming the raw `heartbeat.run.log` chunks —
the server-side orchestrator never builds them. (Even the OpenClaw gateway, which *does* receive a
live structured WebSocket event stream, **flattens every event into a raw `onLog` stdout line**,
discarding the structure as far as the control plane is concerned.)

**Consequence for stuck-vs-working:** the only live signal the orchestrator has is **output
liveness** — `lastOutputAt`/`lastOutputSeq`/byte progress + PID-alive checks. It can detect "no
bytes for a while" and "process is dead," but it **cannot distinguish a model spinning on a bad
tool loop from one doing useful deep work**, because both emit bytes and neither is semantically
inspected mid-run.

**Semantic judgment is strictly post-hoc.** `run-liveness.ts:classifyRunLiveness` runs **only after
`runStatus === "succeeded"`** and classifies into `advanced | completed | blocked | plan_only |
empty_response | needs_followup | failed`, based on **durable side-effect evidence** (comments,
doc/plan revisions, work products, workspace operations) + **regex over the final stdout excerpt**.
*The system infers whether the agent was "working" by checking what it produced, not by watching it
work.* This is the architectural fact the rest of chorus's comparison turns on.

---

## 3. Adapter types

Registered in `server/src/adapters/registry.ts` (`registerBuiltInAdapters`).

**Local CLI / session adapters** (spawn a coding-agent CLI as a child process, capture stdout,
resume by session id): `claude_local` (the canonical impl, `packages/adapters/claude-local/`),
`codex_local`, `gemini_local`, `grok_local`, `opencode_local`, `pi_local`, `acpx_local` (ACP
multiplexer), `cursor` (`requiresMaterializedRuntimeSkills`), `hermes_local` (external npm pkg
registered as builtin; the registry wrapper injects `PAPERCLIP_API_KEY`/`PAPERCLIP_RUN_ID` + an
auth-guard prompt).

**Cloud / gateway adapters** (no local process; phone the agent elsewhere): `cursor_cloud`,
`openclaw_gateway` — a **WebSocket gateway client** (ed25519 device-auth, protocol v3 handshake,
sends one `agent` request, gets `status=ok` or polls `agent.wait`, forwards live event frames as
log lines). The clearest embodiment of "agents run wherever and phone home" — the control plane
holds a socket, not a process.

**Generic transport adapters** (the BYO escape hatches, unremovable): `process` (spawn any command;
**also the fallback** when an unknown type is requested) and `http` (POST a JSON payload to a URL;
2xx = accepted; fire-and-forget webhook, no streaming).

**Bring-your-own-agent — external adapter plugins (dynamic registry):** the `adaptersByType` Map is
**mutable**. External packages export `createServerAdapter(): ServerAdapterModule`. `plugin-loader.ts:
buildExternalAdapters` reads the adapter-plugin-store, dynamically `import()`s each package, validates
the `type`, and extracts a sandboxed `./ui-parser` export for the UI. An external adapter may
**override a builtin** (original saved in `builtinFallbacks` so the override can be paused/resumed/
unregistered). Input validation is open-ended (`assertKnownAdapterType` consults the live registry).
*This process boundary is also an abstraction boundary — it is why Paperclip is agent-agnostic.*

---

## 4. Environments & workspaces

Three distinct concepts, all orchestrated by `environment-run-orchestrator.ts`:

- **Environment** (`environments.ts`) — *where* code runs. `driver`: `local`, `ssh`, or `sandbox`
  (managed Kubernetes, `provider: "kubernetes"`). Resolved per run via a priority chain:
  execution-workspace config > issue settings > project policy > agent default > company default.
- **Execution workspace** (`execution-workspaces.ts`) — *what filesystem/cwd* the agent gets.
  `mode` (`shared_workspace`/`isolated_workspace`/`operator_branch`/`adapter_default`) × `strategy`
  (`project_primary`/`git_worktree`/`adapter_managed`/`cloud_sandbox`). Realized to a concrete cwd
  per run, tied to a git branch.
- **Runtime service** (`local-service-supervisor.ts`) — *long-lived processes* (dev servers,
  previews) a workspace needs. Scoped, with `lifecycle: shared|ephemeral`, a `reuseKey`, and health
  tracking. Supervised by PID/process-group liveness.

**Lifecycle (orchestrator-owned):** per heartbeat — `resolveEnvironment` → `acquireLease`
(logged via `environment.lease_acquired` activity) → `realizeForRun` (materialize the workspace
local/remote; run provision commands; persist realization metadata) → `resolveEnvironmentExecutionTarget`
(produce the provider-neutral `AdapterExecutionTarget` the adapter consumes) → `releaseForRun`
(release/expire/fail leases; never letting cleanup errors mask the original run failure).

**Low-trust containment** (`low-trust-runtime-containment.ts`): when the resolved trust preset is
`low_trust_review`, `assertLowTrustWorkspaceIsolation` **hard-fails the run** unless **all** hold:
isolated workspaces enabled, mode `isolated_workspace`, the issue is inside the active trust
boundary, and the env driver is **`sandbox`**. So low-trust agents are forced into
sandbox-driver + isolated-workspace and denied service spawning by default.

---

## 5. Wakeup / invocation

**Queue-based, process-spawn execution — not webhook-in or a direct call.**

1. **Enqueue** — something (issue assignment, comment, recovery, productivity review, liveness
   continuation, manual `wakeup` API, scheduler tick) calls `enqueueWakeup(agentId, opts)`: validate
   company/agent/budget, build a `contextSnapshot`, write an `agent_wakeup_requests` row + a `queued`
   `heartbeat_runs` row, emit `heartbeat.run.queued`.
2. **Claim** — the tick loop prioritizes queued runs (in-progress issues first, then
   dependency-ready, then priority/age) and `claimQueuedRun` up to available concurrency slots,
   re-checking invokability and stamping `executionRunId`.
3. **Execute** — `executeRun(runId)`: add to `activeRunExecutions`, acquire env/workspace via the
   orchestrator, mint the JWT, call `adapter.execute(...)`. Local adapters spawn an OS child process;
   `openclaw_gateway` opens a WebSocket; `http` POSTs.

So the trigger is: **DB-backed wakeup request → queued run row → tick-loop claim → process spawn (or
socket/webhook).** There is no inbound webhook that starts an agent and no synchronous "run now" RPC
bypassing the queue — even the manual API path goes through `enqueueWakeup`.

---

## Key files

- Contract: `packages/adapter-utils/src/types.ts` (`ServerAdapterModule:352`,
  `AdapterExecutionContext:122`, `AdapterExecutionResult:69`)
- Registry/plugins: `server/src/adapters/registry.ts`, `server/src/adapters/plugin-loader.ts`
- Invocation/streaming/cancel/wakeup: `server/src/services/heartbeat.ts`
- **Post-hoc liveness**: `server/src/services/run-liveness.ts`
- Process plumbing: `packages/adapter-utils/src/server-utils.ts`
- Canonical local adapter: `packages/adapters/claude-local/src/server/execute.ts`
- Gateway adapter: `packages/adapters/openclaw-gateway/src/server/execute.ts`
- Environments/workspaces/containment: `server/src/services/environment-run-orchestrator.ts`,
  `environments.ts`, `execution-workspaces.ts`, `low-trust-runtime-containment.ts`
