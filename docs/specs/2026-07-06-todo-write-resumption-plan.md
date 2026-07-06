# Plan — cross-beat resumption via `todo_write` (backend engineer)

*2026-07-06 · design lens: agent-harness-construction (action space / observation / recovery / context budget) · grounded in codebase probes + field practice.*

## The problem (from a live failure)

An honest multi-file beat exhausts its wall-clock budget mid-build. Making the quality gate real
(install ruff/mypy, fix the findings `compileall` hid) pushed a 2-domain service past its beat budget →
`TimeoutError` → the task **strands to `BLOCKED`**, and the half-built worktree (domain packages,
`mypy.ini`, partial tests) sits there with **nothing to pick it up**. The employee is stateless across
beats by design; today there is no durable "what's done / what's left" that the next beat resumes from.

## What already exists — DO NOT rebuild (verified)

- **`dream.todo_write` PERSISTS to disk.** `tools/builtin/todo_write.py:75` → `atomic_write_text(path,…)`,
  path `confine_path(ctx.working_dir, "TODO.md")`. It is **not** in-context like Claude Code's TodoWrite
  (which is ephemeral — confirmed). So the durable-file half is free; we grant it, we don't build it.
- **Persistent per-employee worktree**, reused every beat: `.chorus/work/{org}/worktrees/{employee_id}`
  (`workspace/_worktree.py:195-207`). No `git reset`/`clean` between beats; uncommitted work survives.
- **Re-dispatch on DoD failure** via the repair ladder → re-wakes the *same* employee, bounded by
  `max_repair_attempts` (`heartbeat/_scheduler.py:1222-1232`). Failed beats never snapshot; the lander
  commits only on PASS.

## The two gaps (this is all that's missing)

1. **A beat *timeout* strands to `BLOCKED`, it does not resume.** The repair ladder only re-dispatches a
   *DoD failure* (needs-changes). A `TimeoutError` is an engine error → `_strand_errored()` → `BLOCKED`
   (human recovery only, `_scheduler.py:690, 703-716`). Budget-exhaustion — the exact case — is the one
   that never auto-resumes.
2. **No re-injection of `TODO.md` at beat start.** Rehydration is *implicit* (the file is on disk in the
   reused worktree), but a fresh beat gets only the task intent — the agent must *choose* to read it.

## Field grounding (convergent)

The whole field runs "filesystem is memory, context is disposable": persistent plan/progress files
re-injected at session start ([planning-with-files](https://github.com/othmanadi/planning-with-files),
[Addy Osmani — long-running agents](https://addyosmani.com/blog/long-running-agents/)); **checkpoint
after each unit, not at the end** (the kill is abrupt); a **completion gate / Ralph loop** that refuses
to stop while an item is `in_progress`; and **session state (ephemeral) ≠ workflow state (persisted,
structured)**.

## Design (the four pillars)

### 1 · Action space
- **Grant Bex `todo_write`** (stable name, narrow schema, deterministic `TODO.md`). No new tool.
- **Add a beat-outcome disposition `incomplete`** (a.k.a. *resume*) to the kernel — distinct from
  `needs_changes`. Overloading `needs_changes` is wrong: it means "a reviewer looked and wants edits",
  it burns the repair budget, and it mislabels telemetry. A timeout is "ran out of clock, nothing wrong,
  continue". Three end-states, three labels: `passed` · `needs_changes` · `incomplete` · (`stranded` for
  a genuinely ambiguous crash).

### 2 · Observation
- `todo_write` returns the **remaining items as `next_actions`** (status/summary/next_actions). If
  dream's builtin returns only the rendered checklist, that is a small dream-side enhancement — note it,
  don't block on it.
- The **report already names the true disposition** (a timeout now reads "incomplete — budget exhausted;
  resume", not "needs-changes"). Extend the same honesty to kernel telemetry / the flow event so
  `incomplete` is a first-class, greppable outcome.

### 3 · Recovery (the reconcile protocol — mode-agnostic)
The agent **cannot reliably tell a clean timeout from a SIGKILL from inside — and must not need to.**
One uniform protocol, correct regardless of how the last beat died:
- **Checkpoint atomically after each finished unit** (`todo_write` already uses `atomic_write_text`), never
  at the end.
- **On resume, reconcile intent vs reality:** `TODO.md` = intent (what I *thought* I finished);
  `git status` + the discovered test/verify command = reality (what *actually* works). Agree → continue
  unchecked items. Disagree → re-verify/fix that item first.
- **Mode-1 vs mode-2 is told by the DoD feedback record**, not by guessing: a `needs_changes` beat left a
  reviewer verdict (specific asks) → address those; a timeout left no verdict → just continue.
- **Explicit stop condition:** after `K` consecutive resumes with **no progress** (TODO unchanged AND
  tests no better), stop resuming → **escalate to decompose** (reuse existing decompose) or human.
  Repeated budget-exhaustion means the task is too big for one beat, not that it needs more clock.

### 4 · Context budget
- `TODO.md` is durable state **off** the context window; re-inject at the **beat (phase) boundary**, not
  mid-beat. This is the "compact at phase boundaries" rule made concrete.

---

## Slices (bite-sized, TDD, smallest-blast-radius first)

### Slice A — grant + brief (works TODAY for the DoD-fail resume path; no kernel change)
- **Files:** `_harness.py` (add `"todo_write"` to `tools`), `_brief.py` (the reconcile directive),
  `tests/employee/test_backend_engineer_brief.py` + `..._subagents.py` (wiring test).
- **Brief directive (verbatim intent):** *"Keep a running `TODO.md` with `todo_write`: list the whole
  task's steps up front, and check each off THE MOMENT it's done — the beat can be killed abruptly.
  FIRST thing every beat: read `TODO.md` and reconcile — `git status` + the test command show what
  actually works; resume the unchecked items, do NOT restart. If a checked item's tests now fail,
  re-verify it first."*
- **TDD:** manifest grants `todo_write`; projects to Bex; brief mentions `TODO.md` + "resume" + "reconcile".
- **Payoff now:** on a `needs_changes` re-dispatch (already looping today), Bex resumes from `TODO.md`
  instead of re-deriving. Cheap, and it's the field-standard behaviour.

### Slice B — the `incomplete` disposition (the load-bearing kernel change; NEEDS the decision below)
- **Files:** the beat-outcome enum + `_scheduler.py` routing (TimeoutError → `incomplete` instead of
  `_strand_errored`), a **separate resume-attempt counter** on the task (distinct from
  `max_repair_attempts`), migration if the counter is persisted.
- **Behaviour:** `TimeoutError` → set task back to `TODO` + re-wake the same employee (like the repair
  ladder, but on its own budget); increment `resume_attempts`; leave the worktree untouched.
- **TDD:** deterministic test — a beat that raises `TimeoutError` re-dispatches the same employee, the
  worktree is intact, `resume_attempts` increments, and it does NOT consume `max_repair_attempts`.

### Slice C — bounded resume + escalate-to-decompose (the stop condition)
- After `K` no-progress resumes (`TODO.md` hash unchanged AND verify command no greener), stop → route
  to decompose (or human). Reuses the existing decompose/manager machinery.
- **TDD:** K resumes with an unchanged `TODO.md` → escalation fires; a resume that *does* progress resets
  the counter.

### Slice D — (optional, field-standard) auto re-inject `TODO.md` at beat start
- A rehydration seam in the factory/context that reads `TODO.md` (if present) into the beat's opening
  context, so resumption doesn't depend on the agent remembering to read. Do this only after A–C prove
  the loop; the brief directive covers it in the meantime.

### Slice E — keyed e2e proof
- Run a task **deliberately too big for one beat** (the 3-domain commerce API is the perfect fixture) and
  prove it **lands across two beats**: beat 1 times out → `incomplete` → `TODO.md` half-checked → beat 2
  reads it, resumes, finishes → PASS. Regenerate the report; the Sprint-evaluation shows beat-1
  `incomplete` → beat-2 `passed`.

---

## The one decision that is yours (blocks Slice B)

**Should a beat timeout auto-resume (same task → same employee → same worktree, bounded by a resume
budget), or keep stranding to `BLOCKED` for a human?** Auto-resume is what "budget exhausted → next beat
continues" requires; it's the whole point. The guard against runaway is Slice C (bounded + escalate to
decompose). Recommendation: **auto-resume with a small resume budget (e.g. 2) + escalate-to-decompose**,
because repeated exhaustion is a decomposition signal, not a clock signal.

## Sequencing
A (cheap, ship now) → **decide** → B → C → E. D is polish. A alone already improves the existing
needs-changes resume path; B is the piece that fixes the budget-exhaustion case you hit.

## Anti-patterns avoided (per the skill)
- No second state system — reuse `todo_write` + the persistent worktree.
- No overloaded label — `incomplete` is its own disposition with its own budget.
- No opaque recovery — the reconcile protocol is an explicit contract with a stop condition.
- No self-grading — reality is checked against git + the real test command, not the agent's claim.
