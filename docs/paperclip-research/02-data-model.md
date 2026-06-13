# 02 — Data model

PostgreSQL + Drizzle ORM, ~90 tables, **all multi-tenant by `company_id`**. The schema
is an **org-as-data + task-DAG-as-data + runtime-as-data** model: nothing about the
company structure, the work graph, or the agent execution loop lives in code state — it
is all persisted rows, so any worker can resume any task by reading the ledger.

> **Unifying principle:** state lives in *rows + partial unique indexes*, not in process
> memory. Locks, holds, claims, leases, decisions, wakes, and recovery owners are all
> persisted, so any worker can crash and another resumes by reading the ledger — and
> idempotency is enforced by Postgres unique constraints rather than coordination code.

Schema files: `packages/db/src/schema/*.ts`. Narrative: `doc/SPEC-implementation.md` §7.

---

## Cluster 1 — Company / org-as-data

| Table | Purpose | Key columns | Invariant |
|---|---|---|---|
| **companies** | Root tenant. | `status` (active/paused/archived), `pauseReason`, `issuePrefix` (unique) + `issueCounter` (per-company monotonic issue numbering), `budgetMonthlyCents`/`spentMonthlyCents`, `requireBoardApprovalForNewAgents`. | Every business row FKs to `companies.id`. Pausing the company gates all execution. |
| **agents** | An employee. | **`reportsTo` → agents.id (self-FK = the manager edge)**; `role`, `title`, `status` (idle/active/running/paused/error/pending_approval/terminated); `adapterType` + `adapterConfig` (how it runs); `runtimeConfig`; `defaultEnvironmentId`; `budgetMonthlyCents`; `permissions` jsonb; `lastHeartbeatAt`. | **Org chart = the `reportsTo` adjacency list.** Same-company manager, no cycles, terminated is irreversible. Indexed `(companyId, reportsTo)` for "direct reports." |
| **company_memberships** | Principal ↔ company roster. | `principalType`/`principalId` (polymorphic: **user or agent**), `membershipRole`, `status`. | Humans and agents are unified as "principals." |
| **goals** | Hierarchical objectives. | **`parentId` → goals.id (self-FK = goal tree)**; `level` (company/team/agent/task), `status`, `ownerAgentId`. | A *separate* tree from the issue tree; ≥1 root `company` goal per company. |
| **projects** | A workstream. | `goalId`, `leadAgentId`, `status`, `env` (secret-aware), `executionWorkspacePolicy`. | Container for issues + workspaces. |
| **project_goals** | M:N project↔goal. | composite PK. | |
| **agent_memberships / project_memberships** | Per-*user* sidebar join state. | `(company,user,target)`, `state` (joined/left). | Sidebar visibility *only*; missing row = joined. NOT an org edge or an ACL. |

**There is no `teams` table.** Team structure is emergent — encoded by `agents.reportsTo`
(the manager tree) plus `projects.leadAgentId` and per-issue assignment.

---

## Cluster 2 — Task ledger / DAG (the heart)

The work DAG, decomposition, "parent waits for children," single-assignee
checkout/locks, and recovery are **all durable rows + partial unique indexes**, never
blocking calls or in-memory state.

### Core table: `issues`
`parentId → issues.id` (self-FK). Identity: `issueNumber` + `identifier` (e.g. `PAP-42`).
Status: `backlog | todo | in_progress | in_review | blocked | done | cancelled`.

- **Single assignee** — `assigneeAgentId` **XOR** `assigneeUserId` (hard invariant). An
  agent-owned `in_progress` is execution-backed; a user-owned one is just human ownership.
- **Two distinct locks** (the atomic-checkout mechanism):
  - `checkoutRunId → heartbeat_runs.id` — **ownership lock** (who owns the right to
    execute this issue; required to enter agent-owned `in_progress`).
  - `executionRunId → heartbeat_runs.id` — **liveness lock** (which run is actually live).
  - plus `executionAgentNameKey`, `executionLockedAt`, `executionPolicy`, `executionState` jsonb.
  - Lock contract: a run owns `checkoutRunId` only while non-terminal; on
    `succeeded/failed/cancelled/timed_out` finalization **compare-and-clears** lock columns
    still pointing at that run (never clobbering a successor's reacquired lock). Stale-lock
    recovery is crash recovery, not retry. A checkout conflict = HTTP 409 = real live owner.
- **Self-wake / monitor columns** make idleness a *scheduled row*, not a thread:
  `monitorNextCheckAt`, `monitorWakeRequestedAt`, `monitorAttemptCount`, `monitorScheduledBy`.
- **Origin / idempotency**: `originKind` + `originId` + `originFingerprint` + `requestDepth`,
  plus **partial unique indexes** that make control-plane-spawned issues exact-once — e.g.
  `issues_open_routine_execution_uq`, `issues_active_liveness_recovery_incident_uq`,
  `issues_active_stale_run_evaluation_uq`, `issues_active_productivity_review_uq`,
  `issues_active_stranded_issue_recovery_uq` (one open recovery/eval issue per
  `(company, originKind, originId)`). This is how the system avoids duplicate self-spawned
  remediation work.

### Two *different* relationships (structure vs dependency)
Deliberately split (see [03](03-task-lifecycle-orchestration.md) and execution-semantics §6):
- **`parentId`** (on `issues`) = **structural** work breakdown. Used for rollup and for
  "wake the parent when all direct children become terminal." **Explicitly NOT a dependency.**
- **`issue_relations`** = **dependency edges**. `(issueId, relatedIssueId, type="blocks")`,
  unique per tuple. This is the real blocker DAG. A blocked issue gets **no queued run** until
  the last blocker is `done`, at which point an `issue_blockers_resolved` wake starts work.
  *"A waits for B" is a row, not a blocking call.*

### Decomposition (manager splits a task into children)
**`issue_plan_decompositions`** — the **exact-once decomposition claim**.
- `sourceIssueId`, `acceptedPlanRevisionId → document_revisions.id` (the accepted "plan"
  doc revision being authorized), `ownerAgentId`/`ownerRunId`.
- `status` (`in_flight`/`completed`), `requestFingerprint`, `requestedChildren` jsonb,
  **`childIssueIds` jsonb** (the durable *partial* result).
- **Unique `(company, sourceIssueId, acceptedPlanRevisionId)`** = the canonical fingerprint.
  Re-accepting/re-reading the same plan revision cannot authorize a second child tree. If a
  run dies mid-fan-out, retries resume from `childIssueIds` instead of recreating siblings.
  **A durable claim + durable partial result, replacing thread reconstruction.**

### "Parent waits for children" as data — tree holds
The literal answer to "how is blocking represented as data":
- **`issue_tree_holds`** — a hold on a subtree root: `rootIssueId`, `mode`, `status`
  (`active`/released), `reason`, `releasePolicy`, full actor provenance for place + release.
- **`issue_tree_hold_members`** — the materialized frontier the hold waits on: `holdId`,
  `issueId`, `parentIssueId`, `depth`, denormalized `issueStatus`/`assigneeAgentId`,
  `activeRunId`/`activeRunStatus`, `skipped`/`skipReason`. The parent "waits" by having an
  active hold whose members aren't yet terminal; releasing the hold emits the wake. **No
  thread blocks — a sweeper reads these rows.**

### Recovery as data
**`issue_recovery_actions`** — first-class "who owns making this unstuck": `sourceIssueId`,
`recoveryIssueId`, `kind`, `cause`, `fingerprint`, `status` (`active`/`escalated`/resolved),
`nextAction`, `evidence`, `wakePolicy`/`monitorPolicy`, `attemptCount`/`maxAttempts`/`timeoutAt`,
ownership handoff fields, `outcome`/`resolutionNote`. **Partial unique indexes** enforce at most
one open recovery per `(company, sourceIssueId)` and per `(company, source, cause, fingerprint)`.

### Supporting tables
`issue_execution_decisions` (append-only per-stage gate outcomes), `issue_approvals` (M:N to
governance approvals), `issue_work_products` (PRs/deploys/docs the task produced — `type`,
`provider`, `externalId`, `url`, `reviewState`, `healthStatus`, `isPrimary`), `issue_comments`
(thread; `authorType` agent/user/system; a top-level user comment can wake the assignee),
`issue_thread_interactions` (structured request/response cards — `suggest_tasks`,
`ask_user_questions`, `request_confirmation` — with `continuationPolicy`/`idempotencyKey`),
`labels`/`issue_labels`, `issue_relations`, `issue_reference_mentions`, `issue_attachments`,
`issue_documents`, `issue_read_states`/`issue_inbox_archives`/`inbox_dismissals`,
`feedback_votes`/`feedback_exports`.

---

## Cluster 3 — Agent runtime / execution

A "heartbeat run" is one invocation of an agent process; the unit every lock points at.

| Table | Purpose | Notable columns |
|---|---|---|
| **heartbeat_runs** | One agent execution. | `status` (queued/running/succeeded/failed/cancelled/timed_out); `invocationSource`; process liveness: `processPid`,`processGroupId`,`processStartedAt`,**`lastOutputAt`**,`lastOutputSeq`,`lastOutputBytes`; retry: `retryOfRunId`,`processLossRetryCount`,`scheduledRetryAt`; liveness: `livenessState`,`livenessReason`,`continuationAttempt`,**`lastUsefulActionAt`**,`nextAction`,`contextSnapshot`; log pointers; `usageJson`/`resultJson`; `sessionIdBefore/After`. Indexed `(company,liveness,created)` + `(company,status,lastOutput)` so the watchdog sweeper finds stuck runs cheaply. |
| **heartbeat_run_events** | Append-only stdout/event stream per run. | `runId`,`seq`,`eventType`,`stream`,`level`,`message`,`payload` — the run transcript, ordered by `(runId, seq)`. |
| **heartbeat_run_watchdog_decisions** | Watchdog verdicts. | `runId`,`decision`,`snoozedUntil`,`reason`,`evaluationIssueId`. |
| **agent_runtime_state** | Per-agent singleton cursor (PK=`agentId`). | `sessionId`, running token/cost totals, `lastRunId`/`lastRunStatus`, `lastError`. The resumable session pointer. |
| **agent_task_sessions** | Adapter session reuse per task. | unique `(company,agent,adapterType,taskKey)`. |
| **agent_wakeup_requests** | The **async scheduler inbox**. | `agentId`,`source`,`reason`,`payload`; `status` (queued/claimed/finished); **`coalescedCount`**, `idempotencyKey`, `runId`. Wakes coalesce; claiming a wake spawns a heartbeat_run. This is how "blocked → resolved → run" happens with no thread waiting. |
| **agent_config_revisions** | Versioned config history + rollback. | `before/afterConfig`, `changedKeys`, `rolledBackFromRevisionId`. |

**Environments & workspaces (where runs execute):** `environments` (driver: local/ssh/sandbox),
`environment_leases` (acquire→use→release/expire→cleanup; decouples scarce env capacity from
runs), `project_workspaces` (persistent repo/dir per project), `execution_workspaces` (per-task
ephemeral branch/worktree; `mode` + `strategyType`), `workspace_operations` (per-command audit),
`workspace_runtime_services` (long-lived dev servers with reuse + health + stop policy).

---

## Cluster 4 — Money / governance

| Table | Purpose | Notable columns |
|---|---|---|
| **budget_policies** | A spend limit. | `scopeType`/`scopeId` (company/agent/project), `metric` (billed_cents), `windowKind`, `amount`, `warnPercent`, **`hardStopEnabled`** (default true). |
| **budget_incidents** | A threshold breach. | `policyId`, `thresholdType`, `amountLimit`/`amountObserved`, `status` (open/...), `approvalId` (link to override approval). Partial-unique per `(policy,windowStart,threshold)`. |
| **cost_events** | Raw LLM usage. | `agentId`,`issueId`/`projectId`/`goalId`/`heartbeatRunId`,`provider`,`model`, token counts, **`costCents`**, `occurredAt`. Immutable; rolled up into `agents.spentMonthlyCents`. |
| **finance_events** | Generalized billing ledger. | `eventKind`, `direction` (debit/credit), `biller`, `amountCents`. Reporting, not enforcement. |
| **approvals** | Human-in-the-loop gate. | `type` (hire_agent / approve_ceo_strategy / budget_override_required / request_board_approval), `status`, `payload`, `decidedByUserId`. |
| **approval_comments** | Discussion on an approval. | |
| **activity_log** | Universal audit trail. | `actorType`/`actorId`, `action`, **`entityType`/`entityId`** (polymorphic), `agentId`, `runId`, `details`. Append-only. |
| **principal_permission_grants** | Authorization grants. | `principalType`/`principalId`, **`permissionKey`**, `scope` jsonb. |

---

## Cluster 5 — Skills / plugins / secrets / documents / assets / routines

- **Skills**: `company_skills` (versioned markdown capability; `trustLevel`, `sharingScope`,
  `publicShareToken`, fork lineage) + `company_skill_versions`/`_stars`/`_comments`.
- **Plugins**: `plugins` (one per installed plugin), `plugin_config`, `plugin_company_settings`,
  `plugin_state` (scoped K/V; scopes instance/company/project/agent/issue/goal/run),
  `plugin_entities` (external-ID mappings), `plugin_jobs`/`plugin_job_runs`,
  `plugin_webhook_deliveries`, `plugin_database_namespaces`/`plugin_migrations` (host-owned
  per-plugin DB schema), `plugin_managed_resources`, `plugin_logs`.
- **Secrets**: `company_secrets` (provider-abstracted, versioned), `company_secret_versions`
  (immutable, enabling rotation), `company_secret_bindings` (binds a secret into a target's
  `configPath`, e.g. `env.FOO`), `company_secret_provider_configs`, `secret_access_events`
  (every resolve audited).
- **Documents**: `documents` (latest snapshot + edit lock), `document_revisions` (immutable
  history — *the artifact decomposition is authorized against*), `document_annotation_threads`/
  `_comments`/`_anchor_snapshots` (inline comments that re-anchor across revisions).
- **Assets**: content-addressed blob metadata (`provider`, `objectKey`, `sha256`).
- **Routines**: `routines` (templated recurring work; `concurrencyPolicy`, `catchUpPolicy`),
  `routine_revisions` (snapshotted env per revision), `routine_triggers` (cron/webhook),
  `routine_runs` (a fired routine creates an issue with `originKind='routine_execution'`).

---

## The data model in a nutshell

1. **`companies`** is the tenant root; the whole DB is a set of isolated companies.
2. **`agents`** are the employees; the **org chart is `agents.reportsTo`** (a self-referential
   manager tree). No `teams` table. Humans + agents unified as principals.
3. **`issues`** are the universal unit of work. The DAG is **two graphs** — `parentId`
   (structural) and `issue_relations type=blocks` (dependency). Decomposition, blocking, and
   recovery are durable rows: `issue_plan_decompositions` (exact-once fan-out),
   `issue_tree_holds`+`_members` ("parent waits" as a materialized frontier),
   `issue_recovery_actions` (one open remediation per source). Single-assignee + two locks
   (ownership/liveness) make execution rights a CAS-on-a-column, not a mutex.
4. **`heartbeat_runs`** are the execution unit every lock points at; liveness/stuck detection
   is `lastUsefulActionAt`/`livenessState` columns swept by watchdog decisions, and async
   progress is `agent_wakeup_requests` (a coalescing queue) rather than blocking calls.
5. **`cost_events`/`finance_events`** meter spend against scoped **`budget_policies`** →
   **`budget_incidents`** → **`approvals`**, with **`activity_log`** as the universal audit.
6. A capability/asset layer hangs off the company: skills, sandboxed plugins, provider-abstracted
   secrets, revisioned documents, content-addressed assets, and routines that fire on schedule to
   spawn issues — closing the loop back to the task ledger.
