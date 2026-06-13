# 11 — Doc → code map

Every research doc, mapped to the **specific Paperclip code files** it is grounded in.
All paths below were verified to exist in the `paperclipai/paperclip` clone read for this
study (paths relative to repo root). Use this as the jump table from a claim to its source.

> Verification: 46 explicitly-cited paths + 18 service files + all bare-name references were
> checked against the repo — 100% resolve. (The design docs under `doc/` are the prose
> spec; the `server/`, `ui/`, `packages/`, `cli/` files are the implementation.)

---

## 00 — README (synthesis)
The one-process control-plane + opaque-byte-stream thesis is grounded in the same files as
docs 01/04/05 below — no unique citations.

## 01 — System overview
| Claim | File |
|---|---|
| Product/goal framing, two-layer model | `doc/GOAL.md`, `doc/PRODUCT.md` |
| "Scheduler in-process, no queue in V1" | `doc/SPEC-implementation.md` §6.3 |
| Boot sequence / one-process startup | `server/src/index.ts` (`startServer`) |
| OTel no-op instrumentation | `server/src/instrumentation.ts` |
| Express app + middleware pipeline | `server/src/app.ts` |
| WebSocket mount on `upgrade` | `server/src/realtime/live-events-ws.ts` |
| In-process event bus keyed by company | `server/src/services/live-events.ts` |
| The orchestration engine (~11k lines) | `server/src/services/heartbeat.ts` |
| Issue state machine + checkout | `server/src/services/issues.ts` |
| Recovery/liveness | `server/src/services/recovery/service.ts` |
| Object storage abstraction | `server/src/storage/service.ts` |
| Contract spine | `packages/shared/src/{constants.ts,api.ts,types/}` |

## 02 — Data model
| Claim | File |
|---|---|
| ~90 tables, one file per table | `packages/db/src/schema/*.ts` (**86 schema files**) |
| Narrative of the schema | `doc/SPEC-implementation.md` §7 |
| `issues`, two locks, origin/idempotency | `packages/db/src/schema/issues.ts` (+ `issue_relations.ts`, `issue_plan_decompositions.ts`, `issue_tree_holds.ts`, `issue_recovery_actions.ts`) |
| `heartbeat_runs`, run events, wakeups | `…/schema/{heartbeat_runs.ts, heartbeat_run_events.ts, agent_wakeup_requests.ts, agent_runtime_state.ts}` |
| budgets / costs / approvals / audit | `…/schema/{budget_policies.ts, budget_incidents.ts, cost_events.ts, finance_events.ts, approvals.ts, activity_log.ts}` |
| secrets cluster | `…/schema/{company_secrets.ts, company_secret_versions.ts, company_secret_bindings.ts, company_secret_provider_configs.ts}` |
| DB clients | `packages/db/src/client.ts` |

## 03 — Task lifecycle & orchestration
| Claim | File |
|---|---|
| Authoritative semantics | `doc/execution-semantics.md` |
| Run engine: enqueue/claim/execute | `server/src/services/heartbeat.ts` (`enqueueWakeup`, `claimQueuedRun`, `executeRun`) |
| Issue transitions + atomic checkout | `server/src/services/issues.ts` (`create`, `checkout`, `decomposeAcceptedPlan`, `clear*RunIfTerminal`, `adopt*CheckoutRun`) |
| Assignment wake | `server/src/services/issue-assignment-wakeup.ts` (`queueIssueAssignmentWakeup`) |
| HTTP status transitions + child-done wakes | `server/src/routes/issues.ts` (`getWakeableParentAfterChildCompletion`, `listWakeableBlockedDependents`) |
| Subtree pause/resume holds | `server/src/routes/issue-tree-control.ts` |
| In-process per-agent start mutex | `server/src/services/agent-start-lock.ts` (`withAgentStartLock`) |
| Assignability / invokability gates | `server/src/services/agent-assignability.ts`, `agent-invokability.ts` |
| Valid-disposition (definition-of-done) | `server/src/services/recovery/successful-run-handoff.ts` (`decideSuccessfulRunHandoff`) |
| Periodic recovery loop wiring | `server/src/index.ts` |

## 04 — Execution & adapters
| Claim | File |
|---|---|
| The adapter contract | `packages/adapter-utils/src/types.ts` (`ServerAdapterModule:352`, `AdapterExecutionContext:122`, `AdapterExecutionResult:69`) |
| Invocation / `onLog` streaming / cancel | `server/src/services/heartbeat.ts` (`adapter.execute` ≈9001, `onLog` ≈8822, `cancelRunInternal` ≈11025) |
| Child-process plumbing | `packages/adapter-utils/src/server-utils.ts` (`runChildProcess`) |
| Adapter registry (`adaptersByType`) | `server/src/adapters/registry.ts` (`registerBuiltInAdapters`) |
| External/BYO adapter loading | `server/src/adapters/plugin-loader.ts` (`buildExternalAdapters`) |
| Canonical local adapter | `packages/adapters/claude-local/src/server/execute.ts` |
| Gateway (phone-home) adapter | `packages/adapters/openclaw-gateway/src/server/execute.ts` |
| Generic `http` transport adapter | `server/src/adapters/http/execute.ts` |
| Post-hoc liveness classification | `server/src/services/run-liveness.ts` (`classifyRunLiveness`) |
| Env / workspace / containment | `server/src/services/environment-run-orchestrator.ts`, `environments.ts`*, `execution-workspaces.ts`*, `local-service-supervisor.ts`, `low-trust-runtime-containment.ts` |

`*` env/workspace mutation logic is in `server/src/services/` orchestrator + the routes `server/src/routes/{environments.ts,execution-workspaces.ts}`.

## 05 — Liveness & recovery
| Claim | File |
|---|---|
| Authoritative model | `doc/execution-semantics.md` (§§1,9–13) |
| Recovery dir (all mechanisms) | `server/src/services/recovery/*` |
| Stranded work, silent-run scan, sweeps | `server/src/services/recovery/service.ts` (`reconcileStrandedAssignedIssues`, `scanSilentActiveRuns`, `buildRunOutputSilence`, `sweepStaleIssueLocks`, `recordWatchdogDecision`) |
| Post-success usefulness classifier | `server/src/services/run-liveness.ts` |
| Bounded auto-continuation | `server/src/services/recovery/run-liveness-continuations.ts` |
| Dependency-graph liveness (pure fn) | `server/src/services/recovery/issue-graph-liveness.ts` (`classifyIssueGraphLiveness`, `ownerCandidatesForRecoveryIssue`) |
| Cheap-model recovery lane | `server/src/services/recovery/model-profile-hint.ts` |
| Startup/periodic sequence | `server/src/index.ts` |

## 06 — Governance, budgets & security
| Claim | File (`server/src/services/` unless noted) |
|---|---|
| Two-gate budgets | `budgets.ts` (`evaluateCostEvent`, `getInvocationBlock`, `pauseAndCancelScopeForBudget`, `resolveIncident`) |
| Hard-stop kills in-flight runs | `heartbeat.ts` (`cancelBudgetScopeWork`) |
| Spend attribution | `costs.ts`; reporting ledger `finance.ts` |
| Approvals state machine | `approvals.ts` (`resolveApproval`); issue link `issue-approvals.ts` |
| Hire hook (wake external runtime) | `hire-hook.ts` (`notifyHireApproved`) |
| Authorization engine | `authorization.ts` (`decide`, `decidePrincipalGrant`, `decideLowTrustAccess`); data `access.ts`, roles `company-member-roles.ts`; session/key layer `board-auth.ts` (CLI `cli/src/client/board-auth.ts`) |
| Secrets | `secrets.ts` (`resolveSecretValueInternal`, `assertBindingContext`, `resolveExecutionRunAdapterConfig`) |
| Trust presets (narrower-wins intersect) | `trust-preset-resolver.ts` (`resolveCoreTrustPreset`); validator `packages/shared/src/trust-policy.ts` |
| Low-trust containment (fail closed) | `low-trust-runtime-containment.ts` (`assertLowTrustWorkspaceIsolation`) |
| Archive cascade | `companies.ts` (`applyArchiveCascadeInTx`); agents `agents.ts` |
| Goals & alignment | `goals.ts`; issue-goal fallback `issue-goal-fallback.ts` |
| Routines (schedule → issue) | `routines.ts` (`tickScheduledTriggers`, `dispatchRoutineRun`); cron parser `cron.ts` |
| Company portability | `company-portability.ts`, `company-export-readme.ts` |

## 07 — API, realtime, auth & MCP
| Claim | File |
|---|---|
| Route mounting | `server/src/app.ts` |
| 43 route factories | `server/src/routes/*` (`issues.ts`, `agents.ts`, `costs.ts`, `approvals.ts`, `environments.ts`, `execution-workspaces.ts`, …) |
| Company-scoping guard | `server/src/routes/authz.ts` (`assertCompanyAccess`, `assertBoard`) |
| Auth normalization (`req.actor`) | `server/src/middleware/auth.ts` (`actorMiddleware`, `verifyLocalAgentJwt`) |
| WebSocket realtime server | `server/src/realtime/live-events-ws.ts` (`setupLiveEventsWebSocketServer`) |
| Event bus | `server/src/services/live-events.ts` (`publishLiveEvent`) |
| MCP server (stateless REST proxy) | `packages/mcp-server/*`; tool defs `packages/mcp-server/src/tools.ts` (`createToolDefinitions`) |
| Aspirational (NOT shipped) interface | `doc/TASKS-mcp.md` |

## 08 — Frontend (board UI)
| Claim | File |
|---|---|
| Routing | `ui/src/App.tsx` |
| Pages | `ui/src/pages/*` (`IssueDetail.tsx` — the heart; Dashboard, DashboardLive, Agents, OrgChart, Goals, Costs, Inbox, Approvals, Routines) |
| Live run surface | `ui/src/components/{ActiveAgentsPanel.tsx, LiveRunWidget.tsx, RunChatSurface.tsx}` |
| Liveness vocabulary | `ui/src/components/IssueRunLedger.tsx` (`LIVENESS_COPY`) |
| Recovery card | `ui/src/components/IssueRecoveryActionCard.tsx` |
| Dual-source streaming engine | `ui/src/components/transcript/useLiveRunTranscripts.ts` |
| UI-side stdout → transcript parser | `ui/src/adapters/http/parse-stdout.ts` |
| Realtime provider (WS → cache invalidation) | `ui/src/context/LiveUpdatesProvider.tsx` |
| Query key factory | `ui/src/lib/queryKeys.ts` |
| REST client | `ui/src/api/client.ts` + per-domain `ui/src/api/*` |
| Plugin slot system | `ui/src/plugins/slots.tsx`, `bridge.ts` |

## 09 — Extensibility
| Claim | File |
|---|---|
| Plugin spec / SDK | `doc/plugins/PLUGIN_SPEC.md`, `packages/plugins/sdk` |
| Plugin capabilities enum | `packages/shared/src/constants.ts` (`PLUGIN_CAPABILITIES`) |
| Plugin manifest type | `packages/shared/src/types/plugin.ts` (`PaperclipPluginManifestV1`) |
| Sandbox providers | `packages/plugins/sandbox-providers/{cloudflare,daytona,exe-dev}` |
| Agent operating manual | `skills/paperclip/SKILL.md` |
| Skills catalog | `packages/skills-catalog/*`; frontmatter parser `…/frontmatter.ts` |
| Teams / company templates | `packages/teams-catalog/*` |
| CLI | `cli/src/*` (entry `cli/src/index.ts`) |
| Shared contract layer | `packages/shared/src/{constants.ts, api.ts, types/, adapter-type.ts, trust-policy.ts, agent-eligibility.ts}` |

## 10 — Implications for chorus
Synthesis doc — cites the same files as 02–06 (the "steal wholesale" list maps to
`issue_plan_decompositions`, `issue_relations`, `issues.ts:checkout`, the recovery ladder
in `recovery/service.ts`, `budgets.ts` two-gate, `low-trust-runtime-containment.ts`,
`company-portability.ts`). No unique citations.

---

## The 8 keystone files (if you read nothing else)
1. `server/src/services/heartbeat.ts` — the run engine (queue, spawn, stream, cancel, wake).
2. `server/src/services/issues.ts` — issue state machine, atomic checkout, decomposition.
3. `server/src/services/recovery/service.ts` — the liveness/stuck-detection ladder.
4. `server/src/services/run-liveness.ts` — post-hoc "did it actually work?" classifier.
5. `packages/adapter-utils/src/types.ts` — the `execute(ctx)→result` adapter contract (the seam).
6. `server/src/services/budgets.ts` — the two-gate spend hard-stop.
7. `packages/db/src/schema/*.ts` — the org/DAG/runtime-as-data model.
8. `doc/execution-semantics.md` — the prose spec the whole orchestration obeys.
