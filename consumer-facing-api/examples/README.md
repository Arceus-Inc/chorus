# Examples — what each script teaches

One runnable script per concept. Each is standalone and stays about **one idea**; the shared wiring
(credentials, a throwaway git repo, building the org) lives in [`_common.py`](_common.py) so the scripts
read as plain `chorus` usage.

Two kinds:

- **offline** (`03`–`09`) touch only the kernel's *data surfaces* — no model, no API keys. They build
  with `offline_org()` and never dispatch a beat, so every group verb and the read model run instantly
  against an in-memory SQLite ledger.
- **live** (`01`, `02`) dispatch real beats through `chorus_harness` against an OpenAI-compatible
  endpoint. They build with `live_org()` and need three env vars (see
  [../QUICKSTART.md](../QUICKSTART.md)); without them they print a one-line skip and exit 0.

```bash
# offline — nothing required:
uv run python consumer-facing-api/examples/03_approvals.py

# live — set creds first:
set -a; eval "$(grep -E '^AZURE_OPENAI_(API_KEY|BASE_URL|DEPLOYMENT)=' .env)"; set +a
uv run python consumer-facing-api/examples/02_team_goal.py
```

---

## `_common.py` — the shared plumbing

Not an example — the toolkit every script imports so it can stay focused. Three jobs:

- **Credentials.** `have_creds()` / `creds()` read `AZURE_OPENAI_API_KEY` / `AZURE_OPENAI_BASE_URL` /
  `AZURE_OPENAI_DEPLOYMENT` from the environment, optionally folding in a `KEY=VALUE` file pointed to by
  `CHORUS_ENV_FILE` (default `./.env`). `have_creds()` lets the live scripts skip cleanly when keys are
  absent; `creds()` exits with a pointer to QUICKSTART.
- **Workspaces.** `seed_repo(path, files)` makes a throwaway git repo (under `/tmp`) the employees branch
  their worktrees from, seeded with whatever `files` you pass. `git_log(repo)` reads back what landed.
- **Orgs.** `offline_org()` builds a `Chorus` with **no** model wired (`dream=None`, no factory) — enough
  for the data-surface concepts. `live_org(seed_files=…)` does the full wiring: opens one `SqliteLedger`,
  builds the `EmployeeHarnessFactory` (dream + creds + per-employee worktrees), and calls
  `Chorus.build(ledger=…, beat_runner_for=factory, landers=factory.landers)` — **the same ledger shared
  by the kernel and the factory**, so a reviewer's verdict and the factory's capability tools write to
  one store. Both return an `Org` dataclass (`.chorus`, `.base`, `.company_main`, `.factory`, `.ledger`).

Read this file once and you've seen the entire `Chorus.build(...)` call you'd lift into your own app.

---

## `01_hire_and_submit.py` — employee · task · DoD  *(live)*

The smallest end-to-end company. Hires a manager, an engineer, and a reviewer; `submit`s one task to the
engineer **with no DoD** — the engineer's *role* defines it (a *reviewed build*: its tests pass **and**
a reviewer approves), so the operator never hand-writes a bar.

It drives the heartbeat with **`tick()` + `drain()`** in a loop (one settled pulse at a time) so the run
is deterministic and reaches `done` in a few pulses, printing the status after each. At the end it reads
`git log` on company main to show the engineer's work merged. This is the script to read first: it's the
§0 front door (`build → hire → submit → run → status`) with nothing else around it.

**Teaches:** roles define the DoD; the heartbeat; reviewed builds landing on company main.
**Watch for:** `pulse N: in_progress → done`, then a commit on company main.

## `02_team_goal.py` — the whole org  *(live, the showcase)*

The full company in one script, driven by **`org.start()`** (the concurrent always-on heartbeat). The
operator states a *goal* and assigns it to the **manager** — that's the only input. From there:

- the manager **decomposes** the goal into child tasks (some independent, some dependent);
- **independent** children run **concurrently** — both engineers at once, up to
  `Caps.max_concurrent_runs` (watch `running_beats` reach 2+);
- a **dependent** child waits until its blockers finish;
- each engineer's build is gated by the **reviewer**; the manager **reacts** to rejections (re-submits)
  and **integrates** the finished subtree → the goal lands `done`, work merged to company main.

The script just `start()`s the heartbeat and polls the read model (`inspect.task`, `status`,
`inspect.scrum_packet`) to narrate it, then `await org.stop()` drains. It's the proof that the kernel
self-heals — rejections, retries, and a timed-out child all resolve without an operator in the loop.

**Teaches:** decompose → concurrent/dependent build → review → react → integrate, under `start/stop`.
**Watch for:** `running_beats=2` (concurrency), children flipping `in_progress → done/rejected`, the
manager re-submitting after a rejection, and finally `goal=done` with a commit on company main. (The
manager is a live model, so the exact decomposition — which functions it splits out, how many react
rounds — varies run to run; the *completion* is reliable.)

## `03_approvals.py` — governance gates  *(offline)*

A human gate on a task. Submits a task, calls `org.governance.open_gate(...)` (the task flips to
`blocked`), reads the open inbox with `approvals()`, then `resolve(..., decision=APPROVE, by="ceo")` —
the gate's effect runs atomically and an `AUTHORIZATION` approve releases the task back to `todo`.

**Teaches:** `org.governance.open_gate` / `approvals` / `resolve`; enum-typed `ApprovalGate` /
`ApprovalDecision`.
**Watch for:** `todo → blocked → todo` as the gate opens and is approved.

## `04_budgets.py` — token-salary caps  *(offline)*

Arms a per-employee spend cap with `org.budgets.set(BudgetScope.EMPLOYEE, "eng1", 500_00, ...)` and
explains the two-gate model: a soft gate warns at `warn_percent`, a hard gate **pauses** the scope until
a human `raise_`s the cap or `dismiss_incident`s it. (A live breach needs real spend, so the script
arms the cap and names the recovery verbs rather than simulating a breach.)

**Teaches:** `org.budgets.set` / `raise_` / `dismiss_incident`; `BudgetScope` / `BudgetWindow`.
**Watch for:** the printed confirmation + the two recovery verbs.

## `05_dod_revision.py` — revising a Definition of Done  *(offline)*

Submits an engineer task with a `Command` DoD (`pytest -q`), then has the **manager** tighten it to
`pytest -q && ruff check .` via `org.dod.revise(task_id, new_verifier, by="moe")`. A *tighten* applies
immediately; a *loosen* would instead open a governance gate (see `03`). Only the assignee's manager may
revise.

**Teaches:** `org.dod.revise`; tighten-applies-now vs loosen-is-gated; revision authority.
**Watch for:** the `ReviseOutcome` and the note that `done` now needs both tools to pass.

## `06_trust.py` — trust presets  *(offline)*

Submits a task under `trust_preset=TrustPreset.LOW_TRUST_REVIEW`, then re-sets it with
`org.trust.set_task(task_id, preset=TrustPreset.STANDARD)`. A trust posture **narrows** a beat at
materialize time (a low-trust beat is read-only / plan-only; standard keeps the role's powers) — so the
effect bites on a live run; offline, the script just attaches and re-sets the posture.

**Teaches:** `submit(trust_preset=…)` and `org.trust.set_task`; `TrustPreset`.
**Watch for:** the preset attached, then changed to standard.

## `07_routines.py` — recurring work: routines, revisions, env  *(offline)*

Walks the whole routine lifecycle on the data surface. `org.routines.add(…, routine_key=…,
env={"GITHUB_TOKEN": "ref:github_token"})` creates a routine at **revision 1** with a secret-ref `env`
binding. `revise(by=…, intent_template=…)` writes a **new head revision** (the live row tracks the
head); `restore(revision_no=1, by=…)` rolls back through a *new* head — history is never rewritten.
`pause`/`resume` toggle firing. Finally it shows the **fail-closed env guard**: an inline secret
(`GITHUB_TOKEN="ghp_…"`) raises `InvalidIntake` before it can ever be stored. When the heartbeat runs,
the tick's CRON step fires any due routine and pins the revision it fired under (see 01/02 for live
dispatch).

**Teaches:** `org.routines.add` (`env`/`routine_key`) / `revise` / `restore` / `pause` / `resume`;
revisions + the secret-ref guard.
**Watch for:** `rev=1 → 2 → 3` across revise/restore, `active → paused → active`, and the rejected
inline secret.

## `08_inspect.py` — the read model  *(offline)*

Hires a small org and submits three tasks — one owned, one **dependent** (`depends_on` the first), one
unowned in the backlog — then reads the kernel back: `org.status()` (the one-call glance),
`org.inspect.task(id)` (assignee, liveness, **blockers**), `org.inspect.stuck()` (the blocked inbox), and
`org.inspect.org_report()` (the rollup). "Working vs stuck" is answered structurally from the ledger,
never guessed from timing.

**Teaches:** `org.status` + `org.inspect.task` / `stuck` / `org_report`; dependency blockers in a task view.
**Watch for:** the dependent task listing the first task in its `blockers`, and the org report's
`completion_rate`.

## `09_plugin_routines.py` — roles that schedule themselves  *(offline)*

Plugin-declared routines: a **role** carries its own standing schedule, and **hiring** an employee of
that role provisions it automatically — no operator `add`. Two halves. First a built-in role: hiring a
PM (`org.hire(role="pm")`) auto-creates its weekly planning routine, visible immediately in
`org.routines.list(employee=…)`. Then a role the kernel never knew about — a `widget` `RolePlugin` with
a `declared_routines=(RoutineDeclaration(…),)`, defined right in the script. `org.workforce.register_role`
+ `org.hire` and its nightly routine schedules itself, with **zero change under `src/chorus/`** — the
reconciler never names a role. This is the "a new role schedules with no kernel change" property.

**Teaches:** `RoutineDeclaration` + `RolePlugin.declared_routines`; hire-time provisioning;
`org.workforce.register_role`.
**Watch for:** the PM's weekly routine present right after hire, and the brand-new `widget` role's
routine scheduling itself on hire.

## `08_inspect.py` — the read model  *(offline)*

Hires a small org and submits three tasks — one owned, one **dependent** (`depends_on` the first), one
unowned in the backlog — then reads the kernel back: `org.status()` (the one-call glance),
`org.inspect.task(id)` (assignee, liveness, **blockers**), `org.inspect.stuck()` (the blocked inbox), and
`org.inspect.org_report()` (the rollup). "Working vs stuck" is answered structurally from the ledger,
never guessed from timing.

**Teaches:** `org.status` + `org.inspect.task` / `stuck` / `org_report`; dependency blockers in a task view.
**Watch for:** the dependent task listing the first task in its `blockers`, and the org report's
`completion_rate`.

---

## A note on the live scripts

`01` and `02` cost model calls and take time (`02` is a multi-beat pipeline — minutes). They're
deterministic in *what they exercise* but not in *exactly how the model decomposes/builds*, so two runs
can differ in the child structure while both reaching `done`. The offline scripts (`03`–`09`) are fully
deterministic and free — start there to learn the surface.
