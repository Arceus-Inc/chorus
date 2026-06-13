# 03 — Task lifecycle & orchestration

Paperclip is an **event-driven control plane (push, not poll) with a periodic
reconciliation backstop.** There is **no central scheduler that polls a work queue.**
Work is driven by `agent_wakeup_requests` rows ("wakes") enqueued on events; the
periodic loop exists *only* to detect and repair work that lost its event-driven path
(crashes, silent stalls).

Core files: `server/src/services/heartbeat.ts` (the run engine), `issues.ts` (the issue
state machine + checkout), `issue-tree-control.ts` (subtree holds), `recovery/service.ts`
(liveness/watchdog), `routes/issues.ts` (HTTP transitions). Periodic loop wired in
`server/src/index.ts`. Authoritative model: `doc/execution-semantics.md`.

---

## 1. The work loop (create → assign → execute → review → done)

| Transition | Owner | Push/Poll | Mechanism |
|---|---|---|---|
| create | `issues.ts:create` | — | If created with an assignee and no explicit status → defaults to `todo` (not `backlog`), so a wake path exists. |
| assign → wake | `issue-assignment-wakeup.ts:queueIssueAssignmentWakeup` | **push** | On assignment, enqueue one `source:"assignment"` wake for the assignee (skipped if `backlog` or no agent). |
| dispatch → execute | `heartbeat.ts:enqueueWakeup` (≈10099) → claim → executor (≈7744) | **push** | Wake → `heartbeat_runs` row → executor auto-checks-out the issue, then invokes the adapter. |
| checkout | `issues.ts:checkout` (≈5480), from executor via `shouldAutoCheckoutIssueForWake` | — | Atomic DB compare-and-set (§3). |
| **adapter invocation (the seam)** | `heartbeat.ts:≈9001` `adapter.execute(...)` | — | The single seam to the adapter, resolved by `agent.adapterType`. `onLog`/`onMeta`/`onSpawn` callbacks stream output back. |
| execute → done/in_review/blocked | the **agent**, via REST status mutation | — | Disposition is agent-self-reported, then *validated* (§5). Never inferred from prose. |
| reviewed → done | human approval or reviewer participant | **push** | See §5. |

**Push vs poll:** push is primary. The `setInterval` in `index.ts` (`heartbeatSchedulerIntervalMs`)
runs the *recovery* sweep + scheduled-routine triggers — it is not the primary dispatch path.
`cron.ts` is just a cron-expression parser used by routines, not the task scheduler.

The **wakeup → queued run → claim → spawn** path in detail
(`heartbeat.ts`):
1. **Enqueue** — `enqueueWakeup(agentId, opts)`: validate company/agent/budget, build a
   `contextSnapshot` (issueId/wakeReason/etc.), write an `agent_wakeup_requests` row and a
   `queued` `heartbeat_runs` row, emit `heartbeat.run.queued`. Wakes **coalesce** by idempotency.
2. **Claim** — the tick loop prioritizes queued runs (in-progress issues first, then
   dependency-ready, then priority/age) and `claimQueuedRun` up to available concurrency slots,
   re-checking invokability (agent exists, not budget-blocked, deps resolved, issue not terminal)
   and stamping `executionRunId`.
3. **Execute** — `executeRun(runId)`: acquire env/workspace via the orchestrator, mint the JWT,
   call `adapter.execute(...)` → for local adapters spawns an OS child process in the realized
   workspace cwd.

---

## 2. Manager decomposition + non-blocking re-invocation

**This is the chorus §5 question, already solved.**

**Decomposition** — `issues.ts:decomposeAcceptedPlan` (≈4580):
- Exact-once primitive keyed on `(sourceIssueId, acceptedPlanRevisionId)`. A durable
  `issue_plan_decompositions` claim row is created `FOR UPDATE` with status `in_flight`
  *before any child is created*.
- Children are created **one-per-transaction in a resumable loop**: each iteration locks the
  claim row, appends one child id to `childIssueIds`, flips status to `completed` when all
  children exist. **A run that dies mid-fan-out resumes from the same fingerprint and reuses the
  already-created child ids — it does not restart.** A second run with a different child set
  hits `conflict(...)`.
- Each child (`createChild`) sets `parentId`, inherits project/goal/workspace, bumps
  `requestDepth`, and **if `blockParentUntilDone` is set, adds the child as a first-class blocker
  of the parent** via `syncBlockedByIssueIds`. *Key: parent-waits-on-child is modeled as a
  blocker, not as `parentId`.*

**Is the parent ever blocked awaiting?** No. The parent run **terminates**. It holds no open
coroutine/await. Re-invocation is purely event-driven.

**"All children done → wake parent"** — two independent push paths, both fired from
`routes/issues.ts` when a child's status mutates:
1. `becameTerminal && issue.parentId` → `getWakeableParentAfterChildCompletion`: returns the
   parent **only if** it is agent-assigned, non-terminal, non-backlog, AND **every** direct child
   is `done|cancelled`; then enqueues an `issue_children_completed` wake carrying child summaries.
2. `becameDone` → `listWakeableBlockedDependents` → `issue_blockers_resolved` wakes to dependents
   whose final blocker just resolved (covers `blockParentUntilDone`).

So a manager that splits work into 3 children and ends its run is re-woken once when the last
child finishes (children-completed) and/or when the blocker chain clears (blockers-resolved).

> `issue-tree-control.ts` is a *separate* concern — it implements operator pause/resume/cancel/
> restore **holds** over a whole subtree (BFS over `parentId`); it is not the children-done-wake
> mechanism.

---

## 3. Single-assignee + atomic checkout

**Invariant:** at most one assignee; `assigneeAgentId` XOR `assigneeUserId`. Paperclip **never
auto-reassigns** (execution-semantics §13).

**The execution lock is a DB compare-and-set, not an advisory lock.** Two columns on `issues`:
`checkoutRunId` (ownership) and `executionRunId` (the live run), plus `executionLockedAt`,
`executionAgentNameKey`.

`issues.ts:checkout` — the grab is a single conditional `UPDATE ... RETURNING`:
```sql
UPDATE issues SET assigneeAgentId=:agent, status='in_progress', startedAt=…, checkoutRunId=:run …
WHERE id = :id
  AND status IN (:expectedStatuses)
  AND (assigneeAgentId IS NULL OR (assigneeAgentId = :agent AND (checkoutRunId IS NULL OR checkoutRunId = :run)))
  AND (executionRunId IS NULL OR executionRunId = :run)
```
If 0 rows return, a second agent already holds the lock → the function self-heals stale locks,
else throws `conflict("Issue checkout conflict")` = **HTTP 409**. The agent must treat 409 as a
real ownership conflict and **stop, not retry**. Postgres row-level write locking serializes the
two competing updates — only one can satisfy `checkoutRunId IS NULL` and win.

**Stale-lock self-healing (crash recovery, not retry):** `clearExecutionRunIfTerminal` /
`clearCheckoutRunIfTerminal` take `SELECT ... FOR UPDATE` on the issue and the referenced run, and
clear lock columns **only if** the run is terminal or missing — never a live run.
`adoptStaleCheckoutRun`/`adoptUnownedCheckoutRun` allow a live actor run to adopt a terminal prior
owner. Backstop: `recovery/service.ts:sweepStaleIssueLocks` on the periodic loop.

`agent-start-lock.ts` is a *separate, in-process* mutex (`withAgentStartLock`, a
`Map<agentId, Promise>` with a 30s staleness escape) that serializes concurrent queued-run starts
for one agent within one process — not the issue lock; the DB checkout is the cross-process authority.

---

## 4. Liveness / stuck detection

The most elaborate subsystem — covered in depth in
[05-liveness-and-recovery.md](05-liveness-and-recovery.md). In short: three orthogonal failure
modes (stranded work / silent active run / useless successful run) are handled by distinct
mechanisms, all driven from the periodic recovery loop, all **conservative** (retry once, surface
explicitly, escalate to a human; never silently complete or reassign).

---

## 5. Definition-of-done & approvals

**Done is status-self-report + validation + (optional) human/approval gate. The artifact is NOT
independently verified.**

- The agent declares disposition by mutating issue status via REST. **Prose comments never
  auto-complete an issue** (execution-semantics §8: "must not silently mark work done from prose").
- The **valid-disposition contract** is enforced by `recovery/successful-run-handoff.ts:
  decideSuccessfulRunHandoff`: if a run **succeeds** but the issue is still `in_progress` with no
  execution-policy state, no human owner, and the run produced handoff-relevant progress →
  Paperclip enqueues **one** corrective "finish handoff" wake (status-only model lane) telling the
  agent to pick exactly one of `done`/`cancelled`, `in_review` *with a real reviewer path*,
  `blocked` *with first-class blockers*, or delegate/continue. If that is also exhausted →
  `reconcileStrandedAssignedIssues` escalates to `blocked` + a recovery owner. So "finished"
  requires the issue *state/path* to record a valid disposition, not just a transcript.
- **`in_review` health**: a review state is healthy only if it has a typed
  `executionState.currentParticipant`, a pending interaction/approval, a human owner, an active
  monitor, or a queued wake. An `in_review` issue assigned back to the same agent with none of
  those is flagged `in_review_without_action_path`.
- **Approval gate** — `approvals.ts` (+ `issue_approvals` linking): a separate row with status
  pending → approved/rejected/revision_requested, decided by a human. This is the human gate; it's
  an explicit linked object, **not** an inference over output.

**There is no step that diffs/tests/inspects the produced artifact to confirm correctness.**
`run-liveness.ts` evidence counts (comments/revisions/work-products) gate *whether a run
progressed*, not *whether the deliverable is correct*. This is the "Enforced Outcomes" gap (still
⚪ on Paperclip's roadmap) and the chorus differentiator — see
[10-implications-for-chorus.md](10-implications-for-chorus.md).

---

## 6. Assignment (routing)

**Manual / explicit, plus structured delegation. No automatic role-match scoring router.**

1. **Direct assignment** — set `assigneeAgentId`; on change, lock columns clear and
   `queueIssueAssignmentWakeup` fires. Assignability validated by `agent-assignability.ts:
   assertAssignableAgent` (rejects paused/terminated/pending_approval, or an invalid org chain —
   terminated ancestor, missing manager, cycle, depth exceeded).
2. **Manager delegation** — a manager run creates children with `createChild`/
   `decomposeAcceptedPlan`, each carrying its own `assigneeAgentId`.
3. **@-mention routing** — a *structured* agent mention in a comment enqueues an
   `issue_comment_mentioned` wake; plain text naming an agent does **not** assign or wake.
4. **Recovery owner selection** (failure path only, off by default) — `issue-graph-liveness.ts:
   ownerCandidatesForRecoveryIssue` *recommends* an owner by walking assignee→reporting-chain →
   creator-chain → root agent → ordered fallback.

**Invokability gate** (orthogonal to assignment): even a correctly-assigned agent won't run if
`agent-invokability.ts:evaluateAgentInvokability` blocks it (paused/terminated/pending_approval/
invalid org chain). `shouldCancelRunsForNonInvokableAgent` cancels in-flight runs for terminated
agents or broken org chains.

---

## Push-vs-poll summary

- **Primary = push.** Events (assign, comment, status change, child terminal, blocker resolved,
  mention) enqueue `agent_wakeup_requests`; `enqueueWakeup` coalesces and creates queued
  `heartbeat_runs`; the executor checks out and invokes the adapter.
- **Recovery = poll.** The `index.ts` interval runs, in order (execution-semantics §10): reap
  orphaned runs → resume queued runs → `reconcileStrandedAssignedIssues` →
  `reconcileIssueGraphLiveness` → `scanSilentActiveRuns` → `sweepStaleIssueLocks` →
  `reconcileProductivityReviews`. The same sequence runs once at startup.
