# 14 — The public facade (two tiers: simple front door, complete kernel)

`Chorus` is the composition root (spec 10 §1) — the one object a consumer touches: `from chorus
import Chorus`, `Chorus.build(...)`, then call methods. Today it is **half-wired**: the basic-loop
verbs work, but **intake (`submit`) and the read model (`status`/`task`/`stuck`/`events`) are
`NotImplementedError` stubs**, and several *built* capabilities (governance resolution, budgets,
trust) have no facade verb at all — reachable only by importing their modules.

This spec closes that **as two tiers**:

- **High-level (flat on `Chorus`)** — the "anyone can run a company" front door: `hire`, `submit`,
  `run_forever`, `status`, `stop`, `assign`. Reads exactly like the example in §0.
- **Low-level (grouped accessors)** — every niche capability, namespaced so it never clutters the
  simple story: `org.governance.*`, `org.budgets.*`, `org.trust.*`, `org.inspect.*`, `org.routines.*`,
  `org.workforce.*`, `org.dod.*`.

The work the **agents own** (decompose, verdict) is on **neither** tier — it lives inside the beat (§5).

It is spec 10 (public API) made complete, touching [08 — Observability](08-observability.md) (the read
model), [04 — Outcomes & governance](04-outcomes-and-governance.md) (governance/budgets/trust),
and [02 — Lifecycle](02-lifecycle-and-recovery.md) (intake). Memory is **not** on the facade — it is
the employee's own faculty (§5/§1).

---

## 0. What is already true

`Chorus.build(db_path, org_repo, memory_repo, dream, beat_runner_for=…)` already wires the concrete
backends (ledger, `LedgerWorkforce`, `AppendOnlyMemoryWriter`, `Scheduler`, `EventBus`,
`LedgerInspector`) and is the only thing that imports dream. The execution engine is supplied by the
consumer through `beat_runner_for` (`chorus_harness.EmployeeHarnessFactory`); **chorus core stays
dream-free** and this spec does not change the construction contract (§6).

**The high-level tier this spec makes run** — the consumer's whole story, end to end:

```python
from chorus import Chorus
from chorus_harness import EmployeeHarnessFactory
import dream

factory = EmployeeHarnessFactory(company_root="./work", creds=...)
org = Chorus.build(db_path="company.db", org_repo="./org", memory_repo="./memory",
                   dream=dream,
                   beat_runner_for=factory.runner_for,   # how a beat runs
                   landers=factory.landers)              # how its output lands

org.hire(name="moe", role="manager")
org.hire(name="eng1", role="engineer", reports_to="moe")
task = org.submit("build a login page", assignee="moe")
await org.run_forever()                                   # the background heartbeat rolls it
org.status()
```

The niche surfaces sit one level down, for power users / Arceus / the CLI:

```python
org.governance.resolve(approval_id, decision=ApprovalDecision.APPROVE, by="me")
org.budgets.set(BudgetScope.EMPLOYEE, "moe", 5000)
org.trust.set_task(task_id, preset=TrustPreset.LOW_TRUST_REVIEW)
org.inspect.task(task_id)
org.routines.add(employee="moe", intent="weekly review", schedule="0 9 * * 1")
```

---

## 1. Scope

**In:** a full **audit-and-wire** in two tiers (above). The stubs (`submit`, `status`, `task`,
`stuck`, `events`) are implemented; every orphaned capability gets a verb under the right group; the
read-model projections (`LedgerInspector.status/task/stuck`) are implemented.

**Migration:** a few verbs that shipped *flat* are **moved into their group** so the tiering is
consistent — `request_hire`/`request_promotion` → `org.governance`, `export/import_workforce` +
`register_role` → `org.workforce`, `revise_dod` → `org.dod`, and the M4-S1 routine verbs
(`add_routine` …) → `org.routines`. Pre-1.0, deliberate; the CLI and `test_public_api` move with them
(§7). `status` stays flat (the one-call glance); detailed reads go under `org.inspect`.

**Out (deferred, with the reason):**

| Deferred | Why |
|---|---|
| **`decompose` / `submit_verdict` on either tier** | **employee tools**, not operator verbs — a manager decomposes via the decompose `BaseTool` mid-beat, a reviewer records a verdict through the review beat. Work the agents own stays inside the beat; the facade never grows a door into it (§5). |
| **A batteries-included constructor** (`build_company(creds=…)`) | the construction contract (bring-your-own execution via `chorus_harness`) is unchanged; a convenience wrapper is a separate, optional follow-up (§6). |
| **`org.memory` (read *or* write)** | memory is the **employee's own faculty**, not an operator surface — a beat reads its memory scope when it rehydrates and writes a sprint delta after it runs, both inside the beat lifecycle. Exposing read or write on the facade would lift an internal employee mechanism onto the operator surface (same category as decompose/verdict). If memory-*inspection* is ever wanted it is an observability concern (`org.inspect`), not an employee-faculty verb. |
| **`horizon` intake / `lattice` consolidation** | sibling-repo seams; `submit` and `MemoryWriter` are the reserved slots they plug into, not things this spec fills. |

---

## 2. The surface

### 2.1 High-level — flat on `Chorus` (the front door)

The minimal "operate a company" set. 🟢 already wired · 🔴 this spec.

| Verb | | Notes |
|---|---|---|
| `Chorus.build(...)` | 🟢 | composition root (§0) |
| `hire(name, role, reports_to=None)` · `terminate(employee_id)` | 🟢 | org as data |
| `submit(intent, *, assignee=None, dod=None, depends_on=(), priority=TaskPriority.MEDIUM, trust_preset=None, trust_boundary=None)` | 🔴 | depth-0 intake (§3) |
| `assign(task_id, employee_id, *, assigned_by=None)` · `send_message(message)` | 🟢 | the async handoffs |
| `tick()` · `run_forever()` · `stop()` | 🟢 | the heartbeat |
| `status()` | 🔴 | the one-call company glance → `WorkforceStatus` |

### 2.2 Low-level — grouped accessors

Each group is a thin facade object reached by a property on `Chorus` (`org.budgets` →
`BudgetsFacade(ledger, …)`); the group holds only the backends it needs (§2.3). 🔴 = this spec,
✦ = migrated from a flat verb (§1).

| Group | Verbs | Delegates to |
|---|---|---|
| `org.inspect` | 🔴 `task(id)` · `stuck()` · `events(*, after=None)` · `scrum_packet(id)` · `org_report()` | `LedgerInspector` + `EventBus.replay` |
| `org.governance` | ✦ `request_hire` · ✦ `request_promotion` · 🔴 `open_gate(task_id, *, gate_kind, reason)` · 🔴 `open_plan_gate(parent_id, *, reason)` · 🔴 `resolve(approval_id, *, decision, by)` · 🔴 `approvals()` | `GovernanceResolver` + `ledger.approvals` |
| `org.budgets` | 🔴 `set(scope, scope_id, amount_cents, *, warn_percent=…, window=…)` · 🔴 `raise(policy_id, new_amount_cents, *, by)` · 🔴 `dismiss_incident(incident_id, *, by)` | `ledger.budget_policies` + `BudgetEnforcer` |
| `org.trust` | 🔴 `set_task(task_id, *, preset, boundary=None)` | `ledger.tasks.set_trust` (new 1-line setter) |
| `org.routines` | ✦ `add(...)` · ✦ `list(*, employee=None)` · ✦ `get(id)` · ✦ `pause(id)` · ✦ `resume(id)` | M4 S1 engine (migrated from the flat `add_routine` …) |
| `org.workforce` | ✦ `register_role(plugin)` · ✦ `export(org_repo)` · ✦ `import_(org_repo)` | workforce / `copy_org` |
| `org.dod` | ✦ `revise(task_id, new_verifier, *, by)` | `lifecycle.revise_dod` |

**No stringly.** Every enum-typed argument crosses as its enum (`TaskPriority`, `ApprovalDecision`,
`ApprovalGate`, `BudgetScope`, `BudgetWindow`, `TrustPreset`), never a string. **Fail-closed**: an
unknown employee/task/approval raises the typed error (`UnknownEmployee`, `KeyError`,
`GovernanceError`) **before** any write.

### 2.3 The group-accessor pattern

A group is a small frozen facade returned by a cached property — no behaviour beyond typed delegation,
so each group is understood and tested in isolation:

```python
class Chorus:
    @property
    def budgets(self) -> BudgetsFacade:
        return self._budgets            # built once in __init__ over the same ledger/enforcer
```

Groups share the one ledger/scheduler/inspector the composition root already holds; they add no new
state, just a named surface. The high-level flat verbs and the groups are **two views of one object**,
never two objects to keep in sync.

---

## 3. Intake — `submit` (spec 10 §5)

The reserved intake seam; creates a flat `depth=0` task and wires assignment / DoD / dependencies /
trust in one call:

```
submit(intent, *, assignee=None, dod=None, depends_on=(),
       priority=TaskPriority.MEDIUM, trust_preset=None, trust_boundary=None) -> Task
  1. task := tasks.submit(Task(id=…, intent, priority, depth=0,
                               trust_preset=trust_preset, trust_boundary=trust_boundary))
  2. if dod              : dod.create(task.id, dod)
  3. for d in depends_on : dependencies.add(task.id, depends_on=d)
  4. if assignee         : assign_task(ledger, task.id, slugify(assignee))   # sets owner + wakes
  5. return task
```

When `horizon` ships it becomes the writer of intake and drives this same path — chorus never grows a
second intake door. An unassigned `submit` leaves the task in `backlog` for a later `assign`.

---

## 4. The read model (spec 08) — the largest piece

`status()` (flat) and the `org.inspect.*` group are thin delegations; the work is implementing the
**`LedgerInspector` projections** that `status`/`task`/`stuck` currently stub. Pure reads over the
ledger + event log — names resolved, liveness derived from durable state (not byte-silence), blockers
from the unresolved `task_dependency` leaves. The view dataclasses already exist (`WorkforceStatus`,
`TaskView`, `EmployeeView`, `RunView`, `IncidentView`); `scrum_packet`/`org_report` are already
implemented on the inspector.

| Surface | Returns | Projection |
|---|---|---|
| `org.status()` *(flat)* | `WorkforceStatus` | employees (+ last-beat/spend), open-task count, running beats, blocked inbox, open incidents |
| `org.inspect.task(id)` | `TaskView` | assignee name, DoD, latest run, derived `liveness`, `blockers` |
| `org.inspect.stuck()` | `list[TaskView]` | the blocked inbox — non-terminal tasks with no action-path primitive (spec 08 §2), ranked |
| `org.inspect.events(after=None)` | `Iterator[Event]` | `EventBus.replay` (already implemented) |
| `org.inspect.scrum_packet(id)` · `org.inspect.org_report()` | `ScrumPacketView` · `OrgObservabilityReport` | already implemented |

"Working vs stuck" is answered **structurally** from typed state, not guessed from timing.

---

## 5. Wiring the groups (delegation detail)

### 5.1 `org.governance` (spec 04 §5)
- `request_hire` / `request_promotion` — migrated from flat (unchanged behaviour).
- `open_gate(task_id, *, gate_kind: ApprovalGate, reason)` → `GovernanceResolver.open_task_gate`;
  `open_plan_gate(parent_id, *, reason)` → `open_plan_gate`.
- `resolve(approval_id, *, decision: ApprovalDecision, by: str)` → `GovernanceResolver.resolve`
  (raises `GovernanceError` on unknown/already-resolved). The facade *opened* gates but couldn't
  *resolve* them — this closes the loop.
- `approvals() -> list[Approval]` — the open-gate inbox (read).

### 5.2 `org.budgets` (spec 04 §3)
- `set(scope: BudgetScope, scope_id, amount_cents, *, warn_percent=…, window: BudgetWindow=…)` →
  `ledger.budget_policies.create` (create/update the scope's policy).
- `raise(policy_id, new_amount_cents, *, by)` → `BudgetEnforcer.raise_budget_and_resume`
  (`ValueError` if it doesn't exceed observed spend).
- `dismiss_incident(incident_id, *, by)` → `BudgetEnforcer.dismiss` (scope stays paused).

### 5.3 `org.trust` (spec 04 §4)
- `set_task(task_id, *, preset: TrustPreset, boundary: Mapping | None = None)` → a new one-line
  `tasks.set_trust(task_id, preset, boundary)` repo setter (the columns already persist via `submit`).

### 5.4 `org.routines` (M4 S1) — migrated
- `add` / `list` / `get` / `pause` / `resume` are the S1 verbs re-homed from flat
  (`add_routine`→`add`, `routine`→`get`, …). Same engine, same tests; the CLI's `routine` noun and any
  caller move to `org.routines.*`.

### 5.5 `org.workforce` — migrated
- `register_role` / `export` / `import_` re-homed from flat (`export_workforce`→`export`).

### 5.6 `org.dod` — migrated
- `revise(task_id, new_verifier, *, by)` re-homed from flat `revise_dod` (manager-authority + in-flight
  rules unchanged, spec 04 §1).

> **Not on the facade — memory is the employee's faculty.** A beat *reads* its memory scope when it
> rehydrates at the start of a run, and *writes* a sprint delta (derived from the run, not
> self-authored) when it finishes — both inside the beat lifecycle, driven by the harness, not by an
> operator. Putting `read` or `write` on the facade would lift an internal employee mechanism onto the
> operator surface. Inspecting stored memory, if ever wanted, is an observability concern for
> `org.inspect`, not an `org.memory` faculty verb.

> **On neither tier — `decompose` and `submit_verdict` are employee tools.** A manager *decomposes* by
> calling the decompose `BaseTool` mid-beat (`chorus_tools`, spec 02 §4); a reviewer *records a verdict*
> through the review beat (`CapabilityService.record_verdict`, spec 04 §1). These are actions the org
> performs **on itself, inside a beat** — not operator verbs. Putting them on the facade (flat *or*
> grouped) would let a human/Arceus reach around the workforce and mutate work the agents own, breaking
> "continuity lives in the ledger, decisions live in beats." They stay where they belong.

---

## 6. The construction contract (two injection seams)

`Chorus.build(...)` stays the single entry; the consumer supplies the execution engine via
`chorus_harness` (which owns dream + creds), keeping chorus core dream-free and the four-repo boundary
intact. Two **symmetric injection seams** plug the harness into the dream-free kernel, both
consumer-supplied (the kernel never imports `chorus_employee` or dream):

- **Execution** — `beat_runner_for=factory.runner_for`: how a dispatched beat *runs* (the
  role-faithful per-employee runner). The seam accepts either the resolver object or its bound method
  (a bare callable is wrapped to the `BeatRunnerFor` protocol via `runner_from`), so the §0 front door
  reads `beat_runner_for=factory.runner_for`.
- **Landing** — `landers=factory.landers`: how a passed beat's deliverable *lands* (the engineer's PR
  snapshot, the manager's subtree merge). The factory autowires `default_landers(company_root, ledger)`
  and exposes it as a property; unset, a passed beat still completes but records no role artifact.

Without the landing seam the §0 example would run a real beat whose output goes nowhere — so wiring it
is part of completing the front door, not a construction-contract change in spirit. A batteries-included
`chorus_harness.build_company(creds=…)` wrapper (both seams wired from one factory in ~3 lines) is a
legitimate **separate, optional** follow-up — noted, not built.

---

## 7. Build plan (TDD slices)

Each slice RED→GREEN→REFACTOR, gated `uv run ruff check` + `uv run mypy --strict src` + `uv run pytest
-q`. Order: **F1 → F2 → (F3 · F4 · F5 in parallel) → F6 → F7.**

| # | Slice | Checkpoint acceptance |
|---|---|---|
| **F1** | **Read model + `org.inspect`** — implement `LedgerInspector.status/task/stuck`; flat `status()` + the `org.inspect` group (task/stuck/events/scrum_packet/org_report) | `status()` projects a real org; `org.inspect.stuck()` lists a blocked task; `task(id)` resolves names + liveness + blockers |
| **F2** | **Intake** — implement flat `submit` (depth-0 + optional assignee/dod/deps/trust) | the §0 high-level example runs end to end: `build → hire → submit → run_forever → status` |
| **F3** | **`org.governance`** — group accessor; `open_gate` · `open_plan_gate` · `resolve` · `approvals` + migrate `request_hire`/`request_promotion` | open a gate → `resolve(APPROVE)` performs the mutation; deny leaves it gated |
| **F4** | **`org.budgets`** — `set` · `raise` · `dismiss_incident` | set a cap → breach pauses → `raise` resumes; `dismiss_incident` keeps it paused |
| **F5** | **`org.trust`** — `tasks.set_trust` + `set_task` + `submit(trust=…)` | a low-trust preset round-trips; inline-secret boundary still fails closed downstream |
| **F6** | **Migrate groups** — re-home `org.routines.*` (+ CLI noun) · `org.workforce.*` · `org.dod.*` from their flat verbs | the migrated verbs work under their group; CLI green; old flat names gone |
| **F7** | **Public API + e2e** — export the group types; update `tests/test_public_api.py`; one deterministic e2e running the §0 high-level snippet **and** touching one verb per group | `import chorus` → the front door reads like §0, every group is reachable, no `NotImplementedError` remains |

### Acceptance (the one bar)
**`import chorus` gives a two-tier kernel that's simple on top and complete underneath.** After F7: the
§0 high-level example runs unchanged (`hire`/`submit`/`run_forever`/`status` flat — anyone can use it);
every niche capability is reachable under its group (`org.governance/budgets/trust/inspect/routines/
workforce/dod`); there is **no `NotImplementedError`** on `Chorus` or `LedgerInspector`; and the
employee's own faculties — decompose, verdict, memory — are on neither tier, staying inside the beat.

---

## 8. What this deliberately leaves for later

- **Batteries-included constructor** (`build_company(creds=…)`) — a `chorus_harness` convenience over
  the unchanged `Chorus.build`; optional, separate.
- **Memory on the facade (read or write)** — memory is the employee's faculty (a beat reads it at
  rehydration, writes it after running), not an operator surface; inspection, if ever wanted, is an
  `org.inspect` concern (§5).
- **`horizon` / `lattice`** — `submit` and `MemoryWriter` are the reserved seams; the siblings fill
  them without a kernel change (spec 11 H1/L1).
