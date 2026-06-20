# Routines — recurring work that schedules itself

A guide to `org.routines`: what a routine is, **why** it exists, how you add / revise / plug one into a
role, and how it all works under the hood. Plain language first, real code paths second.

Runnable companions: [`examples/07_routines.py`](examples/07_routines.py) (lifecycle) and
[`examples/09_plugin_routines.py`](examples/09_plugin_routines.py) (roles that schedule themselves).

---

## What is a routine?

chorus is a **company staffed by AI workers** — you give it work, it assigns it, the workers do it.

A **routine** is a *standing instruction to do work on a schedule*. Like a recurring calendar reminder —
except the reminder doesn't just ping someone, it **creates the work and hands it to an employee**.

> "Every Monday at 09:00, run the dependency bump."

That's a routine: an **intent** (what), a **cron schedule** (when), and an **owner** (who). When its time
arrives, the heartbeat (chorus's pulse) spawns a task and the normal machinery runs it — nobody has to
remember to start it.

---

## Why we built it (the four needs)

A *real* recurring-work system needs four things, and each was built as one slice:

| Need | Slice | In one line |
|---|---|---|
| It actually fires, reliably, no duplicates | **S1** | You can create a recurring job and it fires; a re-fire while the last is still running *folds in* instead of piling up. |
| You can edit it safely | **S2** | Routines are **versioned** — full history, and an edit **never re-judges** a job already underway. |
| Secrets stay safe | **S3 (guard)** | A routine binds a secret **by reference, never a raw value** — an inline secret is rejected before it can be stored. |
| Roles bring their own | **S6** | A role *declares* its routines; **hiring** that role provisions them automatically — a brand-new role schedules itself with **no kernel change**. |

The throughline: **routines are scheduled, self-creating work — reliable, safely versioned, secret-safe,
and able to come bundled with a role so the org schedules itself as it grows.**

---

## Using it — the `org.routines` surface

Everything is offline-safe (no model needed) on the data surface. Enums are typed; no stringly args.

### Add (S1 + S3)

```python
view = org.routines.add(
    employee="eng1",
    intent_template="run the weekly dependency bump",
    schedule="0 9 * * 1",                 # 5-field cron — 09:00 every Monday
    routine_key="weekly-dep-bump",        # stable identity (used by S6 reconcile)
    env={"GITHUB_TOKEN": "ref:github_token"},  # secret *ref*, never a raw value
)
# view.latest_revision_no == 1
```

`env` binds secrets by handle. Pasting a real secret is **rejected fail-closed**:

```python
org.routines.add(..., env={"GITHUB_TOKEN": "ghp_realSecret"})   # raises InvalidIntake
```

### Revise & restore (S2)

```python
v2 = org.routines.revise(view.id, by="eng1",
                         intent_template="bump deps AND run a security audit")
# v2.latest_revision_no == 2 — a new head; only the fields you pass change

v3 = org.routines.restore(view.id, revision_no=1, by="eng1")
# v3.latest_revision_no == 3 — rolls back to v1's body through a *new* head; history is never erased
```

Only the routine's **owner** or the owner's **manager** may edit it. A no-op revise (nothing actually
changed) is a safe no-op.

### Pause / resume / read

```python
org.routines.pause(view.id)        # drops out of the firing scan
org.routines.resume(view.id)
org.routines.get(view.id)          # one resolved view: definition + triggers + recent firings
org.routines.list(employee="eng1") # all of an employee's routines
```

---

## How it works under the hood

### The data: history + a pointer

S2's migration (`0019_routine_revisions.sql`) gives routines two storage halves:

- **`routine_revision` table** — the **history book**. Every version is one immutable row (v1, v2, v3…).
  Rows are only ever *appended*, never changed or deleted.
- **The `routine` row** — the **live record**. It carries `latest_revision_id` / `latest_revision_no`
  (a **pointer to the current version**, the "head") plus a mirrored copy of the current definition for
  fast reads. It also holds `routine_key` and `env`.

Two more tables complete the picture: **`routine_trigger`** (the cron clock — its `next_run_at` is the
edge the tick selects on) and **`routine_run`** (one row per firing).

### Adding a routine — `chorus/cron/_add.py`

`org.routines.add` resolves the employee name → id and delegates to the kernel helper
**`add_routine(ledger, *, employee_id, …)`**, which does one create unit:

1. **env guard** (`assert_no_inline_secrets`) — reject a raw secret before any write;
2. **parse the cron** — a bad schedule fails here, so no orphan routine is left behind;
3. write the **routine row** + **revision 1** + the **cron trigger**.

The facade and the plugin reconciler (below) share this exact helper, so revision 1 is seeded in one
place.

### Revising — `chorus/cron/_revise.py`

`revise_routine(ledger, *, routine_id, revised_by, …)`:

1. **authority** — owner or owner's manager, else refuse;
2. read the current **head** revision;
3. build the new version = head **overlaid with only the fields you passed**;
4. if identical → raise `NoRoutineRevision` (write nothing);
5. **append** the new revision (`revision_no = head + 1`), then **`set_head`** — one atomic update that
   moves the pointer *and* mirrors the new definition onto the live row.

So an edit is just **"append a row to history, then move the pointer."** Nothing is overwritten.
`restore` is the same shape: it copies an old revision into a *new* head (recording where it came from).

```
BEFORE                          AFTER revise
routine row:                    routine row:
  latest_revision_no = 1          latest_revision_no = 2     ← pointer moved
  intent = "bump deps"            intent = "bump deps+audit" ← mirror updated
routine_revision:               routine_revision:
  v1: "bump deps"                 v1: "bump deps"            ← untouched
                                  v2: "bump deps+audit"      ← appended
```

### Firing — and why an edit never re-judges live work (`chorus/cron/_fire.py`)

When a routine is due, `fire_routine` reads `latest_revision_id` **at that instant**, **stamps it onto
the firing** (`routine_run.routine_revision_id`), and sources the spawned task's intent from *that pinned
version*. The firing is now permanently tied to the version it started under.

If you revise the routine a second later, the pointer moves — but the already-running job still carries
its old pinned revision. The new version only takes effect on the **next** firing. That is the entire
"never re-judge work already underway" guarantee: **the run remembers which row it fired under.**

---

## Plugging a routine into a role (S6)

Some recurring work is just *part of a role*. A PM always files a weekly planning review — you shouldn't
have to set that up by hand for every PM you hire.

A role plugin carries **`declared_routines`** — a tuple of **`RoutineDeclaration`** (a `routine_key`,
intent, schedule, and optional `env`). The PM ships one:

```python
# src/chorus_employee/pm/__init__.py
PM_WEEKLY_PLANNING = RoutineDeclaration(
    routine_key="pm-weekly-planning-review",
    intent_template="Weekly planning review: assess goals and open work, update plan.md …",
    schedule="0 9 * * 1",
)
# RolePlugin(name="pm", …, declared_routines=(PM_WEEKLY_PLANNING,))
```

Now **hiring** provisions it automatically:

```python
org.hire(name="Ada", role="pm")
org.routines.list(employee="ada")   # the weekly routine is already there
```

### How that happens in code

`Chorus.hire` (the facade), right after creating the employee, calls
**`reconcile_declared_routines(ledger, employee_id, declarations)`** (`chorus/cron/_reconcile.py`). For
each declaration it **upserts by `(employee_id, routine_key)`**:

- **absent** → `add_routine(…)` (create it);
- **present but the definition drifted** → `revise_routine(…)` (a new revision);
- **unchanged** → leave it alone.

It is **idempotent** (safe to re-run) and — the important part — **role-agnostic**: the reconciler never
mentions `pm` or `analyst`. So you can define a **brand-new role**, register it with
`org.workforce.register_role(...)`, hire into it, and its declared routine schedules itself **with zero
change under `src/chorus/`**. That is chorus's core promise made literal: *the engine is fixed; an
organization's behaviour is data you plug in.* See `examples/09_plugin_routines.py`.

Declarations are validated **fail-closed at registration** — a bad cron or an inline secret in a
declaration is rejected the moment the plugin is registered, never at firing time.

---

## Security: refs, never values (S3)

`env` is for **bindings**, not secrets. A key that looks like a secret (`*TOKEN`, `*KEY`, `*PASSWORD`,
`*SECRET`, `*CREDENTIAL`, `*API*`) must hold a `ref:` handle. A raw value raises `InvalidIntake` at the
door — at `add`, at `revise`, and at plugin registration. The same rule lives in one place
(`assert_no_inline_secrets`) so "what counts as a secret" is defined once.

*(Resolving those refs to real values when a low-trust beat runs is a later step — the lock is in now;
the key-lookup comes with the materialize-time work.)*

---

## Where to look in the code

| Piece | File |
|---|---|
| Public surface | `org.routines` → `src/chorus/groups/_routines.py` |
| Create | `chorus/cron/_add.py` (`add_routine`) |
| Edit / roll back | `chorus/cron/_revise.py` (`revise_routine`, `restore_routine`) |
| Fire (pins the revision) | `chorus/cron/_fire.py` (`fire_routine`) |
| Role declarations → routines | `chorus/cron/_reconcile.py` (`reconcile_declared_routines`) |
| The declaration type | `chorus/roles/_routine_declaration.py` (`RoutineDeclaration`) |
| Secret guard | `chorus/trust/_containment.py` (`assert_no_inline_secrets`) |
| Storage | migration `0019_routine_revisions.sql`; tables `routine`, `routine_revision`, `routine_trigger`, `routine_run` |
| Examples | `examples/07_routines.py`, `examples/09_plugin_routines.py` |

**One breath:** *Routines are scheduled, self-creating work — created through one shared `add_routine`,
safely versioned by appending to a history table and moving a pointer, pinned at firing so live work is
never re-judged, secret-safe by construction, and able to ride along with a role so hiring grows the
org's recurring work on its own.*
