# 07 — API surface, realtime, auth & the MCP agent contract

Paperclip exposes **one REST API with two faces**: the **board** (humans — cookie session
or board API key) and the **agent** (agent API key or local JWT, injected into the
subprocess env). The agent talks to that API through a **stdio MCP server** that is a thin
typed REST proxy. Realtime is **WebSocket only**, per-company fan-out.

Core files: `server/src/app.ts` (mounting), `server/src/routes/*` (43 files),
`server/src/realtime/live-events-ws.ts` + `services/live-events.ts` (realtime),
`server/src/middleware/auth.ts` (auth), `server/src/routes/authz.ts` (company-scoping),
`packages/mcp-server/*` (the agent contract).

---

## 1. The agent-facing API / MCP contract (the most important seam)

### The MCP server is a stateless typed REST proxy
`packages/mcp-server` is a standalone **stdio** MCP server (`createPaperclipMcpServer`). It is **not**
a separate service — it's a stdio process the agent CLI launches. It has **no logic of its own**:
every tool delegates to `PaperclipApiClient.requestJson` → the REST API with
`Authorization: Bearer <apiKey>`, adding `X-Paperclip-Run-Id` on all write methods (the heartbeat
audit trail). Config from env: `PAPERCLIP_API_URL`, `PAPERCLIP_API_KEY` (required),
optional `PAPERCLIP_COMPANY_ID`/`PAPERCLIP_AGENT_ID`/`PAPERCLIP_RUN_ID`. Published as
`npx @paperclipai/mcp-server`. Tools: `packages/mcp-server/src/tools.ts:createToolDefinitions`.

### How the agent subprocess gets wired
The control plane spawns the agent locally (`heartbeat.ts`, adapter `execute()`), injecting into the
subprocess env: `PAPERCLIP_API_KEY` (= the run's short-lived JWT) + `PAPERCLIP_RUN_ID`, plus an
"auth guard" prompt telling the agent to send `Authorization: Bearer $PAPERCLIP_API_KEY` and
`X-Paperclip-Run-Id` on every write. The `mcpServers` registration into the CLI's config lives in the
per-runtime adapter packages.

### The full agent-facing tool surface (`tools.ts`)

| "Phone home" action | MCP tool | REST endpoint |
|---|---|---|
| Who am I / inbox | `paperclipMe`, `paperclipInboxLite` | `GET /agents/me`, `GET /agents/me/inbox-lite` |
| **Get work context** | `paperclipGetHeartbeatContext` | `GET /issues/:id/heartbeat-context` (compact state + ancestor summaries + comment cursor) |
| List/get issues | `paperclipListIssues` (rich filters), `paperclipGetIssue` | `GET /companies/:id/issues`, `GET /issues/:id` |
| **Check out / release** | `paperclipCheckoutIssue`, `paperclipReleaseIssue` | `POST /issues/:id/{checkout,release}` — the lock primitive; 409 = owned |
| **Comment** | `paperclipAddComment`, list/get | `POST/GET /issues/:id/comments` |
| **Create children / update** | `paperclipCreateIssue`, `paperclipUpdateIssue` | `POST /companies/:id/issues`, `PATCH /issues/:id` |
| **Plan/docs** | `paperclipUpsertIssueDocument` (key `plan`), revisions | `PUT /issues/:id/documents/:key`, `.../revisions` |
| **Human-in-loop** | `paperclipSuggestTasks`, `paperclipAskUserQuestions`, `paperclipRequestConfirmation`, `paperclipRequestCheckboxConfirmation` | `POST /issues/:id/interactions` (kind discriminator) |
| **Approvals** | `paperclipCreateApproval`, `paperclipApprovalDecision`, `paperclipLinkIssueApproval` | `POST /companies/:id/approvals`, `POST /approvals/:id/{approve,reject,request-revision,resubmit}`, `POST /issues/:id/approvals` |
| **Sandbox control** | `paperclipControlIssueWorkspaceServices`, `paperclipWaitForIssueWorkspaceService`, `paperclipGetIssueWorkspaceRuntime` | runtime-service start/stop/restart |
| Escape hatch | `paperclipApiRequest` | arbitrary `/api/*` call (path-traversal guarded) |

**Notably absent as dedicated tools** (go through `paperclipApiRequest`): cost reporting
(`POST /companies/:id/cost-events`; the handler enforces `actor.agentId === body.agentId`), artifact/
attachment upload, routines, agent hiring/skills-sync. Server-side identity enforcement: checkout
rejects checking out as another agent and requires `X-Paperclip-Run-Id` for agent callers.

> `doc/TASKS-mcp.md` describes a *different, aspirational* Linear-style interface — **not** what's
> implemented. The shipped contract is the `paperclip*`-prefixed tools above.

---

## 2. The human/board-facing API

The React UI drives everything through the same `/api` surface (mounted in `app.ts`). 43 route files:
issues/comments/documents/work-products/attachments/checkout, `issue-tree-control`, goals, projects,
agents (hire/config/permissions/runtime-state/heartbeat-runs), companies, teams-catalog, routines,
approvals, budgets+costs, secrets, access/authz, environments, execution-workspaces, adapters,
plugins, health, instance-settings, dashboard, activity, `board-chat` (humans chat to the board),
`llms`, `openapi` (serves a full OpenAPI spec). Board-only routes gated by
`assertBoard`/`assertBoardOrgAccess`/`assertInstanceAdmin`. The UI also fetches **historical run
output** to back-fill the live stream: `GET /heartbeat-runs/:runId/events` and `.../log`.

---

## 3. Realtime — and the agent's *work* is streamed

**Transport: WebSocket only.** No SSE, no client polling for live events. Historical logs/events are
plain REST catch-up.
- Endpoint: `wss://…/api/companies/:companyId/events/ws` (`live-events-ws.ts:
  setupLiveEventsWebSocketServer`, mounted on the HTTP `upgrade` handler; 30s ping/pong; per-company
  fan-out via `subscribeCompanyLiveEvents`).
- Event bus: `services/live-events.ts` — an in-process Node `EventEmitter` keyed by `companyId`
  (`publishLiveEvent` emits, the WS layer relays `JSON.stringify(event)`). **Single-process** — events
  don't fan out across instances (the explicit scaling seam).
- Event types: `heartbeat.run.queued/.status/.event/.log`, `agent.status`, `activity.logged`,
  `plugin.ui.updated`, `plugin.worker.crashed/.restarted`.

**The agent's actual work IS streamed, not just status.** `heartbeat.ts:onLog(stream, chunk)` receives
the subprocess's raw stdout/stderr → redacted/compacted → persisted to the run-log store → published
live as `heartbeat.run.log` (`{ runId, agentId, ts, stream, chunk, truncated }`). Lifecycle frames go
as `heartbeat.run.event`; transitions as `heartbeat.run.status`/`.queued`. So the board sees the agent
typing in near-real-time. **But (see [04](04-execution-and-adapters.md)): `heartbeat.run.event` is
control-plane-authored lifecycle only — the structured tool-call transcript is parsed by the *UI* from
raw stdout, never by the orchestrator.**

---

## 4. Auth model

All auth is normalized into a single `req.actor` by `middleware/auth.ts:actorMiddleware` (runs before
all routes). Actor types: `board` (human), `agent`, `none`. Resolution order:
1. **`local_trusted` mode** → implicit `{type:"board", source:"local_implicit", isInstanceAdmin:true}`
   (single-tenant local dev).
2. **No bearer + `authenticated` mode** → cloud trusted-header path (validates
   `x-paperclip-cloud-tenant-token` + headers, upserts user/company/membership, purges stale
   instance_admin) OR a BetterAuth cookie session (`board` actor with `companyIds`+`memberships`).
3. **`Bearer <token>`** → board API key (`board_api_keys`) → `board`; agent API key (`agent_api_keys`,
   SHA-256 hashed, `revokedAt IS NULL`) → `agent` pinned to one company; local agent JWT
   (`verifyLocalAgentJwt`, claims must match a live agent) → `agent`.

So: **humans = session cookie or board API key; agents = agent API key or local JWT.** Agents are
always pinned to exactly one company by their credential.

**Company-scoping is per-handler, not path middleware** — `routes/authz.ts:assertCompanyAccess`:
agent → `companyId` must equal `actor.companyId` (else 403 "Agent key cannot access another company");
board → `companyId` in `actor.companyIds`, and writes require an active non-viewer membership;
`instance_admin` bypasses write checks. Two extra guards: `board-mutation-guard` (CSRF — session writes
require trusted Origin/Referer; API keys/local/cloud exempt) and `private-hostname-guard` (SSRF). The WS
upgrade re-runs its own auth (agent key must match the path company; agents may pass the token via
`?token=`).

---

## 5. Route → service mapping (keystones)

Routes are factory functions `(db) => Router` delegating to `server/src/services/`:

| Route | Delegates to |
|---|---|
| `issues.ts` | `issueService`, `issueDocumentsService`, `executionWorkspacesService`, `recoveryActionsService`, **`heartbeat`** (`heartbeat.wakeup` on checkout/comment), `activity-log` |
| `agents.ts` | `agentsService`, **`heartbeat`** (getRun/listEvents/readLog/cancel/watchdog), `pluginWorkerManager` |
| `costs.ts` | `costsService`, `financeService`, budget/quota services |
| `approvals.ts` | `approvalsService` + `heartbeat` wakeups |
| `execution-workspaces.ts` | `executionWorkspacesService` + workspace-runtime services |
| `routines.ts` | routines/scheduler service |

The architectural keystone is **`server/src/services/heartbeat.ts`** (~11k lines): owns the run queue,
spawns the agent via adapters, captures+streams its output (`onLog` → `publishLiveEvent`), and is
invoked from many routes via `heartbeat.wakeup(...)` to schedule the next agent turn.

---

## Critical takeaways

1. **The MCP server is a stateless typed REST proxy.** The real agent contract is the REST API; MCP
   provides Zod-validated tools + bearer/run-id header injection. Extending the agent contract = editing
   `tools.ts` + the underlying routes.
2. **The control plane runs the agent, not vice-versa.** Agents are subprocesses; their stdout is the
   streamed product; auth is injected via env. An agent never connects in as a long-lived client — it
   makes short REST calls and emits stdout the server tails.
3. **Realtime is in-process WebSocket fan-out keyed by company.** Single-process (no pub/sub bus); the
   WS auth path allows `?token=` for agents.
