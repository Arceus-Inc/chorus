# 07 — Memory

How an employee reads and writes durable knowledge. chorus's equivalent of Paperclip's
`doc/memory-landscape.md` — but constrained by B4.1: **chorus owns the memory *mechanism*; lattice
owns the *consolidation policy*.** chorus captures memory at the **sprint level** — one raw,
append-only episodic delta per beat, with provenance — and **lattice (a sibling repo) owns
consolidation**. Until lattice ships, the writer stays append-only and a clean seam is left for it.

---

## 1. The contracts (dream's, reused)

chorus codes against `dream.contracts.memory` (dream-sdk-explained §1):

- **`MemoryScope`** — `private | project | team | company`. The visibility partition.
- **`MemoryType`** — `user | feedback | project | reference`. The taxonomy.
- **`MemoryRecord`** — `id, scope, type, content, source(path), frontmatter`. One per `*.md`.
- **`MemoryStore`** (read) — `list / get / search`. dream ships the read side + a file-backed default.
- **`MemoryWriter`** (write) — `apply(MemoryDelta) / rollback`. **chorus implements this.** Its
  docstring literally says *"implemented outside the SDK (e.g. lattice)"* — chorus provides the
  append-only writer **and reserves the seam**; the lattice sibling later replaces it with a
  consolidating writer (promotion / compaction / forgetting).
- **`MemoryDelta`** — an auditable diff (`create|update|delete` + `rationale`), not a raw write.

---

## 2. Read at beat start — progressive disclosure

dream's memory layer (dream-sdk-explained §5) renders a **catalogue**:
one-line teasers (id + description) go into the system prompt; full bodies load lazily via a
`memory_get` tool. So a beat starts with cheap recall and pulls detail only when needed.

```python
# rehydrate (spec 06)
records = memory_store.scope(emp.memory_scope)      # MemoryStore.list/search
catalogue = render_catalogue(records)               # teasers -> prompt
# full bodies fetched on demand inside the beat via memory_get
```

Scope selection: an employee reads its own `memory_scope` (e.g. `project`) plus broader scopes it's
entitled to (`team`, `company`). Narrower is private to the employee.

---

## 3. Write at beat end — append-only raw delta

After `run_task` returns, chorus writes **one raw episodic delta** — what happened — and nothing
more (B4.1):

```python
class AppendOnlyMemoryWriter:                 # chorus owns the MECHANISM
    async def apply(self, delta: MemoryDelta) -> MemoryRecord:
        # write a NEW *.md under the scope dir; never merge/compress/forget
        path = scope_dir(delta.scope) / f"{delta.target_id}.md"
        write_markdown(path, frontmatter=delta.metadata, body=delta.new_content)
        return scan_one(path)
    async def rollback(self, record_id, to_version):   # git revert
        ...
```

- It **never consolidates** — no promotion episodic→semantic, no compaction, no forgetting. The
  memory git just grows.
- The body carries **provenance** (B4.1, memory-landscape's non-negotiable): every record links back
  to the `run_id` / `task_id` that produced it (`frontmatter: {run_id, task_id, employee_id}`), so a
  later reader can explain *where a memory came from*.

### The sprint-delta content schema

Each beat emits exactly **one** raw episodic record with a fixed, typed frontmatter + a free-form
body — stable enough that lattice can later consolidate over it, raw enough that chorus makes no
judgement about worth:

```markdown
---
kind: sprint_delta            # the one episodic record type chorus writes
run_id: r_8f2…               # provenance (required)
task_id: t_41a…
employee_id: e_eng_2
scope: project
intent: "add retry to the upload client"   # what the beat set out to do
outcome: done                 # done | blocked | needs_changes  (mirror of the disposition)
score: 0.83                   # the evaluator's score, verbatim (no thresholding)
artifacts: ["pr:org/repo#214"]            # what landed (spec 04 §2)
files_touched: ["src/upload/client.py"]   # for later recall/dedup by lattice
created_at: 2026-06-14T18:22:09Z
---
What happened, in the employee's words: the fix, what fought back, what to try next.
```

The rules: every field above the `---` is **derived from the run, never authored by the worker**
(the worker can't claim a score); `outcome`/`score`/`artifacts` are copied verbatim from the
`RunTaskResult` (spec 05) so the record is an *honest* trace, not a self-report. chorus writes this
and stops — it does **not** synthesize a summary, dedup against prior deltas, or decide salience;
those are lattice's (§4).

> The day chorus decides *what is worth remembering*, it has rebuilt lattice inside itself. M2 writes
> raw and stops there.

### Concurrent writes to a scope (the memory git)

A shared scope (`project`/`team`/`company`) can receive deltas from **several beats at once**, so the
writer must be safe without a lock that serializes the whole org:

- **One file per record, named by `run_id`** (`{scope}/{run_id}.md`) — because each run id is unique,
  two concurrent beats *never target the same path*, so append-only writes are conflict-free by
  construction (no merge needed for the common case). This is why the writer is append-only-by-file,
  not append-to-one-log.
- **Commit per delta** with the run's identity as author; the scope git's history is the audit trail.
  If the backend is a real git repo and two commits race, the writer retries the commit on a stale-
  index error (rebase-onto-latest, never force) — the *content* never conflicts (disjoint files), only
  the index pointer, so the retry is always clean.
- **The read path tolerates partial writes**: `MemoryStore.list` scans whatever `*.md` are committed;
  an in-flight write that hasn't committed is simply not yet visible — there is no half-record, because
  a record becomes visible only at commit. A crash mid-write leaves an uncommitted file the next scan
  ignores (and the tick's recovery doesn't need to clean it — it's inert).
- **lattice's consolidating writer** is the *only* thing that ever rewrites existing files; it takes a
  scope-level lock for compaction precisely because it merges, while chorus's append-only writer never
  does. The seam keeps the contended path entirely on lattice's side.

---

## 4. The lattice seam (deferred consolidation)

When lattice exists, it plugs in **without chorus changing**:

- chorus keeps writing raw deltas via `MemoryWriter`; lattice **replaces** the writer (or runs as a
  background curator) and owns promotion / compaction / contradiction / forgetting — submitting its
  own `MemoryDelta`s with rationales (auditable diffs, not arbitrary writes).
- chorus keeps the **read path** and provenance; lattice keeps the **write/curation policy**.

This is the `MemoryStore`(read, chorus) / `MemoryWriter`(write, lattice) split, exactly as dream's
contracts encode it.

---

## 5. The provider-adapter shape (from memory-landscape, for later scale)

Paperclip's memory-landscape defines a **two-layer** model worth carrying forward as a seam (not
M1–M4 work): chorus owns *binding + provenance + the six-primitive portable core* (ingest, search,
recall, browse, forget, usage-report); a **provider adapter** owns *extraction, embedding, ranking,
profile synthesis, forgetting logic*. The file-backed default is the M-series implementation;
swapping in a vector/graph provider (mem0, etc.) is a later adapter behind the same `MemoryStore`/
`MemoryWriter` contracts. Required: support **both** provider-managed extraction *and* chorus-managed
curated writes; never assume one storage shape; cost/usage is a first-class metric.

---

## 6. Memory in the milestones

| Milestone | Memory |
|---|---|
| **M1** | one scope (`project`), read-at-start catalogue, no write yet |
| **M2** | three scopes (employee/team/org) + the append-only `MemoryWriter` + provenance |
| **M3+** | unchanged mechanism; richer recall as roles diversify |
| **(later)** | the provider-adapter seam; lattice owns consolidation |
