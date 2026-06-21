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

- **BUG-005 — `done` ≠ landed (unmerged author branch).** A delegated leaf can reach terminal `done` while
  its author's worktree branch is **never merged** to company `main` (no `merge chorus/<eid>` commit). The
  integrate/`sync_to_main` path closes the subtree on the DoD verdict alone; it never re-checks that every
  contributing branch actually merged, so a `done` deliverable can be **silently absent from `main`**.
  (Seen on `--org`: an engineer's module read `done` in the ledger yet that author had zero merge commits and
  the file never appeared on `main`.)
- **BUG-006 — Managers assign deliverable children to non-engineer roles.** `decompose` is fail-closed against
  assigning to **reviewers** (M3 §5), but there is **no equivalent guard for `pm`/`analyst`**. A manager
  repeatedly assigned a shell-required, Command-DoD child to an `analyst` (no shell / `agent_review` role) →
  the child went `rejected` and the manager **re-assigned the same task to the same analyst**, looping. The
  role-eligibility guard should extend to all non-engineer roles for Command-DoD deliverables.
- **BUG-007 — Top-of-tree goal terminalizes `blocked` on multi-tier integrate churn.** On `--org` the director's
  top integrate oscillates between subtrees that disagree on a shared module's location/ownership; bounded only
  by `max_integrate_iterations` + wall-clock, it exhausts iterations and the **goal closes `blocked`** (not
  `done`) even with most leaves `done`. The cap masks the churn rather than resolving it (cf. BUG-001 at scale).
- Engineers commit **harness-internal artifacts into company `main`** — dream's `docs/exec-plans/*.json|.md` and
  `docs/evals/*.json` (30+ files) land in the deliverable repo. No land-time `.gitignore` / artifact exclusion
  for harness paths. (Same root cause as the fabricated `git push`/PR links + scaffolded `docs/`.)
- Manager's first `decompose` often `[ERR]`s then retries OK (noisy, non-fatal).
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
- **`--org` 3-level run** (gpt-5.2): vera → moe/max → ada/bo/cy/di; decompose + integrate cascade fire at both
  tiers and `report.py` draws the org chart + tree from the ledger. **But** the goal terminalized `blocked`
  (BUG-007), one author's branch never merged so a `done` deliverable was missing from `main` (BUG-005), and a
  deliverable child was looped onto an `analyst` and twice `rejected` (BUG-006). Ledger: 22 tasks → 18 done /
  2 rejected / 2 blocked.
- **No cross-child file ownership → duplicate + orphaned modules.** Independent engineer children each create the
  same package/module from scratch (no shared-file allocation at `decompose`; no content reconciliation at
  integrate). `sync_to_main` ff-merges fragments **by branch, never by content**, so `main` can end with two
  competing implementations of one module — and the package `__init__` exporting neither. The kernel merges
  branches; it does not de-duplicate or reconcile their contents.
- **`done` is a ledger state, not a landed-artifact guarantee.** The `done` disposition keys off the DoD verdict;
  it never re-verifies the named deliverable is present on `main`. Combined with the Command-DoD bypass above, a
  subtree can read `done` while its real artifact is shallow, unmerged, or missing. An objective floor that
  re-checks "the deliverable exists on `main` and is non-empty" would close BUG-005 + the off-brief gap.
- **Command-DoD bypass reconfirmed at org scale.** Whole subtrees pass on stub/off-brief output because the
  planner LLM gates `evaluator_enabled` (see PM finding above). Reinforces: pin `evaluator_enabled=True` whenever
  a beat carries `verification_steps`.
