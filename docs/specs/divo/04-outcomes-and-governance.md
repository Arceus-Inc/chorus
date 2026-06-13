# 04 — Outcomes, DoD & governance

The two things Paperclip's ROADMAP still lists as ⚪ **open** — *Enforced Outcomes* and *Artifacts &
Work Products* — plus the governance Paperclip *did* solve (two-gate budgets, fail-closed trust).
This is where chorus's **differentiator** lives: because it is dream-native, the evaluator verifies
the real artifact against a typed Definition-of-Done.

---

## 1. Definition of Done — a typed verifier (the differentiator)

Paperclip's "done" is **self-report + validation + optional human approval — the artifact is never
independently verified** (`run-liveness.ts` counts whether a run *progressed*, not whether the
deliverable is *correct*). chorus closes this because dream's evaluator sees the real artifact.

**DoD = the cheapest *sufficient* verifier for the artifact class** (B3.1). It is generated at intake,
persisted typed on `task.dod`, and enforced by dream's evaluator inside `run_task`. Three tiers:

```
DoD = Command          # objective gate: a shell command must exit 0 (tests/CI/typecheck)
    | AgentReview      # judgment gate: a Reviewer employee renders a verdict
    | HumanApproval    # a person decides (the approval primitive)
```

```json
// task.dod
{
  "kind": "command",
  "spec": { "command": "pytest -q && ruff check .", "timeout_s": 300 },
  "artifact_class": "pr"
}
// or
{ "kind": "agent_review", "spec": { "reviewer_role": "reviewer", "rubric": "..." },
  "artifact_class": "spec" }
// or
{ "kind": "human_approval", "spec": { "approver": "board" }, "artifact_class": "decision" }
```

**Rules** (B3.1–B3.3):
- A worker's self-report is **never** evidence. `done` requires the verifier to pass *and* a valid
  disposition recorded (spec 02 §5).
- **Judgment-class work without a Reviewer is just self-report** — so the **Reviewer role ships with
  the first non-code role** (M3), not later. An Analyst with no Reviewer is Paperclip.
- Free-form checklists are banned; the DoD is a typed `Verifier` so the evaluator can't rationalize.

### The chorus⟂dream evaluator seam (the M1 decision)

dream's `run_task` already runs an evaluator that verifies the *sprint contract* per task. chorus's
DoD is the *task-level* outcome. The seam: **chorus passes `dod` down into `run_task`**, and dream's
evaluator enforces it as the final acceptance — so chorus is a thin orchestrator around dream's
evaluator, not a second outer verification layer. (`harness.run_task(..., dod=task.dod)`; the
generator turn-loop writes the artifact, the evaluator turn-loop runs the `Command`/`AgentReview`.)

---

## 2. Outcome landing — the artifact/work-product model

"Done" is not "the run finished" — it is "the deliverable **landed** somewhere a reviewer can verify
it" (Paperclip `AGENT-ARTIFACTS.md`). Role-specific:

| Role | Landing |
|---|---|
| Engineer | PR opened → CI green → (repair) → merge |
| Reviewer | an approve/block verdict on a diff |
| PM | a spec/decision artifact, persisted + reviewable |
| Analyst | a data finding, persisted + reviewable |

The `artifact` row (spec 01) carries the outcome. Two artifact classes (Paperclip's, kept):
- **uploaded artifact** — a durable blob (PR ref, doc, finding, screenshot). Server-canonicalized
  metadata (`content_type`, `byte_size`, paths) — *not* worker-supplied. The primary, durable form.
- **workspace_file reference** — a second-class pointer (`relative_path` inside a registered
  workspace; **no host-absolute paths, no `..` escape**). A convenience, not a deliverable.

**Completion pattern** (strict): generate + verify locally → persist artifact → link it in the final
task comment → set status. A local path is never the sole access path — the reviewer (human or agent)
must be able to reach the artifact, or the work isn't landed.

> Q3 from Corebelief dissolves here: a PM spec or Analyst finding lands *wherever a Reviewer can
> verify it* — verifier first, storage second.

---

## 3. Budgets — the two-gate hard-stop (Paperclip's, transplanted)

Caps need **both** gates threaded at *every* run-start site — a single post-hoc check leaks (B2.4).

**Gate 1 — proactive pre-invocation block** (`budgets.invocation_blocked`, the tick §3d + every
dispatch site): before starting any beat, check company-paused / company-over → employee-paused /
employee-over, returning a block reason or none. **No employee runs while a hard-stop is active for
it or its company.**

**Gate 2 — reactive auto-pause + kill** (on each `cost_event`): recompute observed spend over
scope+window via fresh SQL; at `warn_percent` → a **soft** `budget_incident` (notify only); at
`amount` with `hard_stop_enabled` → a **hard** incident **paired with an approval**, then pause the
scope (`pause_reason='budget'`) **and cancel in-flight runs + pending wakes**. Hard-stop both flips
status *and* kills live work.

`spent_monthly_cents` is **recomputed live from `cost_event` on read, never trusted.** Resolution is
human-only: `raise_budget_and_resume` (amount must exceed observed) or dismiss (scope stays paused).

---

## 4. Trust — fail-closed presets (Paperclip's `LOW-TRUST-PRESETS`, transplanted)

Two presets: `standard` (default) and `low_trust_review` (containment for hostile/prompt-injected
input — external PRs, untrusted tickets, dependency diffs). The preset is resolved by **intersecting
the layered policy sources (employee / task / run); narrower wins; any conflict, cross-scope, or
unsupported preset → `denied` (fail closed).** A low-trust preset with no concrete scope is denied.

**Containment ≠ privacy** (the key invariant): low-trust limits what the agent can *read/mutate via
the API* and prevents raw untrusted output from being promoted into higher-trust context — it does
**not** hide work from the board.

**Runtime containment fails closed** unless **all** hold: sandbox-driver execution, isolated
workspace, the task is inside the boundary, secret refs are in the boundary allow-list, and **no
inline sensitive values** (raw keys rejected — must use approved refs). For dream-native chorus this
maps onto dream's `permissions` (9-step fail-closed `evaluate`) + `sandbox` adapter + `roles`
toolset — the mechanism already exists; chorus supplies the preset resolution + boundary scope.

---

## 5. Approvals & governance gates

`approval` is the first-class governed-action queue: `type` (`hire_employee\|budget_override\|
plan_approval\|board_approval`), `status` (`pending→approved\|rejected\|revision_requested`),
`decided_by_user_id`. Governance actions **are** org mutations: approving a `hire_employee` activates
the pending employee + upserts its budget policy; rejecting terminates it. Budget overrides resolve
via §3. A `human_approval` DoD is just an approval linked to the task.

---

## 6. What chorus owns vs. what's deferred

| Capability | chorus M1–M4 | Deferred (Arceus / horizon / lattice) |
|---|---|---|
| Evaluator-verified DoD | **owns (M1)** — the differentiator | — |
| Artifact landing | owns (M1 engineer; M3 reviewer) | rich previews → Arceus |
| Two-gate budgets | owns (M2) | billing/finance ledger → Arceus |
| Fail-closed trust | owns (via dream permissions) | multi-tenant isolation → Arceus |
| Memory | append-only raw write/read (M2) | consolidation → lattice |
| Direction / what-to-do-next | intake + cron only | strategy → horizon |

> The synthesis: chorus is **Paperclip-shaped for the org, dream-native for the loop, and owns the
> evaluator-verified outcome Paperclip still lacks** — closing *Enforced Outcomes* at M1 precisely
> because it is dream-native, while deferring *Memory consolidation* and *Direction* to the siblings
> that will own them.
