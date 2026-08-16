# Stateful Agent Harnesses: 2026 Research Report

*Generated: 2026-08-16 | Primary sources reviewed: 29 | Confidence: high on architecture, medium on preview APIs*

## Executive summary

The state of the art is a layered harness, not a single framework: thread-scoped checkpoints or sessions for execution continuity, a separate cross-thread memory store, typed task and handoff contracts, deterministic gates before dispatch, and append-only traces with feedback attached to exact runs. LangGraph expresses the checkpoint/store split most clearly; the OpenAI Agents SDK provides the cleanest session, handoff, approval, and context-filtering primitives; Microsoft Agent Framework and Google ADK make orchestration ownership explicit; Letta is the strongest memory-native design; Temporal is the durability ceiling when ordinary application persistence is insufficient. [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence), [OpenAI Agents SDK sessions](https://openai.github.io/openai-agents-python/sessions/), [Microsoft Agent Framework workflows](https://learn.microsoft.com/en-us/agent-framework/workflows/), [Google ADK sessions](https://adk.dev/sessions/), [Letta memory blocks](https://www.letta.com/blog/memory-blocks/), [Temporal workflow execution](https://docs.temporal.io/workflow-execution)

Arceus owns the MP1 continuity substrate on `origin/main`. Dream stores and resumes task-scoped role sessions ([Dream #92](https://github.com/Arceus-Inc/dream/pull/92), [Dream #104](https://github.com/Arceus-Inc/dream/pull/104)); Chorus keeps the task-to-Dream handle, workspace binding, and metering ([Chorus #89](https://github.com/Arceus-Inc/chorus/pull/89)). The coordinated replacement stack that closes typed task-truth projection, durable landed-run carryover, audience-safe per-beat push, and cache-stable prompt separation is merged: [Dream #108](https://github.com/Arceus-Inc/dream/pull/108) and [Dream #109](https://github.com/Arceus-Inc/dream/pull/109), plus [Chorus #107](https://github.com/Arceus-Inc/chorus/pull/107) and the typed task context plane landed via stacked [Chorus #122](https://github.com/Arceus-Inc/chorus/pull/122), [Chorus #123](https://github.com/Arceus-Inc/chorus/pull/123), and [Chorus #125](https://github.com/Arceus-Inc/chorus/pull/125). Standalone [Chorus #109](https://github.com/Arceus-Inc/chorus/pull/109) was closed after its commit merged through that stack; do not treat it as pending work.

The old [Chorus #80](https://github.com/Arceus-Inc/chorus/pull/80) `feat/task-context-packet` PR remains superseded, not a branch to rebase wholesale. Its behavioral intent is now implemented through typed objects and the existing injection seam in `src/chorus/context/`, without a second continuation system. Open [Dream #100](https://github.com/Arceus-Inc/dream/pull/100) is not the replacement either: it proposes explicit message injection at the public runner boundary, distinct from durable handle-based resume in Dream #92/#104, and must be ported onto the current runner modules before it can land.

## Research questions

1. How do leading harnesses separate short-term execution state from durable memory?
2. How do they make delegation, ownership, and pre-dispatch validation structural?
3. How do they connect traces, evaluator feedback, memory use, and product outcomes?
4. Which mechanisms materially improve Arceus, and which would duplicate existing layers?

## 1. Execution continuity and memory

LangGraph makes the essential split explicit. A checkpointer stores thread-scoped graph state for continuity, fault recovery, human interruption, and time travel; a store holds application-defined data shared across threads. Its documentation recommends using both when an application needs both kinds of state. [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence), [LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts), [LangGraph time travel](https://docs.langchain.com/oss/python/langgraph/use-time-travel)

The OpenAI Agents SDK follows the same principle through sessions and resumable run state. Sessions automatically retrieve history before a run and append the new turn afterward. Approval interruptions can be resumed with the same stored session. The SDK also exposes a callback that filters or reorders retrieved history before the model call, plus explicit retrieval limits. It warns against combining client-side sessions with server-managed continuation in the same run. [OpenAI Agents SDK sessions](https://openai.github.io/openai-agents-python/sessions/), [running agents](https://openai.github.io/openai-agents-python/running_agents/), [human-in-the-loop](https://openai.github.io/openai-agents-python/human_in_the_loop/)

Letta takes the memory-native route: persisted memory blocks are compiled into model context, can be edited independently, and can be shared across agents. The MemGPT paper behind Letta describes virtual context management and hierarchical memory tiers rather than an ever-growing prompt. [Letta documentation](https://docs.letta.com/), [Letta memory blocks](https://www.letta.com/blog/memory-blocks/), [MemGPT paper](https://arxiv.org/abs/2310.08560)

Temporal is relevant only when workflow execution itself must survive arbitrarily long failures. Workflow executions are replayable, and Continue-As-New carries current state into a fresh history to bound event-log growth. It does not solve semantic memory or context selection. [Temporal workflow execution](https://docs.temporal.io/workflow-execution), [Continue-As-New](https://docs.temporal.io/workflow-execution/continue-as-new)

AutoGen offers a lighter explicit state/memory API: agents and teams save and load state, while memory components update model context through a distinct protocol. [AutoGen state](https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/tutorial/state.html), [AutoGen memory](https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/memory.html)

### Arceus decision

Keep Dream sessions as the short-term continuation mechanism and Lattice as cross-thread learned memory. Chorus projects typed control-plane facts through `VolatileBeatPacket` and audience-filtered rendering; the design does not replay transcripts, introduce a second checkpoint store, or make the packet responsible for provider conversation state.

This is an inference from the products above and the current Arceus code paths, not a vendor prescription. Current evidence: `src/chorus/adapters/dream_beat.py` for task-keyed session admission; `src/chorus/context/` for typed projection and rendering; `src/chorus_harness/_dream_hooks.py` for volatile packet injection; `src/chorus_harness/_factory.py` for per-beat packet assembly.

### Full-stack context-management stress map

| Layer | Current owner and evidence | Stress it absorbs | Boundary to keep |
|---|---|---|---|
| Dream | Merged durable `FileSessionStore` snapshots in [#92](https://github.com/Arceus-Inc/dream/pull/92) and task `session_scope` role threads in [#104](https://github.com/Arceus-Inc/dream/pull/104); merged [#108](https://github.com/Arceus-Inc/dream/pull/108) typed evaluation/hook roles and [#109](https://github.com/Arceus-Inc/dream/pull/109) cache-stable prompt assembly | Process death, short beat windows, in-task repair, and cache-stable provider context | It owns transcripts and active context, not company/task truth. |
| Chorus | Merged task/session handle in [#89](https://github.com/Arceus-Inc/chorus/pull/89); merged [#107](https://github.com/Arceus-Inc/chorus/pull/107) prompt-waist removal and typed task context plane in [#122](https://github.com/Arceus-Inc/chorus/pull/122)/[#125](https://github.com/Arceus-Inc/chorus/pull/125) with append-only `run_carryover` | Stable task identity, workspace/cost attribution, durable carryover, and audience-safe per-beat facts | It stores task truth and the Dream handle, never Dream's transcript. |
| Horizon | Target consumer of typed `OUTCOME_LANDED` events for goal health and re-planning; it can consume landed-run carryover from Chorus | Goal drift and recovery prioritization | Horizon remains the strategy consumer, not the task-context store. |
| Lattice | Receives Chorus's episodic sprint delta after a beat | Cross-thread learned-pattern recall | Retrieved learning is advisory, not the current task contract or source of truth. |
| Podium | Target product projection for outcome phase/recovery state | Human recovery visibility and final-product coordination | It must not infer or overwrite the underlying task/run audit. |

### Compaction is not durable planning

Compaction is a context-window control, not a durable plan, contract, or audit record. OpenAI's compaction session rewrites stored conversation history; Anthropic's context editing compacts old context into a summary; Hermes calls its default compressor lossy summarization; OpenCode calls compaction lossy even while retaining earlier messages outside active model context; and OpenHarness can replace the whole message history with a structured summary. [OpenAI Agents SDK sessions](https://openai.github.io/openai-agents-python/sessions/), [Anthropic context editing](https://platform.claude.com/docs/en/build-with-claude/context-editing), [Hermes context compression](https://hermes-agent.nousresearch.com/docs/developer-guide/context-compression-and-caching/), [OpenCode compaction](https://opencode.ai/v2/docs/compaction), [OpenHarness sessions](https://docs.open-harness.dev/core/sessions)

Those are useful ways to keep a role operating within a context window. None establishes typed goal ownership, immutable acceptance criteria or file claims, provenance joins, or a replayable decision trail. Dream may compact its own active context; Chorus/Horizon/Lattice/Podium must retain their respective durable facts independently.

## 2. Delegation and orchestration gates

The leading systems make orchestration ownership explicit. OpenAI represents handoffs as tools with typed input and gives the runner one owner for turns, tools, guardrails, sessions, and approvals. Tool and agent guardrails execute before or around actions; approval interruptions are part of the run state. [OpenAI handoffs](https://openai.github.io/openai-agents-python/handoffs/), [OpenAI guardrails](https://openai.github.io/openai-agents-python/guardrails/)

Microsoft Agent Framework models workflows as executors connected by typed edges, with checkpointing and human request/response ports. This is the clearest current example of making routing a typed workflow concern instead of manager prose. [Microsoft Agent Framework overview](https://learn.microsoft.com/en-us/agent-framework/overview/), [workflows](https://learn.microsoft.com/en-us/agent-framework/workflows/), [human-in-the-loop](https://learn.microsoft.com/en-us/agent-framework/workflows/human-in-the-loop)

Google ADK separates LLM agents from workflow agents such as sequential, loop, and parallel orchestrators. Session state is the shared context surface, while explicit transfers or agent tools determine ownership changes. [Google ADK agents](https://adk.dev/agents/), [Google ADK sessions](https://adk.dev/sessions/)

CrewAI's task model carries description, expected output, context, and guardrails; hierarchical execution requires an explicit manager. Human feedback pauses a flow as a workflow state. [CrewAI tasks](https://docs.crewai.com/en/concepts/tasks), [CrewAI processes](https://docs.crewai.com/en/concepts/processes), [CrewAI human feedback](https://docs.crewai.com/en/concepts/flows)

Paperclip is the closest control-plane comparison. It makes company, goal, task, org-chart, budget, approval, and persistent heartbeat state primary rather than treating chat as the system of record. [Paperclip repository](https://github.com/paperclipai/paperclip)

### Arceus decision

Move the load-bearing decomposition rules into the Chorus kernel in small steps:

1. Enforce manager cardinality and ownership before any child, team, or claim mutation.
2. Add typed file claims to child plans and reject empty, overlapping, or out-of-parent scopes before dispatch.
3. Project sibling claims into the existing per-beat packet; do not build an agent chat bus.
4. Delete the corresponding roster prose only after each invariant has a test-backed gate.

This sequence keeps one owner for dispatch and makes failures specific and retryable. It also avoids coupling Dream to company/task semantics.

## 3. Provenance, evaluation, and product truth

OpenTelemetry's GenAI conventions are converging on structured spans and events for model calls, tool calls, and evaluations. The current agentic-system proposal discusses tasks, actions, agents, teams, artifacts, and memory as related observability objects, but it remains draft work and exact names may change. [OpenTelemetry GenAI conventions](https://github.com/open-telemetry/semantic-conventions-genai), [agentic-system proposal](https://github.com/open-telemetry/semantic-conventions-genai/issues/35), [GenAI events specification](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-events.md)

LangSmith distinguishes a run from a trace and a thread, then binds feedback to a specific run. Datasets and evaluators form the repeatability layer. [LangSmith observability concepts](https://docs.langchain.com/langsmith/observability-concepts), [LangSmith evaluation](https://docs.langchain.com/langsmith/evaluation)

OpenAI recommends the same progression: collect traces, attach graders to workflow behavior, then promote representative cases into datasets and repeated eval runs. Agents SDK traces already include model calls, tool calls, handoffs, guardrails, and custom spans. [OpenAI observability integrations](https://developers.openai.com/api/docs/guides/agents/integrations-observability), [OpenAI agent evals](https://developers.openai.com/api/docs/guides/agent-evals)

Reflexion demonstrates the smaller feedback loop: convert task feedback into a durable verbal reflection used on a later attempt. Agent Lightning shows how structured trajectories can support a broader learning loop. Neither should be the provenance system of record. [Reflexion paper](https://arxiv.org/abs/2303.11366), [Agent Lightning](https://github.com/microsoft/agent-lightning)

### Arceus decision

Use existing durable rows and append-only events as the source of truth, then expose a typed traversal/read model. Do not add Neo4j, GraphRAG, embeddings, or a second mutable truth graph. The minimum useful lineage must answer:

- which task and goal a run served;
- which artifact a run produced;
- which gate or evaluator judged it;
- which cost events belong to the same trace;
- which learned pattern was retrieved or applied;
- which later outcome supports or contradicts that pattern.

Feedback should identify an exact run/event and preserve numeric score, categorical label, and explanation. A final GoalJudge should create such a judgment before Podium declares product success; it must not overwrite the underlying run or artifact rows.

## Product comparison

| Product | Strongest mechanism | Arceus lesson | Do not copy |
|---|---|---|---|
| LangGraph | Checkpoint/store separation | Keep Dream continuity separate from Lattice memory | A second graph runtime |
| OpenAI Agents SDK | Sessions, typed handoffs, guardrails, approvals | Filter session input and gate actions structurally | Dual continuation mechanisms |
| Letta | Explicit persisted memory blocks | Push a small memory floor, keep deep retrieval | One self-editing transcript blob |
| Temporal | Replayable durable workflows | Use only if current ledger recovery proves insufficient | Temporal as semantic memory |
| Microsoft Agent Framework | Typed workflow edges and HITL ports | Validate routing before dispatch | Prompt-defined topology |
| Google ADK | Explicit workflow ownership and session state | One shared state surface per run path | Custom orchestration where a graph suffices |
| AutoGen | Message contracts and explicit state | Keep behavior contracts inspectable | Chat as governance |
| CrewAI | Task guardrails and hierarchical manager | Typed task expectations and human gates | Manager prose as invariant |
| Paperclip | Full control plane and durable heartbeats | Keep org/task/budget/approval truth in Chorus/Podium | Duplicating Dream's LLM loop |

## MP1 completion audit

| MP1 requirement | Current state | Exact evidence |
|---|---|---|
| B01 — retain task/session identity across beats | Complete. Dream persists typed snapshots and role threads below one stable task scope; Chorus reuses that task identity and owns its handle, workspace, and spend. | [Dream #92](https://github.com/Arceus-Inc/dream/pull/92): `src/dream/services/session_store.py` and `src/dream/harness.py`; [Dream #104](https://github.com/Arceus-Inc/dream/pull/104): `src/dream/runner/role.py`; [Chorus #89](https://github.com/Arceus-Inc/chorus/pull/89): `src/chorus/ledger/_agent_session_beat.py` and `src/chorus/ledger/repos/agent_sessions.py`. |
| B07 — resume the existing plan instead of fully replanning every beat | Complete. Dream's `PlanAdmission.RESUME` skips the planner and loads the existing ledger when the stable task ledger exists; Chorus reuses `task_id` when it passes that admission. | `src/dream/runner/_run.py`; [Dream #104](https://github.com/Arceus-Inc/dream/pull/104); `src/chorus/adapters/dream_beat.py`; [Chorus #89](https://github.com/Arceus-Inc/chorus/pull/89). |
| Typed task-truth projection and audience-safe per-beat push | Complete. Chorus projects bounded task contracts, DoD, ancestry, inbox, budget, sibling findings, and lattice wake into one immutable `TaskContextPacket`, then renders audience-filtered volatile context each beat. | `src/chorus/context/`; [Chorus #122](https://github.com/Arceus-Inc/chorus/pull/122); [Chorus #125](https://github.com/Arceus-Inc/chorus/pull/125); `src/chorus_harness/_dream_hooks.py`. |
| Durable landed-run carryover across reassignment | Complete. Append-only `run_carryover` rows persist typed evaluator carryover and are projected into the task context plane for the next assignee. | `src/chorus/ledger/repos/run_carryovers.py`; `src/chorus/heartbeat/_scheduler.py`; `src/chorus/context/_project.py`. |

The replacement stack that closed the reassignment gap is merged on `origin/main`: Dream [#108](https://github.com/Arceus-Inc/dream/pull/108) typed evaluation carryover and role-aware hooks, Dream [#109](https://github.com/Arceus-Inc/dream/pull/109) cache-stable prompt assembly, Chorus [#107](https://github.com/Arceus-Inc/chorus/pull/107) prompt-waist removal, and the TCP stack ([#122](https://github.com/Arceus-Inc/chorus/pull/122), [#123](https://github.com/Arceus-Inc/chorus/pull/123), [#125](https://github.com/Arceus-Inc/chorus/pull/125)). Transcript ownership stays in Dream; task truth stays in Chorus; Horizon and Podium remain downstream consumers.

Merge-state verification used Chorus `origin/main` at `93bd5de` (2026-08-16). TCP commit `3b3b828` is an ancestor of that tip. Focused continuity-boundary tests from the original audit (43 session/admission/reconnect cases) remain valid evidence for B01/B07; TCP coverage lives in `tests/context/`, `tests/harness/test_register_employee_hooks.py`, `tests/harness/test_lattice_beat_start.py`, and `tests/heartbeat/test_run_carryover.py`.

MP2–MP7 remain roadmap documentation context only; another session owns their implementation and this report does not propose code for them.

## Existing MP2–MP7 roadmap context (not implemented here)

Another session owns these steps; they are retained only to place the MP1 audit in the wider program.

1. Remove integrate-cap success fabrication and escalate exhausted loops.
2. Add deterministic manager decomposition gates; then remove mapping prose.
3. Add durable typed file claims and overlap/coverage validation.
4. ~~Extend the volatile packet with bounded typed task truth and durable carryover.~~ Done on main via the typed task context plane; do not revive the stale [#80](https://github.com/Arceus-Inc/chorus/pull/80) implementation wholesale.
5. Add a typed provenance traversal over existing rows and record the missing memory-applied relationship.
6. Wire Horizon replan signals to a deduplicated CEO wake.
7. Add an independent GoalJudge at Podium finalization.

## Explicitly deferred

- Neo4j, GraphRAG, and embeddings: relational joins and a push path are not yet exhausted.
- Temporal: the Chorus ledger provides recovery plus SQL-backed idempotency and exact-once invariants for specific rows (for example tasks, claims, wakes, and recovery actions), not general exactly-once workflow effects. Add another workflow engine only after measured durability gaps.
- Transcript replay and a second session store: Dream owns session continuity.
- Free-form inter-agent chat: peer file claims cover the coordination need with less state.

## Methodology

Three independent research lanes examined durable harness state, orchestration gates, and provenance/evaluation. Sources were restricted to official product documentation, official repositories/specifications, and primary research papers. The synthesis was cross-checked against current `origin/main` and open branches in Chorus, Dream, Horizon, Lattice, and Podium on 2026-08-16. Product APIs marked preview or draft above should be re-verified before direct dependency adoption.

## Validation

- External research links rechecked against primary sources.
- Merge-state claims verified against GitHub PR states and Chorus `origin/main` at `93bd5de`.
- TCP presence verified: `3b3b828` is an ancestor of `93bd5de`; `src/chorus/context/` and `run_carryover` tables/repos exist on the tip.
- `git diff --check` clean on this file.
