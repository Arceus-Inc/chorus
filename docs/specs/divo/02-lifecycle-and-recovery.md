# 02 — Lifecycle & recovery

The task state machine, the **liveness-as-visibility contract**, exact-once decomposition, and
the conservative recovery ladder. Transplanted near-verbatim from Paperclip's authoritative
`execution-semantics.md` (2026-06-10), adapted for dream-native chorus — where most of the
*silent-stall* machinery evaporates but the *crash-recovery* and *DAG-correctness* machinery
stays.

> **The contract in one sentence** (`execution-semantics.md` §8): chorus must never leave an
> agent-owned, non-terminal task in a state where nobody is responsible for the next move and
> nothing will wake or surface it. **This is a visibility contract, not an auto-completion
> contract.**

---

## 1. The four separated concepts

The model keeps four things strictly apart (don't blur them):

1. **structure** — `parent_id` (work breakdown, rollup).
2. **dependency** — `task_dependency` (blockers).
3. **ownership** — who is responsible now (`assignee_employee_id` XOR `assignee_user_id`).
4. **execution** — whether chorus currently has a *live path* to move the task forward.

The health question is always about #4.

---

## 2. The status machine

```
backlog ──▶ todo ──▶ in_progress ──▶ in_review ──▶ done
   │          │           │   │  ▲         │
   │          │           │   │  └─────────┘ (changes requested)
   ▼          ▼           ▼   ▼
cancelled  blocked ◀──────┘  done
```

Legal transitions (Paperclip's, kept):
`backlog→{todo,cancelled}`, `todo→{in_progress,blocked,cancelled}`,
`in_progress→{in_review,blocked,done,cancelled}`, `in_review→{in_progress,done,cancelled}`,
`blocked→{todo,in_progress,cancelled}`. Terminal: `done`, `cancelled`.

Side effects: entering `in_progress` sets `started_at`; `done` sets `completed_at`; `cancelled`
sets `cancelled_at`. **Entering `in_progress` happens by checkout, never by a bare status PATCH.**

Per-status meaning (the operator contract):
- `backlog` — parked; no execution/pickup expectation.
- `todo` — actionable, not yet claimed; an employee-assigned `todo` needs a *wake path* so the
  assignee actually sees it.
- `in_progress` — actively owned, **execution-backed** for employees (strict; must not go silent).
- `in_review` — execution paused; the next move belongs to a reviewer/approver, not the executor.
- `blocked` — cannot proceed until something external changes; **name the blocker + who acts**.
- `done`/`cancelled` — terminal.

---

## 3. The liveness contract — when is a task *healthy*?

An agent-owned, non-terminal task is **healthy** iff it has at least one **action-path primitive**
(`execution-semantics.md` §8). Otherwise it is **stalled** and must be surfaced as recovery work —
never silently completed or reassigned.

Valid action-path primitives (any one suffices):
- an active `run` linked to the task,
- a queued `wake`/continuation deliverable to the responsible employee,
- a typed execution participant (review stage),
- a pending interaction or linked approval awaiting a named responder,
- an active one-shot `monitor` (`next_check_at`) that will wake the assignee,
- a human owner (`assignee_user_id`),
- a first-class `task_dependency` chain whose unresolved leaves are *themselves* healthy,
- an open `recovery_action` naming owner + next action.

Per-status health (transplanted):
- **`todo`** healthy if: queued wake exists, OR intentionally resting after a completed beat with
  no interrupted-dispatch evidence, OR explicitly surfaced as stranded. Stalled if dispatch was
  interrupted and nothing remains queued and no recovery is open.
- **`in_progress`** healthy if: active run, OR queued continuation, OR active monitor, OR open
  recovery. *A still-running-but-quiet run is NOT automatically stalled* — that's the watchdog's
  job (§6), and in dream-native chorus the watchdog is lease-based, not silence-based.
- **`in_review`** healthy if: typed participant, OR pending interaction/approval, OR human owner,
  OR active run/queued wake, OR active monitor, OR open recovery. **Assigning back to the same
  employee with a "please review" comment is NOT a review path.**
- **`blocked`** healthy if: first-class blockers whose unresolved *leaf* is itself live/waiting,
  OR an open recovery action with its own live path, OR a named external owner/action. An
  intermediate `blocked` task does not make the chain healthy — surface the *first stalled leaf*.

**What never counts as done/liveness** (§8): prose comments never auto-complete a task; document
comments don't wake the assignee; plain text naming an employee is not assignment. Routing requires
a *structured* primitive (mention, assignment mutation, interaction response, blocker, wake).

### Lease defaults (the lease clock that replaces silence thresholds)

The board lease is the single liveness primitive (§6). SDK defaults, all overridable per role/run:

| Knob | Default | Meaning |
|---|---|---|
| `lease_ttl` | **120 s** | a claim is live only while its lease is unexpired |
| `renew_interval` | **30 s** (¼ TTL) | the running beat re-stamps the lease this often |
| `renew_grace` | **2 missed renewals** (~60 s) | slack before a lease is *eligible* to be reaped |
| `reap_after` | `lease_ttl + renew_grace` (~180 s) | the tick may reclaim the claim only past this |

The asymmetry is deliberate (Paperclip's rule): **renew aggressively, reap conservatively.** A
beat renews at ¼ TTL so transient pauses never trip it; the tick reaps only after TTL *and* grace
*and* a structured no-progress check, so a slow-but-live run is never stolen. Reaping is **crash
recovery, not retry** (§6) — it releases the lock and surfaces recovery work, it never re-dispatches
blindly.

---

## 4. Decomposition — exact-once (the manager recursion)

When a manager splits a task, it writes children to the ledger and **its run ends** — it never
blocks awaiting them (B1.2). Backed by `decomposition_claim` (spec 01):

1. Acceptance of a plan revision is *permission to decompose that one revision*. The fingerprint is
   `(source_task_id, accepted_plan_revision_id)`.
2. Before creating any child, create/reuse the durable claim (`in_flight`). Create children
   **one-per-transaction**, appending each id to `child_task_ids`; flip to `completed` when all
   exist. **A run that dies mid-fan-out resumes from the same fingerprint and reuses the partial
   result** — never restarts, never double-fans-out.
3. Each child sets `parent_id`, inherits goal/workspace, bumps `request_depth`, and — if it must
   gate the parent — is added as a first-class `task_dependency` of the parent. *Parent-waits-on-
   child is a blocker, not `parent_id`.*
4. While the claim is `in_flight`, the source task must expose a live path for that fingerprint.

**Re-invocation** (push, never await): when the *last* child of a parent becomes terminal, fire a
`children_done` wake to the parent's assignee (only if the parent is employee-assigned, non-terminal,
non-backlog, and **every** direct child is `done|cancelled`). When the *last* blocker of any task
reaches `done`, fire `deps_resolved`. The manager is re-woken as a *fresh session* — which is why
its original intent must be durable (the accepted plan revision; B1.3).

---

## 5. Definition of done

`done` = the employee declares a disposition **and** dream's evaluator verified the artifact against
the typed `dod` (spec 04). The valid-disposition contract (Paperclip's successful-run handoff):
if a run *succeeds* but the task is still `in_progress` with no execution-policy state, no human
owner, and produced handoff-relevant progress → chorus enqueues **one** corrective "finish handoff"
wake telling the employee to pick exactly one of: `done`/`cancelled`, `in_review` *with a real
reviewer path*, `blocked` *with first-class blockers*, or delegate/continue. If that is exhausted →
escalate to `blocked` + a recovery owner. **"Finished" requires the task state/path to record a
valid disposition, not just a transcript.**

> chorus closes Paperclip's ⚪ **Enforced Outcomes** gap here: Paperclip stops at "self-report +
> validation"; chorus adds *evaluator-verifies-the-artifact* because it's dream-native (spec 04).

---

## 6. Recovery — the three-tier ladder (conservative, never auto-reassign)

All driven from the tick (spec 03), in the §10 sequence. Three outcomes by how much can be safely
inferred (`execution-semantics.md` §12):

| Tier | When | Action |
|---|---|---|
| **Auto-recover** | ownership clear, only execution continuity lost | requeue **one** dispatch/continuation wake; **preserve the owner — never choose a replacement** |
| **Explicit recovery action** | a bounded owner/action is identifiable but can't be safely completed | open a typed `recovery_action` (source-scoped by default; task-backed only for independent repair) naming owner/cause/evidence/next-action/wake-policy |
| **Human escalation** | next safe action needs board judgment / budget / unavailable info | leave a visible trail; do not silently retry |

The two crash failure modes (§9):
- **Stranded `todo`** (dispatch recovery): latest run failed/timed-out/cancelled and no live path →
  enqueue one `assignment_recovery` wake; if that also finishes stranded → `blocked` + recovery.
- **Stranded `in_progress`** (continuity recovery): live run disappeared → enqueue one continuation
  wake; if still stranded → `blocked` + recovery.

**Cheap-model recovery lane** (§9.3 = dream's `wake_model`): a `cheap` profile is for *status-only*
overhead (update liveness, clear bad status, record disposition, ask for help) carrying guard
context `allow_deliverable_work=false`, `allow_document_updates=false`, `resume_requires_normal=true`.
Any run that can continue *source* work must use the normal lane; cheap hints are scrubbed from
copied retry/resume/child contexts.

### The watchdog, dream-native (the big simplification)

Paperclip's silent-active-run watchdog classifies output silence (`60min`/`4h` thresholds) by
*reconstructing* liveness from stdout timing — ~350KB of code. **chorus deletes it.** Because we
witness dream's structured event stream and the coordination board's **lease clock**:
- "stuck" = the lease expired (the run's process/heartbeat stopped renewing it) **and** the
  structured state shows no progress — not a guess from byte-silence.
- dream's `runtime/_watchdog.py` already finds stale claims on the board; the tick consumes them
  (spec 03 step a) and opens a `recovery_action`. No silence thresholds, no regex over stdout, no
  per-adapter parsers.

What survives from Paperclip's watchdog: **source-aware folding** — before opening recovery, re-read
the source task; if it's terminal with durable same-run terminal activity after the evidence point,
*fold* (resolve) the alert. (Avoids "the run handle stayed hot but the work actually finished.")

### The `recovery_action` state machine

A `recovery_action` row (spec 01 Cluster B) is itself a tracked lifecycle, so recovery never
becomes its own silent dead state:

```
open ──(owner acts / wake resolves the source path)──▶ resolved
  │
  ├─(folded: source found terminal on re-read)───────▶ folded
  ├─(superseded by a newer action on same source)────▶ superseded
  └─(ladder exhausted, needs board judgment)─────────▶ escalated ──▶ (human/horizon)
```

Invariants: at most **one** `open` recovery_action per `(source_kind, source_id)` fingerprint
(partial-unique index, spec 01); `resolved|folded|superseded|escalated` are terminal; an `open`
action *is* a valid liveness path (§3), so opening one keeps its source healthy while the named
owner is pending. `escalated` emits an `activity(verb='recovered')` row and a `wake` to the
human/horizon responder — it is the only tier that leaves the SDK's autonomous loop.

---

## 7. Startup & periodic reconciliation (the tick's recovery pass)

On startup and each tick, in sequence (`execution-semantics.md` §10, slimmed):
1. reap orphaned `running` runs (lease expired on the board) → release locks.
2. resume persisted `queued` runs.
3. reconcile stranded assigned work (§6 modes a/b).
4. scan stale leases → fold source-resolved or open/update `recovery_action`.
5. *(later)* productivity review.

Because the scheduler is a pure function of the ledger (B2.2), this pass is just *re-deriving* from
rows — a crashed chorus restarts, re-reads, and continues. **There is nothing to strand**, which is
why chorus needs no `stranded-run-sweeper` band-aid (the thing that bit Arceus).

---

## 8. What this does NOT mean (Paperclip's §13, kept)

chorus does **not**: auto-reassign work to a different employee; infer dependency from `parent_id`
alone; treat human-held work as beat-managed execution. The model is intentionally conservative:
**preserve ownership, retry once when execution continuity was lost, open an explicit recovery
action when a bounded owner/action is known, escalate visibly otherwise.**
