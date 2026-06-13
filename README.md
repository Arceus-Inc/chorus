# chorus

> **dream** completes one task. **chorus** runs the org that completes one sprint.

chorus is an **SDK** — a library, exactly like [dream](https://github.com/Arceus-Inc/dream).
It is not a running company and it is not bound to any particular repository. It
ships the abstractions for *a workforce of agents that do durable, assignable
work*; the **consumer** supplies the workspace those agents act on.

One-line charter: **chorus is everything that makes a `dream` task belong to a
named employee in an org, and turns its artifacts into landed work.**

---

## The product map

```
dream      one task        →  the employee (plan → sprint → evaluate loop)
chorus     one sprint      →  the org of employees that do durable work   ← this repo
horizon    one company     →  strategy / OKRs / direction
lattice    the people      →  employee growth + memory consolidation
```

Strict bottom-up dependency. **chorus depends on dream; nothing depends
sideways.** chorus, horizon, and lattice are siblings that never import each
other — they meet only at the data layer (ledger, org repo, memory repo) and at
`dream.contracts` typed Protocols.

## What chorus owns

- **Identity — `Employee`.** Who an agent is: name, role, the role's toolset
  (built on `dream.roles`), its memory scope. A `dream` run is always *somebody's*.
- **Org-as-data — `Workforce`.** The org chart (managers ↔ reports) as data,
  not a process tree. Hire/fire is an edit to that data.
- **Task ledger — the DAG.** Plans with `depends_on` edges, states, and scored
  selection. The single source of truth for "what work exists and where it is."
- **Scheduler.** Dispatches only *eligible* tasks (dependencies satisfied),
  enforces concurrency/cost caps, and **re-invokes a manager when its children
  complete** — push-driven, never blocking.
- **Assignment.** Which employee gets which task (role match + scoring).
- **Definition-of-done.** Generated at intake, persisted on the plan, and gated
  by the **evaluator against the real artifact** — never a self-report.
- **Outcome integration.** The role-specific "land the work" step: for an
  engineer, PR → CI → repair → merge; for others, persisting the role's artifact.

## The boundary — what chorus must NOT do

Scope discipline is the whole game.

- chorus does **not** reimplement the sprint loop. `dream`'s planner → generator
  → evaluator already runs it. chorus *calls* it.
- chorus does **not** decide company direction (that is horizon) or how
  employees grow (that is lattice).
- Hierarchy is **data, not topology**: no nested process trees. A manager never
  blocks awaiting a report — delegation is a ledger write; completion *events*
  drive re-invocation.

## First principles (inherited bets)

| Bet | How chorus honours it |
|---|---|
| Hierarchy is data, not topology | The org chart and the task DAG are rows/files; the runtime is a flat set of durable sessions. |
| No unbounded agent trees, ever | A manager never blocks on a report; the scheduler enforces caps. |
| The ledger is the source of truth; push-driven, not polling | Every task transition is a durable write; completion events drive the next step. |
| The evaluator sees outcomes, not prose | Definition-of-done is generated at intake and verified against the real artifact. |
| State lives in rows, not process memory | Locks, holds, claims, and recovery owners are persisted, so any worker can crash and another resumes by reading the ledger. |

## Roadmap

- **M1 — One engineer, full vertical.** A single `Employee` takes a task,
  runs it via `dream`, has its DoD generated at intake and verified by the
  evaluator, then lands the outcome (PR → CI → repair → merge). *Proves the
  dream↔chorus seam and outcome-landing end to end.*
- **M2 — Two engineers, cross-employee interaction.** Concurrency, a task DAG
  with dependency edges, mailbox, three memory scopes.
- **M3 — One manager, two reports.** The Manager role: decompose → dispatch →
  get re-invoked on child completion → integrate. *Proves hierarchy-as-data and
  non-blocking delegation.*
- **M4 — Full dynamic org.** Product/PM + Analyst roles, dynamic hire/fire as
  org-data edits, scored selection across a heterogeneous workforce. Exposes
  (does not build) the seams horizon and lattice plug into.

## Status

🚧 Pre-implementation. This repo currently holds direction only; M1 is next.

## License

TBD.
