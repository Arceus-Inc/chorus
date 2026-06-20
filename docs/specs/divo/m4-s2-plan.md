# M4 S2 — Routine revisions (implementation plan)

> Implements spec [13 §2/§3](13-recurring-work.md): a routine becomes versioned — an append-only
> `routine_revision` history, a head pointer on the live row, and a run that **pins** the revision it
> fired under so an in-flight edit never re-judges a firing. Mirrors the §1 DoD-revisability pattern.

## Spec-vs-reality drift recorded

§2.4 assumed one combined `0018_routine_revisions.sql` carrying the revision schema *and* the
coalesce-default flip. S1 already shipped `0018` as coalesce-only, so S2 lands a fresh
**`0019_routine_revisions.sql`**. No behavioural difference; the migration number is the only change.

## Schema (`0019_routine_revisions.sql` + declarative `schema/`)

- **`routine`** (rename-rebuild, cf. 0017/0018) gains: `env` (JSON secret-ref bindings, S3 gives it
  meaning), `routine_key` (stable reconcile identity, S6), `latest_revision_id` → `routine_revision`,
  `latest_revision_no` (NOT NULL DEFAULT 1). New partial-unique index
  `routine_employee_key_uq(employee_id, routine_key) WHERE routine_key IS NOT NULL`.
- **`routine_revision`** (new): immutable, append-only; `(routine_id, revision_no)` unique.
- **`routine_run`** gains `routine_revision_id` (`ALTER TABLE … ADD COLUMN`, appended last to match
  parity) — the def each firing fired under.
- **Data migration**: any existing routine gets a synthesized revision 1 from its current columns
  (deterministic id `rrev_seed_<routine_id>`), then `latest_revision_id` is pointed at it. Fresh DBs
  have zero routines, so the synthesis is a no-op there. FK is OFF during apply (runner line 163), so
  the routine↔routine_revision circular reference is safe; the app connection (FK ON) is handled by
  ordering writes: insert routine (head NULL) → append revision → `set_head`.

## Code (clean, immutable, no get/setattr)

- **Models** (`ledger/_models.py`): new frozen `RoutineRevision`; `Routine` gains `env` /
  `routine_key` / `latest_revision_id` / `latest_revision_no`; `RoutineRun` gains
  `routine_revision_id`.
- **Repos**: new `RoutineRevisionRepo` (`append` / `get` / `head` / `by_routine` / `get_by_no`);
  `RoutineRepo.create` persists the new columns; `RoutineRepo.set_head(routine_id, *, revision_id,
  revision_no)`; `RoutineRunRepo.record` writes the pin.
- **Lifecycle** (`cron/_revise.py`): `revise_routine(...)` snapshots head ⊕ patch → new head revision
  (raises `NoRoutineRevision` on a no-op, so the S6 reconciler is idempotent); `restore_routine(...)`
  copies an old revision into a new head (`restored_from_revision_id` provenance, never mutates
  history). Authority guard: the routine **owner** or the owner's **manager** (`reports_to`).
- **Firing** (`cron/_fire.py`, ~2 lines): read `routine.latest_revision_id`, stamp it on every
  `routine_run`, and source the spawned task's `intent` from the **pinned** revision. The engine
  (concurrency / catch-up / exact-once / typed origin) is untouched; the S0 floor (`test_fire.py`)
  stays green.
- **Facade**: `org.routines.add(..., env=, routine_key=)` creates rev1; new `revise` / `restore`
  verbs; `RoutineView` surfaces `latest_revision_no`.

## TDD order (RED → GREEN per slice, gated by ruff + mypy --strict + pytest)

1. **Schema/migration** — parity test + `0019` applies + synthesizes rev1.
2. **Repo** — `RoutineRevisionRepo` append/head/by_no; `set_head`; run pin round-trips.
3. **revise/restore** — new head on change, `NoRoutineRevision` on no-op, restore provenance,
   authority (owner ✓ / manager ✓ / stranger ✗).
4. **fire pins + in-flight invariant** — a firing stamps the head; revising mid-flight leaves the
   recorded run's pin unchanged and the spawned task's intent sourced from the pinned revision.
5. **facade + e2e** — add→revise→fire→restore through `org.routines`, every branch covered.
