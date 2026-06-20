# post-dev-wiring — bugs & feature coverage

Status of the standup-app post-dev wiring: bugs fixed/open, features tested/untested, and findings.
All runs use gpt-5.2 (`chorus/.env`). Driver: `standup-app/feature_tests.py`; modes: `run.py --solo/--team/--org`.

## Bugs — fixed

- **BUG-001 — `--team` never terminates.** Reviewer-gated DoD + shell-less reviewer spun on `needs-changes 0.0`.
  Fix (run.py): engineer DoD → `Verifier.command("pytest -q && ruff check .")`; pass `roles=plugins` to both the
  factory AND `Chorus.build`; poll loop exits on all-children-done/stall.
- **BUG-002 — Shared-file decomposition drops a deliverable.** Branch collision dropped the test file; manager also
  split impl/tests into deadlocking children. Fix (demo goal): disjoint files + self-contained children.
- **BUG-003 — Manager integrate beat blind to subtree.** Manager worktree cut from `main`, never refreshed.
  Fix: `CompanyWorkspace.sync_to_main()` ff-merge of `main`, called from `materialize()` on integrate beats.
- **BUG-004 — plan/`decompose` beat fails "planner reply missing &lt;spec&gt;".** Cause: stale `.env` key returned
  empty completions (looked like a model/prompt bug). Fix: refresh key; probe `/chat/completions` first.
- **Director goal ended `blocked` (top-of-tree integrate).** Poll loop stopped one tick before the director's
  integrate wake; plus occasional mis-decompose. Fix (run.py): keep ticking until the goal closes (`rollup_grace_s`);
  kernel `max_integrate_iterations=3` mechanically closes churny decomposes.

## Bugs — open / not fixed

- Manager's first `decompose` often `[ERR]`s then retries OK (noisy, non-fatal).
- Engineers fabricate `git push`/PR links and scaffold a `docs/` dir despite goal text.
- An objective `Verifier.command` DoD is **silently skippable** (see findings) — not a hard floor today.
- chorus **episodic** memory capture is inert in the supported build path (see findings).
- Pre-existing unrelated test failures: `test_factory.py::…memory_search` (planner now toolless);
  `test_verify_runner.py::test_runs_in_the_worktree` (uses `cat`, not on Windows).

## Features — tested

- **Engineer solo beat** (`--solo`) — worktree work, objective DoD, deliverable lands on `main`.
- **Manager + reviewer team** (`--team`) — decompose → two disjoint-file engineers → integrate → subtree lands.
- **3-level org** (`--org`) — director → two leads → engineers; integrate cascade at each tier; 4 modules land.
- **Decomposition, integrate cascade, worktree isolation + merge, objective Command DoD** — covered by the above.
- **PM role** (`doc` → `plan.md`) — lander works; on-brief content NOT enforced (see findings).
- **Analyst role** (`finding` → `findings.md`) — on-brief, artifact lands.
- **Routines / cron** — live every-minute cron fires, spawns + runs a task; PM weekly auto-provision (`0 9 * * 1`).
- **Governance — hire-approval gate** — `request_hire` holds a PENDING hire until `resolve(APPROVE)`, then it runs.
- **Budgets** — 1¢ cap trips a HARD incident + pending approval, pauses new work, `raise_` resumes.
- **Memory — durable cross-beat recall** — a fact known only to beat 1 is recalled by the same engineer in beat 2.

## Features — not tested

- **Trust presets** (`trust.set_task`) — tool-permission narrowing per preset.
- **Messages** (`send_message` → wake → recipient reads it on next beat).
- **Dependencies / ordering** (`depends_on` gate holds task 2 until task 1 is `done`).
- **Recovery** (stranded run → recovery card → resolve/re-dispatch).
- **Reviewer block escalation** (`_route_block` — rejected child → manager reaction / re-dispatch).
- **Governance plan gate** (`open_plan_gate` withholds a decompose until resolved) — only the hire gate is tested.

## Findings while testing

- **PM Command DoD is silently skippable.** A chorus `Verifier.command` DoD runs only via dream's oracle, which runs
  only when `evaluator_enabled` is true — and the **planner LLM** decides that, emitting `false` for doc/plan tasks →
  the gate never executes and the task passes off-brief. Overriding the PM's DoD also **replaces** its default
  `agent_review` reviewer, so semantic drift isn't caught either. Fix idea: pin `evaluator_enabled=True` when a beat
  carries `verification_steps`.
- **Budget hard-stop is post-hoc.** Gate 2 prices spend **after** a beat, so a one-beat task still finishes; the stop
  pauses the **next** invocation (Gate 1 holds new dispatch while paused). Company scope id must be the factory
  `company_id` (`"acme"`), not `"company"`.
- **Governance.** `org.hire(...)` always bypasses the gate; only `request_hire` is gated. A pending hire's wake is
  **held** (not dropped) and dispatches on the next tick after `resolve(APPROVE)`.
- **Memory.** Cross-beat recall rides dream's durable PROJECT memory. Separately, chorus **episodic** capture is OFF:
  `Chorus.build` builds an `AppendOnlyMemoryWriter` but never threads it into the `Scheduler`, so no `SprintDelta`
  files are written during real runs.
- **Manager integrate** now reads landed files `[ok]` and renders genuine `pass 1.0` after the BUG-003 sync fix.
- **`--org` 3-level run** (gpt-5.2): vera → moe/max → ada/bo/cy/di all `done`; 4 modules land; BUG-003 sync fires at
  both tiers; `report.py` draws the org chart + decomposition tree from the ledger.
