# M3 first cut — manager capability tools + the manager↔engineers loop

**Date:** 2026-06-18 · **Status:** design (approved in brainstorm; pending writing-plans)
**Milestone:** M3 ("one manager, two reports") — first cut.

## 1. Goal & non-goals

**Goal.** Make *one manager + two engineers* actually work together, end to end: a manager takes a
task, fans it into children assigned to two engineers, the engineers do the work, and when the
children finish the manager is re-invoked to integrate and close the parent. This requires giving the
manager **real, harness-registered capability tools** (`decompose`, `submit_task`, `assign_task`) — the
foundation M3 has been missing.

**Non-goals (deferred):**
- The **Reviewer / AgentReview verdict path** — the manager's "done" is verified by a *mechanical*
  check this cut; the reviewer-verified version is the next M3 slice.
- **PM / Analyst** roles.
- `submit_task` creating **standalone (non-child)** top-level work — only child creation is in scope.
- **In-beat richness that depends on a child's run *outcome*** (the manager waiting to see whether a
  child *succeeded* before creating more, all in one beat). This requires **blocking delegation** — a
  manager beat holding its lease while children run — which breaks the beat / concurrency / crash model
  (B1.2/B1.3). Adaptive "see results → create more" happens **across beats**, in the `children_done`
  re-invocation (Slice 2). *Structural* in-beat use (chaining real child IDs to wire deps) is
  **allowed** — Path A enables it.

## 2. Background — why this is needed

Audited on `main`: the M3 *substrate* exists (the `decompose()` lifecycle with exact-once claim +
depth cap, `children_done` wake firing, the manager/reviewer role plugins, recovery ladder, monitors),
but **no M3 behaviour is wired**:
- `src/chorus_tools/` is empty; the old `DecomposeTaskTool` is gone.
- The manager's harness, materialized through `EmployeeHarnessFactory`, gets **only `read_file`** — its
  declared `submit_task`/`assign_task` are *dropped* (the factory maps only dream built-ins).
- `decompose()` is only ever called from the **CLI verb** / tests, never from a beat.
- There is no integrate loop and no manager/reviewer lander.

So the manager exists on paper and can do nothing. This design builds the capability-tool seam and the
fan-out→integrate loop on top of the existing substrate + the M2 dependency/concurrency machinery.

## 3. Key decisions (locked in brainstorm)

| Decision | Choice | Why |
|---|---|---|
| Tool execution model | **Path A — live mutation** | spike-confirmed: a custom `BaseTool.execute()` runs **in dream's loop, in-process**, and can mutate a captured Python object (a ledger handle) + return real IDs. Chorus-only, no dream change. |
| Manager tools (by **responsibility**, not overlapping creators) | `decompose` = **bulk wave**; `submit_task` = **incremental add**; `assign_task` = **route/reassign** | distinct *moves*. `submit_task`/`assign_task` are only *exercised* once the manager reacts to child outcomes across beats — so they land in Slice 2, not Slice 1 (which needs only `decompose`). See §6.1. |
| `submit_task` semantics | **creates a child** of the manager's current task | so `children_done` fires → the integrate loop works. |
| Loop closure | **B1 — manager integrates in a re-invocation beat** | the manager does the second half of its job, not a kernel shortcut. |
| Manager DoD (this cut) | **Mechanical** — "all children terminal" | closes the loop without the unbuilt reviewer. |
| Idempotency | **label-keyed creates**, idempotent on `(parent_id, label)` | the spike showed a tool can fire twice per beat (generator retries) — labels dedupe; reuses the exact-once claim. |
| Task context into the tool | **per-beat context file** the kernel writes to the worktree | the tool has `ctx.working_dir`; no dream change. |

## 4. The spike (evidence Path A is viable)

A throwaway custom `RecordTool(BaseTool)` was registered into a dream harness registry and a real keyed
beat asked the model to call it. Result: `execute()` ran **in-process** and mutated a closure-captured
`SINK` list (`VERDICT: PASS`). Side-findings folded into this design: (a) the tool fired **twice** in
one beat → idempotency is mandatory; (b) `ctx.working_dir` is stable across calls → a reliable anchor
for the per-beat context file; (c) dream already threads a task context into `ctx.metadata` (its own
`cron_list` reads it) — a possible future channel, but the file stays the chorus-only path.

## 5. Architecture

```
 manager beat (dream run_task, in the manager's worktree)
   │  kernel wrote {worktree}/.harness/beat-context.json = {task_id, employee_id} before the beat
   │  model calls decompose([...]) live (Slice 1); submit_task / assign_task in the adaptive beat (Slice 2)
   ▼
 capability tool.execute()
   │  reads beat-context.json → parent_id, actor
   │  calls the injected CapabilityService → decompose()/assign_task() LIVE (exact-once by label)
   │  returns real child IDs
   ▼  beat ends
 Scheduler.run_beat (post-beat, beside lander/memory steps)
   │  parent now owns children, non-terminal  → PARK the parent (delegated; not done/failed)
   ▼
 children dispatch to eng-A / eng-B  →  engineer beats (M2 machinery) → PRs merged
   │  all children terminal → CHILDREN_DONE wake re-invokes the manager
   ▼
 manager INTEGRATE beat (no new children) → Mechanical DoD "all children terminal" → parent done
   ▼
 ManagerLander records the `subtree` artifact (children + their outcomes)
```

The one genuinely new kernel concept is a **fifth beat outcome — "delegated/awaiting-children"** —
because a decompose beat is neither pass, DoD-fail, errored, nor cancelled: it *succeeded by
delegating*, and the parent waits to be re-invoked.

## 6. Components (each: what · how · depends on)

1. **`chorus_tools/` capability tools** — dream `BaseTool`s; each `execute()` reads the per-beat
   context, calls the capability service, returns real IDs. Three **distinct responsibilities** (not
   overlapping creators), landing in two slices:
   - **`decompose`** (`_decompose.py`) — **bulk wave**: create an N-child DAG + assign + wire deps in
     one call. The only tool the single-fan-out first cut needs. **Slice 1.**
   - **`submit_task`** (`_submit_task.py`) — **incremental add**: create *one* child (e.g. a fix the
     manager spawns after reading a failed child). **Slice 2** (adaptive integrate).
   - **`assign_task`** (`_assign_task.py`) — **route/reassign**: (re)assign an *existing* task to a
     chosen report. **Slice 2.**
   *Depends on:* dream `BaseTool`, the capability service, the per-beat context file.
2. **`CapabilityService`** (`chorus/lifecycle/_capability.py`) — a thin, dream-free seam wrapping the
   ledger's `decompose()` / `assign_task()` with the idempotency-by-label rule. The tools hold this, not
   the raw ledger. *Depends on:* `SqliteLedger`, `lifecycle/_decompose.py`, `_coordination.assign_task`.
3. **Per-beat context file** — `Scheduler.run_beat` writes `{worktree}/.harness/beat-context.json`
   (`task_id`, `employee_id`) before dispatching the beat; consumed/ignored otherwise. *Depends on:* the
   worktree path (from the materialized harness).
4. **Factory registration** (`chorus_harness/_factory.py`) — when a role declares a capability tool,
   register the chorus tool (constructed with the injected `CapabilityService`) into the harness
   `ToolRegistry` — the new branch beside dream built-ins. The factory gains a read-only capability
   handle (the bounded coupling Path A requires). *Depends on:* `CapabilityService`, dream `ToolRegistry`.
5. **Kernel park/integrate** (`chorus/heartbeat/_scheduler.py`) — post-beat: parent owns non-terminal
   children ⇒ **park** (the new disposition); parent's children all terminal & beat created none ⇒
   **Mechanical DoD** ⇒ `done`. *Depends on:* `dependencies`/`tasks` repos, `children_done` (already firing).
6. **`ManagerLander`** (`chorus_employee/manager/_lander.py`) — on the integrate beat passing, record a
   `subtree` artifact (children + outcomes). Registered in `default_landers`. *Depends on:* `LanderRegistry`.
7. **Team rehydration** (factory) — append the manager's reports (id + role, read from the workforce at
   materialize) to its brief overlay, so the model names valid assignees. *Depends on:* a read-only
   workforce handle in the factory.
8. **Manifest update** (`chorus_employee/manager/_harness.py`) — Slice 1: tools = `("read_file",
   "decompose")`; Slice 2 adds `"submit_task", "assign_task"`. The dropped-tools note is removed.

## 7. Idempotency & validation

- **Creates are idempotent on `(parent_id, label)`** — re-firing returns the existing child. Substrate:
  the exact-once decomposition claim / a unique index on `(parent_id, label)`.
- **Validation at apply** (reusing existing checks): `depends_on` labels must resolve among siblings; no
  cycles (the dependency repo rejects them); `assignee` must be a real, invokable **report** of the
  manager (else create unassigned + surface); total depth ≤ the depth cap (fail closed → `DepthCapped`).
- **assign_task** validates the target is invokable and is the manager's report; assign-to-same is a no-op.

## 8. Error handling

- A capability tool called **outside a manager context** (no beat-context file, or actor not a manager)
  returns a structured tool error (dream's three-part contract), never a silent mutation.
- A decompose beat that creates **zero** children is treated as a normal beat (no park) — the manager
  did not delegate.
- The integrate beat with a **non-terminal** child still present ⇒ stays parked (re-woken on the next
  `children_done`); it never marks the parent done prematurely.
- All ledger mutation stays exact-once under generator retries (the label rule), so a re-fired beat is safe.

## 9. Testing

- **Unit (deterministic):** each tool writes/calls the capability service correctly; idempotency
  (double-fire → one child); the `CapabilityService` (create child, assign, wire deps, depth cap).
- **Kernel (deterministic):** decompose beat → parent parked; `children_done` → integrate beat →
  Mechanical DoD → `done`; a non-terminal child keeps it parked. Fake beat runner, no model.
- **Acceptance (keyed e2e):** hire manager + eng-A + eng-B (reports_to manager); assign a top task to the
  manager; it decomposes into 2 assigned children; both engineers complete; `children_done` re-invokes
  the manager; it integrates; parent `done`; `subtree` artifact recorded. HTML report under `reports/`,
  matching the M1/M2 verification style.
- **Crash-safety (reuse M1):** kill the manager mid-fan-out → the exact-once claim means retry reuses the
  already-created children (no duplicates).

## 10. Build order (slices for writing-plans)

**Slice 1 — fan-out + mechanical integrate (`decompose` only).** The walking skeleton of the loop.
1. `CapabilityService` + idempotency (TDD, dream-free).
2. The **`decompose`** `BaseTool` over the service (TDD).
3. Per-beat context file + factory registration of capability tools (TDD; assert a materialized manager
   harness actually carries `decompose`).
4. Kernel park/integrate + the "delegated" disposition + **Mechanical** DoD (TDD).
5. `ManagerLander` + `default_landers`; manifest tools = `("read_file", "decompose")`; team rehydration.
6. Keyed acceptance e2e + report — manager + 2 engineers, single fan-out → both done → integrate → done.

*Within Slice 1: steps 1–2 and 4 are independent; 3 depends on 1–2; 5 depends on 4; 6 is last.*

**Slice 2 — adaptive integrate (`submit_task` + `assign_task` go live, and get used).**
7. `submit_task` + `assign_task` `BaseTool`s + their service methods (TDD); add both to the manager manifest.
8. The integrate beat becomes a *real* manager beat that **reacts to child outcomes** — a failed child →
   `submit_task` a fix → `assign_task` it; an overloaded report → `assign_task` a reassignment; grown
   scope → `decompose` a new wave. The Mechanical DoD gives way to "the manager decided it's integrated."
   Keyed e2e of the adaptive path. *(This is also where the Reviewer/AgentReview verdict path can replace
   the mechanical gate — see §1 non-goals.)*

## 11. Risks & open questions

- **Factory ↔ ledger coupling** (Path A): the factory becomes capability-aware. Bounded, but it widens
  the factory's job — keep the handle read-only + behind the `CapabilityService` seam.
- **Mid-beat ledger writes** under the beat's lock: safe in the single-threaded async model (confirmed
  in-process), but the `CapabilityService` must open its own short transaction and not assume an open one.
- **The "delegated" disposition** touches the four-way failure contract (spec 05 §5) — add a fifth state
  carefully so recovery/liveness don't mis-classify a parked parent as stalled.
- **Team rehydration** overlaps spec-06 §6 (rehydration bundling) — scope it to just the reports list.

## 12. File touch list

| Area | New | Modified |
|---|---|---|
| Tools | `chorus_tools/{_submit_task,_assign_task,_decompose}.py`, `__init__.py` | — |
| Service | `chorus/lifecycle/_capability.py` (`CapabilityService`) | `lifecycle/__init__.py` |
| Factory | — | `chorus_harness/_factory.py` (register capability tools + per-beat context + team) |
| Kernel | — | `chorus/heartbeat/_scheduler.py` (park/integrate, disposition), `heartbeat/_beat.py` (disposition) |
| Manager | `chorus_employee/manager/_lander.py` | `chorus_employee/manager/_harness.py`, `chorus_employee/__init__.py` (landers) |
| Tests/e2e | `tests/chorus_tools/`, `tests/heartbeat/test_manager_loop.py`, `examples/m3_manager_loop.py`, `reports/m3-*.html` | — |
