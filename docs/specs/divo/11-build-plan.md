# 11 — Build plan (M1 → M4)

The construction order. Each milestone names: the **goal**, the **data tables** it adds (spec 01),
the **dream APIs** it calls, the **new chorus code**, the **acceptance** (what proves it), and what
it deliberately **defers**. Parallels Paperclip's `10-implications` "concrete M1 starting point."

The order honors the vision: one engineer → two engineers + cross-team → manager + reports → full
dynamic org.

---

## M1 — One engineer, full vertical

**Goal.** A single Engineer employee takes a submitted task, runs it via `dream.run_task` with a DoD
generated at intake and **verified by the evaluator**, then lands the outcome (PR → CI → repair →
merge).

| | |
|---|---|
| **Tables** | `employee`(1), `task`, `run`, `goal`, `artifact` |
| **dream reuse** | `run_task`, `roles` (engineer manifest), `coordination` board `ClaimManager`, the event stream |
| **New chorus code** | `Chorus.build/submit`, a *trivial* `tick` (eligible → checkout → beat), the Engineer role plugin, `OutcomeLander` for PR→CI→merge, `SqliteLedger`, `GitWorkforce(1)` |
| **DoD seam** | `submit` generates a `Command` verifier; passed **into** `run_task` (spec 05 §5) |
| **Acceptance** | submit a task → it runs → the evaluator verifies the artifact against the DoD → PR merged → task `done`. Kill mid-run, restart, the lease-recovery pass re-dispatches; **no stranded sweeper needed.** |
| **Proves** | the dream↔chorus seam + outcome-landing + crash-safety, end to end. Closes ⚪ **Enforced Outcomes** at the smallest scale. |
| **Defers** | wakes, cron, decomposition, multiple employees, memory writes. |

> M1 is the walking skeleton. No `wake` table yet — dispatch is "scan eligible, run one." The point
> is to nail the seam and prove evaluator-verified done.

---

## M2 — Two engineers, cross-employee interaction

**Goal.** Two employees working concurrently, with a dependency DAG and the wake-driven scheduler.

| | |
|---|---|
| **Tables** | + `wake`, `task_dependency`, `cost_event`, `budget_policy`, `budget_incident` |
| **dream reuse** | board two-lock + lease watchdog; `MemoryStore`/`MemoryWriter` contracts |
| **New chorus code** | the real `tick` (recover → dispatch loop, per-employee serialization), `wake` coalescing (the partial-unique index), `task_assigned`/`deps_resolved` wakes, assignment (hard role filter), the two-gate budgets, the `AppendOnlyMemoryWriter` + 3 scopes, the mailbox (`message` wake) |
| **Acceptance** | submit A and B with `B depends_on A`; B is withheld until A is `done`, then a `deps_resolved` wake dispatches B. Two beats run concurrently under the concurrency cap; a hard budget breach pauses + kills. |
| **Proves** | concurrency, dependency edges as data, push-driven dispatch, two-gate caps, append-only memory with provenance. |
| **Defers** | managers, decomposition, cron, the Reviewer. |

---

## M3 — One manager, two reports

**Goal.** The Manager role: decompose → dispatch (ledger writes) → be re-invoked on child completion
→ integrate. Plus the Reviewer (the verifier for judgment work).

| | |
|---|---|
| **Tables** | + `decomposition_claim`, `recovery_action`, `monitor`, `artifact_revision` |
| **dream reuse** | `run_task` per child; `swarm` (optional, for bounded intra-task helpers) |
| **New chorus code** | exact-once decomposition (the `decomp_source_revision_uq` claim + durable partial result), `children_done` wakes (non-blocking re-invocation), the Manager + Reviewer role plugins, the `AgentReview` DoD tier, the three-tier recovery ladder + monitors (spec 02 §6) |
| **Acceptance** | a manager splits a task into 3 children, its beat ends; when the last child finishes, a `children_done` wake re-invokes the manager (fresh session, durable intent) which integrates and marks the parent `done`. Kill the manager mid-fan-out → retry resumes from the same fingerprint, reuses created children. A PM task is verified by a Reviewer, not self-report. |
| **Proves** | hierarchy-as-data, the non-blocking delegation model (B1.2/B1.3), judgment-class DoD via Reviewer. |
| **Defers** | cron, dynamic hiring, PM/Analyst breadth. |

---

## M4 — Full dynamic org

**Goal.** Heterogeneous workforce, recurring work, dynamic org edits, portability.

| | |
|---|---|
| **Tables** | + `routine`, `routine_trigger`, `routine_run`, `approval` |
| **dream reuse** | `tasks/_cron` parser |
| **New chorus code** | cron firing (`fire_routine`, the double-fire guard), monitors fully, the PM + Analyst role plugins, dynamic hire/fire as data edits (+ approval gate), the slug-portable `export`/`import` (spec 09), the inspector surfaces (spec 08) |
| **Acceptance** | a routine fires on schedule → spawns a task → normal dispatch runs it (exact-once across ticks). Export a workforce → import into a fresh ledger → the org + routines re-materialize, secrets re-prompted. Add a new role plugin → it schedules with no kernel change. |
| **Proves** | the org scales in roles and headcount without code changes; recurring work is native; companies are portable. |
| **Defers (→ Arceus / siblings)** | inbound channels (Slack/GitHub), multi-tenant hosting, the web board, horizon (direction), lattice (consolidation). |

---

## Post-M4 — the sibling integration milestones (horizon, lattice)

These are not chorus features — they are the moments a **sibling repo** plugs into a seam chorus
already reserved (spec 00 §5a). chorus needs **no kernel change** for either; the milestone is
"prove the seam holds."

| Milestone | Sibling | The seam it fills | What proves it |
|---|---|---|---|
| **H1 — horizon takes intake** | horizon | `submit` / `task.depth=0` intake slot + the `goal` tree (spec 10 §5) | horizon drives `submit` from OKR direction; chorus executes identically; the stub intake is *retired*, not rewritten |
| **L1 — lattice replaces the writer** | lattice | the `MemoryWriter` swap behind `MemoryStore`/`MemoryWriter` (spec 07 §4) | lattice's consolidating writer replaces `AppendOnlyMemoryWriter`; chorus's read path + provenance unchanged; raw deltas it already wrote are consolidated |

The invariant the two milestones jointly prove: **the four-repo architecture was real from M1.**
Because every sibling seam was a typed contract + a stub default (never a stub the sibling must rip
out), H1 and L1 are *additions at the seam*, not migrations through the kernel. If either requires
editing the scheduler, ledger, or recovery, the seam was wrong — and that's the test.

---

## Per-milestone test strategy

Each milestone ships with the test class that *proves its specific invariant*, layered on the prior:

| Milestone | The test that proves it | Failure-injection / crash test |
|---|---|---|
| **M1** | `test_public_api` pins the surface; an integration test runs a real `submit → run_task → evaluator → merge`; a `Command` DoD that fails forces the repair loop | kill the process mid-beat → restart → lease-recovery re-dispatches; assert **no duplicate run, no stranded task** |
| **M2** | dependency-gating test (`B` withheld until `A` done); concurrency test (two beats under the cap); a budget test that a hard breach pauses + kills | crash mid-dispatch → assert the `wake` coalescing index holds (no double-dispatch); `cost_event` race → live-recompute still blocks |
| **M3** | decomposition exact-once test (3 children, fingerprint reuse); `children_done` re-invocation test; a Reviewer-verified PM task | kill the manager **mid-fan-out** → retry resumes from the same `decomposition_claim`, reuses created children, never double-fans-out |
| **M4** | cron exact-once-across-ticks test; export→import round-trip (org + routines re-materialize, secrets re-prompted); a new role plugin schedules with no kernel diff | two ticks fire the same routine edge → `claim_cron_edge` lets exactly one win; multi-process tick (Postgres) → `SKIP LOCKED` drains disjoint wakes |
| **H1 / L1** | a sibling-seam contract test: horizon/lattice bind only `dream.contracts` + chorus contracts (import-graph assertion: **no chorus internals imported**) | swap the stub for the sibling impl → the full M1–M4 suite still passes unchanged |

The through-line: **every milestone's headline test is a crash/exact-once test**, because the whole
thesis is that crash-safety lives in the partial-unique indexes + the lease clock (spec 01, spec 02),
not in coordination code. A milestone isn't done until its failure-injection test is green.

---

## The dependency graph (what unblocks what)

```
M1 seam (run_task + DoD + landing + lease recovery)
  └─▶ M2 wakes + deps + budgets + memory-writer
        └─▶ M3 decomposition + children_done + recovery + Reviewer
              └─▶ M4 cron + monitors + dynamic org + portability
                    ├─▶ H1 horizon fills the intake seam (submit / goal tree)
                    └─▶ L1 lattice fills the memory-writer seam (consolidation)
```

Each milestone is shippable on its own (a real, if small, working org). The first slice to build is
**M1's seam** — and the single riskiest, highest-value thing in it is the **DoD pass-down to dream's
evaluator** (spec 05 §5), because that's both the differentiator and the proof that being
dream-native pays off.

---

## Cross-check: what M1–M4 drops vs Paperclip

The whole right-hand column of Paperclip's complexity, never built (because dream-native):
the subprocess/adapter layer, the MCP/REST/auth/WebSocket stack, the output-silence watchdog +
`classifyRunLiveness`, the per-adapter stdout parsers, the React board (in the SDK), and multi-company
tenancy. chorus's M1–M4 is the org plumbing + the evaluator-verified outcome — the parts that are
*orthogonal to observability* plus the one frontier Paperclip left open.
