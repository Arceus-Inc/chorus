# Human intervention backlog

**Last updated:** 2026-08-16  
**Status:** 8 open decisions blocking merge or stack rebasing

## Maintenance rule

Record **only** PRs that need an explicit human product, architecture, or security decision. Remove an entry as soon as the decision is recorded and the PR is unblocked (merged, closed with rationale, or retargeted). Do not keep resolved or superseded items here — repairable CI/rebase work belongs in the PR, not this list.

---

## Chorus [#48 — Org run v2](https://github.com/Arceus-Inc/chorus/pull/48)

| Field | Detail |
|---|---|
| **Decision** | Is [spec 15 cross-child coherence](specs/divo/15-cross-child-coherence.md) still the target — manager-authored `AGENTS.md`, deliverable-coherence DoD on integrate — or should #48 yield to the current AGENTS.md / TCP architecture? |
| **Why not automate** | Fork between an older org-run implementation (coherence checker, contract plan, scaffold/worktree wiring) and whatever the live factory/TCP path now treats as canonical. Merging without a direction call risks shipping the wrong integration model or duplicating abandoned machinery. |
| **Unblock** | Choose one: **(A)** reaffirm spec 15 → rebase #48 onto current `main`, reconcile naming/seams, merge; **(B)** supersede spec 15 → close #48 with a short replacement note and open a TCP-aligned org-run PR if still needed. |

---

## Chorus [#50 — Growth Marketer (Mira)](https://github.com/Arceus-Inc/chorus/pull/50)

| Field | Detail |
|---|---|
| **Decision** | (1) Extend the existing Marketer role vs register a separate Growth Marketer ("Mira") role. (2) Accept net-new kernel modules `chorus.webplugins` and `chorus.swarm` as shared workforce primitives, or keep growth tooling role-local. |
| **Why not automate** | #50 adds registry-level capabilities (trust-scoped plugins, Tier-2 swarm agents, SEND/SPEND gates) that every role inherits — not a localized employee tweak. Role-boundary and kernel-surface choices are product calls. |
| **Unblock** | Record: role strategy (extend vs new) + kernel strategy (accept webplugins/swarm vs shrink to Mira-only). Then either merge #50 as-is, or split into a scoped role PR without kernel expansion. |

---

## Chorus [#81 — credential brokerage](https://github.com/Arceus-Inc/chorus/pull/81)

| Field | Detail |
|---|---|
| **Decision** | Wait for parked [Dream #84](https://github.com/Arceus-Inc/dream/pull/84) (typed brokered credential contract) **or** reject Chorus-only persistence without the Dream ToolContext broker seam. Do not merge until Dream #84 is accepted. |
| **Why not automate** | Blocked on Dream #84. Landing #81 first would persist credentials without the shared ToolContext broker contract — a cross-repo security/architecture fork, not a rebase. |
| **Unblock** | Choose: **(A)** accept Dream #84 → rebase/merge #81 against the typed broker contract; **(B)** reject #81 if Chorus-only persistence without the broker seam is not acceptable. |

---

## Chorus [#88 — default-on OTLP export](https://github.com/Arceus-Inc/chorus/pull/88)

| Field | Detail |
|---|---|
| **Decision** | Approve **default-on** OTLP (core dependency, `http://localhost:4318` fallback, opt-out via `OTEL_SDK_DISABLED`). Confirm acceptable shutdown behavior when no collector is present (~6 s retry at exit per [dream#93](https://github.com/Arceus-Inc/dream/pull/93)). Decide whether Chorus owns this surface long-term or waits for a shared Dream OTLP API first. |
| **Why not automate** | Default-on telemetry changes every deployment's latency, dependency graph, and ops contract. Dream-vs-Chorus ownership is an explicit seam decision ([spec 08](specs/divo/08-observability.md)); automation cannot pick the org-wide observability default. |
| **Unblock** | Choose: **(A)** merge default-on + document env guidance for collector-less runs; **(B)** flip to opt-in; **(C)** defer until Dream exposes a shared OTLP provider and migrate in a follow-up. |

---

## Chorus [#97–#101 — reflection chain](https://github.com/Arceus-Inc/chorus/pull/97)

Stack: [#97 coach](https://github.com/Arceus-Inc/chorus/pull/97) → [#98 run pins](https://github.com/Arceus-Inc/chorus/pull/98) → [#99 proposals](https://github.com/Arceus-Inc/chorus/pull/99) → [#100 reviews](https://github.com/Arceus-Inc/chorus/pull/100) → [#101 authorization](https://github.com/Arceus-Inc/chorus/pull/101). Base [#96](https://github.com/Arceus-Inc/chorus/pull/96) is merged.

| Field | Detail |
|---|---|
| **Decision** | Rewrite #97 (Reflection Coach routine + factory wiring) for the current AGENTS.md / harness factory — **or** drop #97 and retarget #98–#101 to anchor on #96's pinned agent-config model without the paused coach role. |
| **Why not automate** | #97 was built against a pre-#96 factory; its role catalog, routine install, and self-exclusion assumptions may not match today's composition root. Retargeting the DB/artifact chain (#98–#101) without choosing the coach entrypoint risks a broken or unsafe learning loop. |
| **Unblock** | Pick stack shape: **(A)** rewrite #97 → rebase #98–#101; **(B)** close #97 → rebase #98 onto #96 and adjust proposal source constraints in #99. Do not merge #98+ until the anchor PR is settled. |

---

## Chorus [#118 — Lattice applied outcome edges](https://github.com/Arceus-Inc/chorus/pull/118)

| Field | Detail |
|---|---|
| **Decision** | Whether to land the Lattice postgres atom/lineage stack before Chorus injects `LatticeRuntime` + `lattice_selection_seal_outbox`. |
| **Why not automate** | Blocked on the unmerged Lattice stack ([Lattice #21](https://github.com/Arceus-Inc/lattice/pull/21) and parents [#10](https://github.com/Arceus-Inc/lattice/pull/10)–[#20](https://github.com/Arceus-Inc/lattice/pull/20)). Chorus cannot safely inject Lattice runtime/outbox against an unmerged atom/lineage schema. |
| **Unblock** | Choose: **(A)** merge Lattice #10–#21 first, then rebase/merge #118; **(B)** hold or retarget #118 until the Lattice stack is accepted. |

---

## Dream [#84 — typed brokered credential contract](https://github.com/Arceus-Inc/dream/pull/84)

| Field | Detail |
|---|---|
| **Decision** | Accept the **ToolContext protocol extension** (broker on session/context) and the **broker** model (grants, leases, proxy/env delivery) vs the existing CredentialPool approach. Approve as the cross-repo contract Chorus depends on. |
| **Why not automate** | Breaking public API on Dream's tool execution surface; security and tenancy semantics (ask/grant/revoke, delivery restrictions) need explicit threat-model sign-off, not merge-bot judgment. |
| **Unblock** | Approve contract shape → merge dream#84 → bump Chorus against the new contract. If rejected, document the CredentialPool-only path and close dependent Chorus PRs. |

---

## Dream [#94 — SecretProxy](https://github.com/Arceus-Inc/dream/pull/94)

| Field | Detail |
|---|---|
| **Decision** | After rebase onto current `main`, approve the new security boundary: `dream_secret_*` placeholders in model-facing inputs, resolve-at-execute, redact-on-return — including ordering vs PRE hooks/permissions and redaction scope for structured, offloaded, and subagent/tool outputs. |
| **Why not automate** | Introduces a trust boundary (what the model vs executor vs transcript see). Placeholder/permission ordering and incomplete redaction paths are security regressions; only a human reviewer should bless the boundary after rebase. |
| **Unblock** | Rebase #94 → security review (hook order, permission checks, redaction matrix) → approve merge or request narrower scope. Chorus trust/containment work should follow, not precede, this decision. |
