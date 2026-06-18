# Handoff — 2026-06-18 — the Manager (M3 Slice 1)

What landed: the **manager** employee, end to end. A one-line goal is decomposed into assigned
subtasks; the parent **parks** while two engineers build and merge their children **concurrently**;
the kernel then **integrates** the completed subtree to `done`. Plus the append-only **memory writer**,
verified for every role. Everything below is on `main` (squash-merged in
[#35](https://github.com/Arceus-Inc/chorus/pull/35), commit `9d0704e`) and green — ruff + mypy
`--strict` + full pytest.

---

## The arc

M3 turned the **manager** from a declared role into a *running* delegator. The engineer (M1/M2) does
work; the manager does **org work** — it owns a subtree, not a diff. The seam that makes a chorus
capability model-callable (**Path A**: the model calls a dream tool that mutates the ledger *live*,
in-process, during a beat) is the foundation; the manager is the first employee built on it.

### 1. The capability seam (`decompose`)

- **`CapabilityService`** (`chorus/lifecycle/_capability.py`) — the dream-free seam a manager beat's
  tools mutate the ledger through. Wraps the exact-once `decompose()` lifecycle + assignment with the
  M3 idempotency rule: **child ids are deterministic per `(parent, label)`**, so a tool re-fired
  within a beat (generator retry) never duplicates children. Validates assignees against the workforce
  **before any mutation** (a model that invents a report id fails closed — no orphan child). Records
  the manager's decomposition as the parent's accepted plan revision (the claim's exact-once key).
- **`decompose` tool** (`chorus_tools/`) — a model-callable dream `BaseTool`: a pydantic children-DAG
  envelope that reads the per-beat **`BeatContext`** from `ctx.working_dir` (which task / run it acts
  for) and delegates to the service. Declared `tier_required = REPO_WRITE` so dream's sandbox trusts a
  mutating tool at the manager's tier instead of denying it.
- **`BeatContext`** (`chorus/heartbeat/_beat_context.py`) — the dream-free model both the kernel
  (writer) and the tool (reader) share, so `{worktree}/.harness/beat-context.json` can't drift. The
  `DreamBeatRunner` drops it before each beat.

### 2. The harness becomes a manager

- **Factory registration** (`chorus_harness/_factory.py`) — when a role declares a capability tool,
  the factory binds it to the live ledger and registers it into the dream registry (the new branch
  beside dream built-ins). Absent a ledger it fails closed (dropped, never crashes).
- **Team rehydration** — the factory appends the live workforce roster (id + role) to a delegating
  role's brief, so the manager assigns to **real** employee ids rather than inventing them.
- **Manager role** (`chorus_employee/manager/`) — brief (a tech-lead planning brief: smallest set of
  independent, self-contained, verifiable subtasks; each its own file; assign by id; then stop),
  manifest (`tools=("read_file","decompose")`, `MemoryScope.TEAM`), DoD, and **`ManagerLander`**
  (records the `subtree` artifact: every child + its terminal status).

### 3. The two-phase lifecycle (`chorus/heartbeat/_scheduler.py`)

The one genuinely new kernel concept is a **fifth beat outcome — "delegated"**:

```
manager beat → decompose([...]) live → parent now owns non-terminal children
   → PARK the parent (blocked; not done, not failed, NOT on the recovery ladder)
children dispatch to eng-A / eng-B → engineer beats (M2 machinery) → PRs merged
   → all children terminal → children_done wake re-invokes the parent
   → MECHANICAL INTEGRATE: the kernel lands the parent done with NO model beat
   → ManagerLander records the `subtree` artifact
```

`gates_parent` makes the parent wait on its children via the existing **M2 dependency gate**, so the
loop closes on the M2 `children_done` / `deps_resolved` machinery with no new wake plumbing.

### 4. Two engineers, concurrent

The two children dispatch under the scheduler's concurrency cap (`max_concurrent_runs`), each as an
**independent engineer beat in its own branch-isolated worktree** (`chorus/{employee}`). The manager
brief keeps each child in its **own new file** so the two `EngineerLander` merges into the company
`main` never collide. A conflicting merge is **recorded** (`merged=false`), never raised — the child
still reaches `done` because its DoD passed in its own worktree, so the subtree completes regardless.

### 5. Memory — one record per beat, per role

`AppendOnlyMemoryWriter` writes one immutable `sprint_delta` per beat to `{company_root}/memory/
{scope}/{run_id}.md` with dream-readable frontmatter (name + run_id/task_id/employee_id/scope/outcome).
The kernel is the writer (the worker never authors its own trace). Scope is the role's: **manager →
`team`, engineers → `project`**. Verified end to end: dream's own `scan_memory_dir` reads back **every**
record (manager + both engineers), each named by its run id, each carrying full provenance, the outcome
honestly mirroring the beat.

---

## What the long run found (and fixed)

A 3-wave long run (`examples/m3_long_run.py`) — sustained multi-goal load no single-shot test exercises
— surfaced **four** real scheduler/seam concurrency bugs, each hiding behind the last. All four are
fixed with regression tests, and **all but one benefit every role, not just the manager**:

1. **Parked manager stranded** — the liveness sweep classified a `blocked` parent whose children just
   landed (blockers resolved, integrate wake pending) as `blocked_no_blocker` → STALLED → recovery →
   the integrate never ran. Fix: `_classify_blocked` treats a blocked task with a **live wake** as
   healthy (matching `_classify`).
2. **Self-repair retries died** (`PlannerAlreadyRan`: dream refuses to re-plan a `task_id` it already
   planned) → every DoD-failed retry ERRORED and stranded. Fix: **dream gets the chorus `run_id` as its
   per-beat task identity** — a re-dispatch is an independent planning pass; the worktree carries state.
   *(M1/M2 seam fix — a lone engineer hit this too.)*
3. **Manager re-decomposed on integrate** — fix #2 removed `PlannerAlreadyRan`'s *accidental* guard,
   so the integrate re-invocation ran a model beat that called `decompose` again (one goal ballooned
   to 7 children / 4 claims, starving later goals). Fix: **the integrate is mechanical** — a
   re-invocation whose subtree is already complete is landed by the kernel with **no manager beat**.
4. **Stale wakes clogged the dispatch slot** — a manager fans out several `deps_resolved` /
   `children_done` wakes per task; once one drives the integrate, the rest point at a now-`done` task,
   fail the checkout CAS every tick, and were **re-queued forever**, starving the employee's other work.
   Fix: the dispatch loop **drains** a wake whose task is terminal instead of re-queuing it.
   *(Benefits every role.)*

> **Note for the next session:** the long run is the most productive test in the suite — four
> timing-dependent kernel bugs that deterministic tests never reach. Keep running it after kernel
> changes. The remaining live caveat is **evaluator noisiness** (dream returns `needs-changes` while
> the command verifier passes) — engineer-quality debt, not an execution-plane blocker.

---

## Folders / files

| Path | What it holds |
|---|---|
| `src/chorus/lifecycle/_capability.py` | `CapabilityService` — the dream-free decompose/assign seam |
| `src/chorus_tools/` | `decompose` dream `BaseTool` + `chorus_tool_registry` (Path A composition layer) |
| `src/chorus/heartbeat/_beat_context.py` | `BeatContext` — the per-beat context tools read |
| `src/chorus_employee/manager/` | the manager's complete config (brief, harness, dod, **`_lander`**) |
| `src/chorus/heartbeat/_scheduler.py` | park / mechanical-integrate / stale-wake drain |
| `src/chorus/lifecycle/_liveness.py` | the parked-manager liveness fix |
| `src/chorus/adapters/dream_beat.py` | per-beat dream task identity (run_id) |
| `examples/` | `m3_decompose_keyed.py` (live decompose), `m3_acceptance.py` (full loop), `m3_long_run.py` (multi-wave) |
| `reports/m3-manager-long-run.html` | the long-run verification report (3/3 goals, memory 11/11) |
| `docs/specs/full-manager/` | **this folder** — handoff + the Slice 2 spec |

---

## State at end of day

- **Manager**: fully wired end to end — one-line goal → decompose → **park** → two engineers build &
  merge **concurrently** → **mechanical integrate** → `done` + `subtree` artifact. Proven with live
  keyed runs (keyed acceptance + a clean 3/3 long run) and the deterministic park/integrate test.
- **Memory writer**: one episodic `sprint_delta` per beat, per role, dream-readable, scope-partitioned
  (manager `team`, engineers `project`) — read back 100% by dream's scanner.
- **Open (remaining M3)** — the build plan is **[`spec.md`](spec.md)**:
  - **Slice 2** — `submit_task` + `assign_task` go live, and the **mechanical integrate becomes an
    adaptive, reacting manager beat** (the manager *decides* it's integrated instead of "all children
    terminal").
  - **The Reviewer** — make `AgentReview` load-bearing: the kernel dispatches a read-only reviewer beat
    that renders an approve/block verdict gating completion, plus a `verdict` lander. (Separate from
    Slice 2; tracked in the build plan's appendix.)
