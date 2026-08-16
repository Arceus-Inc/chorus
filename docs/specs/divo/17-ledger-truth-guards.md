# 17 — Ledger-truth guards (`done` ⇒ landed · capability-checked assignment)

> Two small, deterministic kernel guards so the ledger reflects *landed reality*, not
> just finish-state. Closes **BUG-005** (`done` ≠ landed) and **BUG-006** (a deliverable
> assigned to a role that can't produce it) — recurring in the live `--org` runs cataloged
> in [`standup-app/hard-task-report/issues.md`](../../../standup-app/hard-task-report/issues.md).

Siblings: [02 — Lifecycle & recovery](02-lifecycle-and-recovery.md) (the repair ladder +
recovery cards), [04 — Outcomes, DoD & governance](04-outcomes-and-governance.md) (the DoD
+ landing), [06 — Roles & workforce](06-roles-and-workforce.md) (role `outcome_kind`).

These guards keep **task** status honest. A later goal-finalization judge that reads durable
evidence (terminal task + verified primary deliverable) must not inherit a false `done` from
an unmerged PR.

---

## 1. BUG-005 — `done` ⇒ landed

### The bug
`_land_passed` → `_land_outcome` → `finalize_beat(PASSED)` marks a task `done`
**unconditionally**. The engineer lander integrates the branch into company `main` and records
merge success on the `pr` artifact, but a *conflicting* integration is recorded
(`PrIntegration.UNMERGED`), not raised — so the task still finalised `done` while its work
never landed.

### The fix
- `_land_outcome` **returns the landed artifact**.
- A typed `pr_landing` helper is the only interpreter of that artifact: an explicit unmerged
  PR **blocks `done`**. Missing merge flags and non-PR artifacts do not (landing stays additive).
- `_land_passed` then routes a **merge-repair ladder** (`_route_merge_conflict`): the author is
  re-dispatched to rebase (a `RECOVERY` wake, `cause=merge_conflict`; the worktree/branch
  persist so the next passed beat re-attempts the merge), bounded by `max_repair_attempts`.
  The cap counts **recorded unmerged-PR landings only**, not every author run (a prior DoD
  failure does not consume merge-repair budget). After the cap the task is `blocked` with a
  recovery card (`cause=merge_conflict_exhausted`).
- An explicit unmerged PR is recorded **without** `review_state=verified`.
- The landed-outcome seam maps **this beat's** landing: rebase is `LandedPhase.NEEDS_REWORK`
  and exhausted merge repair is `LandedPhase.STRANDED` — never `TERMINAL_PASS`. A later
  successful merge is `TERMINAL_PASS`; historical unmerged artifacts do not poison
  `OUTCOME_LANDED`.

*No DB migration — reuses `recovery_action` + `max_repair_attempts`.*

## 2. BUG-006 — capability-checked assignment

### The bug
A manager assigned a *code* (`pr`) child to a `pm` (produces `doc`) or `analyst` (produces
`finding`); the non-coding role can't land that deliverable, so the child stranded/rejected at
the DoD. A reviewer guard already existed; pm/analyst had none — and they have *legitimate*
outcomes, so a flat deny would be wrong.

Cross-craft DoD selection (`DeliverableKind`) still judges undeclared work by the *task's*
deliverable. This guard is the opt-in *assignment* check: when the manager **declares** an
`OutcomeKind`, the assignee's role must be able to produce it.

### The fix
- `ChildPlan` / the decompose and `submit_task` tools gain a typed **`outcome_kind`**
  (`OutcomeKind`). The tools **omit it by default** (backward-safe: undeclared skips the check);
  internal callers leave it `None`. Declaring a kind is opt-in fail-closed.
- `CapabilityService.decompose` / `submit_one` refuse a child whose declared kind differs from
  what its assignee's role lands (`backend_engineer`/`engineer`/`frontend_engineer` → `pr`,
  `pm` → `doc`, `analyst` → `finding`, `manager` → `subtree`, `reviewer` → `verdict`,
  `designer` → `design`, `marketer` → `content`, `ceo` → `directive`), returning
  `DecomposeResult.outcome_mismatches` (typed `OutcomeMismatch` records). Nothing is created
  (fail-closed).
- A child with **no declared outcome** skips the check. A role outside the catalog (a custom
  plugin) also skips it (fails *open*).

*No DB migration — the guard runs at decompose/submit time.*

## 3. Touchpoints
- `src/chorus/outcomes/_pr_landing.py` — typed PR integration disposition.
- `src/chorus/outcomes/_outcome_kind.py` — `OutcomeKind` enum.
- `src/chorus/lifecycle/_outcome_capability.py` — catalog + mismatch check.
- `src/chorus/heartbeat/_scheduler.py` — `_land_outcome` return; `_land_passed` merge gate;
  `_route_merge_conflict`; `OUTCOME_LANDED` uses this beat's `PrLanding`.
- `src/chorus/lifecycle/_capability.py` — `ChildPlan.outcome_kind`, wired into
  `decompose`/`submit_one`.
- `src/chorus_tools/_decompose.py` / `_manager_actions.py` — declared `outcome_kind` + refusal.

## 4. Tests
- `tests/outcomes/test_pr_landing.py` — unmerged / merged / missing flag / non-PR.
- `tests/heartbeat/test_outcome_landing.py` — unmerged branch re-dispatches then blocks; a
  prior DoD failure does not consume the default merge-repair cap; unmerged PRs are not
  `review_state=verified`; an unmerged-then-successful-merged tick is `TERMINAL_PASS` with
  a verified latest artifact; a clean merge / no-lander still finalise `done`.
- `tests/heartbeat/test_landed_outcome_derivation.py` — unmerged rebase is `NEEDS_REWORK`,
  exhausted merge repair is `STRANDED`, never `TERMINAL_PASS`.
- `tests/tools/test_decompose_tool.py` / `tests/tools/test_manager_action_tools.py` — omitted
  `outcome_kind` skips the check; an explicit `pr` child to a pm is refused.
- `tests/lifecycle/test_outcome_capability.py` — typed mismatch vs match vs undeclared vs
  unknown role.
- `tests/lifecycle/test_capability.py` — a `pr` child to a pm is refused (nothing created); a
  `doc` child to a pm is allowed; an undeclared outcome skips the check.

## 5. Out of scope
- Re-dispatch beyond the author (an autonomous integrator that resolves conflicts itself).
- Threading a full `RoleRegistry` into `CapabilityService` (the typed canonical catalog
  mirrors each default/legacy plugin; custom-role coverage is a follow-up).
- Goal-finalization judging from durable evidence (a sibling change; this guard only keeps
  task `done` honest so that evidence cannot be a false status).
- The stranded-`todo` liveness guard.
