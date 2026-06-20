# 13 — Recurring work (M4)

How the org does work **no one re-assigns each time**: a standing `(cron + intent + assignee + policy)`
bundle that the tick keeps minting fresh tasks from. This is the M4 headline — *heterogeneous
workforce, recurring work, portability* — pinned to code, and grounded in a fresh read of the
Paperclip clone `6756ae8` (`server/src/services/routines.ts`, `cron.ts`, `plugin-managed-routines.ts`,
`company-portability.ts`; `packages/db/src/schema/routines.ts`).

It extends [03 — Scheduler](03-scheduler.md) (the firing engine), [01 — Data model](01-data-model.md)
(the routine cluster), [06 — Roles & workforce](06-roles-and-workforce.md) (PM + Analyst), and
[09 — Extensibility & portability](09-extensibility-and-portability.md) (plugin-declared routines,
the company package). It is the single place to read M4.

---

## 0. What is already true (do not rebuild)

The cofounder's M1–M3 work already landed the **firing engine and its tables**. This spec is the
*reachability, richness, roles, and portability* shell around an engine that is done. The audit
that opened M4 mistook missing surfaces for a missing engine — it is not missing.

`src/chorus/cron/_fire.py :: fire_routine` already, per beat:

- resolves one due `routine_trigger` into ledger writes — **never** an agent call;
- advances the cron edge under a **double-fire guard** (`claim_fire` CAS on `next_run_at`);
- records the firing **exact-once** (`routine_run.idempotency_key` partial-unique index);
- honours **concurrency policy** — `skip_if_active` suppresses, `coalesce` folds onto the live run
  (linking `coalesced_into_run_id`), `always` spawns regardless;
- honours **catch-up policy** — `skip_missed` jumps the edge past `now`, `backfill_one` advances a
  single cron step per tick (one missed window per tick, throttled);
- is **timezone-aware** (`parse_cron(expr, base=…, timezone=trigger.timezone)`);
- stamps a **typed origin** on the spawned task — `origin_kind = ROUTINE_EXECUTION`,
  `origin_id = routine.id`, `origin_fingerprint = idempotency_key`;
- supports two targets — `spawn_task` (the normal path) and `next_beat` (a context note via a
  `CRON_DUE` wake);
- is wired into the live tick (`src/chorus/heartbeat/_scheduler.py`, the recover → **CRON** →
  monitors → dispatch order).

Tables `routine`, `routine_trigger`, `routine_run` exist (`src/chorus/ledger/schema/`) with repos
exposing `create` / `get` / `list_active` / `claim_fire` / `record` / `dispatch`. Enums
`RoutineConcurrency`, `RoutineCatchUp`, `RoutineTarget`, `RoutineRunStatus`, `OriginKind` exist in
`src/chorus/ledger/_models.py`.

**The one reason recurring work is unusable today:** nothing can *create* a routine.
`Chorus.add_routine` is `raise NotImplementedError("spec 03 §4: persist routine + trigger")`. M4
closes that, then adds the richness Paperclip carries around the same engine.

---

## 1. Scope — what M4 is, and what it is not

### In scope

| Area | This spec |
|---|---|
| **Reachability** | `add_routine` facade verb + `routine` CLI noun; the engine becomes usable |
| **Concurrency default** | flip the column default `skip_if_active` → **`coalesce`** (safe-by-default: no pile-ups, firings are recorded not lost) |
| **Revisions** | a routine is **versioned** — every edit snapshots a `routine_revision`; a run **pins the revision it fired under**; `restore` |
| **Env bindings** | a routine carries **trust-checked `env`** secret bindings (reuses §4 boundary) |
| **Heterogeneous workforce** | `chorus_employee/pm` + `chorus_employee/analyst` — full plugins with landers (plan doc / findings doc) |
| **Plugin-declared routines** | a plugin ships a `RoutineDeclaration`; the kernel **reconciles** it into routine+trigger — schedules with **zero kernel diff** |
| **Portability** | `copy_org` carries routines + triggers + current revision; secret **bindings** re-prompted, never values |

### Out of scope (deferred, with the reason)

| Deferred | Why |
|---|---|
| **Webhook / external triggers** | chorus has **no HTTP server** — nothing could deliver the POST. A listener (open port, HMAC verify, replay window) is a *horizon/hosting* surface, not a local-kernel one. The `routine_trigger.kind` column stays, but M4 ships **only `kind='cron'`.** |
| **Manual `routine fire <id>` CLI** | with no external origin to emulate, the cron edge is the only firing path in M4. Revisit alongside the horizon listener. |
| **Routine `variables`** (`{var}` substitution) | with no trigger payload to bind from, a cron routine's `intent_template` is effectively static. `env` (below) covers the real need (secret access); variables add schema without value. |
| **Multi-process firing race** (`SKIP LOCKED`) | single-process `claim_fire` already wins exact-once. Multi-tenant Postgres firing is an Arceus concern ([12 — Storage](12-storage.md)). |

---

## 2. The routine entity (data model)

A routine is the standing instruction; a trigger is its clock; a run is one firing. The three
tables exist — M4 **adds** the revision pin, the env binding, and a new `routine_revision` table.

### 2.1 `routine` — additive columns

```
routine (existing)               +M4
  id                                env                 TEXT     -- JSON RoutineEnv (secret-ref bindings), nullable
  employee_id  → employee           latest_revision_id  TEXT     -- → routine_revision(id), the live definition
  goal_id      → goal               latest_revision_no  INTEGER  NOT NULL DEFAULT 1
  parent_task_id → task
  intent_template
  target            DEFAULT 'spawn_task'
  concurrency_policy DEFAULT 'coalesce'   -- M4 flips this from 'skip_if_active'
  catch_up_policy   DEFAULT 'skip_missed'
  status            DEFAULT 'active'      -- active | paused
  created_at / updated_at
```

`env` is **never** raw secret values — it is a binding to secret *refs* (e.g. `{"GITHUB_TOKEN":
"ref:github_token"}`), validated against the §4 `TrustBoundary.secret_ref_allowlist` at materialize.
A routine with an inline secret in `env` is rejected at `add_routine` time (fail-closed), mirroring
`assert_contained`'s "no inline secret" rule.

### 2.2 `routine_revision` — new table (full versioning)

Mirrors the §1 DoD-revisability pattern: an immutable, append-only history; the live row points at
the head; a run pins the revision it fired under so an edit **never re-judges a firing in flight**.

```sql
CREATE TABLE routine_revision (
    id                       TEXT PRIMARY KEY,
    routine_id               TEXT NOT NULL REFERENCES routine(id),
    revision_no              INTEGER NOT NULL,
    intent_template          TEXT NOT NULL,
    target                   TEXT NOT NULL,
    concurrency_policy       TEXT NOT NULL,
    catch_up_policy          TEXT NOT NULL,
    env                      TEXT,           -- JSON snapshot of the binding
    change_summary           TEXT,
    restored_from_revision_id TEXT REFERENCES routine_revision(id),
    created_at               TEXT NOT NULL
);
CREATE UNIQUE INDEX routine_revision_no_uq ON routine_revision(routine_id, revision_no);
```

A **snapshot is the unit of edit.** `revise_routine` writes a new `routine_revision` (revision_no =
head + 1), then advances `routine.latest_revision_id` / `latest_revision_no` to it — one atomic
write. `restore(routine_id, revision_no)` writes a *new* head revision whose body copies the target
revision and whose `restored_from_revision_id` records the provenance (never mutates history).

### 2.3 `routine_run` — pins the revision

```
routine_run (existing)           +M4
  id                                routine_revision_id  TEXT  -- → routine_revision(id), the def this run fired under
  routine_id / trigger_id
  status            DEFAULT 'received'   -- received | dispatched | coalesced | suppressed
  dispatch_fingerprint
  idempotency_key   (partial-unique)
  linked_task_id    → task
  coalesced_into_run_id
  created_at
```

**In-flight invariant.** `fire_routine` reads `routine.latest_revision_id` *at firing* and stamps it
on the run. The spawned task's `intent` is taken from that pinned revision's `intent_template`. If a
manager edits the routine while a run is mid-flight, the live run keeps executing the pinned
definition; the next firing picks up the new head. This is the §1 rule ("a revision never re-judges
a recorded verdict") applied to routines.

### 2.4 Migration

One migration `0019_routine_revisions.sql` (the rename-rebuild parity pattern, cf. 0014–0018):
adds `routine.env` / `latest_revision_id` / `latest_revision_no` / `routine_key` (+ the
`(employee_id, routine_key)` unique index of §5.2), adds `routine_run.routine_revision_id`, and
creates `routine_revision`. (S1 already shipped `0018` as the coalesce-default flip, so the revision
schema lands as `0019` — `routine` and `routine_run` are both rebuilt for clean column placement.)
Existing routines (none in a fresh DB; defensively, any seeded) get a synthesized revision 1 from
their current columns. Parity test `tests/ledger/test_schema_parity.py` compares migrated DDL to the
declarative `schema/*.sql`.

---

## 3. Lifecycle — create, edit, pause, fire

### 3.1 Create (`add_routine`)

`Chorus.add_routine` stops being a stub. It wires the **existing** repo methods — no new engine:

```
add_routine(*, employee, intent_template, schedule, target='spawn_task',
            concurrency='coalesce', catch_up='skip_missed', env=None, timezone='UTC') -> Routine
  1. resolve employee → employee_id (fail-closed if absent)
  2. validate env against the employee's trust boundary (no inline secrets)   [§4 reuse]
  3. routine_revision rev1  := snapshot(intent_template, target, policies, env)
  4. routine                := create(... latest_revision_id=rev1.id, latest_revision_no=1)
  5. routine_trigger        := create(kind='cron', cron_expression=schedule, timezone=timezone,
                                      next_run_at=parse_cron(schedule, base=now, timezone=timezone))
  6. return the Routine
```

`schedule` is a 5-field cron string ([03 §4](03-scheduler.md)); `timezone` defaults to `UTC` (the
trigger column default) and `parse_cron` already computes the first `next_run_at` in that zone. The
trigger's `next_run_at` is what the tick's CRON step selects on.

### 3.2 Edit / pause / resume / restore

| Verb | Effect |
|---|---|
| `revise_routine(routine_id, **patch, change_summary)` | new head `routine_revision`; advances the live pointer. In-flight runs unaffected (§2.3). |
| `pause_routine(routine_id)` | `status = paused`. `fire_routine` already no-ops on a non-`active` routine — paused routines never fire. |
| `resume_routine(routine_id)` | `status = active`. The trigger's `next_run_at` resumes selecting. |
| `restore_routine(routine_id, revision_no)` | new head copied from `revision_no`, `restored_from_revision_id` set. |

Authority: a routine is owned by its `employee_id`. Revising another employee's routine follows the
same manager-authority guard as §1 `revise_dod` (assignee `reports_to`). Out of M4's critical path;
specified here so the verb isn't authority-blind.

### 3.3 Fire (unchanged engine, two new reads)

`fire_routine` gains exactly two lines: read `routine.latest_revision_id`, stamp it on the
`routine_run` and source the spawned task's `intent` from the pinned revision. Everything else —
concurrency, catch-up, exact-once, the typed origin, the `CRON_DUE` wake — is already correct and
**must not be re-touched**. The acceptance tests in §6 lock the existing behaviour as a regression
floor before the two-line change lands.

---

## 4. Heterogeneous workforce — PM + Analyst

Roles are already an enum-backed manifest set (`chorus/roles/_defaults.py` defines `pm` and
`analyst`). What is missing is their **plugins** under `chorus_employee/` — the brief, the DoD
generator, and the lander that turns a passed beat into a real artifact. M3 shipped this shape for
`engineer` / `manager` / `reviewer`; M4 ships two more, proving the workforce is heterogeneous, not
hard-coded to three.

| Plugin | Brief (what it does) | DoD | Lander → artifact |
|---|---|---|---|
| `chorus_employee/pm` | turn a goal/prompt into a written **plan / spec** | doc-exists DoD (the plan file is present + non-empty) | `pm_lander` → `Artifact(kind=plan_doc)` snapshotting the worktree's plan file |
| `chorus_employee/analyst` | research a question → a written **findings** doc | doc-exists DoD (findings file present) | `analyst_lander` → `Artifact(kind=findings_doc)` |

Each plugin is one package (brief, `_config.py`, `_dod.py`, `_lander.py`) and registers via
`default_landers` (`src/chorus_employee/__init__.py`) — the same registry the engineer/manager/
reviewer landers already join. No kernel branch on role: the scheduler calls `lander_for(outcome_kind)`,
which now resolves PM/Analyst outcomes too. A PM/Analyst **task** already runs today (the role
materializes a harness); M4 gives it somewhere to **land**.

---

## 5. Plugin-declared routines — "schedules with no kernel change"

The M4 acceptance bar *"a new role plugin schedules with no kernel change"* is met **literally**: a
plugin declares its recurring work in its own manifest, and a reconciler — not a kernel edit —
creates the routine. This mirrors Paperclip's `plugin-managed-routines.ts`.

### 5.1 The declaration (lives with the plugin)

```python
@dataclass(frozen=True)
class RoutineDeclaration:
    routine_key: str            # stable identity for reconcile (idempotent upserts)
    intent_template: str
    schedule: str               # cron expression
    target: RoutineTarget = RoutineTarget.SPAWN_TASK
    concurrency: RoutineConcurrency = RoutineConcurrency.COALESCE
    catch_up: RoutineCatchUp = RoutineCatchUp.SKIP_MISSED
    env: Mapping[str, str] | None = None
```

A plugin (e.g. the PM plugin) exposes `declared_routines() -> Sequence[RoutineDeclaration]` — e.g. a
PM that files a **weekly planning review** every Monday 09:00.

### 5.2 The reconciler (one kernel-side function, role-agnostic)

```
reconcile_declared_routines(ledger, *, employee_id, declarations) -> ReconcileResult
  for each declaration:
    existing := routine by (employee_id, routine_key)      # routine_key column added to routine
    if absent  -> add_routine(... from declaration)         # create + rev1 + trigger
    if present -> revise_routine if the declaration changed  # new revision, idempotent on no-op
  returns {created, revised, unchanged}
```

The reconciler is **declaration-driven** — it never names `pm` or `analyst`. Registering a *new*
role plugin that declares routines therefore schedules recurring work with **zero diff to the
kernel**: the proof is a test that imports a fresh plugin module, runs the reconciler, and asserts a
routine + trigger exist and fire — with no edit under `src/chorus/`. (`routine.routine_key` +
`(employee_id, routine_key)` unique index is the only schema addition this needs; folded into
migration 0018.)

---

## 6. Portability — routines travel with the org

`copy_org` ([09](09-extensibility-and-portability.md), `src/chorus/workforce/_package.py`) carries
employees parents-first today. M4 extends the package so an exported company **re-materializes its
recurring work**, matching Paperclip's `company-portability.ts` manifest (agents + routines +
triggers + secret bindings).

- **Export** writes, per employee, their routines + each routine's **current revision** (not the
  full history — history is local audit, not portable state) + triggers. Secret values are **never**
  exported; only the binding **refs** (`env` keeps `ref:…`, the allowlist travels, the values do
  not).
- **Import** re-creates each routine via the same `add_routine` path (fresh revision 1 from the
  exported definition) and its trigger with a recomputed `next_run_at`. Bound secret refs that the
  importing company can't resolve are surfaced as a **re-prompt list** (the operator supplies the
  values), never silently dropped or invented.

Round-trip invariant: `export(org) → import(org')` yields, for every employee, the same routines
(by `routine_key` where present, else by intent+schedule) and triggers — the M4 portability
acceptance.

---

## 7. Public surface (facade + CLI)

Facade ([10](10-public-api-and-cli.md), `src/chorus/facade.py`):

```python
add_routine(*, employee, intent_template, schedule, target='spawn_task',
            concurrency='coalesce', catch_up='skip_missed', env=None, timezone='UTC') -> Routine
revise_routine(routine_id, *, change_summary, **patch) -> Routine
restore_routine(routine_id, revision_no) -> Routine
pause_routine(routine_id) -> None
resume_routine(routine_id) -> None
list_routines(*, employee=None) -> list[Routine]
routine(routine_id) -> RoutineView            # def + triggers + recent runs (read model, spec 08)
```

CLI ([10](10-public-api-and-cli.md), `src/chorus_cli/_commands.py`) — a single `routine` noun:

```
chorus routine add <employee> <intent> --schedule "<cron>" [--timezone <tz>]
                                       [--concurrency coalesce|skip_if_active|always]
                                       [--catch-up skip_missed|backfill_one] [--env KEY=ref:…]
chorus routine list [--employee <name>]
chorus routine show <routine_id>          # definition + triggers + last N runs
chorus routine pause|resume <routine_id>
chorus routine revise <routine_id> [--intent …] [--schedule …] --summary "<why>"
chorus routine restore <routine_id> <revision_no>
```

Inspector ([08](08-observability.md)): `routine(id)` surfaces the live revision, the trigger's
`next_run_at`, and recent runs with their `status` (received/dispatched/coalesced/suppressed) and
`linked_task_id` — so "this task came from routine X, run Y" is visible, and a coalesced/suppressed
firing is observable, not silent.

---

## 8. Build plan (TDD slices)

Each slice is RED → GREEN → REFACTOR, gated by `uv run ruff check` + `uv run mypy --strict src` +
`uv run pytest -q`, with an e2e checkpoint. Dependency order: **S1 → (S2, S3, S4, S5, S7 parallel)
→ S6 → S8.**

| # | Slice | Checkpoint acceptance |
|---|---|---|
| **S0** | **Regression floor** — characterization tests pinning the *current* `fire_routine` (concurrency, catch-up, exact-once, typed origin) before any change | existing engine behaviour is locked green |
| **S1** | **Reachability** — implement `add_routine` (wire `routines.create` + `triggers.create` + `parse_cron`); `routine` CLI noun; flip default → `coalesce` | `routine add` → tick fires it → spawns a task → dispatch runs it (keyed e2e) |
| **S2** ✅ | **Revisions** — migration 0019 (`routine_revision` + `routine.env`/`latest_revision_*` + `routine_run.routine_revision_id` + `routine.routine_key`); `revise/restore`; run pins revision | edit a routine mid-flight → the live run keeps the pinned definition; restore writes a new head |
| **S3** ◑ | **Env bindings** — `routine.env` validated at `add_routine`/`revise`/registration (fail-closed `assert_no_inline_secrets`, done); allow-list resolution at materialize (deferred) | inline-secret env rejected (done); allow-listed `ref:` resolved at materialize (deferred) |
| **S4** | **PM plugin** — `chorus_employee/pm` (brief, DoD, lander) + registry | a PM routine fires → lands a `plan_doc` artifact |
| **S5** | **Analyst plugin** — `chorus_employee/analyst` (brief, DoD, lander) + registry | an Analyst routine fires → lands a `findings_doc` artifact |
| **S6** ✅ | **Plugin-declared routines** — `RoutineDeclaration` + `reconcile_declared_routines` (hire-time); PM ships a weekly routine | a fresh plugin + hire creates a firing routine **with no diff under `src/chorus/`** |
| **S7** | **Portability** — `copy_org` carries routines + triggers + current revision; secret-binding re-prompt list | `export → import` round-trips routines + triggers; unresolved refs surface, never drop |
| **S8** | **Acceptance + HTML report** — one keyed e2e run | create → coalesce + backfill_one across ticks → spawn → dispatch → land; plugin-declared routine schedules; export→import round-trip — all in one report |

### Acceptance (the three M4 bars, as runnable assertions)

1. **Recurring work is real & safe.** A cron routine fires **exact-once across ticks**, and when it
   re-fires while its last task is live it **coalesces** (recorded `coalesced_into_run_id`), not
   piles up. `backfill_one` replays missed windows one-per-tick after downtime.
2. **A new role schedules with no kernel change.** Registering the PM plugin (which declares a
   routine) + running the reconciler yields a firing routine — proven by a test that touches no file
   under `src/chorus/`.
3. **The org is portable.** `export(org) → import(org')` re-materializes every employee's routines
   and triggers; bound secret refs are re-prompted, never leaked or dropped.

---

## 9. What this deliberately leaves for later

- **Webhook / external triggers + the HTTP listener** — the `kind` column is ready; delivery is a
  horizon surface (port, HMAC, replay window). A webhook-origin run is inherently low-trust and will
  reuse §4 (`LOW_TRUST_REVIEW`) when it lands.
- **Routine variables** — `{var}` templating waits for a trigger payload to bind from (i.e. waits
  for webhooks).
- **Multi-process firing** (`SKIP LOCKED`) — single-process `claim_fire` is exact-once; the
  distributed case is an Arceus/Postgres concern ([12](12-storage.md)).
- **Routine budgets / rate caps** — a routine that spawns too often is a budget concern
  ([04](04-outcomes-and-governance.md)); M4 relies on `concurrency=coalesce` to bound overlap, not
  on a spend gate.
