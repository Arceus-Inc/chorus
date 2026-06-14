# 05 — The dream seam (execution)

How a beat actually runs. This is chorus's equivalent of Paperclip's
[`04-execution-and-adapters`](../../paperclip-research/04-execution-and-adapters.md) — but
*inverted*: where Paperclip spawns a subprocess and tails opaque stdout, chorus calls a function
and witnesses a typed event stream. This single difference is the reason chorus exists separately.

---

## 1. The seam in one call

The entire chorus⟂dream boundary is **one function call** inside `run_beat` (spec 03 §3):

```python
result = await dream.run_task(
    task_id = task.id,
    intent  = task.intent,
    role    = employee.role.manifest,   # dream.roles.RoleManifest
    dod     = task.dod,                  # typed verifier (spec 04) — enforced by dream's evaluator
    worktree_root = workspace,
    observer = event_bus.emit,          # witness the structured stream
)   # -> dream.RunTaskResult
```

That's it. No process spawn, no stdin/stdout pipes, no MCP server, no JWT, no adapter registry.
`run_task` runs planner → bounded sprint loop (generator turn-loop → evaluator turn-loop) → returns
a `RunTaskResult` with the final ledger, the per-sprint outcomes, and the full event trail.

---

## 2. What dream does for chorus (so chorus doesn't)

`run_task` already owns the entire inside of a task (dream-sdk-explained §3–4):

- **plan once** → narrative spec + JSON step ledger (with a Definition-of-Done section);
- **per sprint**: negotiate a `SprintContract` (≤3 rounds) and **write it to disk before the
  generator touches a file** (durable intent), run the generator, run the evaluator, apply
  pass/needs-changes/fail to the step ledger;
- **the engine** under each head: the turn loop, tool dispatch, the permission gate, the
  heartbeat/coma monitor, checkpointing, the structured event stream;
- **autowiring**: chorus passes `None` for the five heads and dream binds its production
  planner/generator/evaluator heads to the configured engine.

So chorus supplies only **(task, role, dod, workspace, observer)** and gets back a verified result.
Everything Paperclip's `heartbeat.ts` does to *manage* an external agent (spawn, stream, cancel,
parse) is gone.

### Versioned contract binding (the one dependency chorus pins)

The seam binds to **`dream.contracts`**, not to dream internals — so the surface chorus depends on is
exactly the Protocols (`ExecPlanLedger`, `MemoryStore`/`MemoryWriter`, `RoleManifest`,
`RunTaskResult`, the event types). chorus pins a **compatible-release** requirement
(`dream ~= MAJOR.MINOR`) and treats `dream.contracts.__contract_version__` as the compatibility key:
at import, chorus asserts the running dream's contract version is within the range it was built
against and **fails fast with a clear error** otherwise, rather than discovering a drifted signature
mid-beat. Because the siblings (horizon, lattice) bind the *same* contracts module, the contract
version is the single coordination point across all four repos — internals may churn freely beneath
it. (Stability policy: contracts follow semver; a breaking Protocol change is a dream MAJOR bump and
a coordinated chorus release.)

---

## 3. role → manifest → toolset

The employee's `role` resolves to a `dream.roles.RoleManifest` (spec 06): system prompt, allowed
tools, permission mode, memory scope, isolation. dream's `compute_minimum_toolset` intersects
*(manifest allow ∩ registered tools ∩ sandbox tier) − disallowed* — capability minimization by
construction. A bounded role **cannot widen itself** mid-run (it emits a recordable capability
request). This is chorus's "role = toolset" (B5.1) — already built in dream; chorus just selects
the manifest per employee.

---

## 4. Witnessing liveness (the observer)

chorus passes `observer = event_bus.emit`. dream streams **structured** events to it:
`TextDelta`, `ToolUseStart`, `ToolUseResult`, `TurnComplete`, plus the macro events
(`planner.started`, `contract.written`, `generator.completed`, `evaluator.completed` with the
outcome + score). chorus **records** these to its event log (spec 08) and reacts to *typed* state —
never to byte timing.

This is the inversion of Paperclip's observability boundary:

| | Paperclip | chorus |
|---|---|---|
| What the orchestrator sees during a run | an **opaque byte stream** (stdout) | dream's **structured events** |
| "is it working or stuck?" | *reconstructed* post-hoc from output-silence + regex | *witnessed* from typed events + the evaluator verdict |
| Transcript of tool calls | rebuilt by **UI-side** `parse-stdout.ts` | already structured in the stream |
| Liveness classifier | `run-liveness.ts` regex over final stdout | `RunTaskResult` + `liveness_state` from the evaluator |

The consequence: chorus's `run` table is **thin** (spec 01) and its recovery is **lease-based**
(spec 02 §6), because it never needs to guess.

---

## 5. The DoD pass-down (the M1 decision, fixed)

chorus passes `dod=task.dod` **into** `run_task`, and dream's evaluator enforces it as the final
acceptance gate — so chorus is a *thin orchestrator around dream's evaluator*, not a second outer
verifier. The generator turn-loop writes the artifact; the evaluator turn-loop runs the DoD's
`Command` (exit 0?) / `AgentReview` (Reviewer verdict) / `HumanApproval`. `run_task` returns
`passed: bool`, and chorus sets the task `done`/`blocked` from it (spec 04 §1).

> This is how chorus closes Paperclip's ⚪ **Enforced Outcomes** gap at M1: the verifier sees the
> real artifact, in-process, because chorus is dream-native.

### The failure contract — when `run_task` does not return a clean pass

`run_task` resolves one of three ways, and chorus maps each to a **typed task state**, never to a
silent stall (spec 02 §3). The mapping is the beat's whole error contract:

| `run_task` outcome | Meaning | chorus does |
|---|---|---|
| returns `passed=True` | evaluator accepted the artifact | `done` + land outcome (spec 04 §2) |
| returns `passed=False` | ran to completion, DoD not met | enter the DoD-failure ladder (spec 04 §1) — `blocked`/repair, **not** an error |
| raises `dream.TaskCancelled` | cooperative cancel (caps/budget/operator) | release lock; leave task in its pre-beat state; record `cancelled` run |
| raises `dream.RunTaskError` (planner/engine/tool fault) | the loop itself failed | `run` marked `failed`; task surfaced as **stranded** → recovery ladder (spec 02 §6), owner preserved |
| raises anything else / process dies | crash | nothing to do *in-band* — the lease expires and the tick's recovery pass reclaims it (spec 02 §7) |

The invariants: a **raise is never swallowed into `done`**; a failed/raised beat always leaves either
a typed disposition or a stranded-task signal the tick can re-derive from rows (B2.2), so no error
path produces a silently dead task. `RunTaskError` carries a typed `phase` (`plan|sprint|evaluate`)
and cause, which chorus records on the `run` and the `recovery_action` evidence so the escalation
trail names *where* it broke.

---

## 6. Cancellation & caps

- **Cancellation**: chorus cancels a beat by cancelling the `run_task` coroutine (it's in-process —
  no SIGTERM to a process group, no `AbortController` over a socket). dream's engine unwinds its
  turn loop cleanly and checkpoints. The board lock is released by the tick's recovery pass if the
  cancel races a crash.
- **Caps**: budget gate 1 blocks *before* `run_task` is called; gate 2 (a `cost_event` crossing the
  hard limit) cancels the in-flight coroutine + pauses the scope (spec 04 §3). dream's own per-run
  `max_turns` + `limits` are the inner bound.

---

## 7. What chorus deliberately does NOT build (the deleted stack)

Because the agent runs in-process, this entire Paperclip subsystem **does not exist** in chorus:

- the **adapter contract** (`ServerAdapterModule`, `execute(ctx)→result`) + the registry;
- the **subprocess plumbing** (spawn, PID/process-group tracking, stdout tailing, kill);
- the **MCP server** (the `paperclip*` tool surface) + the REST API it proxies;
- **auth injection** (the per-run JWT, `PAPERCLIP_API_KEY`, the run-id header);
- the **WebSocket** stream-back + the per-adapter `parse-stdout` UI parsers;
- the **output-silence watchdog** + thresholds + `classifyRunLiveness`.

> If BYO-agent (a non-dream runtime) is ever needed, the move is **ship chorus as a dream
> adapter** — re-introduce the process boundary at the edge without making it chorus's internal
> model (Corebelief: "dream-as-adapter"). The SDK stays in-process.
