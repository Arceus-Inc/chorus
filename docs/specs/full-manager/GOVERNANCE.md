# §5 governance — the generalized governed-action queue

Status: **implemented** on `dev/m3-governance` (Slices 1–6, branched off `main`). Gate green — ruff +
mypy `--strict` + full pytest. Closes the §5 deferrals in
[06.5-deferred-from-spec04.md](../divo/06.5-deferred-from-spec04.md): `hire_employee`, `plan_approval`,
`board_approval`, and the third resolution `revision_requested`. Suite:
`examples/governance_suite.py` → `reports/m3-governance.html`.

## What exists, what's missing

Shipped (M3): the `approval` row + repo + the partial `GovernanceResolver` that owns the **task gate**
(acceptance / authorization), CLI verbs (`approval list/open/approve/deny`), and the `human_approval`
DoD hook. The resolver is hard-wired to task subjects and a binary approve/deny.

Missing: every other governed action. `approval` has no notion of *which* governed action it is; there
is no employee `pending` state; there is no `revision_requested`; and the resolver owns the side-effect
inline, so a new action means editing the resolver.

## The shape (Approach A — a registry of governed-action handlers)

```
GovernancePolicy (declarative, injected)        — decides WHEN a gate is required
        │  auto-open at the call site (decompose / hire / land)
        ▼
GovernanceResolver.open(action, subject) ──► approval row (pending) + handler.on_open(park subject)
        │
   human / CLI resolves (3-way)
        ▼
GovernanceResolver.resolve(approval, decision) ─► registry.get(action).on_<decision>(ledger, approval)
        │   one atomic ledger txn + one audited Activity
        ▼
ActionOutcome (subject's new status + wakes fired)
```

The resolver is a **thin, atomic, audited dispatcher**. Each governed action is one small
`GovernedAction` handler that owns its open/approve/deny/revise org mutation — mirroring the existing
`LanderRegistry` / `RoleRegistry` / `DoDKind`-dispatch idiom. Adding a fifth action later is one new
handler, no resolver edit.

Design rules honoured: dispatch on **typed enums**, never raw strings; no `getattr`/`setattr`; one file
per handler (no god file); pure-chorus and dream-free (governance is a ledger mutation, not a beat).

## 1. Data model

```python
class ApprovalAction(StrEnum):        # the governed action — the spec-04 §5 `type`
    HIRE_EMPLOYEE   = "hire_employee"
    PLAN_APPROVAL   = "plan_approval"
    BOARD_APPROVAL  = "board_approval"
    BUDGET_OVERRIDE = "budget_override"   # stays owned by the §3 enforcer; modelled for completeness
    TASK_GATE       = "task_gate"         # today's acceptance/authorization gate, folded in

class ApprovalStatus(StrEnum):        # + the third resolution
    PENDING; APPROVED; DENIED; EXPIRED
    REVISION_REQUESTED = "revision_requested"

class ApprovalSubjectKind(StrEnum):   # + employee (plan→TASK subject, board→ARTIFACT subject)
    BUDGET_INCIDENT; TASK; ARTIFACT
    EMPLOYEE = "employee"

class EmployeeStatus(StrEnum):        # + the pending state hire_employee needs
    IDLE; ACTIVE; RUNNING; PAUSED; ERROR; TERMINATED
    PENDING = "pending"
```

`Approval` gains one field: `action: ApprovalAction` (default `TASK_GATE` for backward construction).
`gate_kind` stays, meaningful only for `TASK_GATE`. `EmployeeStatus.PENDING` is added to the kernel's
`_UNINVOKABLE_EMPLOYEE_STATUSES` — a pending hire can never be leased for a beat.

**Migration 0015** — `approval.action`, via the rename-rebuild parity pattern used by 0014 (so the
stored DDL matches the declarative `schema/approval.sql`, keeping the parity test green). Backfill:

```sql
action = CASE subject_kind WHEN 'budget_incident' THEN 'budget_override' ELSE 'task_gate' END
```

The new *enum values* (`revision_requested`, `employee`, `pending`) need no DDL — those columns carry no
DB `CHECK` (same precedent as `TaskStatus.REJECTED`). So Slice 1 is one narrow migration.

## 2. The dispatch seam

```python
class ApprovalDecision(StrEnum):          # replaces resolve(approve: bool)
    APPROVE = "approve"
    DENY = "deny"
    REQUEST_REVISION = "request_revision"

@dataclass(frozen=True)
class ActionOutcome:                       # what a handler's side-effect did
    subject_status: str                    # the gated subject's new status value
    wakes_fired: int = 0

class GovernedAction(Protocol):            # one per action — independently testable, dream-free
    action: ApprovalAction
    def on_open(self, ledger, approval) -> None: ...        # park / flag the subject at open
    def on_approve(self, ledger, approval) -> ActionOutcome: ...
    def on_deny(self, ledger, approval) -> ActionOutcome: ...
    def on_revise(self, ledger, approval) -> ActionOutcome: ...

class GovernanceRegistry:                  # action → handler, fail-closed (unknown action raises)
    @classmethod
    def from_actions(cls, actions: Iterable[GovernedAction]) -> "GovernanceRegistry": ...
    def get(self, action: ApprovalAction) -> GovernedAction: ...

def default_actions(ledger) -> list[GovernedAction]:   # TaskGate, Hire, Plan, Board
    ...
```

The resolver shrinks to a dispatcher (one ledger transaction, one audited `Activity` per call):

```python
class GovernanceResolver:
    def __init__(self, ledger, registry: GovernanceRegistry | None = None): ...

    def open(self, *, action, subject_id, reason, gate_kind=None, subject_kind=None, now) -> Approval:
        handler = self._registry.get(action)
        with txn: approvals.request(pending) → handler.on_open(approval) → audit GATED
        return approval

    def resolve(self, approval_id, *, decision: ApprovalDecision, decided_by_user_id, now) -> ResolveOutcome:
        handler = self._registry.get(approval.action)
        with txn: approvals.set_status(...) → handler.on_<decision>(approval) → audit
        return ResolveOutcome(approval_id, subject_id, decision, subject_status, wakes_fired)
```

`open_task_gate(...)` stays as a thin wrapper (`open(action=TASK_GATE, gate_kind=…, subject_kind=TASK)`)
so the existing `human_approval` DoD hook and CLI keep working unchanged. `ApprovalRepo` gains
`set_status(id, status, *, decided_by_user_id)` generalising `approve`/`deny` (which stay as wrappers)
to cover `revision_requested`.

## 3. The four handlers (open + resolve semantics)

Each is one file under `chorus/governance/_actions/`.

### TaskGateAction (`_task_gate.py`) — `TASK_GATE`
The existing `_apply_task`, lifted verbatim, plus `on_revise`.
- `on_open`: park the task `BLOCKED`.
- `on_approve`: `ACCEPTANCE` → `finalize_beat(PASSED)` → `DONE`; `AUTHORIZATION` → `TODO` + wake assignee.
- `on_deny`: `ACCEPTANCE` → DoD `FAILED`, stays `BLOCKED`; `AUTHORIZATION` → `CANCELLED`.
- `on_revise`: task → `TODO` + a `RECOVERY` wake to the assignee (send the work back).

### HireEmployeeAction (`_hire.py`) — `HIRE_EMPLOYEE`, subject = employee id
`request_hire` creates the employee `PENDING` **and** its `budget_policy` up front (role + cents are
known at request time, so nothing is stuffed stringly into `reason`). The gate only flips activation.
- `on_open`: assert the subject employee is `PENDING` (a guard, no side-effect).
- `on_approve`: `PENDING` → `ACTIVE`. Subject status `active`. (The budget policy already exists; the
  handler re-upserts idempotently so the spec's "activates + upserts budget" reads true at approval.)
- `on_deny`: `PENDING` → `TERMINATED`.
- `on_revise`: stays `PENDING`; the requester amends (e.g. re-`request_hire` with a new budget) and a
  fresh gate opens. Subject status `pending`.

A `PENDING` employee is uninvokable and its budget policy is inert until activation, so a never-approved
hire is harmless (it occupies a row but is never leased). No staging table — no migration beyond 0015.

### PlanApprovalAction (`_plan.py`) — `PLAN_APPROVAL`, subject = parent task id
A manager decomposed; the children exist `BLOCKED` (held by the gate). The approval signs off the plan.
- `on_open`: the parent already owns `BLOCKED` children (created so by decompose under policy); no-op.
- `on_approve`: every child `BLOCKED` → `TODO` + a `TASK_ASSIGNED` wake to its assignee. Parent unchanged.
- `on_deny`: every child → `CANCELLED`; parent → `BLOCKED` + a recovery card (the plan was rejected).
- `on_revise`: every child → `CANCELLED`; parent → `TODO` + a `RECOVERY` wake to the manager (re-plan).

### BoardApprovalAction (`_board.py`) — `BOARD_APPROVAL`, subject = artifact id
Gates promotion of a landed deliverable artifact to the board / external.
- `on_open`: append a `GATED` activity on the artifact; no task status change.
- `on_approve`: append a `PROMOTED` activity on the artifact (and, if present, set its promoted flag via
  an `artifact_revision`). Subject status `promoted`.
- `on_deny`: append `DENIED`; not promoted.
- `on_revise`: wake the artifact's source-task assignee (`RECOVERY`) to revise. Subject status `revision`.

`BUDGET_OVERRIDE` is **not** registered here — budget incidents keep resolving via the §3 enforcer; the
resolver rejects a `budget_override` subject the same way it does today, so there is no double-owner.

## 4. GovernancePolicy (auto-open)

A declarative, injected value (alongside `Caps`), resolved fail-closed — **no gate unless opted in**:

```python
@dataclass(frozen=True)
class GovernancePolicy:
    require_hire_approval: bool = False
    plan_approval_roles: frozenset[str] = frozenset()      # manager roles whose plans need sign-off
    board_artifact_classes: frozenset[str] = frozenset()   # artifact classes that promote to the board

    def hire_gate_required(self) -> bool: ...
    def plan_gate_required(self, manager_role: str) -> bool: ...
    def board_gate_required(self, artifact_class: str) -> bool: ...
```

Auto-open call sites (the kernel opens the gate; humans/CLI resolve it):

| Action | Where it opens | Behaviour when **not** required |
|---|---|---|
| `hire_employee` | `request_hire` facade verb | activate the employee immediately (today's direct hire) |
| `plan_approval` | the `decompose` lifecycle, post-fan-out | children created `TODO` as today |
| `board_approval` | the outcome-landing path (artifact recorded) | artifact lands ungated as today |

Policy default (empty) = today's behaviour exactly, so every existing test and run is unchanged until an
org opts in.

## 5. Integration points

- `chorus/lifecycle/_decompose.py` — when `policy.plan_gate_required(manager_role)`, create children
  `BLOCKED` and open a `PLAN_APPROVAL` gate on the parent (one gate per decomposition). Threads the
  policy in the same way the depth cap is threaded.
- `chorus/facade.py` — `request_hire(name, role, *, budget_cents)`: create the employee `PENDING` + a
  `pending_employee` staging row; if `policy.hire_gate_required()` open a `HIRE_EMPLOYEE` gate, else
  activate immediately. CLI `hire` routes through it.
- the lander / `_land_outcome` path — when an artifact's class ∈ `policy.board_artifact_classes`, open a
  `BOARD_APPROVAL` gate on the artifact.
- `GovernanceResolver` is constructed with the `default_actions(ledger)` registry in the facade/CLI
  composition root.

## 6. CLI / facade surface

- `approval list` — now shows the `action` column.
- `approval approve <id>` / `approval deny <id>` / **`approval revise <id>`** (the new 3-way verb).
- `hire <name> <role> [--budget cents]` — routes through `request_hire` (gated or immediate per policy).
- `approval open …` — unchanged (task gate).

## 7. Build order (TDD; e2e at each checkpoint)

1. **Data model + migration 0015** — enums, `Approval.action`, `EmployeeStatus.PENDING` (uninvokable),
   migration up + parity + backfill, repo round-trip incl. `set_status`. *(checkpoint: repo + migration tests)*
2. **Dispatch seam** — `GovernedAction`/`ActionOutcome`/`ApprovalDecision`/`GovernanceRegistry`; resolver
   refactor to dispatcher; `TaskGateAction` re-expresses today's gate + `on_revise`. *(checkpoint: existing
   governance tests stay green + a 3-way resolve test)*
3. **hire_employee** — handler + `request_hire` (creates employee `PENDING` + budget policy) + policy +
   CLI. *(e2e: request → pending → approve → active + budget / deny → terminated)*
4. **plan_approval** — handler + decompose integration + policy. *(e2e: decompose → gate → approve →
   children run; revise → re-plan)*
5. **board_approval** — handler + landing integration + policy. *(e2e: land → promote gate → approve →
   promoted)*
6. **Final e2e + HTML report** — one governed org run exercising all four gates + `revision_requested`;
   `reports/m3-governance.html`. Update [06.5](../divo/06.5-deferred-from-spec04.md) §5 to shipped.

Each checkpoint runs the gate: `ruff` + `mypy --strict` + full `pytest`.

## Out of scope

`budget_override` (stays with §3), DoD revisability (§1, a separate 06.5 item), trust presets (§4),
employee re-hire workflows, and approval expiry automation (the `EXPIRED` status exists; a sweep that
sets it is horizon).
