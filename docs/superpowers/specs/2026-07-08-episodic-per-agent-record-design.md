# Episodic per-agent record — design

**Status:** design, approved in brainstorm. Not built.
**Scope:** all employees. Two coupled slices of the episodic-memory spec (`docs/specs/lattice/…`,
the Hermes re-plumb):
- **Slice A** — the per-agent keyed record (write side, §3–§9).
- **Slice B** — `recall()`, the pull-channel read that closes the loop (§11). Depends on A.

---

## 1. Context — what exists today (grounded, not aspirational)

The episodic **write path is already live**. At every non-cancelled beat-end the scheduler
builds a `SprintDelta` and `AppendOnlyMemoryWriter` appends one `*.md` record per beat:

- `src/chorus/memory/_writer.py` — `SprintDelta` dataclass + `AppendOnlyMemoryWriter` (idempotent, one file per `run_id`).
- `src/chorus/heartbeat/_scheduler.py` — `_capture_memory` → `_sprint_delta` → `writer.apply(...)` (line ~724).
- `src/chorus_cli/_beats.py` — roots the writer at `company_root/memory`.

Honest fields already populated from the run: `run_id`, `task_id`, `employee_id`, `scope`,
`intent`, `outcome` (`done`/`needs_changes`/`blocked`), `score`, `created_at`, `body`.

**Three facts this slice acts on:**

1. `files_touched` is declared on `SprintDelta` but **never populated** — always `()`. The
   fingerprint (the structural key every downstream reader keys on) does not exist in any
   record written so far.
2. `artifacts` is likewise declared but **never populated** — always `()`.
3. Each record identifies its author only by `employee_id`; there is no `role`, and records
   physically co-locate under `<scope>/<run_id>.md` — not partitioned per agent.

**The open loop this build closes.** chorus writes to `company_root/memory/…`; dream reads
durable memory from `~/.dream/memory/{proj}-{hash}/` — a different directory, so today the write
path is a write-only stream nothing reads back. Slice A makes the record *keyed*; Slice B
(`recall()`, §11) makes it *read*. An FTS5 index and the consolidation/lattice policy remain
later slices.

---

## 2. Goal

Make every beat write a **complete, keyed, per-agent** episode — attributable (who + role),
structural (which files), provenanced (what landed), honestly stamped (when it ran / when
recorded) — and give the employee `recall()` to read its own past episodes mid-beat, each with
its outcome attached. End to end: a beat's honest trace becomes memory the same agent can pull
next time. All employees, via the shared kernel. Also the substrate the offline lattice
sleep-readers later consume.

---

## 3. Schema — `SprintDelta`

Two new fields; two existing-but-empty fields populated. Every field is derived from the run,
never authored by the worker.

| field | change | source at capture |
|---|---|---|
| `run_id`, `task_id`, `employee_id`, `scope`, `intent`, `outcome`, `score`, `created_at`, `body` | unchanged | as today |
| `files_touched: tuple[str, ...]` | **populate** | the beat's git diff (§5) |
| `artifacts: tuple[str, ...]` | **populate** | `ledger.artifacts.list_for_task(task_id)` → each artifact's `resource_ref` (fallback `url`, then `external_id`), skipping empties |
| `role: str` | **new** | `employee.role` |
| `recorded_at: datetime` | **new** | `now` at write (v1: equals `created_at`; the seam diverges only when a future backfilling writer sets record-time separately) |

`to_memory_delta()` adds `role` and `recorded_at` to the frontmatter `metadata` dict
(ISO-formatted datetime, matching `created_at`).

`files_touched` stays a flat path set: **no** add/modify/delete tags, **no** size cap at
write. Structural overlap needs only the path set; retention is forever-honest, so a large diff
is stored whole and down-weighted later by the consolidator, never truncated at capture.

---

## 4. Storage layout — per-agent partition

Change the write path from `<root>/<scope>/<run_id>.md` to:

```
company_root/memory/
  <employee_id>/
    r_8f2a….md      # one record per beat, named by run_id
    r_91c4….md
```

- **Depth-preserving:** the current layout is one dir level; agent-first is one dir level. The
  rollback glob `self._root.glob(f"*/{record_id}.md")` and `_scan_back` need **no change**.
- **Scope moves to frontmatter** (already in `metadata["scope"]`). Episodic memory is one
  agent's own history, so per-agent partition is the honest model; scope (private/project/
  team/company) is retained as a tag, not a directory.
- **Safe today:** nothing reads chorus's memory dir yet (recall/lattice not built; dream reads
  its own dir). Verified: no reader assumes the `<scope>/` layout.

Writer change (`AppendOnlyMemoryWriter.apply`): derive the subdir from
`delta.metadata["employee_id"]` instead of `delta.scope.value`. When `employee_id` is absent
(a non-sprint-delta caller), fall back to `delta.scope.value` so the writer stays generic.

**Loop-close note (later slice):** when the read path is pointed at this dir, dream's scanner
expects scope subdirs — reconcile then (configure dream per-agent, or add a scope view). Not
this slice.

---

## 5. Fingerprint capture — Approach A (baseline SHA at dispatch)

`_capture_memory` runs **after** the lander commits, so for a passed beat the worktree is clean
(`git diff HEAD` shows nothing) while a failed/errored beat's work is still uncommitted, and
worktrees persist across beats. A single disposition-agnostic capture:

1. **At dispatch**, where the beat's `working_dir` is already resolved, capture
   `base_sha = git -C <working_dir> rev-parse HEAD`. Thread it (one optional `str`) to
   `_capture_memory`.
2. **At capture**, in `<working_dir>`:
   ```
   files_touched = git diff --name-only <base_sha>          # tracked changes vs working tree
                 ∪ git ls-files --others --exclude-standard  # new untracked files
   ```
   `git diff --name-only <base_sha>` compares base → **working tree**, catching both the
   lander's commit and any uncommitted work in one shot — precise to this beat, uniform across
   dispositions.

Result: sorted, de-duplicated tuple of repo-relative paths.

---

## 6. Data flow

```
dispatch beat ─► capture base_sha (git rev-parse HEAD in working_dir)
     │
   run beat ─► land (passed) / repair / strand
     │
_capture_memory(run_id, employee, task, result, base_sha, now):
     ├─ files_touched ← git diff <base_sha> ∪ untracked      (best-effort)
     ├─ artifacts     ← ledger.artifacts.list_for_task(task_id)
     ├─ role          ← employee.role
     ├─ recorded_at   ← now
     └─ SprintDelta(...).to_memory_delta() ─► writer.apply ─► <employee_id>/<run_id>.md
```

---

## 7. Error handling & edge cases

- **No worktree** (reviewer, in-memory test runner): `working_dir is None` → `base_sha None` →
  `files_touched=()`. Honest (a read-only beat touched no worktree files). `artifacts` may
  still be non-empty from the ledger.
- **git failure** (not a repo, detached, subprocess error): `contextlib.suppress` the specific
  `subprocess.CalledProcessError`/`OSError` → `files_touched=()`. Fingerprint capture must
  **never** fail a beat.
- **base_sha unavailable** (fresh worktree with no HEAD): `files_touched=()` — never diff
  against the empty tree (that would mark every file touched), never raise.
- **Cancelled beat:** unchanged — records nothing (existing guard).
- **recorded_at == created_at** in v1 (documented in code).

---

## 8. Testing (TDD, gate: `ruff format && ruff check && mypy --strict && pytest`)

Unit (`tests/memory/test_writer.py`, extend):
- `SprintDelta` round-trips through `to_memory_delta` → `_render` → `_scan_back` **with**
  `role` and `recorded_at` in frontmatter.
- `AppendOnlyMemoryWriter.apply` writes to `<employee_id>/<run_id>.md`; two employees →
  two dirs; re-apply same `run_id` is an idempotent no-op; rollback still finds the record.
- Absent `employee_id` in metadata → falls back to `<scope>/<run_id>.md`.

Unit (`tests/heartbeat/…`, new/extend):
- `_sprint_delta` sets `role` from the employee and `recorded_at` from `now`.
- Fingerprint helper: a temp git repo where a beat commits file `a.py` and leaves `b.py`
  uncommitted (both since `base_sha`) → `files_touched == ("a.py", "b.py")`; a new untracked
  `c.py` is included; `base_sha=None` → `()`; a non-repo dir → `()` (suppressed).
- `_capture_memory` populates `artifacts` from a ledger with a recorded artifact.

Integration:
- A real (fake-runner) beat end-to-end writes a record whose frontmatter has non-empty
  `files_touched`, `role`, `recorded_at`, and (when landed) `artifacts`, under
  `<employee_id>/`.

---

## 9. Compatibility

The store is append-only markdown-with-frontmatter. New fields mean older records simply lack
them; readers default. The layout change only affects **new** writes; any pre-existing
`<scope>/<run_id>.md` records remain readable by the rollback glob (`*/…`). No migration.

---

## 10. Deferred (explicitly not this build)

FTS5 index (add when recall latency bites) · push/ambient channel (a distilled-lesson catalogue
in the system prompt — reserved for lattice, not raw episodes) · consolidation/lattice
(episodic→semantic, idle-heartbeat, two-arm gate) · richer per-role fingerprint dimensions ·
`outcome_source`/DoD-kind (hard-gate vs agent-review weighting) · physical scope views.

---

## 11. Slice B — `recall()` (closes the loop, pull channel)

**What / why.** Slice A makes the episodic stream keyed but still write-only. `recall()` is the
read primitive that turns it into memory the employee actually uses: a chorus `BaseTool` the
employee calls mid-beat to search **its own** past beats, each returned **with its outcome
attached** (§06 — recall the diary, but the diary is stamped pass/fail). This is the loop-closer,
the *pull* channel. Raw episodes are **not** pushed into the system prompt (a per-beat catalogue
is unbounded and noisy); the ambient/push channel is reserved for distilled lessons (lattice).

**Tool contract (`chorus_tools` `RecallTool`, tool name `recall`):**
- Input: `query: str | None` (keyword over `intent`+`body`), `files: list[str] | None`
  (fingerprint — rank by overlap with each record's `files_touched`), `limit: int = 5`. At
  least one of `query`/`files` is required.
- Reads only the calling employee's dir: `company_root/memory/<employee_id>/*.md` —
  `employee_id` comes from the stamped per-beat context (the same context the decompose /
  `test_evidence` capability tools read); `company_root` is injected at construction.
- Ranking: if `files` given, score = `|files ∩ record.files_touched|` (exact structural
  overlap — the spec's key), recency (`created_at`) as tie-break. If only `query`, naive
  term-score over `intent`+`body` (dream-style, no embeddings). Both provided → sum. Records
  from the current run are excluded.
- Output per hit — **outcome first**, so the claim and its result travel together:
  `run_id`, `outcome`, `score`, `files_touched`, `created_at`, prose snippet. An empty result
  is a normal (non-error) response.
- Read-only: no ledger write, no `CapabilityService`/idempotency.

**Honesty (§08).** The returned prose is worker-authored and untrusted — the tool labels it
plainly as a past note (data, not instructions); it is never surfaced as a directive.

**Wiring.** Construct `RecallTool(memory_root, …)` in `EmployeeHarnessFactory` (same seam as the
evidence tools); map `"recall": "recall"` in the chorus→dream tool map; add `"recall"` to each
of the 6 employees' tools tuple; a one-line brief directive ("at beat-start, `recall` past beats
on this task's files before planning").

**Depends on Slice A** — recall over a fingerprint-less stream is keyword-only; the fingerprint
is what makes structural recall work.

**TDD.** `RecallTool` over a temp dir with 3 seeded records: fingerprint overlap ranks the right
record first; `outcome` present in output; keyword-only path; empty result is non-error; reads
only the given employee's dir (isolation); current run excluded. A wiring test that a
materialized employee exposes `recall`. Then the gate.
