# 06 — Governance, budgets & security

The control plane owns the enforcement that makes an autonomous company *governable*:
budgets that hard-stop spend, approval gates on governed actions, an authorization
engine, scoped secrets, and fail-closed low-trust containment. This doc focuses on the
**code that actually blocks/pauses/denies**, not just the data.

Core files (all `server/src/services/` unless noted): `budgets.ts`, `costs.ts`,
`finance.ts`, `approvals.ts`, `issue-approvals.ts`, `authorization.ts`, `access.ts`,
`board-auth.ts`, `secrets.ts`, `trust-preset-resolver.ts`,
`low-trust-runtime-containment.ts`, `companies.ts`, `agents.ts`, `hire-hook.ts`,
`company-portability.ts`, `goals.ts`, `routines.ts`, `cron.ts`.

---

## 1. Budgets — the two-gate hard-stop (the most important enforcement)

Two tables drive it: **`budget_policies`** (limits) and **`budget_incidents`** (events).

**Policy model** (`budgets.ts`): `scopeType ∈ company|agent|project`, `metric` (`billed_cents`),
`windowKind` (`calendar_month_utc` default), `amount`, `warnPercent` (default 80),
`hardStopEnabled` (default **true**). `upsertPolicy` mirrors the amount onto
`companies.budgetMonthlyCents`/`agents.budgetMonthlyCents` and **immediately re-evaluates** (pauses
right then if already over).

**Spend attribution** (`costs.ts`): per agent **and** company **and** optionally project/issue.
`costService.createEvent` inserts the event, recomputes agent + company monthly spend, writes them
back, then calls `budgets.evaluateCostEvent(event)` — *the trigger point*. Spend is also rolled up
per issue subtree (recursive CTE), per provider/biller/model, and per rolling 5h/24h/7d window. (Note:
`companies.spentMonthlyCents` is **recomputed live from `cost_events`** on read, never trusted.)

### Gate 1 — reactive auto-pause (`budgets.ts:evaluateCostEvent`)
On each cost event, for every active relevant policy:
1. recompute observed via fresh SQL `sum(costCents)` over scope+window.
2. **soft** (`observed ≥ ceil(amount·warnPercent/100)`) → create a soft incident + log
   `budget.soft_threshold_crossed` (notification only, no approval row).
3. **hard** (`hardStopEnabled && observed ≥ amount`) → create a `hard` incident **paired with an
   `approvals` row of type `budget_override_required`**, then `pauseAndCancelScopeForBudget`:
   - `pauseScopeForBudget` sets `pauseReason:"budget"` + `pausedAt` on the scope (company →
     `status:"paused"`).
   - fires the `cancelWorkForScope` hook → `heartbeat.ts:cancelBudgetScopeWork`: cancels in-flight
     runs (`cancelRunInternal("Cancelled due to budget pause")`) + pending wakeups.
   - **So hard-stop both flips status AND kills in-flight runs.**

### Gate 2 — proactive pre-invocation block (`budgets.ts:getInvocationBlock`)
A **start-time gate** that prevents new work *before* any cost event fires. Checks, in order:
company paused / company over → agent paused-for-budget / agent over → project paused-for-budget /
project over, returning `{scopeType, scopeId, reason}` or `null`. **Called at ~10 run-start sites**
across `heartbeat.ts`, `plugin-host-services.ts`, `productivity-review.ts`, and `recovery/service.ts`
(e.g. the scheduled-retry gate returns `allowed:false, errorCode:"budget_blocked"`). **No agent can
be invoked while a budget hard-stop is active for it, its project, or its company.**

> **chorus lesson:** caps need *both* a reactive auto-pause+kill and a proactive block threaded at
> *every* spawn site — not just a post-hoc check.

**Resolution is human-only** (`resolveIncident`): `raise_budget_and_resume` (must set
amount > current observed) → bump policy, clear `pauseReason:"budget"`, resolve incident, mark linked
approval `approved`. Or dismiss → mark approval `rejected`, scope stays paused.

`finance.ts` is a separate, broader ledger (debit/credit, billers, estimated charges) for
accounting/reporting — **not** an enforcement gate.

---

## 2. Approvals & governance

`approvals` is the **first-class governed-action queue** (`approvals.ts`): `type`, `requestedBy*`,
`status` (pending / approved / rejected / revision_requested), `payload`, `decidedByUserId`.

- **Reviewer routing & change requests are state-machine transitions** (`resolveApproval`): only
  `pending`/`revision_requested` can be approved/rejected; `requestRevision` sends it back with a
  note; `resubmit` flips revision → pending with an updated payload. Idempotent re-approval.
- **Governance actions ARE org mutations.** `approve` of a `hire_agent` approval either activates the
  `pending_approval` agent or creates the agent from payload, **upserts an agent budget policy** if
  `budgetMonthlyCents>0`, and fires `notifyHireApproved` (the hire-hook). `reject` of a `hire_agent`
  **terminates** the pending agent. Budget overrides are also approvals
  (`budget_override_required`), resolved via §1.
- **Approval-as-workflow-step on issues** (`issue-approvals.ts`): `issue_approvals` links an approval
  to an issue, making it a gate attached to a work item (same-company enforced).
- **The hire-hook** (`hire-hook.ts`): `notifyHireApproved` looks up the agent's adapter and, if it
  implements `onHireApproved`, calls it with a canned "you were hired, expect task assignment"
  message. Failures are non-fatal (logged to `activity_log`). This is how an external runtime
  (e.g. OpenClaw) gets woken on hire.

**What requires approval:** new agents (when `companies.requireBoardApprovalForNewAgents`) →
`pending_approval` + a `hire_agent` approval; budget overrides → `budget_override_required`;
protected-agent assignment (policy-marked) → denied until an explicit grant exists.

---

## 3. Authorization engine

`authorization.ts:authorizationService.decide` is the central allow/deny. **Principals = `user` and
`agent`** (unified), each an active `company_memberships` row + zero-or-more
`principal_permission_grants` (`permissionKey` + optional JSON `scope`), plus a global
`instance_user_roles` (`instance_admin`).

Key rules:
- actor `none` → `deny_unauthenticated`.
- **local board** (`source:"local_implicit"`) → always allow (the single-user `local_trusted` mode).
- **instance admin** → allow, *except* `cloud_tenant` actors are never elevated even with stale admin
  rows (explicit hardening).
- **same-company agent** → standard read visibility; **cross-company is hard-denied**
  (`deny_company_boundary`).
- **grant decision** (`decidePrincipalGrant`): active membership → matching grant → `scopeAllows`
  checks the requested scope against grant scope (project ids, target-agent ids, **manager-subtree**
  via `agentIsInSubtree`). `tasks:assign_scope` requires structured scope.
- **task assignment** has a "simple mode" company-wide default (non-viewer member may assign) unless
  an authorization policy restricts it (`protectedAgent.requiresApproval` → `requires_approval`;
  `private`/`protected` → needs an explicit grant). Unknown policy data **fails closed**.
- self-permissions (agent mutates its own assigned issue / wakes itself / updates its own config);
  manager-chain (`tasks:manage_active_checkouts` if the actor manages the assignee in the subtree);
  legacy CEO role grants `agents:create`.

`access.ts` manages this data (`setPrincipalGrants`, `ensureMembership`, role-default grants from
`company-member-roles.ts`, invite grants always giving agents `tasks:assign`) and guards
last-active-owner removal with a `FOR UPDATE` lock (reassigning the archived member's open issues).
`board-auth.ts` is the authenticated-mode session/key layer (`board_api_keys` hashed + 30-day TTL,
CLI auth challenge/approve flow).

---

## 4. Secrets — storage, scoping, injection

`company_secrets` (provider-backed, versioned) + `company_secret_versions` (immutable, enabling
rotation) + `company_secret_bindings` (binds a secret to a consumer target's `configPath`, e.g.
`env.FOO`) + `secret_access_events` (every resolve audited). **Everything is company-scoped** —
`resolveSecretValueInternal` refuses cross-company.

- **Binding requirement** (`assertBindingContext`): resolution requires a `configPath` **and** a
  matching binding row for that consumer; otherwise `binding_missing`. *This is the scoping
  enforcement — a secret resolves only where it's explicitly bound.*
- **Injection into runs**: agent/project/routine env stores `secret_ref` bindings. At run start
  `resolveExecutionRunAdapterConfig` resolves adapter + project + routine env through the secret
  service, producing a resolved env injected into the agent process. Resolved values are recorded as
  access events but **never logged/persisted in plaintext** and never placed in revisions unsanitized.
- **Low-trust secret restriction**: a low-trust run passes `allowedBindingIds`; `assertBindingContext`
  rejects any binding not in that allow-list (`binding_not_allowed`), and `assertLowTrustEnvConfigAllowed`
  **rejects inline sensitive env values** (`low_trust_inline_sensitive_env_denied`) — low-trust agents
  must use approved refs, never raw keys.
- **Plugins** resolve secrets only with `secrets.read-ref` (rate-limited, refs must be UUIDs,
  currently fail-closed until company-scoped plugin config lands).

---

## 5. Low-trust presets (the hostile-input security envelope)

Two core presets: `standard` (company-visible default) and `low_trust_review` (containment for
hostile/prompt-injected input). The preset is **resolved by intersecting four policy sources** —
agent `permissions.authorizationPolicy.trustBoundary`, project `executionWorkspacePolicy`, issue
`executionPolicy`, run policy (`trust-preset-resolver.ts:resolveCoreTrustPreset`). **Narrower wins;
conflicts / cross-company / unsupported preset → `denied` (fail closed)**; a low-trust preset with no
concrete scope → `missing_low_trust_boundary_scope` deny.

`authorization.ts:decideLowTrustAccess`: low-trust agents are denied company-wide reads,
`runtime.manage`, and `secrets.read` by default, and confined to issues/projects/agents inside the
boundary (recursive ancestry check, depth-capped at 12). Runtime containment
(`low-trust-runtime-containment.ts`) fails closed unless env driver = `sandbox`, workspace mode =
`isolated_workspace`, the issue is in-boundary, and (for runtime-service mutations) the boundary
grants `runtime.manage`.

> **chorus lesson:** dream already has a tier/trust-ramp; the transplantable pattern is
> *narrower-wins intersection across the layered policy sources, deny on conflict, fail closed.*

---

## 6. Goals & alignment

`goals` is a 4-level self-referential tree (`level` company/team/agent/task, `parentId`). The
mission = `getDefaultCompanyGoal` (active root `company` goal). **Every issue gets a `goalId`
resolved at create time** (`issue-goal-fallback.ts:resolveIssueGoalId`): explicit → project's goal →
company default; children inherit `parent.goalId`. So the alignment chain is **company goal → project
goal → issue goal**, and the parent/sub-issue tree is the "because → because" chain. Alignment is
realized *structurally* (the goal FK + parent tree), not via a generated prose "mission narrative."

---

## 7. Routines (recurring/scheduled work → issues)

A `routines` row (templated title/description with `variables`, `env`, `assigneeAgent`,
`concurrencyPolicy` = `skip_if_active`/`coalesce`/`always_enqueue`, `catchUpPolicy`) + `routine_triggers`
(cron/webhook/manual). `cron.ts` is a self-contained 5-field parser + `nextCronTick` calculator.
Firing (`tickScheduledTriggers`, from the same `setInterval` as heartbeat):
1. **atomically claims** the tick via conditional `UPDATE ... WHERE nextRunAt = <old>` advancing to
   the next tick (optimistic-concurrency guard against double-fire across ticks/instances),
2. if the project is paused → record a *suppressed* run (no backfill),
3. else dispatch (`dispatchRoutineRun`, under a `routines FOR UPDATE` lock): idempotency keys,
   variable interpolation, `concurrencyPolicy` (skip/coalesce if a live execution issue exists), then
   `issueSvc.create` makes a `todo` issue with `originKind:"routine_execution"` assigned to the
   routine's agent. `syncRunStatusForIssue` finalizes the `routine_run` when the issue terminates.

---

## 8. Company portability — what makes a company reusable

`company-portability.ts` + `company-export-readme.ts`. **Export** serializes a company into a portable
markdown package + `CompanyPortabilityManifest`: `agents/<slug>/<entry>.md` (with `reportsTo` *slug*),
`PROJECT.md`, issues, skills, plus a generated `README.md` with a **Mermaid org chart**.

The **reusability mechanism = slug-based identity + portability filtering + env-input externalization**:
- IDs become slugs; `reportsTo` becomes `reportsToSlug` so the org survives re-import into a fresh company.
- Config values pruned to defaults; **system-dependent values stripped** (absolute commands, non-portable
  `repoUrl`s, absolute paths classified `system_dependent` and omitted with warnings). Only `portable`
  values ship.
- **Secrets never leave**: env values are extracted into declared `envInputs` (which keys are needed,
  required/optional, plain vs secret — *not the values*). On **import**, operator-supplied values
  re-materialize real `company_secrets` and bindings are rewritten to fresh `secret_ref`s. Forbidden
  adapters are blocked in `agent_safe` import mode; instruction/prompt-template fields are stripped.

This is the `companies.sh` / "Agent Company package" path — a company becomes a git-importable template.

> **chorus lesson:** this is exactly the "portable git-markdown org" bet, with the hard parts solved —
> slug identity that survives re-import, portability filtering, and secret externalization.

---

## Cross-cutting enforcement summary

| Gate | Code | Blocks |
|---|---|---|
| Budget hard-stop (reactive) | `budgets.ts:evaluateCostEvent` → `pauseAndCancelScopeForBudget` → `heartbeat.ts:cancelBudgetScopeWork` | On cost ≥ limit: pause scope + cancel in-flight runs/wakes |
| Budget pre-invocation (proactive) | `budgets.ts:getInvocationBlock` (~10 sites) | Starting any run while scope is budget-paused/over |
| Authorization | `authorization.ts:decide` | Cross-company, missing membership/grant, out-of-scope, restrictive assignment policy, low-trust boundary |
| Approval gate | `approvals.ts` + `issue-approvals.ts` | Hiring, budget overrides, protected-agent assignment |
| Secret binding/scope | `secrets.ts:assertBindingContext` | Cross-company secret, unbound configPath, low-trust binding not allow-listed, inline sensitive env |
| Low-trust containment | `low-trust-runtime-containment.ts` | Non-sandbox driver, non-isolated workspace, out-of-boundary issue — fails closed |
| Archive cascade | `companies.ts:applyArchiveCascadeInTx` | Pauses agents, cancels runs/wakes company-wide |
| Routine double-fire | `routines.ts` conditional-update claim | Duplicate dispatch across ticks/instances |
