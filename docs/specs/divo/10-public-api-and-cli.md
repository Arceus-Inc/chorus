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

    # intake (replaces horizon)
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
`AppendOnlyMemoryWriter`, the dream board `ClaimManager`, the `Scheduler`, and injects them. Nothing
else creates concrete classes.

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
