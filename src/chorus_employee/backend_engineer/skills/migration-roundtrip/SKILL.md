---
name: migration-roundtrip
description: How to prove a schema migration is REVERSIBLE, not just forward-applicable — apply it, roll it back, and re-apply against the SAME real engine production runs, so a bad deploy has a way out. A migration with an unexercised (or missing) down path is a one-way door you find out about during an incident.
when_to_use: Read whenever the change includes a schema migration (a new table/column/index, a type change, a constraint) or any DDL against a real datastore. Use it to prove the down path actually reverts, before the migration lands — the rollback you never ran is the one that fails at 3am.
---

# Migration round-trip — a migration you can't roll back is a one-way door

A migration that applies cleanly forward proves exactly one thing: it applies forward. It does not
prove you can get *back* — and the moment a forward-only migration ships a bug, there is no safe exit
but a restore-from-backup with data loss. "It has a down migration" is not proof either: an unrun down
path is code that has never executed, i.e. probably broken. The only proof is the **round-trip**, run
against the real engine.

## 1. Every forward migration ships a matching, exercised down path

- Write the **down** migration alongside the **up** — the exact inverse (add column ⇄ drop column,
  create table ⇄ drop table, add constraint ⇄ drop constraint). If your migration tool generates it
  (Alembic `downgrade()`, Rails `change`/`down`, Django `migrations`), still *run* it; if it's raw SQL,
  author `00N_x.down.sql` next to `00N_x.up.sql`.
- An **irreversible** step (a destructive `DROP COLUMN` that loses data, a lossy type narrowing) is a
  design decision, not an oversight — call it out explicitly and gate it behind an expand/contract
  plan (add-new → backfill → switch → drop-old across separate deploys), never a single silent
  one-way migration.

## 2. Prove it against the SAME engine production runs — never SQLite

DDL is where engines differ most: Postgres transactional DDL, `NOT VALID` constraints, `CONCURRENTLY`
indexes; MySQL's implicit commits; column-type coercion rules. A round-trip that "passes" against
SQLite proves nothing about the Postgres your service actually runs. Boot the real engine as a
disposable container (see `testcontainers-integration`) — `podman run` / `docker run` /
`docker-compose up`, whichever runtime the sandbox has — and run the round-trip against it.

## 3. The round-trip: apply → write → roll back → re-apply, asserting state each step

Against the live container, in one probe script:

1. **Apply** the migration (up). Assert the new schema exists (the column/table/index/constraint is
   there — query the catalog: `information_schema`, `\d`, `pg_indexes`).
2. **Write** a row that exercises the new schema, so the round-trip carries data, not just DDL.
3. **Roll back** (down). Assert the schema is returned to its **prior** state — the added object is
   gone, and — critically — the pre-existing tables/rows are **untouched** (a down migration that
   drops more than it added, or corrupts existing data, is worse than no rollback).
4. **Re-apply** (up again). Assert it succeeds a second time — proving the migration is idempotent
   enough to redeploy, and that the down didn't leave the schema in a state the up can't handle
   (e.g. a leftover object that makes the second `CREATE` fail).

If any step diverges from the expected schema/data state, the migration is **not** round-trip-safe —
report it as a failing gate, don't land it.

## 4. Record it as its own `test_evidence` gate

Hand the round-trip to `test_evidence` as a named gate alongside lint/types/unit:

```
test_evidence(gates=[
  {"name": "unit",      "command": "pytest -q"},
  {"name": "migration", "command": "bash migration_roundtrip.sh"},  # boots PG, up/rollback/re-up
])
```

A green `test_evidence/manifest.json` carrying a `migration` gate that actually booted a real engine
and ran the full round-trip is the proof the deploy has a safe exit — not a claim that "the down
migration exists."

## Why this is a skill, not a tool

Which migration tool, which catalog query proves the schema state, what "prior state" means for this
change is per-stack, per-diff know-how — discovered, not hardcoded (§03). `test_evidence` stays a
stack-blind executor; this skill is how you decide what round-trip gate to hand it.
