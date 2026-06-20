<div align="center">

# chorus

### An SDK for running an **org of AI agents** that completes one sprint.

*`dream` completes one task. **chorus** runs the org that completes one sprint.*

![python](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)
![tests](https://img.shields.io/badge/tests-1117%20passing-2ea44f)
![typing](https://img.shields.io/badge/mypy-strict-1f6feb)
![lint](https://img.shields.io/badge/ruff-clean-261230)
![built on](https://img.shields.io/badge/built%20on-dream-8A2BE2)
![status](https://img.shields.io/badge/M1–M4-implemented-2ea44f)

</div>

---

chorus is a **library** — like [dream](https://github.com/Arceus-Inc/dream), not a running product. It
ships the abstractions for *a workforce of agents that do durable, assignable work*, and you supply the
workspace they act on. Hire employees, submit work, and a heartbeat dispatches it, gates it against a
real definition-of-done, and lands the artifacts — recovering from crashes by reading the ledger, never
by holding a process tree in memory.

> **The whole charter, in one line:** chorus is everything that makes a `dream` task belong to a named
> employee in an org, and turns its artifacts into landed work.

```python
from chorus import Chorus, Schedule, Weekday

org = Chorus.build(db_path="company.db", org_repo="./org", memory_repo="./mem", dream=dream,
                   beat_runner_for=factory, landers=factory.landers)   # one wiring call

org.hire(name="moe",  role="manager")
org.hire(name="eng1", role="engineer", reports_to="moe")
org.hire(name="ria",  role="reviewer", reports_to="moe")   # the engineer's reviewed build needs a reviewer

# one-shot work — the engineer's *role* defines the bar (a reviewed build), so you never hand-write a DoD
org.submit("In calc.py add subtract(a, b) and a test for it.", assignee="eng1")

# recurring work — typed schedules, not raw cron strings
org.routines.add(employee="eng1",
                 intent_template="run the weekly dependency bump",
                 schedule=Schedule.weekly(Weekday.MONDAY, at="09:00"))

org.start()          # the always-on, concurrent heartbeat
...                  # work dispatches, gets reviewed, and lands on company main
await org.stop()
```

New here? Start with the **[Quickstart](consumer-facing-api/QUICKSTART.md)** — nothing-to-a-running-company
in five minutes — then the runnable **[examples](consumer-facing-api/examples/)**.

---

## Why chorus

A single agent loop ([dream](https://github.com/Arceus-Inc/dream)) can finish *one* task. Real work needs
more: many tasks with dependencies, different kinds of worker, a manager that decomposes and integrates,
a way to verify the result, budgets, approvals, and recurring jobs — all surviving crashes. chorus is
that layer, built on three bets:

- **Hierarchy is data, not topology.** The org chart and the task DAG are rows and files; the runtime is
  a flat set of durable sessions. A manager never blocks awaiting a report — delegation is a ledger
  write, and completion *events* drive the next step.
- **The ledger is the source of truth.** Every transition is a durable write. Any worker can crash and
  another resumes by reading rows — locks, claims, leases, and recovery owners all live in the database.
- **The evaluator sees outcomes, not prose.** A task's definition-of-done is generated at intake and
  verified against the *real artifact* (tests run, a reviewer's verdict) — never a self-report.

---

## The one surface you call — `org`

`Chorus` is a two-tier facade: a flat front door for the common path, and grouped accessors for
everything else.

| Front door | What it does |
|---|---|
| `Chorus.build(...)` | Compose a company over one ledger + the execution/landing seams |
| `org.hire / terminate` | Edit the workforce (data, not a process) |
| `org.submit / assign` | Put work on the ledger and route it |
| `org.tick / drain` | One deterministic pulse (recover → cron → dispatch) |
| `org.start / stop` | The always-on concurrent heartbeat |
| `org.status` | The one-call company glance |

| Group | Surface |
|---|---|
| `org.routines` | recurring work — `add` / `revise` / `restore` / `pause` / `resume` ([deep dive](consumer-facing-api/ROUTINES.md)) |
| `org.governance` | human approval gates — `open_gate` / `approvals` / `resolve` |
| `org.budgets` | token-salary caps — `set` / `raise_` / `dismiss_incident` |
| `org.trust` | per-task trust posture — `set_task` (low-trust beats run boxed-in) |
| `org.dod` | revise a task's Definition of Done (tighten now / loosen is gated) |
| `org.workforce` | `register_role` + portable `export` / `import_` |
| `org.inspect` | the read model — task views, the stuck inbox, the org rollup |

---

## What's built

- **Roles as plugins** — `engineer`, `reviewer`, `manager`, `pm`, `analyst` ship in the box; a
  `RolePlugin` (manifest + DoD + outcome-kind) adds a new employee type the kernel never knew about,
  with **no scheduler/ledger/recovery change**.
- **Task DAG + scheduler** — `depends_on` edges, eligibility, concurrency/cost caps, and a push-driven
  heartbeat that re-invokes a manager when its children finish.
- **Definition-of-done & reviewed builds** — generated at intake, verified against the artifact; an
  engineer's build must pass its tests *and* a reviewer's verdict before it lands.
- **Manager decomposition** — decompose → delegate → react to rejections → integrate the finished
  subtree, all as ledger writes.
- **Recurring work (routines)** — versioned & editable (an in-flight edit never re-judges a running
  firing), secret-safe `env` (refs, never raw values), and **roles that schedule themselves** on hire.
- **Governance, budgets, trust** — human approval gates, per-scope spend caps with incidents, and
  fail-closed low-trust containment.
- **Liveness & recovery** — a reconcile sweep reaps orphaned leases, cascades failures, and revives
  stranded subtrees — the same sequence at startup and every tick.
- **Portability** — `export(org) → import(org')` round-trips the workforce through git-markdown.

---

## Architecture

A **dream-free kernel** with two injection seams, so the engine never imports the model or the workspace:

```
your app ──▶ chorus (the kernel: ledger · scheduler · lifecycle · governance · roles)
                 │  beat_runner_for  →  how a beat runs   ┐
                 │  landers          →  how its work lands ┘ ── chorus_harness ──▶ dream ──▶ model
                 └─ roles ◀── chorus_employee (engineer · reviewer · manager · pm · analyst)
```

| Package | Responsibility |
|---|---|
| `chorus` | the kernel — facade, ledger, heartbeat, lifecycle, governance, budgets, trust, cron, roles |
| `chorus_employee` | the built-in role plugins (one package per role) |
| `chorus_harness` | the execution layer — turns a beat into a real `dream` run against a model |
| `chorus_tools` | capability tools (decompose / assign / submit) exposed to manager beats |
| `chorus_cli` | the command-line surface |

### Product map

```
dream      one task        →  the employee (plan → sprint → evaluate loop)
chorus     one sprint      →  the org of employees that do durable work   ← this repo
horizon    one company     →  strategy / OKRs / direction
lattice    the people      →  employee growth + memory consolidation
```

Strict bottom-up dependency: **chorus depends on dream; nothing depends sideways.** horizon and lattice
are future siblings — chorus stubs their intake/consolidation seams and absorbs neither.

---

## First principles (inherited bets)

| Bet | How chorus honours it |
|---|---|
| Hierarchy is data, not topology | The org chart and task DAG are rows/files; the runtime is a flat set of durable sessions. |
| No unbounded agent trees, ever | A manager never blocks on a report; the scheduler enforces caps. |
| The ledger is the source of truth | Every transition is a durable write; completion events drive the next step. |
| The evaluator sees outcomes, not prose | DoD is generated at intake and verified against the real artifact. |
| State lives in rows, not process memory | Locks, holds, claims, and recovery owners persist — any worker can crash and another resumes. |

---

## Status

**M1–M4 implemented**, gated by `ruff` + `mypy --strict` + **1117 passing tests** over a 19-migration ledger.

| Milestone | Scope |
|---|---|
| **M1** | One engineer, full vertical: task → `dream` run → DoD gated by the evaluator → outcome lands. |
| **M2** | Two engineers: concurrency, a task DAG with dependency edges, mailbox, memory scopes. |
| **M3** | One manager, two reports: decompose → dispatch → re-invoke on completion → integrate. |
| **M4** | Dynamic org: PM + Analyst roles, hire/fire as data, recurring work (routines: reachable, versioned, secret-guarded, plugin-declared), the two-tier public facade. |

---

## Documentation

| | |
|---|---|
| **[Quickstart](consumer-facing-api/QUICKSTART.md)** | Nothing to a running company in five minutes. |
| **[Concepts](consumer-facing-api/CONCEPTS.md)** | Every idea and the one verb that drives it. |
| **[Routines deep dive](consumer-facing-api/ROUTINES.md)** | Why recurring work exists and how it works in code. |
| **[Examples](consumer-facing-api/examples/)** | One runnable script per concept + the full team-goal demo. |
| **[Paperclip research](docs/paperclip-research/)** | A code-level study of prior art that shipped the same thesis. |

---

## Development

```bash
uv sync --all-extras          # install (Python 3.11+)

uv run pytest -q              # the full suite
uv run ruff check .           # lint
uv run mypy --strict src      # types

# run an offline example (no model, no keys):
uv run python consumer-facing-api/examples/03_approvals.py
```

The kernel is model-free; live examples need an OpenAI-compatible endpoint (see the
[Quickstart](consumer-facing-api/QUICKSTART.md)).

## License

TBD.
