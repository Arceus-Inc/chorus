# 05 — Liveness & recovery (the silent-stall machinery)

This is the most sophisticated subsystem in Paperclip — and it exists **entirely to
compensate for the process boundary** ([04](04-execution-and-adapters.md)). Because the
agent is an opaque byte stream, Paperclip cannot *watch* it work; it must *reconstruct*
"is this alive?" from external signals: output-silence timing, durable side-effect
evidence, and DAG/ownership row state. `recovery/service.ts` alone is 147KB.

Authoritative model: `doc/execution-semantics.md` (605 lines). Code:
`server/src/services/recovery/*`, `run-liveness.ts`, `issues.ts`. Driven from the
periodic loop in `server/src/index.ts`.

---

## The core mental model: four separated concepts

execution-semantics §1 keeps four things that are easy to blur strictly separate:

1. **structure** — `parentId` (work breakdown)
2. **dependency** — blockers (`issue_relations type=blocks`)
3. **ownership** — who is responsible now (`assigneeAgentId` XOR `assigneeUserId`)
4. **execution** — whether the control plane currently has a *live path* to move the issue forward

The system's health question is about #4: **does the issue have a live execution path, an explicit
waiting path, or a recovery path?** If not, it is *stalled* and must be surfaced — never silently
completed or reassigned.

## The liveness contract (liveness-as-visibility, not auto-completion)

> "Paperclip should never leave work in a state where nobody is responsible for the next move and
> nothing will wake or surface it. **This is a visibility contract, not an auto-completion
> contract.** If Paperclip cannot safely infer the next action, it surfaces the ambiguity with a
> blocked state, a visible notice, or an explicit recovery action. It must not silently mark work
> done from prose comments or guess that a dependency is complete."

An issue is **healthy** when the product can answer "what moves this forward next?" without a human
reconstructing intent. The valid **action-path primitives** (any one suffices):

- an active run linked to the issue
- a queued wake / continuation deliverable to the responsible agent
- a typed execution-policy participant (`executionState.currentParticipant`)
- a pending issue-thread interaction or linked approval awaiting a named responder
- a one-shot issue **monitor** (`executionPolicy.monitor.nextCheckAt`) that will wake the assignee
- a human owner (`assigneeUserId`)
- a first-class **blocker chain** whose unresolved leaves are themselves healthy
- an open **explicit recovery action** naming the owner + action needed

An issue is **stalled** when it is non-terminal but has none of these. → surface as blocked/recovery.

## Issue monitors (deferred self-wake against external systems)

`executionPolicy.monitor` (`nextCheckAt`, `notes`, `serviceName`, redacted `externalRef`,
`timeoutAt`/`maxAttempts`/`recoveryPolicy`) is a **one-shot** deferred check for `in_progress`/
`in_review` issues waiting on an async system (CI, deploys, review services). When it fires,
Paperclip clears it and queues an `issue_monitor_due` wake; if still pending, the assignee must
**re-arm** with a new `nextCheckAt`. Bounds are enforced (exhausted `timeoutAt`/`maxAttempts` →
`recoveryPolicy`: `wake_owner` | `create_recovery_issue` | `escalate_to_board`). Monitors are *not*
recurring intervals; use `blocked` when no Paperclip assignee owns the polling path.

---

## The three failure modes (and their distinct mechanisms)

All driven from the periodic loop. All **conservative**: retry once, surface, escalate — never loop,
never reassign.

### (a) Stranded assigned work — run/wake *disappeared*
`recovery/service.ts:reconcileStrandedAssignedIssues`. Scans agent-assigned, non-user-owned issues
in `todo`/`in_progress`; skips any with a live path, pending wake/interaction, or pause hold.
- **stranded `todo`** (dispatch recovery): no run → enqueue one initial dispatch wake; latest run
  failed/cancelled/timed-out and auto-recovery already failed once → escalate to `blocked` + visible
  comment; else enqueue exactly one `assignment_recovery` wake.
- **stranded `in_progress`** (continuity recovery): enqueue one continuation wake; if a productive
  continuation already ran and there's still no live path → escalate to `blocked` + recovery action.

### (b) Silent active-run watchdog — process is `running` but produces no output
`recovery/service.ts:scanSilentActiveRuns` + `buildRunOutputSilence`. **The literal silent-stall
detector.** Thresholds: `SUSPICION = 60 min`, `CRITICAL = 4 h`, `CONTINUE_REARM = 30 min`. Silence
age = `now − coalesce(lastOutputAt, processStartedAt, startedAt, createdAt)`. Classification:
`not_applicable | snoozed | critical (≥4h) | suspicious (≥1h) | ok`.
- **suspicious** → one **medium-priority** `stale_active_run_evaluation` watchdog recovery issue
  (max one open per run).
- **critical** → raise to **high priority** and, when needed for correctness, **block the source
  issue on the evaluation task — without cancelling the live process.**
- **The watchdog never auto-kills the run.** Resolution is an explicit decision via
  `recordWatchdogDecision`: `snooze` (quiet-until window), `continue` (acknowledge, re-arm 30 min),
  or `dismissed_false_positive`. Only the board or the assigned recovery owner may record it.

**Source-aware folding** (execution-semantics §11): before creating/escalating watchdog work, the
watchdog re-reads the linked source issue. It **folds** (resolves) the alert when the source is
terminal *with durable same-run terminal activity after the evidence point* and there's no
independent evidence of harmful/detached work. This is the exact "`apply_patch` ran long, the run
looked dead, but the work actually completed" case — *don't kill on silence; check if the source
issue already reached a disposition.*

### (c) Useless successful run — run *succeeded* but did nothing useful
`run-liveness.ts:classifyRunLiveness` (post-success only): `advanced`/`completed`/`blocked`/
`plan_only`/`empty_response`/`needs_followup`/`failed`, from concrete evidence counts (comments, doc
revisions, work products via `hasConcreteActionEvidence`) + regex intent parsing. `plan_only`/
`empty_response` are **auto-continued, bounded** (`recovery/run-liveness-continuations.ts`, max 2
attempts); `needs_followup` ("described work but not safe to auto-continue") is **not** auto-continued.

### (d) Dependency-graph liveness — structurally-dead graphs
`recovery/issue-graph-liveness.ts:classifyIssueGraphLiveness` (pure function):
`blocked_by_unassigned_issue`, `blocked_by_assigned_backlog_issue`, `blocked_by_uninvokable_assignee`,
`blocked_by_cancelled_issue`, `invalid_review_participant`, `in_review_without_action_path`. Walks
blocker chains to the first stalled leaf and recommends owner candidates. **Disabled by default** —
advisory unless an operator enables instance-level auto-recovery.

---

## Three recovery outcomes (execution-semantics §12)

| Outcome | When | Action |
|---|---|---|
| **Auto-recover** | ownership clear, only execution continuity lost | requeue *one* dispatch/continuation wake; preserve the existing owner; **never choose a replacement agent** |
| **Explicit recovery action** | a problem is identifiable but cannot be safely completed | open a typed `issue_recovery_action` (source-scoped by default; issue-backed only for independent repair work) naming owner/cause/evidence/next-action/wake-policy |
| **Human escalation** | next safe action needs board judgment / budget / unavailable info | leave a visible issue/comment trail; do not silently retry |

> "The recovery model is intentionally conservative: preserve ownership, retry once when the control
> plane lost execution continuity, open an explicit recovery action when a bounded owner/action is
> known, escalate visibly when the system cannot safely keep going." (execution-semantics §13)
> Paperclip **does not** auto-reassign work to a different agent, **does not** infer dependency from
> `parentId` alone, **does not** treat human-held work as heartbeat-managed.

## The cheap-model recovery lane (= dream's `wake_model`)

execution-semantics §9.3 / §11.5: a `modelProfile: "cheap"` lane is for **status-only operational
recovery overhead only** (update task liveness, clear bad status, record a disposition, ask for
human/manager intervention). Those wakes carry guard context `allowDeliverableWork: false`,
`allowDocumentUpdates: false`, `resumeRequiresNormalModel: true`. Any run that can continue source
work must use the normal lane; cheap recovery hints are scrubbed from copied retry/resume/child
contexts. This is precisely the Arceus/dream `wake_model` cost lever.

## Startup & periodic reconciliation (execution-semantics §10)

On startup and on each periodic tick, in sequence:
1. reap orphaned `running` runs
2. resume persisted `queued` runs
3. reconcile stranded assigned work (a)
4. scan silent active runs (b), fold source-resolved watchdogs or create/update watchdog recovery
5. reconcile productivity reviews (later, separate — unusual progression patterns on source issues)

## False-positive risk (killing live work) — and how it's bounded

The design is explicitly built to minimize killing live work:
- The watchdog (b) **never cancels** a running process; worst case it blocks the source issue on a
  review task and waits for a human/owner decision. A genuinely-busy-but-quiet run (a long compile,
  a 2-hour generation) is *not* killed.
- Residual risk lives in three documented places: bounded auto-continuation of `plan_only`/
  `empty_response`; the `hasRecentVisibleProgress` exemption (added precisely because batch
  workflows making progress every heartbeat were being escalated to `blocked` after two productive
  heartbeats — a real near-miss); and source-aware folding (avoids manager-review churn on a
  completed issue whose run handle merely stayed hot).

---

## The chorus takeaway

This entire subsystem is the **tax of the process boundary**. dream-native chorus gets the
*structured event stream* and **witnesses** liveness — so the silent-run watchdog, the
output-silence classification, and the post-hoc regex-over-stdout evaluation largely **evaporate**.
But the parts that are about the **DAG and crash recovery** — the liveness-as-visibility contract,
the three-tier recovery ladder, stranded-work reconciliation, exact-once recovery rows, the
cheap-recovery lane — are orthogonal to observability and chorus should adopt them. See
[10-implications-for-chorus.md](10-implications-for-chorus.md).
