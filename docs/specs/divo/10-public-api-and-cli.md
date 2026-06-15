# 10 — Public API & CLI

The surface a consumer touches. chorus's equivalent of Paperclip's
[`07-api-realtime-auth-mcp`](../../paperclip-research/07-api-realtime-auth-mcp.md) — but since chorus
is an in-process **library**, its "API" is Python objects, not a REST/MCP surface. (The REST/MCP/auth
stack only reappears in Arceus, which exposes chorus over a network.)

---

## 1. The `Chorus` facade — the composition root

One object, built once, wires the concrete backends and is the only thing that imports dream (the
"wiring" from earlier). Public methods:

```python
class Chorus:
    @classmethod
    def build(cls, *, db_path, org_repo, memory_repo, dream, *,
              roles=None, caps=None) -> "Chorus": ...

    # intake (stub until horizon ships — the horizon handoff seam)
    def submit(self, intent: str, *, assignee=None, dod=None, depends_on=()) -> Task: ...

    # the heartbeat
    async def tick(self) -> TickReport: ...          # one kernel pulse
    async def run_forever(self, interval_s=2.0): ...  # drive ticks until stopped

    # org-as-data
    def hire(self, *, name, role, reports_to=None) -> Employee: ...
    def terminate(self, employee_id: str) -> None: ...

    # cron
    def add_routine(self, *, employee, intent_template, schedule, target="spawn_task") -> Routine: ...

    # inspection (read model)
    def status(self) -> WorkforceStatus: ...          # employees, open tasks, runs, incidents
    def task(self, task_id: str) -> TaskView: ...
    def events(self, *, after=None) -> Iterator[Event]: ...
    def stuck(self) -> list[TaskView]: ...            # the blocked inbox (spec 08)
```

`build()` is the composition root: it news-up `SqliteLedger`, `GitWorkforce`, `GitMemoryStore`, the
`AppendOnlyMemoryWriter`, the `Scheduler` (checkout + lease on the ledger), and injects them. Nothing
else creates concrete classes.

### The read-model return shapes (typed, not dicts)

The inspection methods return frozen dataclasses so consumers bind to a typed surface the public-API
test pins — never ad-hoc dicts:

```python
@dataclass(frozen=True)
class TickReport:                 # what one pulse did (spec 03)
    at: datetime
    recovered: int                # stale leases reaped / stranded tasks reconciled
    routines_fired: int
    wakes_dispatched: int
    beats_started: int            # async dispatches kicked off this tick (not awaited)
    blocked_by_budget: int

@dataclass(frozen=True)
class WorkforceStatus:            # the company at a glance (spec 08)
    employees: tuple[EmployeeView, ...]   # name, role, status, last_beat_at, spend
    open_tasks: int
    running_beats: int
    blocked: tuple[TaskView, ...]         # the blocked inbox, ranked
    open_incidents: tuple[IncidentView, ...]  # budget / recovery

@dataclass(frozen=True)
class TaskView:                   # one task, resolved for reading
    id: str; intent: str; status: TaskStatus; priority: str
    assignee: str | None          # employee name or human id
    goal_id: str | None; depth: int; request_depth: int
    dod: Verifier; latest_run: RunView | None
    liveness: str                 # 'healthy' | 'stalled' (derived, spec 02 §3)
    blockers: tuple[str, ...]     # unresolved task_dependency leaves
```

These are **read projections**, not the ledger rows — they resolve names and liveness so the caller
never re-implements the queries. `events()` yields the spec 08 `Event` envelope verbatim.

### Public exceptions (the typed failure surface)

The facade raises a small, pinned hierarchy — callers catch types, never parse messages:

```python
class ChorusError(Exception): ...              # root of everything chorus raises
class InvalidIntake(ChorusError): ...          # submit() with a bad intent/assignee/dod
class UnknownEmployee(ChorusError): ...         # hire/assign to a missing employee
class OrgInvariantViolation(ChorusError): ...   # reports_to cycle, double assignee, terminate root
class RolePluginInvalid(ChorusError): ...       # registration validation failed (spec 09 §1)
class RolePluginConflict(ChorusError): ...      # slug re-register without replace=True
class BudgetBlocked(ChorusError): ...           # submit/dispatch refused by a hard-stop
class PackageImportError(ChorusError): ...      # version gate / unresolved refs (spec 09 §3)
```

`dream`-originated faults (`RunTaskError`, `TaskCancelled`, spec 05) are **not** re-wrapped — they
surface as the dream types so the seam stays honest; chorus only adds its own org-level errors above.

A consumer (an `examples/` file, or Arceus) does only:

```python
import dream
from chorus import Chorus

c = Chorus.build(db_path="./chorus.db", org_repo="./org", memory_repo="./mem", dream=dream)
c.hire(name="alice", role="engineer")
c.submit("Build the login page", assignee="alice")
await c.run_forever()
```

---

## 2. The CLI — `chorus`

A thin wrapper over the facade (the chorus analog of `paperclipai`):

```
chorus submit "<intent>" [--assignee E] [--dod CMD] [--depends-on T,...]
chorus tick                       # one pulse (cron/dev)
chorus run                        # run_forever
chorus employees [list|hire|terminate]
chorus routines  [list|add|pause]
chorus inspect   [status|task <id>|events|stuck]
chorus export <path> | import <path>     # portable package (spec 09)
```

Intake via the CLI is the only way work enters until well after M4 (no inbound Slack/GitHub channels
— those are Arceus, post-M4).

---

## 3. The public-API pin (`tests/test_public_api.py`)

Like dream, **the public API is exactly what `chorus/__init__.py` re-exports**, and a test pins it so
a refactor can't silently change the surface. Everything else (`_`-prefixed modules) is private and
may change.

```python
# chorus/__init__.py  — the entire public surface
from chorus.facade import Chorus
from chorus.roles import Role, RoleManifest, RolePlugin, default_roles
from chorus.ledger import Task, TaskStatus, ExecPlan      # re-exports dream contracts where shared
from chorus.heartbeat import Wake, WakeReason, TickReport
from chorus.cron import Routine, parse_cron
from chorus.outcomes import Verifier, Command, AgentReview, HumanApproval
from chorus.events import Event   # the taxonomy (spec 08)
__all__ = [ ... ]   # pinned by test_public_api.py
```

---

## 4. Contrast with Paperclip's surface (why chorus has no REST/MCP)

Paperclip's agent contract is a **REST API fronted by a stateless MCP server**, with per-run JWTs and
a WebSocket for streaming — *all machinery to bridge the process boundary* (research
[07](../../paperclip-research/07-api-realtime-auth-mcp.md)). chorus has no process boundary:

| Paperclip | chorus |
|---|---|
| agent "phones home" over REST (`checkout`, `comment`, `create child`) | the kernel does these in code; the employee's tools are Python callables |
| stateless **MCP server** (`paperclip*` tools → REST) | no MCP — tools are registered on the dream engine in-process |
| **auth**: per-run JWT, board API keys, agent keys | none — no network actor to authenticate (auth is Arceus) |
| **WebSocket** realtime fan-out | in-process event bus; `chorus.events()` iterator |

So extending chorus's "agent contract" = registering a tool/role on the engine, not editing a
`tools.ts` + a route. The network surface is purely an Arceus concern, layered *on top of* this
library API.

---

## 5. The horizon handoff seam (on `submit`)

`submit()` is the reserved intake seam (spec 00 §5a). Today it is the *stub* — a human/CLI/cron hands
in an intent and chorus creates a flat `depth=0` task. When **horizon** ships it becomes the writer
of intake: horizon owns *what to do next* (OKR-driven prioritisation, direction) and drives the same
`submit` path (or writes `task`/`goal` rows directly), while chorus keeps executing exactly as it
does now. The contract chorus pins so horizon can plug in without a kernel change:

- `submit` stays the single intake entry point; horizon calls it (or the ledger seam beneath it) —
  chorus never grows a second intake door.
- `task.depth=0` is the **intake slot** horizon fills; `goal_id` resolves into the `goal` tree
  horizon will own (spec 01 Cluster D). Until then, operators seed `company` goals and `submit`
  attaches to them.
- chorus does **not** prioritise across intake (no "what's most important" logic) — it executes what
  it's given in scheduler order (spec 03). That judgement is horizon's, reserved, not stubbed-in.

---

## 6. API stability & deprecation policy

The pinned surface (§3) is a contract, versioned with the package:

- **Semver.** chorus follows semver; a breaking change to the `__all__` surface or a public
  dataclass/exception shape is a **major** bump. Additive changes (new method, new optional field,
  new `Event` type) are **minor**.
- **Deprecation window.** a public symbol is deprecated for **one minor cycle** before removal:
  it keeps working, emits a `DeprecationWarning` naming the replacement, and is listed in the
  changelog — never removed in the same release it's deprecated.
- **`_`-prefixed is private.** anything not re-exported from `chorus/__init__.py` may change at any
  time; `test_public_api.py` is the enforcement, so an accidental surface change fails CI.
- **Contracts track dream.** the `dream.contracts` re-exports (spec 05) move with dream's contract
  version; a dream MAJOR that breaks a Protocol is a coordinated chorus MAJOR.
