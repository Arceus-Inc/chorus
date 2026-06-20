# Concepts

Every idea in `chorus`, the one verb that drives it, and the example that shows it. `chorus` runs **one
sprint of an org**: a workforce of role-faithful agents that do durable, reviewable work and leave an
auditable trail in a SQLite ledger.

## The mental model

```
operator ──hire──▶ employees ──submit──▶ tasks ──the heartbeat──▶ beats ──land──▶ company main
                      │                     │                        │
                   a role            a Definition of Done       a dream run
              (manager / engineer    (what 'done' means)      (plan→sprint→evaluate)
               / reviewer / …)
```

The operator only ever **hires**, **submits**, and **starts the heartbeat**. Everything else — who does
what, in what order, gated by which review — is the org acting on itself, recorded in the ledger.

---

## Employee — `org.hire` / `org.terminate`

An employee is **data, not a process**: a row with a name, a **role**, and who it reports to. The role
is the whole identity — its tools, its brief, its permission posture, *and its default Definition of
Done*. Hiring validates the org chain (no unknown manager, no cycle, no duplicate); terminating is
irreversible and cancels the employee's in-flight work.

```python
org.hire(name="moe", role="manager")
org.hire(name="eng1", role="engineer", reports_to="moe")
```

Roles ship in `chorus_employee`: **manager** (decomposes + integrates), **engineer** (builds, reviewed),
**reviewer** (read-only verdicts). → `examples/01`, `examples/02`

## Task — `org.submit` / `org.assign`

A unit of work: an intent, a priority, an owner, optional dependencies. `submit` is the one intake door
— it creates the task and (if you name an assignee) hands it over. Unassigned tasks wait in the backlog.

```python
a = org.submit("build the dashboard", assignee="eng1")
b = org.submit("wire the API", assignee="eng1", depends_on=(a.id,))   # b waits for a
```

→ `examples/08` (dependencies + the read model)

## Definition of Done (DoD) — defined by the role · revised via `org.dod`

The **objective bar** for a task. You almost never write one: a task inherits its assignee role's DoD at
intake (an engineer's is a *reviewed build* — its tests pass **and** a reviewer approves). A manager can
**revise** it: a tighten applies now, a loosen opens a governance gate. → `examples/05`

## Decompose — the manager does it, mid-beat

A goal is too big for one beat, so the **manager decomposes** it into child tasks (calling the decompose
tool inside its beat — not an operator verb). Independent children run concurrently; dependent children
wait. When the subtree finishes, the manager **integrates** it and the parent lands `done`. → `examples/02`

## Review — the reviewer does it, the kernel gates on it

An engineer's reviewed build parks for review; a **reviewer** beat inspects the work *in the author's
worktree* (read-only) and records a verdict. Approve → the kernel runs the objective floor, then lands
it. Block → it routes back for repair or to the manager. → `examples/02`

## The heartbeat — `org.start` / `org.stop` · `org.tick` / `org.drain`

The kernel pulse: each tick recovers stale work, fires due routines, then dispatches ready beats (up to
`Caps.max_concurrent_runs` at once). Two ways to drive it:

| Verb | Use |
|---|---|
| `org.start()` / `await org.stop()` | the **concurrent always-on** runner — beats overlap across pulses, no barrier. Production. |
| `await org.tick()` / `await org.drain()` | **single-step** one pulse to completion — deterministic. Tests, demos. |

→ `examples/01` (tick/drain), `examples/02` (start/stop)

## Approval — `org.governance`

A human gate. Open one on a task, read the open inbox, resolve it (approve / deny). Resolving runs the
gate's effect atomically — an authorization approve releases the task; an acceptance approve completes
it. Hiring and promotions can route through the same queue. → `examples/03`

```python
appr = org.governance.open_gate(task.id, gate_kind=ApprovalGate.AUTHORIZATION, reason="sign-off")
org.governance.resolve(appr.id, decision=ApprovalDecision.APPROVE, by="ceo")
```

## Budget — `org.budgets`

A token-salary cap per employee or company. Two gates: a soft one warns; a hard one **pauses** the scope
until a human `raise_`s the cap or `dismiss_incident`s it. Inert until you set a policy. → `examples/04`

## Trust — `org.trust`

A named posture that **narrows** a beat (a low-trust task is materialized read-only / plan-only; standard
keeps the role's powers). Set it at `submit(trust_preset=…)` or later with `org.trust.set_task`. → `examples/06`

## Routine — `org.routines`

Recurring work: a cron schedule that spawns a task each time it fires. The heartbeat's CRON step fires due
routines through the same dispatch path. **add** (with a secret-ref `env` binding + a stable
`routine_key`) / list / get / pause / resume, plus **revise** and **restore** — a routine is *versioned*:
each edit writes a new head revision, a firing pins the revision it ran under (an in-flight edit never
re-judges it), and `restore` rolls back through a new head without rewriting history. `env` binds secret
**refs, never raw values** — an inline secret is rejected fail-closed at write time. → `examples/07`

A **role** can also carry its own routines: a plugin declares `RoutineDeclaration`s, and **hiring** an
employee of that role provisions them automatically — a new role schedules recurring work with no kernel
change. → `examples/09`. Full deep dive (why + how it works in code): [ROUTINES.md](ROUTINES.md).

## The read model — `org.status` / `org.inspect`

`status()` is the one-call company glance (employees, open tasks, running beats, blocked inbox,
incidents). `org.inspect.*` is the detail: a resolved task view (assignee, liveness, blockers), the stuck
inbox, the scrum packet (a manager's children), the org rollup. **Working vs stuck is answered
structurally from the ledger — never guessed from timing.** → `examples/08`

## Workforce portability — `org.workforce`

Register a new role plugin; `export` the live org to a portable git-markdown tree and `import_` it back —
so a company is reproducible.

---

## On neither tier (the employee's own faculties)

Three things are **not** operator verbs — the agents do them inside the beat:

- **decompose** — the manager calls it mid-beat (above).
- **submit_verdict** — the reviewer records it through the review beat (above).
- **memory** — a beat reads its memory scope when it rehydrates and writes a sprint delta when it
  finishes, both inside the beat lifecycle. Memory is the employee's faculty, not an operator surface.
