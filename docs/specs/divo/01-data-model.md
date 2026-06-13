# 01 — Data model

The chorus ledger. Every row is durable; the scheduler holds no state not in these tables
(B2.2). Transplanted from Paperclip's 86-table model — slimmed to the dream-native,
single-workforce, two-repo world — with the **partial-unique indexes carried over verbatim**,
because those indexes *are* the crash-safety contracts (they make self-spawned work exact-once
at the database layer instead of in coordination code).

SQL is written in the SQLite ∩ Postgres intersection. `id` = text uuid. `*_at` = ISO-8601 text
(SQLite) / timestamptz (Postgres). JSON columns = `text` (SQLite `json1`) / `jsonb` (Postgres).

---

## Cluster A — Work: `task`, `task_dependency`, `decomposition_claim`

### `task` — the universal work unit (≈ Paperclip `issues`)

The ExecPlan made durable. One `task` row per unit of work, at any depth of the org's recursion.

| Column | Type | Meaning |
|---|---|---|
| `id` | text PK | uuid |
| `parent_id` | text FK→task | structural breakdown (NOT a dependency — §B) |
| `goal_id` | text FK→goal | alignment chain; resolved at create (company→project→task) |
| `intent` | text | the goal/description |
| `status` | text | `backlog\|todo\|in_progress\|in_review\|blocked\|done\|cancelled` |
| `priority` | text | `critical\|high\|medium\|low` (default `medium`) |
| `assignee_employee_id` | text FK→employee | **XOR** with `assignee_user_id` (hard invariant) |
| `assignee_user_id` | text | human ownership (not execution-backed) |
| `checkout_run_id` | text | ownership lock → **lives on dream's board**; mirrored here for queries |
| `execution_run_id` | text | liveness lock → which run is live now |
| `dod` | json | the typed Definition-of-Done verifier (spec 04) |
| `depth` | int | `0` = root (intake/horizon slot); `>0` = chorus decomposition |
| `origin_kind` | text | `manual\|routine_execution\|decomposition\|stranded_recovery\|stale_run_eval\|productivity_review` |
| `origin_id` | text | the entity that spawned this task |
| `origin_fingerprint` | text | default `'default'`; the exact-once key for self-spawned work |
| `request_depth` | int | delegation hop count (cap enforced) |
| `created_by_employee_id` / `created_by_user_id` | text | provenance |
| `started_at` / `completed_at` / `cancelled_at` | ts | set on entering those states |
| `created_at` / `updated_at` | ts | |

**Hard invariants** (from `execution-semantics.md` §2, §3):
1. **Single assignee**: `assignee_employee_id` XOR `assignee_user_id`. Never both.
2. **`in_progress` requires an assignee** and (for employee-owned) an execution-backed path — it must never become a silent dead state (§ liveness, spec 02).
3. **Every task traces to a goal** (`goal_id` resolved at create: explicit → project's goal → company default; children inherit parent's).
4. **The two locks are distinct**: `checkout_run_id` = *who owns the right to execute*; `execution_run_id` = *which run is live*. A run owns `checkout_run_id` only while non-terminal; finalization compare-and-clears (never clobbering a successor). Stale-lock clearing is **crash recovery, not retry**. A checkout `409` = a real live owner → the caller stops, never retries.

> **chorus note:** the locks are *enforced* on dream's coordination `board.sqlite` (`ClaimManager`,
> `checkout_run_id`/`execution_run_id`). The `task` columns are a denormalized mirror for the
> board UI and the scheduler's eligibility queries; the board is the source of truth *of now*.

**Indexes** (Paperclip's, kept): `(assignee_employee_id, status)`, `(parent_id)`, `(goal_id)`,
`(status)`, `(origin_kind, origin_id)`.

**The partial-unique-index crash-safety contracts** — transplanted verbatim from
`issues.ts`, adapted to chorus origin kinds. *One open self-spawned task per source:*

```sql
-- one open routine execution per (origin_id, fingerprint)
CREATE UNIQUE INDEX task_open_routine_uq ON task(origin_kind, origin_id, origin_fingerprint)
  WHERE origin_kind='routine_execution' AND origin_id IS NOT NULL
        AND execution_run_id IS NOT NULL
        AND status IN ('backlog','todo','in_progress','in_review','blocked');

-- one open stranded-recovery task per source
CREATE UNIQUE INDEX task_active_stranded_recovery_uq ON task(origin_kind, origin_id)
  WHERE origin_kind='stranded_recovery' AND origin_id IS NOT NULL
        AND status NOT IN ('done','cancelled');

-- one open stale-run evaluation per source run
CREATE UNIQUE INDEX task_active_stale_run_eval_uq ON task(origin_kind, origin_id)
  WHERE origin_kind='stale_run_eval' AND origin_id IS NOT NULL
        AND status NOT IN ('done','cancelled');

-- one open productivity review per source
CREATE UNIQUE INDEX task_active_productivity_review_uq ON task(origin_kind, origin_id)
  WHERE origin_kind='productivity_review' AND origin_id IS NOT NULL
        AND status NOT IN ('done','cancelled');
```

> These four indexes are why chorus never duplicates its own remediation/recurring work, even
> across crashes and concurrent ticks. The DB rejects the second insert; no coordination code
> needed. **Keep them. They are the contract.**

### `task_dependency` — the real DAG (≈ `issue_relations type=blocks`)

`parent_id` is *structure*; this is *dependency*.

| Column | Type | Meaning |
|---|---|---|
| `id` | text PK | |
| `task_id` | text FK→task | the dependent |
| `depends_on_id` | text FK→task | the blocker |
| `created_at` | ts | |

```sql
CREATE UNIQUE INDEX task_dependency_uq ON task_dependency(task_id, depends_on_id);
```

**Rules:** a task with unresolved dependencies gets **no queued run** (the scheduler withholds
it). "A waits for B" is this row, not a blocking call. When the *last* `depends_on` reaches
`done`, the scheduler fires a `deps_resolved` wake (spec 03). `cancelled` does **not** count as
resolved. No self-edges; cycles rejected.

### `decomposition_claim` — exact-once fan-out (≈ `issue_plan_decompositions`)

The manager-splits-work primitive. The single most important crash-safety object after the locks.

| Column | Type | Meaning |
|---|---|---|
| `id` | text PK | |
| `source_task_id` | text FK→task | the task being decomposed |
| `accepted_plan_revision_id` | text FK→artifact_revision | the authorized plan revision |
| `status` | text | `in_flight\|completed` |
| `request_fingerprint` | text | |
| `requested_children` | json | the intended child specs |
| `child_task_ids` | json | **the durable partial result** (accumulated one-per-tx) |
| `owner_run_id` | text | who holds the in-flight claim |
| `completed_at` | ts | |

```sql
-- THE canonical fingerprint: re-reading the same accepted plan can't authorize a 2nd child tree
CREATE UNIQUE INDEX decomp_source_revision_uq
  ON decomposition_claim(source_task_id, accepted_plan_revision_id);

CREATE INDEX decomp_active_owner_idx ON decomposition_claim(owner_run_id)
  WHERE status='in_flight';
```

**Contract** (`execution-semantics.md` §7, verbatim intent):
- The claim is **durable before fan-out starts**; partial progress (`child_task_ids`) is durable
  while underway; the completed child set is durable after.
- A run that creates 2 of 5 children and dies → the retry **resumes from the same fingerprint and
  reuses the 2 already-created ids**. It never restarts. A second run with a different child set
  hits the unique index → conflict.
- While `in_flight`, the source task **must expose a live path** for the same fingerprint (active
  run / queued continuation / monitor / recovery / explicit blocker) — never leave it where a
  second run can reinterpret the acceptance as fresh permission.

---

## Cluster B — Liveness: `recovery_action`, `monitor`

### `recovery_action` — liveness-as-visibility (≈ `issue_recovery_actions`)

The first-class "who owns making this unstuck." See spec 02 for the contract.

| Column | Type | Meaning |
|---|---|---|
| `id` | text PK | |
| `source_task_id` | text FK→task | |
| `recovery_task_id` | text FK→task | nullable; set only for issue-backed independent repair |
| `kind` | text | `missing_disposition\|stranded\|workspace\|stale_run_watchdog\|graph_liveness` |
| `status` | text | `active\|escalated\|resolved` |
| `owner_employee_id` / `owner_user_id` | text | who owns the next move |
| `previous_owner_employee_id` / `return_owner_employee_id` | text | handoff provenance |
| `cause` | text | |
| `fingerprint` | text | |
| `evidence` | json | bounded, redacted |
| `next_action` | text | |
| `wake_policy` / `monitor_policy` | json | how it moves forward |
| `attempt_count` / `max_attempts` | int | bounded |
| `timeout_at` / `last_attempt_at` / `resolved_at` | ts | |
| `outcome` / `resolution_note` | text | `restored\|delegated\|false_positive\|blocked\|escalated\|cancelled` |

```sql
-- at most one open recovery per source task
CREATE UNIQUE INDEX recovery_active_source_uq ON recovery_action(source_task_id)
  WHERE status IN ('active','escalated');
-- and at most one per (source, cause, fingerprint)
CREATE UNIQUE INDEX recovery_active_fingerprint_uq
  ON recovery_action(source_task_id, cause, fingerprint)
  WHERE status IN ('active','escalated');
```

### `monitor` — deferred self-wake (≈ `executionPolicy.monitor`)

One-shot, for a task waiting on an external system (CI, deploy, review service).

| Column | Type | Meaning |
|---|---|---|
| `id` | text PK | |
| `task_id` | text FK→task | |
| `employee_id` | text FK→employee | who gets woken |
| `next_check_at` | ts | when to fire |
| `notes` | text | non-secret "what to check" |
| `external_ref` | text | **secret-adjacent → redacted before persist, omitted from wakes** |
| `timeout_at` / `max_attempts` / `attempt_count` | | bounded |
| `recovery_policy` | text | `wake_owner\|create_recovery\|escalate` on exhaustion |

**Rules:** one-shot — on fire, clear it and queue a `monitor_due` wake; if still pending the
assignee must **re-arm** with a new `next_check_at`. Cleared when the task goes terminal or
human-owned. Re-arming an exhausted monitor is rejected. *Not* a recurring interval.

---

## Cluster C — Scheduling: `wake`, `routine`, `routine_trigger`, `routine_run`, `run`

### `wake` — the coalescing push inbox (≈ `agent_wakeup_requests`)

| Column | Type | Meaning |
|---|---|---|
| `id` | text PK | |
| `employee_id` | text FK→employee | |
| `reason` | text | `task_assigned\|deps_resolved\|children_done\|message\|cron_due\|monitor_due\|recovery\|manual` |
| `payload` | json | `{task_id?, note?, comment_id?, ...}` |
| `status` | text | `queued\|claimed\|done` |
| `coalesce_key` | text | dedup key; default `employee:reason:task` |
| `coalesced_count` | int | how many triggers folded in |
| `idempotency_key` | text | optional |
| `run_id` | text FK→run | set on claim |
| `created_at` / `claimed_at` / `finished_at` | ts | |

```sql
-- coalescing: at most one queued wake per key
CREATE UNIQUE INDEX wake_queued_key_uq ON wake(coalesce_key) WHERE status='queued';
CREATE INDEX wake_employee_status_idx ON wake(employee_id, status);
```

### `routine` / `routine_trigger` / `routine_run` — cron (≈ Paperclip routines)

`routine`: template + owner + policies.

| Column | Type | Meaning |
|---|---|---|
| `id` | text PK | |
| `employee_id` | text FK→employee | assignee |
| `goal_id` / `parent_task_id` | text | inheritance |
| `intent_template` | text | with `{date}`/`{datetime}` |
| `target` | text | `spawn_task\|next_beat` |
| `concurrency_policy` | text | `skip_if_active\|coalesce\|always` |
| `catch_up_policy` | text | `skip_missed\|backfill_one` |
| `status` | text | `active\|paused` |

`routine_trigger`: the schedule.

| Column | Type | Meaning |
|---|---|---|
| `id` | text PK | |
| `routine_id` | text FK→routine | |
| `kind` | text | `cron\|webhook\|manual` |
| `cron_expression` | text | 5-field |
| `timezone` | text | |
| `next_run_at` | ts | **the double-fire guard target** |
| `last_fired_at` | ts | |

`routine_run`: one firing → one task.

| Column | Type | Meaning |
|---|---|---|
| `id` | text PK | |
| `routine_id` / `trigger_id` | text | |
| `status` | text | `received\|dispatched\|coalesced\|suppressed\|completed\|failed` |
| `dispatch_fingerprint` | text | exact-once dispatch |
| `idempotency_key` | text | |
| `linked_task_id` | text FK→task | the spawned task |
| `coalesced_into_run_id` | text | |

```sql
CREATE INDEX routine_trigger_next_run_idx ON routine_trigger(next_run_at);
CREATE UNIQUE INDEX routine_run_idempotency_uq ON routine_run(idempotency_key)
  WHERE idempotency_key IS NOT NULL;
```

**Double-fire guard:** firing is a conditional `UPDATE routine_trigger SET next_run_at=<next>
WHERE id=? AND next_run_at=<old>` — optimistic concurrency, so two ticks can't fire the same edge.

### `run` — one beat (≈ `heartbeat_runs`, but THIN)

A run is one `dream.run_task` invocation. Paperclip's `heartbeat_runs` has ~50 columns (PID,
process group, stdout excerpts, `last_output_at`, output-silence bookkeeping) — **chorus drops
all of it.** We witness dream's event stream and the lease lives on the board.

| Column | Type | Meaning |
|---|---|---|
| `id` | text PK | |
| `employee_id` | text FK→employee | |
| `task_id` | text FK→task | |
| `wake_id` | text FK→wake | what triggered it |
| `status` | text | `queued\|running\|succeeded\|failed\|cancelled\|timed_out` |
| `lease_expires_at` | ts | crash-recovery clock (mirrors board) |
| `liveness_state` | text | from dream's evaluator: `advanced\|completed\|blocked\|plan_only\|empty\|needs_followup\|failed` |
| `outcome` | json | dream `RunTaskResult` summary (sprints, final ledger, pass/fail) |
| `usage` | json | tokens/cost from the event stream |
| `continuation_attempt` | int | bounded liveness continuations |
| `started_at` / `finished_at` | ts | |

```sql
CREATE INDEX run_employee_started_idx ON run(employee_id, started_at);
CREATE INDEX run_status_lease_idx ON run(status, lease_expires_at);  -- the recovery sweep
```

> Compare: Paperclip needs `processPid`, `processGroupId`, `lastOutputAt`, `lastOutputSeq`,
> `stdoutExcerpt`, `livenessState` reconstructed by regex. chorus needs `lease_expires_at` +
> `liveness_state` *from the evaluator*. The shrink is the whole dream-native thesis.

---

## Cluster D — Org & alignment: `employee`, `goal`

### `employee` — the Workforce (≈ `agents`)

| Column | Type | Meaning |
|---|---|---|
| `id` | text PK | |
| `name` | text | |
| `role` | text | maps to a dream `RoleManifest` (spec 04) |
| `reports_to` | text FK→employee | **the org chart = this adjacency list** |
| `memory_scope` | text | which memory partition this employee reads/writes |
| `status` | text | `idle\|active\|running\|paused\|error\|terminated` |
| `budget_monthly_cents` / `spent_monthly_cents` | int | |
| `paused_at` / `pause_reason` | | |
| `last_beat_at` | ts | |

**Invariants** (Paperclip's): same-company manager (moot — one workforce), **no cycles** in
`reports_to`, `terminated` is irreversible. There is **no `teams` table** — team structure is
emergent from `reports_to` + per-task assignment.

### `goal` — the alignment tree (≈ `goals`)

`id`, `title`, `level` (`company\|team\|employee\|task`), `status`, `parent_id` (self-FK),
`owner_employee_id`. ≥1 root `company` goal. Every task's `goal_id` resolves into this tree.

---

## Cluster E — Money: `budget_policy`, `budget_incident`, `cost_event`

Two-gate budgets (spec 04). `budget_policy`: `scope_type` (`company\|employee`), `scope_id`,
`amount`, `warn_percent` (default 80), `hard_stop_enabled` (default **true**), `window_kind`.

```sql
CREATE UNIQUE INDEX budget_policy_scope_uq
  ON budget_policy(scope_type, scope_id, metric, window_kind);
```

`budget_incident`: `policy_id`, `threshold_type` (`soft\|hard`), `amount_limit`, `amount_observed`,
`status`, `approval_id`.

```sql
CREATE UNIQUE INDEX budget_incident_window_uq
  ON budget_incident(policy_id, window_start, threshold_type) WHERE status <> 'dismissed';
```

`cost_event`: `employee_id`, `task_id`/`run_id`, `provider`, `model`, token counts, `cost_cents`,
`occurred_at`. Immutable. `spent_monthly_cents` is **recomputed live from cost_events on read,
never trusted** (Paperclip rule).

---

## Cluster F — Outcomes: `artifact`, `artifact_revision`

The Enforced-Outcomes surface (spec 04). `artifact`: `task_id`, `type` (`pr\|doc\|finding\|
artifact\|workspace_file`), `provider`, `external_id`, `url`, `review_state`, `health_status`,
`is_primary`, `resource_ref` (json). `artifact_revision`: immutable history — *the thing
decomposition is authorized against* (the `accepted_plan_revision_id` above).

---

## The data model in one breath

`company-goal → task (DAG via parent_id structure + task_dependency edges) → run (one
dream.run_task) → artifact`, owned by an `employee` (org = `reports_to`), scheduled by `wake`s
and `routine`s, kept honest by `recovery_action`/`monitor` (liveness) and `budget_*` (caps) —
**every self-spawned row made exact-once by a partial-unique index, every lock on dream's board,
every run thin because the evaluator and event stream replace the watchdog.**
