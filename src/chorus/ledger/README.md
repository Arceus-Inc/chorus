# `chorus.ledger` — the durable store (spec 01, spec 12 §6)

The ledger is chorus's source of truth for *what work exists and where it is*: the DAG of work, the
org tree, scheduling/liveness rows, money, outcomes — and procedural skills. It is **Postgres, the
only store** — raw native SQL (uuid, timestamptz, jsonb, boolean) behind the one concrete `Ledger`
class, with **no ORM**. Every table carries `company_id` + FORCE ROW LEVEL SECURITY scoped by the
session's `app.company_id`, so one shared schema serves every company (M5 tenancy).

```
ledger/
├── _ledger.py      # the Ledger facade — connection, bootstrap, repos, cross-aggregate atomics
├── _connection.py  # LedgerConnection — psycopg wiring (qmark→%s, savepoint-per-write, loaders)
├── _migrations.py  # the authored Postgres delta stream (applied-set runner, forward-only)
├── _models/        # frozen dataclasses + StrEnums per domain — the typed row shapes
├── migrations/     # NNNN_name.sql — immutable deltas applied on top of the baseline
├── schema/         # per-table .sql — the frozen BASELINE that bootstraps fresh databases
└── repos/          # one focused repo per aggregate (table), composed by the facade
```

## Using the DB

Open a ledger (bootstraps a fresh database and applies any pending deltas on the way in):

```python
from chorus.ledger import Ledger, Task

ledger = Ledger.open("postgresql://localhost/chorus", company_id=str(uuid.uuid4()))
try:
    ledger.tasks.submit(Task(id=mint_id(), intent="ship the thing"))
finally:
    ledger.close()
```

`company_id` (canonical uuid text) pins the session's tenancy context: FORCE RLS scopes every
read/write to that company, and the `company_id` column DEFAULT stamps every insert. In tests, use
`chorus.testing.open_test_ledger()` / the `ledger` fixture (a fresh template-copied database per
test on the session's throwaway PG18 cluster).

You never touch SQL or a connection directly — every read/write goes through a **per-aggregate repo**
exposed on the facade. The repos are wired in `_ledger.py`:

| Attribute | Repo | Table(s) |
|---|---|---|
| `ledger.tasks` | `TaskRepo` | `task` (submit, checkout, eligibility, locks) |
| `ledger.dependencies` | `DependencyRepo` | `task_dependency` (the DAG) |
| `ledger.decomposition_claims` | `DecompositionClaimRepo` | `decomposition_claim` (exact-once fan-out) |
| `ledger.recovery_actions` | `RecoveryActionRepo` | `recovery_action` |
| `ledger.monitors` | `MonitorRepo` | `monitor` (deferred self-wake) |
| `ledger.wakes` | `WakeRepo` | `wake` (coalescing push inbox) |
| `ledger.routines` / `routine_triggers` / `routine_runs` | routine repos | cron |
| `ledger.runs` | `RunRepo` | `run` (one beat) |
| `ledger.agent_sessions` | `AgentSessionRepo` | `agent_session` (the handle pointing at a dream conversation) |
| `ledger.skills` / `skill_revisions` | skill repos | `skill`, `skill_revision` (procedural memory HEAD + history) |
| `ledger.employees` / `goals` | org repos | `employee`, `goal` |
| `ledger.budget_policies` / `budget_incidents` / `cost_events` | budget repos | two-gate money |
| `ledger.dod` / `artifacts` / `artifact_revisions` | outcome repos | enforced outcomes |
| `ledger.messages` / `approvals` / `activity` | coordination repos | mailbox, gate, audit |

The kernel types against the concrete `Ledger` class directly — one driver, no protocol
indirection. The domain facades that ride it (`chorus.skills.SkillStore`) compose these repos
rather than owning connections.

### Agent sessions (the handle, not the transcript)

dream is the runtime, so dream owns the conversation: messages and tool calls live in its
session store and a beat continues a thread by handing back its key. What the ledger keeps is
the control-plane row mapping `(employee, task)` to that key, plus the parts chorus is
answerable for — spend against a budget, the last run to touch the thread, where it worked,
and why a resume failed.

```python
from chorus.ledger import begin_beat_session, dream_session_key_for_task, persist_beat_account

session = begin_beat_session(
    ledger, employee_id=employee.id, task_id=task.id, run_id=run.id
)
# session.dream_session_key == dream_session_key_for_task(task.id)
# The beat runner passes it as run_task(session_scope=...); dream derives one
# session per role beneath it ({scope}-planner, -generator, -evaluator).
persist_beat_account(ledger, session.id, input_tokens=…, output_tokens=…, cost_cents=…)
```

One **open** session per task (partial unique index). Seal/abort frees the slot for a fresh
thread.

Mirroring the messages here as well would give one conversation two sources of truth, and the
copy in Postgres would always be the stale one. Read a transcript from dream.

### Cross-aggregate transactions

A single repo write is atomic on its own (savepoint-per-write under the hood). When an operation
must touch **several** tables at once, wrap it so it commits (or rolls back) as one unit:

```python
with ledger.transaction():
    ledger.tasks.submit(child)
    ledger.decomposition_claims.add_child(claim_id, child.id)   # both, or neither
```

Inside the block, repos defer their per-call commits; the outermost block commits once on success or
rolls back on any exception. The facade exposes the spec-mandated multi-table operations built on this:

- `ledger.finalize_beat(task_id=…, run_id=…, dod_status=…, verdict=…)` — at beat end, writes the
  `dod` verdict **and** derives `task.status='done'` (+ `completed_at`) **and** enqueues the
  downstream `wake` rows (`deps_resolved` / `children_done`) the *next* beat picks up — all in one
  transaction (spec 01 Cluster F, spec 03). A non-passed verdict only records the dod result.
- `ledger.create_child(claim_id, child)` — creates a decomposition child `task` and records it on the
  claim's `child_task_ids` atomically (spec 02 §4), so a crash mid-fan-out never strands a task.

### Conventions baked into the repos

- **Immutable models** — every row is a `@dataclass(frozen=True)` under `_models/`; enums are `StrEnum`.
- **Native types on the wire** — uuid ids (`mint_id()` = uuidv7; `derive_id()` = deterministic uuid5),
  `timestamptz` in UTC read back as canonical ISO text, `jsonb` blobs, real booleans.
- **Crash-safety is in SQL**, not application locks: partial-unique indexes for exact-once /
  coalescing / single-pending guarantees, CAS-style conditional `UPDATE`s, and DB-level `CHECK`/`FK`
  constraints as defense-in-depth. Unique keys are company-prefixed unless the id is a minted uuid
  (`tests/ledger/test_ledger_conformance.py` freezes the deliberate global-unique list).

## Schema lifecycle: baseline + authored deltas

Two layers, both owned here (deployments — e.g. podium's alembic — orchestrate, never author):

- **`schema/<table>.sql`** — the **frozen baseline**: one native-PG file per table (DDL + RLS +
  indexes), FK-dependency-ordered at load. `baseline()` returns `(id, checksum, statements)`;
  fresh databases bootstrap from it under an advisory lock, recording the checksum in
  `chorus_schema_migrations`. Once databases exist, the baseline never changes — a checksum
  mismatch raises `SchemaDriftError`.
- **`migrations/NNNN_name.sql`** — the **authored delta stream** (first delta: `0002_skills`).
  `Ledger.open` applies pending deltas in id order inside the bootstrap transaction, recording each
  in `chorus_schema_migrations` (`id`, `checksum`, `applied_at` — the applied-set model, so two
  branches that each add a migration merge as two rows, never a renumber). It **refuses to open**
  when the database is *ahead* of the SDK (`LedgerAheadError`) or a shipped delta was edited after
  apply (`MigrationDriftError`). `ledger.schema_version()` reports the newest applied id.

`tests/ledger/test_pg_migrations.py` pins the invariant: a baseline+deltas database and a fresh
bootstrap converge on identical columns, indexes, and FORCE-RLS posture.

Deployments whose runtime role cannot run DDL apply the same deltas as the schema owner via
`load_migrations()` (each `Migration` exposes `statements()` and `table_names()` for exact-table
grants); `Ledger.open` then sees the rows and skips — podium does this generically in its alembic
`env.py`, so a new delta here needs zero podium code.

### Adding a migration

1. Create the next-numbered file, e.g. `migrations/0003_add_widget.sql`, with the forward DDL —
   native Postgres, and every new table follows the house pattern: `company_id uuid NOT NULL
   DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid`, ENABLE + FORCE ROW LEVEL
   SECURITY, an InitPlan-wrapped isolation policy, company-prefixed indexes. Copy an existing
   `schema/*.sql` or `migrations/0002_skills.sql` as the template.
2. If it's a new table, add a `repos/<aggregate>.py`, models under `_models/`, and wire the facade
   attribute in `_ledger.py` plus the `repos/__init__.py` and `chorus.ledger.__init__` exports.
3. Run the suite — migrations + conformance + your new tests must pass:

```bash
uv run pytest -q tests/ledger
uv run ruff check . && uv run mypy src
```

> Migrations are immutable once merged. Need to change a shipped one? Ship a *new* migration that
> migrates forward — never edit history (the checksum gate will reject it anyway).
