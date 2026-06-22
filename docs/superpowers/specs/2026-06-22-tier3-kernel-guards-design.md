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

### 3.3 — Integration verification at the goal root — fixes the verdict-honesty headline

Two composing layers on the integration worktree, both gating the goal-root `done`.

#### 3.3a — Objective command floor (deterministic) — fixes tooldeck

**Already exists, currently bypassed.** `_scheduler.py::_integrate_floor_verdict` runs the parent's `command` DoD against the integrator's worktree (= company main once children merge) at rollup, and parks `BLOCKED` if any step exits non-zero. It returns `None` (→ mechanical `done`) when **no `command` DoD is pinned** — which is the case for `--org --task` goals (`rollup_dod=None`). The `--org --chatroom` path already pins one (`run.py:330–350`); the single-task path does not. tooldeck's red-after-merge slipped through here.

**Fix.**
- **Gap A (wiring):** pin an objective rollup `command` DoD on the goal root in the `--org --task` path — run the stack-aware `gate_check.py` on the integrated tree, identical to the chatroom path.
- **Gap B (kernel fail-closed):** a delegated parent/goal with **deliverable-producing children but no integration evaluator at all** must not close `done` by silent mechanical rollup. When `_integrate_floor_verdict` returns `None` *and* the subtree produced deliverables *and* no rubric watchdog is configured (see 3.3b), surface it rather than accept — the integration worktree was never evaluated.

**Files.** `standup-app/run.py` (pin rollup DoD on the `--task` goal); `src/chorus/heartbeat/_scheduler.py` (fail-closed branch at the mechanical-rollup acceptance, `~:758`). `tests/heartbeat/test_integrate_floor.py`.

#### 3.3b — Watchdog: a dream-evaluator pass on the goal root (judgment) — fixes ppo_lite, dpo_tune

**Why the floor is not enough.** A command floor only answers *"does the command exit 0 on the merged tree?"* It is **blind to green-but-hollow**: a test that passes by `pytest.skip` (ppo_lite), or a suite green over the wrong package (dpo_tune). No deterministic command catches this; no per-task evaluator sees it. Only a judgment over the *assembled whole vs the brief* can — paperclip's task-watchdog ("treat every stopped leaf as a claim that must be verified against evidence; do not accept 'done' without proof").

**Spec-16-faithful framing.** The watchdog is **the goal-root task's own dream `run_task` evaluator pass**, on the integration worktree, with the **brief as its rubric**. It is read-only (dream's evaluator is read-only/no-shell — the *objective* shell verification is 3.3a). This is "one task = one verdict" for the goal root, which today closes with *no* evaluator. It is **not** a reviewer-role beat (that is the per-task double-eval spec 16 deleted) and **not** a second eval of any child.

**Mechanism (ported from `TASK-WATCHDOG.md` §"How a scan works").** When the goal subtree comes to rest:
1. **Walk the subtree**, excluding watchdog-origin tasks (so it cannot trigger on itself).
2. **Live-path check** — any included task with an active run / queued wake / open recovery → subtree is LIVE → do not fire.
3. **Stop fingerprint** = SHA-256 over the stopped leaves' `(id, status, blockers)` + the goal's rubric. Compare to the goal's `integration_review_fingerprint`; equal → already reviewed, suppress; new → proceed.
4. **Dispatch one evaluator beat** on the goal root: a dream `run_task` (read-only) over company main, rubric = the brief, prompt = "each stopped leaf's `done` is a *claim* — verify the assembled tree actually satisfies the goal: required surfaces present and exercised (no self-skipping tests), one coherent package/API (no rival duplicates), the brief met."
5. **Verdict.**
   - **accept** → record the fingerprint as reviewed → the goal closes `done` (honest).
   - **needs-changes / fail** → open an `INTEGRATION_GAP` recovery task assigned to the goal's decomposer/manager, carrying the evaluator's findings as the packet → the goal stays open → the manager re-dispatches → subtree eventually re-rests → re-evaluated (new fingerprint).
6. **Idempotency / one review at a time:** the fingerprint gate + a single live `INTEGRATION_GAP` recovery per goal prevent stacking.

**The gate.** The goal-root `done` transition (the mechanical-rollup acceptance and the integrate-cap acceptance, `_scheduler.py:758`/`774`) is extended: a goal cannot finalize `done` until (3.3a floor passes **and**) the watchdog has accepted the *current* rested fingerprint.

**Scope enforcement.** Watchdog-originated mutations are confined to the watched subtree, reusing the existing trust-boundary / capability seam (spec §4 trust). It cannot approve board-level decisions or escape the goal subtree.

**Files.**
- migration `0020_integration_review.sql` + declarative `schema/task.sql` parity: add `task.integration_review_fingerprint TEXT NULL` and `task.origin_kind TEXT NULL` (marks watchdog-origin recovery tasks, excluded from the walk).
- `src/chorus/lifecycle/_watchdog.py` (pure): subtree walk, live-path check, `stop_fingerprint(...)`. No I/O — fully unit-testable.
- `src/chorus/heartbeat/_scheduler.py`: a rollup branch that, before mechanical `done`, runs the floor (3.3a) then dispatches the goal-root evaluator beat (3.3b) and routes accept/reopen.
- `src/chorus/recovery/__init__.py`: `INTEGRATION_GAP` recovery kind + opener.
- the goal-root rubric is carried by the goal's `Verifier` (reuse `Verifier.rubric()` from spec 16); `run.py` sets it to the brief in `--org`.
- `tests/lifecycle/test_watchdog.py` (fingerprint + walk, pure), `tests/heartbeat/test_integration_watchdog.py` (accept/reopen wiring), one keyed e2e.

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
| tooldeck | `RED-AFTER-MERGE`, `DONE-MASKS-RED-SUITE`, `REGISTER-API-SPLIT` (suite goes red) | **3.3a** |
| ppo_lite | `SKIP-ILLUSION`, `MISSING-CORE`, `DONE-MASKS-INCOMPLETE` | **3.3b** |
| dpo_tune | `TEST-ILLUSION`, `DUP-PACKAGE`, `WRONG-PACKAGE-SHIPPED`, `WRONG-LOSS`, `DONE-MASKS-SPLIT-BRAIN`, `NO-OWNERSHIP` | **3.3b** |
| tooldeck | `RIVAL-VALIDATOR`, `ALL-LANDED-STILL-INCOHERENT`, `NO-OWNERSHIP` | **3.3b** |
| all four | `STRAY`, `TARGET-COMMITTED`, harness leak | **3.4** |
| all four | `README` stub | *Tier 4 — noted, out of scope* |

**Note on scope honesty.** 3.3b makes these goals close **honestly**: ppo_lite/dpo_tune flip from false-`done` to correctly-`blocked` (the watchdog reopens an `INTEGRATION_GAP`), and tooldeck blocks on the red floor. Whether the org then *fixes* the gap and reaches a real `done` is spec-15's job (cross-child coherence). This spec guarantees the verdict is truthful; it does not guarantee the org succeeds.

---

## 5. Data model

Migration `0020_integration_review.sql` (+ declarative `schema/task.sql` parity):
- `task.integration_review_fingerprint TEXT NULL` — last rested-subtree fingerprint the watchdog accepted/reviewed; gates re-evaluation.
- `task.origin_kind TEXT NULL` — `'integration_watchdog'` marks watchdog-origin recovery tasks; excluded from the subtree walk.

No new tables — the watchdog is auto-on-goal-root (not opt-in/configurable like paperclip), so it needs no config row; the goal's existing `Verifier` carries the rubric.

---

## 6. Testing strategy (TDD throughout)

- **Unit (pure):** `_classify_todo` predicate (3.2); `done⇒landed` gate with fake lander (3.1); `stop_fingerprint` + subtree walk + live-path check (3.3b); snapshot exclude-list (3.4).
- **Integration (scheduler):** rollup runs floor → red ⇒ BLOCKED (3.3a); rollup dispatches evaluator → accept ⇒ done, needs-changes ⇒ INTEGRATION_GAP recovery + goal stays open (3.3b); fail-closed when no evaluator present (3.3a Gap B).
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
3. **3.3a objective floor** — wire rollup DoD + kernel fail-closed.
4. **3.3b watchdog** — (a) migration + fingerprint/walk pure, (b) evaluator dispatch at rollup, (c) accept/reopen + INTEGRATION_GAP, (d) done-gate, (e) e2e.
5. **3.4 hygiene** — lander exclude-list + `.gitignore` seed.
6. **Re-run 1–4 + deep-probe** (§7).

Each slice: RED test → GREEN → gate (ruff + mypy --strict + pytest) → commit.

---

## 9. Non-goals / explicit deferrals

- **README generation** and **brief-surface completeness assertions** beyond what the evaluator judges — Tier 4, separate.
- **Spec-15 coherence enforcement** (AGENTS.md contract that *prevents* rival packages) — this spec makes incoherence produce an honest `blocked`; spec 15 makes it not happen.
- **Configurable/opt-in watchdogs** (paperclip's per-issue config + custom instructions) — chorus's is auto-on-goal-root, fixed mandate. Configurability is a later extension.
- **Completing the `reviewed_build` collapse into dream** (spec 16 §9 deferral) — untouched.

---

## 10. Risks

- **Watchdog false-reopen** (evaluator wrongly rejects a good goal, e.g. tinyvec): mitigated by the fingerprint loop (re-evaluates after the manager responds) + bounded recovery attempts. The rubric must be calibrated to *the brief*, not gold-plating.
- **3.2 over-eager stranding**: bounded by the `assign_task`-always-enqueues-a-wake invariant; the one flipped test documents the contract change.
- **Cost**: 3.3b adds one read-only evaluator beat per goal-rest. Bounded by the fingerprint (one eval per distinct rested state) — not per tick.
