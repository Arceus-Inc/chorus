# 12 — Storage architecture

Where each durable thing lives, why **SQLite-now** is both correct and reversible, and the
disciplines that stop "we'll need Postgres later" from ever becoming a rewrite. This pins the
decision behind spec 01 (the ledger) and spec 07 (memory) so it stays true under pressure.

---

## 1. The principle — partition by store, not "one DB"

There is no single chorus database. Each durable concern sits behind **its own contract** and
picks the backend that fits it. SQLite is therefore *only ever* the ledger's default driver — it is
never a place where "Postgres-y" things accidentally land. The thing people fear ("a pile of stuff
stuck in SQLite that should be in Postgres") cannot happen if every store is routed deliberately.

---

## 2. The store → backend routing table

| Store | Contract | Holds | SDK backend (chorus) | Distribution backend (Arceus) | Why this backend |
|---|---|---|---|---|---|
| **Ledger** | `Ledger` | tasks, wakes, routines, runs, goals, budgets | **SQLite-WAL** (a file) | Postgres | hot, transactional, crash-safe; **schema is portable** |
| **Coordination board** | dream `coordination` | the two locks (`checkout`/`execution`) + lease | dream `board.sqlite` | Postgres claims | reuse dream — chorus doesn't rebuild it |
| **Memory — working** | `MemoryStore`/`MemoryWriter` | episodic notes, durable knowledge | git-markdown | git / Postgres | slow, diffable, provenance-linked |
| **Memory — long-term** | `MemoryStore` (vector) | semantic recall over a growing corpus | file/`sqlite-vss` index (later) | **Postgres + pgvector** / vector DB | genuinely needs vectors — **never the ledger** |
| **Artifacts / blobs** | object-store seam | files, PR refs, rendered outputs | filesystem | S3-compatible | not a DB at all |
| **Analytics / rollups** | — (read the ledger) | reporting, cross-company | — | Postgres read replica | an Arceus concern |

Read the table as the answer to "what about the stuff that should be in Postgres?": **route it.**
Concurrency/multi-tenant → the Postgres *driver* of the same ledger (a runtime swap, not a schema
change). Vector search → the long-term memory store (Postgres+pgvector *now*, independently — it was
never the ledger's job). Blobs → an object store. None of it gets stuck.

---

## 3. The two disciplines (the insurance)

1. **The kernel is DB-agnostic.** Scheduler/recovery/outcomes code touches only the Protocols
   (`Ledger`, `WakeQueue`, `RoutineStore`, `MemoryStore`/`MemoryWriter`, `Inspector`) — it never
   imports `sqlite3`/`psycopg`. (The scaffold already enforces this: `ledger/_ledger.py` is a
   `Protocol` + a `SqliteLedger` driver.)
2. **The ledger schema stays in the SQLite ∩ Postgres intersection** (§4). Same DDL translates to
   both dialects, so a second driver is a *translation*, not a redesign.

If both hold, "switch to Postgres" = add one driver class + run the same tests (§5). There is no
corner to paint into.

---

## 4. The portable intersection (ledger schema rules)

**Allowed in the ledger schema** (exists + behaves the same in both engines):

- text `uuid` ids; `json` columns (SQLite `json1` text ↔ Postgres `jsonb`); ISO-8601 text ↔
  `timestamptz`; integer cents.
- **partial-unique indexes** — the crash-safety contracts (spec 01). Both engines support `CREATE
  UNIQUE INDEX … WHERE …`.
- the **conditional `UPDATE … WHERE … RETURNING`** checkout / claim. Works on both (SQLite serializes
  writes; Postgres uses row locks).
- recursive CTEs for subtree rollup.

**Banned from the ledger schema** (driver-specific → live in the driver, never the contract):

- `SELECT … FOR UPDATE` / `SKIP LOCKED` (Postgres-only). Model ownership as the conditional-UPDATE
  CAS instead. *The Postgres driver MAY use `SKIP LOCKED` internally for the wake queue as an
  optimization, but the `WakeQueue` contract must not require it.*
- `pgvector` / `sqlite-vss` — not in the ledger; that's the long-term memory store (spec 07).
- `LISTEN`/`NOTIFY` — the ledger is **passive** (B2.3); the tick polls. No push from the DB.
- stored procedures, triggers, engine extensions, dialect-specific types.

---

## 5. The conformance test — insurance you can run

The real guarantee is a **single test suite parameterized over any `Ledger` implementation**.
`SqliteLedger` passes it today; `PostgresLedger` runs the *identical* suite the day it exists — if
green, the swap is proven, not hoped.

```python
# tests/test_ledger_conformance.py
@pytest.fixture(params=["sqlite"])          # add "postgres" when the driver lands
def ledger(request, tmp_path): ...           # build the driver under test

def test_submit_is_exact_once_for_origin(ledger): ...   # origin index rejects the 2nd insert
def test_set_status_stamps_timestamps(ledger): ...       # in_progress→started_at, done→completed_at
def test_list_eligible_gates_on_dependencies(ledger): ...# withheld until last depends_on is done
def test_list_eligible_ordering(ledger): ...             # in_progress → deps-ready → priority/age
def test_release_locks_is_terminal_only(ledger): ...     # never clears a live run's lock (CAS)
def test_checkout_conflict_is_409(ledger): ...           # 2nd claimant loses, doesn't corrupt
# + WakeQueue: coalescing on coalesce_key; RoutineStore: claim_edge double-fire guard
```

Write these against the **Protocol**, not `SqliteLedger`. That is what turns "we might need
Postgres" into a non-event.

---

## 6. The migration path (when chorus becomes Arceus)

1. `PostgresLedger(Ledger)` — same tables, Postgres dialect (`uuid`/`jsonb`/`timestamptz`; the
   wake-queue claim may use `SKIP LOCKED`).
2. Run the §5 conformance suite against it → green.
3. One-shot row copy SQLite → Postgres (rows are plain; ~50 lines).
4. Arceus wires `PostgresLedger` in `Chorus.build(...)`. **Kernel unchanged.**

Days, not a rewrite — *because* of §3.

---

## 7. Cost-of-being-wrong (why SQLite-now is the right bet)

| Choice | If the bet is wrong | Standing cost |
|---|---|---|
| **SQLite now** (recommended) | add one driver + run existing tests + copy data — bounded, reversible | none; stays a zero-infra library |
| **Postgres now** | — | every dev/test/example needs a PG server; the SDK stops being a library; you pay Arceus's infra before you have Arceus |

SQLite-now is cheaper *and* reversible. Postgres-now is neither.

---

## 8. Consequence for the other specs

- **Spec 01** is the *portable* ledger DDL. `SqliteLedger` applies it; `PostgresLedger` will
  translate it. Keep every column/index inside §4.
- **Spec 07** owns the long-term memory store — that is where pgvector / a vector DB belongs, behind
  `MemoryStore`/`MemoryWriter`, **separate** from the ledger and allowed to be Postgres "elsewhere"
  from day one.
- **Where the SQLite file lives**: consumer-supplied `db_path` (most library-like), with a default of
  `~/.chorus/<workforce>.db`.
