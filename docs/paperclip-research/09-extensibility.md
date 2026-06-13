# 09 — Extensibility (plugins, skills, teams, CLI, shared contract)

Paperclip keeps a **thin core, rich edges**. Optional capability lives in plugins;
agent know-how lives in skills; reusable orgs are markdown templates; and a shared
Zod/constants contract layer is the spine everything binds to.

Core: `packages/plugins/*`, `doc/plugins/PLUGIN_SPEC.md`, `packages/mcp-server/*` (see
[07](07-api-realtime-auth-mcp.md)), `skills/*` + `packages/skills-catalog/*`,
`packages/teams-catalog/*`, `cli/*`, `packages/shared/*`.

---

## 1. Plugin system

Spec: `doc/plugins/PLUGIN_SPEC.md`. SDK: `packages/plugins/sdk` (`@paperclipai/plugin-sdk`). Manifest:
`packages/shared/src/types/plugin.ts` (`PaperclipPluginManifestV1`).

### Two extension classes
- **Platform modules** — trusted, in-process, low-level; explicit registries (`registerAgentAdapter`,
  `registerStorageProvider`, `registerSecretProvider`, `registerRunLogStore`). Where **new agent
  adapters** and storage/secret backends go.
- **Plugins** — globally installed per instance, **out-of-process**, additive, capability-gated, isolated
  via the SDK + RPC protocol. Categories: `connector | workspace | automation | ui`.

### What a plugin can contribute (manifest)
- **Agent tools** — `tools[]`; namespaced `pluginId:toolName`; needs `agent.tools.register`; routed via
  `executeTool` RPC with run context.
- **Scheduled jobs** — `jobs[]` with cron `schedule`; `jobs.schedule`.
- **Webhooks** — `POST /api/plugins/:pluginId/webhooks/:endpointKey`; `webhooks.receive`.
- **Scoped API routes** — under `/api/plugins/:pluginId/api/*`; host enforces auth
  (`board|agent|board-or-agent|webhook`), capability, checkout policy, and company resolution before
  dispatch to `onApiRequest`.
- **Restricted DB namespace** — `database: { migrationsDir, namespaceSlug?, coreReadTables? }`. Host
  derives a Postgres namespace from the plugin key, runs checksum-recorded migrations before worker
  start. Runtime `ctx.db.query()` allows `SELECT` from the namespace + manifest-whitelisted core tables;
  `ctx.db.execute()` allows writes **only** inside the namespace.
- **Managed resources** — agents, projects, routines, **skills** (full `SKILL.md`) the plugin can
  provision and re-resolve by stable key (resolution tracks `missing|resolved|created|relinked|reset`).
- **Environment drivers** — `environmentDrivers[]` (`environment_driver`/`sandbox_provider`); concrete
  sandbox providers in `packages/plugins/sandbox-providers/{cloudflare,daytona,exe-dev}`.
- **Trusted local folders** — operator-configured absolute root per company; `ctx.localFolders.*` with
  traversal/symlink-escape protection.
- **UI** — `ui.slots[]` + `ui.launchers[]` (~16 slot types — see [08](08-frontend.md)), each capability-gated.
- **Instance config** — JSON Schema with `x-paperclip-*` form extensions.
- **Events** — subscribe to core domain events (`issue.created`, `agent.run.finished`,
  `approval.decided`, `budget.incident.opened`, `cost_event.created`, …) + plugin-to-plugin events.
- **Real-time streams** — `ctx.streams.*` fanned out via SSE `GET /api/plugins/:id/bridge/stream/:channel`.
- **Agent invocation/sessions** — `ctx.agents.invoke` + `ctx.agents.sessions.*`, capability-gated.

The full set is `PLUGIN_CAPABILITIES` (`packages/shared/src/constants.ts`).

### Load & sandbox model
- Install is **global/instance-level** (no per-company install table; per-company mappings live in
  `plugin_config`/`plugin_state`/`plugin_company_settings`). On-disk under
  `~/.paperclip/instances/<id>/plugins/`. Requires a writable fs + npm at runtime (single-node assumption).
- Install flow: resolve npm pkg → install → validate manifest → reject incompatible `apiVersion` → show
  requested capabilities to operator → persist `plugins` row → start worker → health-check → `ready|error`.
- Load order: core platform modules → built-in first-party plugins → installed plugins. Plugins **cannot
  override core routes/actions**; UI slot IDs auto-namespaced.
- **Process model**: third-party plugins run **out-of-process** (one Node worker per plugin, host↔worker
  over JSON-RPC on stdio). RPC: `initialize`/`health`/`shutdown` (required) + `onEvent`/`runJob`/
  `handleWebhook`/`getData`/`performAction`/`executeTool`/`onApiRequest` (optional). Failure isolation
  (mark `error`, backoff retry, never drop others); graceful shutdown 10s → SIGTERM → 5s → SIGKILL.
- **Trust caveat (today):** plugin workers **and UI bundles are trusted code** — UI runs same-origin with
  the board session, so manifest capabilities are not a frontend sandbox. The real sandboxing is:
  out-of-process workers + capability gating + the restricted DB namespace + path-safe local folders.

---

## 2. Skills

Two things share the name "skill":

- **The `paperclip` skill** (`skills/paperclip/SKILL.md`) — the prose operating manual injected into
  every agent run. It defines the **heartbeat model**: agents wake in short windows, do work, exit.
  Procedure: identity → approval follow-up → inbox → pick work → **checkout** (mandatory; never retry
  409) → `heartbeat-context` → do work → update status → delegate via child issues. Encodes governance
  (budget auto-pause, approvals, blockers, interactions, plans-as-issue-documents under key `plan`).
  Rule #1: "never ask a human to do what an agent could do."
- **Company skills catalog** (`packages/skills-catalog`) — installable markdown capability packs.
  `CatalogSkill`: `kind` (`bundled|optional`), category, `trustLevel` (`markdown_only|assets|
  scripts_executables`), `recommendedForRoles`, `requires`, `files[]` (each sha256'd), `contentHash`.
  Bundled examples: `qa-acceptance`, `github-pr-workflow`, `issue-triage`, `task-planning`, `wireframe`.

Discover/install via the CLI (`skills browse|search|install|...`, `skills agent {list|sync|clear}` to
attach skills to an agent, mirroring `POST /api/agents/:id/skills/sync`). Install copies a catalog skill
→ the company skills library → optionally syncs onto agents (a `desiredSkills` model).

---

## 3. Teams / company templates

`packages/teams-catalog`. A **team** is a portable `agentcompanies/v1` package: a `TEAM.md` with
frontmatter (`manager`, `includes`, `requiredSkills`, `recommendedForCompanyTypes`) + a directory tree
of `agents/*/AGENTS.md`, `projects/*/PROJECT.md`, `tasks/*/TASK.md`, optional `skills/*/SKILL.md`,
`.paperclip.yaml`. Example: a CTO + senior-coder + QA pod.

**Instantiation** is CLI + REST (there is **no `companies.sh`**): `teams preview/install`
(`POST /api/companies/:id/teams/catalog/ref/{preview,install}`) with `--collision-strategy`,
`--target-manager-agent-id`, `--secret-value`, source-policy gates; on `403 agents:create` it can fall
back to creating a **board approval** instead of failing (the agent-safe path). The general portability
mechanism is **company import/export** (`company export/import`) → a portable markdown package; see
[06 §8](06-governance-budgets-security.md) for the slug-identity + env-input externalization that makes
it reusable.

---

## 4. CLI (`cli/src` → `paperclipai`)

Two halves: **instance** (`onboard`, `doctor --repair`, `configure`, `db:backup`, `run`,
`heartbeat run --agent-id` to run one heartbeat with live logs) and **control-plane client**
(`company`, `issue`, `agent`, `project`, `goal`, `approval`, `cost`, `workspace`, `routine`, `adapter`,
`skill`/`skills`, `teams`, `secrets`, `plugin`, `auth bootstrap-ceo`, …). API base resolution:
`--api-base` → `PAPERCLIP_API_URL` → context profile → local config port → `http://localhost:3100`.

---

## 5. Shared contract layer (`packages/shared`)

The dependency root — MCP server, CLI, plugins, server, UI all consume `@paperclipai/shared`.
- **`constants.ts`** (~1175 lines) — every enum/union the system agrees on: `ISSUE_STATUSES`,
  `ISSUE_THREAD_INTERACTION_KINDS`, `ISSUE_ORIGIN_KINDS`, `APPROVAL_TYPES`, `AGENT_ADAPTER_TYPES`/
  `AGENT_ROLES`/`AGENT_STATUSES`, `ROUTINE_*`, `ENVIRONMENT_*`, `GOAL_*`, `DEPLOYMENT_MODES`, the entire
  `PLUGIN_*` family, and `LIVE_EVENT_TYPES`.
- **`types/`** — domain types (issue, agent, project, goal, approval, cost, heartbeat, routine,
  environment, secrets, plugin manifest+records, teams-catalog, company-portability, work-product, …).
- **`api.ts`** — the Zod request/response schemas the MCP server imports (`createIssueInputSchema`,
  `checkoutIssueSchema`, the four interaction payload schemas, `createApprovalSchema`,
  `upsertIssueDocumentSchema`, …).
- **Validators** — `adapter-type.ts` (open-ended so external adapters validate), `trust-policy.ts`
  (`TRUST_PRESETS`), `agent-eligibility.ts` (org-chain rules), `frontmatter.ts` (parses the markdown
  frontmatter powering skills/teams/agents packages).

> **Key takeaway:** the contract is markdown-frontmatter + Zod-validated JSON, and the REST API is the
> single source of truth. The MCP server, the `paperclip` skill, and the CLI client are three parallel
> front-ends onto that same REST surface; plugins extend it out-of-process behind capability gates;
> skills and teams are portable markdown packages resolved by content-hash.
