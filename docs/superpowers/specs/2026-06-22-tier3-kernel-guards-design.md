# Tier-3 Kernel Guards — Honest Verdicts at the Integration Boundary

**Date:** 2026-06-22
**Branch:** `org-run-v2`
**Status:** design — pending user approval → writing-plans
**Informed by:** paperclip (`doc/TASK-WATCHDOG.md`, `server/src/services/recovery/issue-graph-liveness.ts`), chorus spec 02 (lifecycle), spec 15 (cross-child coherence), spec 16 (unified task eval).

---

## 1. Purpose

The V2 `--org` re-run of hard tasks 1–4 produced **dishonest verdicts**: three goals closed `done` over broken deliverables, and one good deliverable was wrongly `blocked`. The kernel's verdict no longer tracks reality.

| run | reality | verdict | direction |
|---|---|---|---|
| tooldeck | integrated `pytest` is RED (4 failed) | `done` | over-reports |
| ppo_lite | ~30% built; the test that needs the missing core **skips itself** | `done` | over-reports |
| dpo_tune | two rival packages, brief-named one not installable, wrong loss | `done` | over-reports |
| tinyvec | builds + tests + real HNSW/persistence | `blocked` | under-reports |

**Goal:** make `done` mean *done* and `blocked` mean *stuck* — deterministically where possible, and with a single judgment pass where a command cannot decide. After this work, re-running tasks 1–4 must yield honest verdicts.

**Guiding principle:** *make the verdict honest before making the work succeed.* Honesty is deterministic and cheap; coherence/success (spec 15) is behavioural and expensive. This spec buys honesty.

**Spec-16 invariant (load-bearing):** *one task = one `run_task` = one verdict; chorus is a thin orchestrator around dream's evaluator, not a second outer verifier.* Every guard here respects it: we add **one evaluator to the integration worktree** (a surface that today has none), never a second evaluator to a worktree dream already judged.

---

## 2. The two evaluation worktrees

Spec 16 collapsed per-task evaluation into dream's single in-beat evaluator. That evaluator runs **once per task, in that task's isolated worktree, read-only**. It never sees siblings or the merged tree. The failures above all live at a surface no per-task evaluator covers — the **integration worktree** (company main, after every child's PR merges):

| | dream in-beat evaluator (exists) | integration evaluator (this spec) |
|---|---|---|
| worktree | engineer's **isolated** worktree | **company main** — the merged tree |
| teeth | read-only rubric judgment | objective command floor **+** read-only rubric judgment |
| when | during generation, per task | at **rollup**, once the subtree rests |
| scope | one task's slice | the **assembled whole** vs the brief |

"One evaluator per worktree" applied to the integration worktree is exactly what's missing. This spec gives that worktree its evaluator. It is **not** a second eval of any task — the goal-root task currently closes by *mechanical rollup* with no evaluator at all.

---

## 3. The four guards

Three deterministic guards + one judgment guard, smallest → largest.

### 3.2 — Stranded-todo liveness (deterministic) — fixes tinyvec

**Bug.** `lifecycle/_liveness.py::_classify_todo` marks a todo `STALLED` only when the *last dispatch was interrupted*. A todo with **no runs at all + no wake + no recovery** falls through to `HEALTHY "resting"` → its blocked parent sees a healthy leaf → goal hangs forever (tinyvec: max's `d1` never dispatched).

**Fix (port paperclip's `hasExplicitWaitingPath`).** A todo is healthy iff it has an explicit forward path — `live_wake | open_recovery | active_monitor` — **or** it is *resting after a clean success* (last run `SUCCEEDED`). Otherwise `STALLED`.

| todo state | before | after |
|---|---|---|
| queued wake | healthy `queued_wake` | unchanged |
| last run SUCCEEDED, no wake | healthy `resting` | unchanged |
| last run FAILED/TIMED_OUT/CANCELLED | stalled `stranded_todo` | unchanged |
| **no runs ever, no wake** | healthy `resting` ❌ | **stalled `stranded_todo`** ✅ |

**Safe because** `lifecycle/_coordination.py::assign_task` enqueues a `TASK_ASSIGNED` wake atomically with the `backlog→todo` move — every legitimately-assigned todo has a wake. A run-less, wake-less todo is genuinely abandoned; the stalled verdict feeds the existing recovery sweep → re-dispatch.

**Files.** `src/chorus/lifecycle/_liveness.py` (predicate). `tests/lifecycle/test_liveness.py` (flip `test_fresh_todo_is_resting_healthy` → stranded; add never-dispatched-blocker-leaf case).

---

### 3.1 — done⇒landed (deterministic) — fixes the done≠landed family

**Bug.** A passed engineer beat finalizes `done` even when its branch never merged (ppo_lite: 3 unmerged; tinyvec: 4/8). `EngineerLander` already records `Artifact.resource_ref["merged"]` — it is just never enforced on this branch.

**Fix (rebuilt from scratch here).** At the passed-beat landing path, gate `done` on the artifact:
- `resource_ref["merged"] is False` (integration conflict) → task does **not** go `done`; route to `BLOCKED` with a `merge_conflict` recovery so the manager re-dispatches.
- A deliverable-role task whose artifact never integrated cannot finalize `done`.

Deterministic; TDD'd with a fake lander returning `merged=False`.

**Files.** kernel finalize seam in `src/chorus/heartbeat/_scheduler.py` (read `Artifact.resource_ref` at `_land_passed`); small helper in `src/chorus/outcomes/`. `tests/heartbeat/test_done_landed.py` (new).

---

### 3.3 — Integration review at the goal root — fixes the verdict-honesty headline

**One mechanism, both teeth.** The goal root gets a `reviewed_build` DoD evaluated at the integration worktree (company main, post-merge) by **the retained `reviewed_build` reviewer beat run at integration scope**. That one beat both (a) runs the objective command floor and (b) renders a brief-rubric judgment — so it catches tooldeck (red merge) *and* ppo_lite/dpo_tune (green-but-hollow) in a single pass.

**Why this, grounded in the code (dream-probed).** Dream's evaluator is in-beat phase-2c — it grades *what a beat's generator produced in its own worktree*, not a pre-existing tree; there is no standalone `evaluate(tree, rubric)` entrypoint. And at the delegated-parent rollup (`_scheduler.py:633-654`) the integrate beat's in-beat verdict is **deliberately discarded** ("its lifecycle is its subtree's, not its own dream verdict"); only `_integrate_floor_verdict` (the command floor) gates. The code itself warns (lines 608-609) that the in-beat evaluator at integrate scope "would judge a worktree the in-beat evaluator can't yet see" — which is exactly why `reviewed_build` keeps a **separate reviewer beat** that materializes at the right worktree with an explicit file manifest (`_worktree_file_manifest`) + `(read_file, submit_verdict)` toolset + `_run_verify_command`. We reuse that beat at the integration boundary.

**Spec-16 consistency.** Spec 16 §9 **explicitly retains** the `reviewed_build` reviewer beat (`_REVIEWER_GATED_DODS = {REVIEWED_BUILD}`); only the `agent_review` double-eval was collapsed into dream's in-beat evaluator. Running the retained beat at integration scope is therefore *not* a resurrection of the deleted reviewer — it is the integration worktree's single evaluator. "One evaluator per worktree": per-engineer worktrees → dream in-beat; integration worktree → this reviewer beat.

**Two gaps to close:**
- **Gap A — wire the DoD.** Pin a `reviewed_build` DoD on the goal root in the `--org --task` path: `verify_command` = stack-aware `gate_check.py` on the integrated tree (the objective floor, already wired for chatroom at `run.py:330-350`), `rubric` = the brief (the judgment). Today `--org --task` pins `rollup_dod=None`, so neither runs — tooldeck/ppo_lite/dpo_tune slipped through here.
- **Gap B — run the reviewer beat at rollup + gate `done`.** Extend the delegated-parent rollup (`_scheduler.py:633-654` and the integrate-cap path `:774`): when the subtree is terminal and the goal carries a `reviewed_build` DoD, dispatch the reviewer beat **materialized at the integration worktree** (company main) rather than mechanically accepting. The verdict gates:
  - **approve** (floor passed + reviewer accepts) → goal closes `done` (honest).
  - **block** (floor red *or* reviewer rejects on coverage/coherence) → open an `INTEGRATION_GAP` recovery task assigned to the goal's decomposer/manager with the reviewer's findings as the packet → goal stays `BLOCKED` → manager re-dispatches → subtree re-rests → re-reviewed.
- **Fail-closed:** a delegated goal whose children produced deliverables but which carries **no** integration evaluator (no `reviewed_build`/`command` DoD) must not close `done` by silent mechanical rollup — surface it. (Defense-in-depth for non-`--org` paths; `--org` always pins the DoD via Gap A.)

**No new hire — the director is the integration reviewer.** The `reviewed_build` reviewer beat needs an invokable employee materialized read-only at the integration worktree; it does **not** need a dedicated "reviewer-role" employee. The **director already fits**: it owns the goal rollup, and its integrate beat already runs *at* the integration worktree (= company main, where `_integrate_floor_verdict` runs the command today). So at rollup the director takes the reviewer pass — `(read_file, submit_verdict)` toolset + the company-main `_worktree_file_manifest` + the brief in the prompt — reads the merged tree, sees the floor result, and renders approve/block. The verdict comes from the director-as-reviewer's *generation* (read_file → submit_verdict), not from dream's in-beat evaluator, so the worktree-visibility concern (lines 608-609) does not apply. The `--org` topology is unchanged (1 director → 2 managers → 3 eng + 1 PM each); no reviewer is hired.

**Idempotency.** Re-dispatch is bounded by the existing review-run gating (one live reviewer run per task) + the integrate-iteration cap (`max_integrate_iterations`) — no new fingerprint table needed. A single live `INTEGRATION_GAP` recovery per goal prevents stacking.

**Scope enforcement.** The reviewer beat is read-only (`(read_file, submit_verdict)`); a `block` opens recovery rather than mutating children directly. Reuses the existing trust-boundary / capability seam (spec §4 trust).

**Files.**
- `standup-app/run.py` — pin the goal-root `reviewed_build` DoD (gate_check + brief rubric) on the `--org --task` goal. No topology change (director-as-reviewer).
- `src/chorus/heartbeat/_scheduler.py` — extend the delegated-parent rollup (`:633-654`, `:774`) to dispatch the **director-as-reviewer** beat at the integration worktree (read-only toolset + file manifest + brief) and gate `done` on its verdict; fail-closed branch when no evaluator is present.
- `src/chorus/recovery/__init__.py` — `INTEGRATION_GAP` recovery kind + opener.
- `tests/heartbeat/test_integration_review.py` — floor-red→block, reviewer-reject→block+INTEGRATION_GAP, approve→done, fail-closed; plus one keyed e2e.

---

### 3.4 — Workspace hygiene (deterministic, small) — fixes the leaks/strays

**Bug.** The deliverable ships harness-internal files (`docs/evals/*`, `docs/exec-plans/*`, seed `gate_check.py`/`plan_check.py`), a committed `target/` (tinyvec, ~1241 files), stray root tests, duplicate plan docs, and a 15-byte README stub — across all four runs.

**Fix.** The engineer/PM lander's snapshot step excludes harness-internal paths and writes a seed `.gitignore` (covers `target/`, `__pycache__`, build dirs) into the company repo. README generation is **out of scope** here (it is a brief-coverage concern, Tier 4) — noted, not built.

**Files.** `src/chorus_employee/engineer/_lander.py` (snapshot exclude-list + `.gitignore` seed); `tests/` lander snapshot test. *(If this proves to belong in `chorus/workspace/` instead, move it there during implementation.)*

---

## 4. Issue-coverage matrix (every finding → its guard)

| report | finding | guard |
|---|---|---|
| tinyvec | `STRANDED-TODO`, `BLOCKED-GOOD-DELIVERABLE` | **3.2** |
| tinyvec / ppo_lite | `BUG-005` done≠landed | **3.1** |
| tooldeck | `RED-AFTER-MERGE`, `DONE-MASKS-RED-SUITE`, `REGISTER-API-SPLIT` (suite goes red) | **3.3** (floor) |
| ppo_lite | `SKIP-ILLUSION`, `MISSING-CORE`, `DONE-MASKS-INCOMPLETE` | **3.3** (reviewer judgment) |
| dpo_tune | `TEST-ILLUSION`, `DUP-PACKAGE`, `WRONG-PACKAGE-SHIPPED`, `WRONG-LOSS`, `DONE-MASKS-SPLIT-BRAIN`, `NO-OWNERSHIP` | **3.3** (reviewer judgment) |
| tooldeck | `RIVAL-VALIDATOR`, `ALL-LANDED-STILL-INCOHERENT`, `NO-OWNERSHIP` | **3.3** (reviewer judgment) |
| all four | `STRAY`, `TARGET-COMMITTED`, harness leak | **3.4** |
| all four | `README` stub | *Tier 4 — noted, out of scope* |

**Note on scope honesty.** 3.3b makes these goals close **honestly**: ppo_lite/dpo_tune flip from false-`done` to correctly-`blocked` (the watchdog reopens an `INTEGRATION_GAP`), and tooldeck blocks on the red floor. Whether the org then *fixes* the gap and reaches a real `done` is spec-15's job (cross-child coherence). This spec guarantees the verdict is truthful; it does not guarantee the org succeeds.

---

## 5. Data model

**No new migration.** The dream-probe collapsed 3.3 onto existing machinery:
- The goal-root verdict rides the existing **`reviewed_build` DoD** (`Verifier` already carries `verify_command` + `rubric`).
- Re-review idempotency reuses the existing **review-run gating** + **integrate-iteration cap** — no fingerprint column needed.
- `INTEGRATION_GAP` is a new `RecoveryKind` enum value (no schema change; `recovery_action.kind` is already free-text-typed).

**No topology change** — the **director** acts as the integration reviewer at rollup (no reviewer hired); the `--org` shape stays 1 director → 2 managers → 3 eng + 1 PM each.

---

## 6. Testing strategy (TDD throughout)

- **Unit (pure):** `_classify_todo` predicate (3.2); `done⇒landed` gate with fake lander (3.1); snapshot exclude-list (3.4).
- **Integration (scheduler):** at delegated-parent rollup the goal-root `reviewed_build` reviewer beat runs at the integration worktree — floor red ⇒ BLOCKED; reviewer rejects (coverage/coherence) ⇒ BLOCKED + `INTEGRATION_GAP` recovery, goal stays open; approve ⇒ done; fail-closed when no evaluator present (3.3).
- **e2e (keyed, mini `--org`):** one run that exercises each path end-to-end.
- **Gate:** `uv run ruff check .` + `uv run mypy --strict src` + full `uv run pytest`.

---

## 7. Validation — re-run tasks 1–4

After implementation, re-run dpo_tune, ppo_lite, tinyvec, tooldeck through `--org --task` and deep-probe each. Expected honest verdicts:

| run | expected verdict | by guard |
|---|---|---|
| tinyvec | progresses past the stranded todo; closes `done` **iff** the integration evaluator accepts | 3.2 + 3.3 |
| tooldeck | `BLOCKED` (integrated `pytest` red) — not false `done` | 3.3a |
| ppo_lite | `BLOCKED` with an `INTEGRATION_GAP` (missing core / self-skip surfaced) — not false `done` | 3.1 + 3.3b |
| dpo_tune | `BLOCKED` with an `INTEGRATION_GAP` (rival packages / wrong package) — not false `done` | 3.3b |

Success = **no run reports a verdict that contradicts its deep-probe reality.**

---

## 8. Build order (slices)

1. **3.2 stranded-todo** — smallest, pure, unblocks tinyvec.
2. **3.1 done⇒landed** — deterministic gate.
3. **3.3 integration review** — (a) pin goal-root `reviewed_build` DoD (gate_check + brief) in `--org --task`; (b) extend delegated-parent rollup to dispatch the **director-as-reviewer** beat at the integration worktree; (c) gate `done` on the verdict — approve⇒done, block⇒BLOCKED + `INTEGRATION_GAP` recovery; (d) fail-closed when no evaluator present; (e) keyed e2e.
4. **3.4 hygiene** — lander exclude-list + `.gitignore` seed.
5. **Re-run 1–4 + deep-probe** (§7).

Each slice: RED test → GREEN → gate (ruff + mypy --strict + pytest) → commit.

---

## 9. Non-goals / explicit deferrals

- **README generation** and **brief-surface completeness assertions** beyond what the evaluator judges — Tier 4, separate.
- **Spec-15 coherence enforcement** (AGENTS.md contract that *prevents* rival packages) — this spec makes incoherence produce an honest `blocked`; spec 15 makes it not happen.
- **Configurable/opt-in watchdogs** (paperclip's per-issue config + custom instructions) — chorus's is auto-on-goal-root, fixed mandate. Configurability is a later extension.
- **Completing the `reviewed_build` collapse into dream** (spec 16 §9 deferral) — untouched.

---

## 10. Risks

- **Director-as-reviewer false-block** (wrongly rejects a good goal, e.g. tinyvec): the rubric must be calibrated to *the brief*, not gold-plating; bounded by the integrate-iteration cap (past the cap the subtree is mechanically accepted, so a mis-calibrated reviewer can't loop forever). Re-review after the manager responds reuses the existing review-run gating.
- **Director reviewing its own goal** (separation of duties): acceptable — the director *delegated* the build to managers/engineers and did not write the code, so this is a manager reviewing subordinates' merged work, not self-review of own output.
- **3.2 over-eager stranding**: bounded by the `assign_task`-always-enqueues-a-wake invariant; the one flipped test documents the contract change.
- **Cost**: 3.3 adds one read-only director-reviewer beat per goal-rest. Bounded by the existing review-run gating (one live reviewer run per task) + the integrate cap — not per tick.
