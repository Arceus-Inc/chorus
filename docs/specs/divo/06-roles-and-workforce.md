# 06 — Roles & the workforce

Who an employee is, what a role is, and how the org is data. chorus's equivalent of Paperclip's
`agents` model (research [02](../../paperclip-research/02-data-model.md) §org) + the role/skill
layer — built on dream's `roles`.

---

## 1. Employee — a replayable identity, not a process

An `employee` (spec 01) has **no continuous existence**. Each beat *rehydrates* it from
`(employee row + role manifest + memory scope + ledger history)`, runs one `run_task`, and
dissolves (B1.1). Continuity lives in the ledger + memory git, never in a running thing.

**Rehydration** (start of every beat):

```python
def rehydrate(employee_id):
    row    = workforce.get(employee_id)            # name, role, reports_to, memory_scope, status
    role   = roles.load_manifest(row.role)         # dream RoleManifest (+ overlay)
    memory = memory_store.scope(row.memory_scope)  # read-side (spec 07)
    return Employee(row, role, memory)
```

Anything an employee must carry between tasks has a durable home (ledger, memory) or it does not
exist. There is no per-employee process to keep alive.

---

## 2. Role — toolset + DoD generator + outcome (the plugin)

A **role** is the unit of heterogeneity. It is exactly three things (Corebelief §6):

```
Role = ( RoleManifest          # toolset + system prompt + permission mode  (dream.roles)
       , DoDGenerator           # intent -> typed Verifier  (spec 04)
       , OutcomeKind )          # what "landed" means for this role  (spec 04 §2)
```

- **RoleManifest** comes from `dream.roles`: `system_prompt`, allowed `tools`, `disallowed_tools`
  (operator veto wins), `permission_mode`, `memory_scope`, `isolation`. `compute_minimum_toolset`
  enforces the intersection; a bounded role can't widen itself (spec 05 §3).
- **DoDGenerator** turns the task intent into a typed `Verifier` at intake (Command / AgentReview /
  HumanApproval) — *how* this role decides "done."
- **OutcomeKind** is *what artifact* satisfies it (PR, verdict, spec, finding).

A role is a **plugin** (spec 09): adding "Designer" = adding a manifest + a DoD generator + an
outcome kind. No kernel change.

### The v0 roles

| Role | Toolset leans | DoD (verifier) | Outcome |
|---|---|---|---|
| **Engineer** | repo-write, run gates | `Command` (CI/tests exit 0) | PR opened, CI green |
| **Reviewer** | read-only | renders the verdict | approve/block on a diff |
| **Manager** | ledger-write (decompose/dispatch) | children dispatched **and** integrated | a completed subtree |
| **Product/PM** | read + write docs | `AgentReview` (Reviewer) | a spec/decision artifact |
| **Analyst** | read + data tools | `AgentReview` (Reviewer) | a data finding |

> **Reviewer is load-bearing, not a luxury** (B3.2): it is the *verifier* for all judgment-class
> work (PM, Analyst). It must ship at M3 with the first non-code role. An Analyst with no Reviewer
> is Paperclip (self-report).

---

## 3. The Workforce — org as data

The org chart **is** the `employee.reports_to` adjacency list (Paperclip: *"there is no teams
table; team structure is emergent"*). No process tree. Invariants (Paperclip's, kept):

- **No cycles** in `reports_to`.
- **`terminated` is irreversible.**
- Hire/fire = a data edit (gated by an `approval` when policy requires — spec 04 §5).
- Humans and employees are unified as **principals** for ownership (a task is assigned to an
  employee XOR a human).

The org *behaves* hierarchical (managers, reports, delegation, review) but the **runtime is flat
and durable** — no employee ever blocks inside another's call stack (B1.2). The only sanctioned tree
is dream's `swarm` (bounded, depth-capped, ephemeral intra-task helpers).

---

## 4. Assignment — a hard filter, never an auto-router

Assignment is **explicit** or a **hard role-eligibility filter** — never a soft score (B5.1;
Paperclip ships no auto-router on purpose). Three paths (Paperclip's):

1. **Direct** — set `assignee_employee_id`; on change, locks clear and a `task_assigned` wake fires.
2. **Manager delegation** — a manager beat creates children via `decomposition_claim`, each carrying
   its own assignee.
3. **Structured mention** — a typed employee mention in a comment fires a `message` wake; *plain
   text naming an employee does not assign or wake* (spec 02 §3).

**Invokability gate** (orthogonal to assignment): even a correctly-assigned employee won't run if
`paused / terminated / pending-approval / invalid-org-chain / budget-blocked`. Runs for a terminated
employee or a broken org chain are cancelled.

Recovery owner selection (failure path, off by default) *recommends* an owner by walking
assignee → reporting chain → creator chain → root — it **never auto-reassigns** (spec 02 §8).

---

## 5. The role brief (`.md`) — thin, not a protocol

Each role has a brief markdown file (the chorus analog of Paperclip's `HEARTBEAT.md`) — but it is
**thin**, because the coordination protocol is *code* (the scheduler does checkout, status, run-id,
"never retry a 409"). The brief is just the role's domain identity:

```markdown
---
role: engineer
memory_scope: project
---
You implement and ship changes. Make the smallest change that satisfies the task.
Definition of done: the verifier on the task must pass (tests + CI green).
House rules: never force-push; leave a PR link in the final comment.
```

Paperclip needs a 440-line `HEARTBEAT.md` because its agent is autonomous across a process boundary
and must be *told* the whole protocol. chorus enforces the protocol in the kernel, so the brief
shrinks to role + DoD framing + house rules.
