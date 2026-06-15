# `chorus.ledger` — the durable store (spec 01)

The ledger is chorus's source of truth for *what work exists and where it is*: the DAG of work, the
org tree, scheduling/liveness rows, money, and outcomes. It is **SQLite by default, Postgres-pluggable
later** — raw, intersection SQL (SQLite ∩ Postgres) behind a `Ledger` Protocol, with **no ORM**.

```
ledger/
├── _ledger.py      # SqliteLedger facade + Ledger Protocol (the swappable seam)
├── _models.py      # frozen dataclasses + StrEnums — the typed row shapes
├── _migrations.py  # the applied-migration-set runner (forward-only)
├── migrations/     # numbered .sql — the ordered, immutable history applied to a DB
├── schema/         # declarative per-table .sql — what the schema *should* look like
└── repos/          # one focused repo per aggregate (table), composed by the facade
```

## Using the DB

Open a ledger (creates the file and applies any pending migrations on the way in):

```python
from chorus.ledger import SqliteLedger, Task

ledger = SqliteLedger.open("chorus.db")   # or ":memory:" for tests
try:
    ledger.tasks.submit(Task(id="t1", intent="ship the thing"))
    task = ledger.tasks.get("t1")
finally:
    ledger.close()
```

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
| `ledger.employees` / `goals` | org repos | `employee`, `goal` |
| `ledger.budget_policies` / `budget_incidents` / `cost_events` | budget repos | two-gate money |
| `ledger.dod` / `artifacts` / `artifact_revisions` | outcome repos | enforced outcomes |
| `ledger.messages` / `approvals` / `activity` | coordination repos | mailbox, gate, audit |

The kernel depends on the `Ledger` **Protocol** (also in `_ledger.py`), never on `SqliteLedger`
concretely — a Postgres-backed ledger can be dropped in behind the same shape (spec 12). Only
`open()` (connection setup) and the migration DDL are dialect-specific.

### Cross-aggregate transactions

A single repo write is atomic on its own. When an operation must touch **several** tables at once,
wrap it so it commits (or rolls back) as one unit:

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

- **Immutable models** — every row is a `@dataclass(frozen=True)` in `_models.py`; enums are `StrEnum`.
- **Timestamps** are ISO-8601 text; **JSON columns** are compact text (`repos/_base.py` helpers).
- **Crash-safety is in SQL**, not application locks: partial-unique indexes for exact-once /
  coalescing / single-pending guarantees, CAS-style conditional `UPDATE`s, and DB-level `CHECK`/`FK`
  constraints as defense-in-depth.

## Migrations

Versioning tracks an **applied-migration set** (not a single integer), so parallel development can't
collide. A runner-owned `schema_migrations` table holds one row per applied migration
(`id`, `checksum`, `applied_at`).

**On `open()`** the runner (`_migrations.py`) diffs the migrations the SDK ships against the rows in
`schema_migrations` and:

- applies anything shipped-but-not-in-the-DB, in `id` order — **forward-only, no down-migrations**;
- **refuses to open** if the DB has a migration the SDK doesn't ship (DB is *ahead* of the SDK);
- **refuses to open** on checksum drift (a shipped migration was edited after it was applied).

Each migration applies inside `BEGIN IMMEDIATE` with an in-lock re-check, so two processes starting at
once can't double-apply.

Migrations apply automatically — there is no separate "run migrations" command; just
`SqliteLedger.open(path)`. To inspect the current version:

```python
ledger.schema_version()   # highest applied migration id, e.g. "0013_review_hardening"
```

### `migrations/` vs `schema/`

Two views of the same schema, kept in sync **by hand** (no ORM to generate one from the other):

- **`migrations/NNNN_name.sql`** — the ordered, **append-only** history. Once a migration has shipped,
  never edit it; add a new numbered file instead. Loaded automatically via `migrations/__init__.py`.
- **`schema/<table>.sql`** — the declarative "what the schema should look like now", one file per
  table. Used by tooling and humans to read the current shape without replaying history.

`tests/ledger/test_schema_parity.py` is the guard: it applies all migrations to a fresh DB and asserts
the result **exactly equals** (by normalized DDL) the objects `schema/` declares. If they drift, it
fails — so any schema change edits **both** places.

### Adding a migration

1. Create the next-numbered file, e.g. `migrations/0014_add_widget.sql`, with the forward DDL.
   - Adding a column/table/index → plain `ALTER`/`CREATE`.
   - Adding a `CHECK`/`FK` to an existing table → SQLite can't `ALTER ADD CONSTRAINT`; rebuild with the
     **rename-old** pattern (rename the old table aside, `CREATE` the final table directly with the new
     name, `INSERT … SELECT`, drop the old, recreate indexes). Creating the final table directly —
     rather than `RENAME`-ing a `_new` table into place — keeps the stored DDL unquoted so parity holds.
     See `0013_review_hardening.sql` for a worked example.
2. Update the matching `schema/<table>.sql` to the new final state.
3. If it's a new table, add a `repos/<aggregate>.py` and wire it into `repos/__init__.py`,
   `_ledger.py` (facade attribute + `Ledger` Protocol), and `__init__.py` exports.
4. Run the suite — parity + e2e + your new tests must pass:

```bash
uv run pytest -q -W error::ResourceWarning
uv run ruff check . && uv run mypy src
```

> Migrations are immutable once merged. Need to change a shipped one? Ship a *new* migration that
> migrates forward — never edit history (the checksum gate will reject it anyway).
