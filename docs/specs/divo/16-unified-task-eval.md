# 16 — Unified task-level evaluation (one evaluator per task)

> Kills the **double-eval**: a single engineer / PM / analyst task is graded
> twice today — once by dream's in-beat evaluator (the third phase of
> planner → generator → evaluator) and again by a *separate* chorus **Reviewer
> beat** dispatched post-hoc for `agent_review` / `reviewed_build`. This spec
> collapses every automated DoD into dream's single evaluator turn-loop, so
> **one task = one `run_task` = one verdict**. It restores
> [05 — the dream seam](05-dream-seam.md) §5's own contract — *"chorus is a thin
> orchestrator around dream's evaluator, not a second outer verifier"* — which
> the M3 load-bearing Reviewer beat silently broke.

Siblings: [04 — Outcomes, DoD & governance](04-outcomes-and-governance.md) (the
DoD vocabulary + the failure ladder), [05 — The dream seam](05-dream-seam.md)
(the `run_task` contract + the evaluator), [06 — Roles & workforce](06-roles-and-workforce.md)
(the Reviewer manifest), [15 — Cross-child coherence](15-cross-child-coherence.md)
(the manager integrate DoD — it rides this same unified path).

---

## 1. The bug it fixes

A task with a judgment-class DoD is evaluated **twice**:

1. **dream's evaluator** runs *inside* the work beat — the third phase of
   `run_task` (planner → generator → **evaluator**,
   [`05-dream-seam.md`](05-dream-seam.md) §1). It already verifies the artifact
   and renders a sprint outcome (`pass` / `needs-changes` / `fail`).
2. **a second chorus Reviewer beat** is then dispatched *after* the work beat
   returns `passed`
   ([`chorus/heartbeat/_scheduler.py`](../../../src/chorus/heartbeat/_scheduler.py)
   `_land_passed` → `_run_review`): a brand-new `run` row, a re-materialized
   worktree, a second model invocation, a second context window — just to render
   an approve/block verdict the first evaluator was already positioned to give.

The cost is **~2× model spend + latency on every judgment-class task**, plus a
second worktree checkout and a second `rev_…` run row per deliverable.

### 1.1 Root cause (code-level)

The split is baked into one method. `Verifier.verification_steps()`
([`chorus/outcomes/_verifier.py`](../../../src/chorus/outcomes/_verifier.py))
renders **only** the `Command` kind into something dream's evaluator can run:

```python
def verification_steps(self) -> tuple[VerificationStep, ...]:
    if isinstance(self.spec, Command):
        return (VerificationStep(command=self.spec.command, ...),)
    return ()   # AgentReview / ReviewedBuild / HumanApproval → nothing
```

So `agent_review` and `reviewed_build` reach dream's evaluator as **empty
verification** — and chorus is *forced* to build a second enforcement path
(`_run_review`, `_resolve_reviewer`, `_review_runner`, `_reviewed_build_passes`,
`_review_intent`, `_worktree_file_manifest`) to gate them. Same concept (a typed
DoD), two enforcement engines.

The deeper cause is the **dream `run_task` contract**: it accepts
`verification_steps: tuple[{kind, command}]`
([`chorus/adapters/dream_beat.py`](../../../src/chorus/adapters/dream_beat.py)
`TaskHarness.run_task`) — it can carry *commands* but has **no slot for a rubric
or a reviewer persona**. So even if chorus wanted to push judgment down, the seam
couldn't carry it. The separate beat is a workaround for a missing argument.

### 1.2 The drift

[04 §1](04-outcomes-and-governance.md) and [05 §5](05-dream-seam.md) both state
the design intent verbatim: chorus **passes the DoD into `run_task`** and dream's
evaluator is the **final** acceptance gate — *"chorus is a thin orchestrator
around dream's evaluator, not a second outer verification layer."* The M3
load-bearing Reviewer beat is exactly the second outer layer those specs said
chorus would not be. This spec is a **return to the stated design**, not a new
one.

---

## 2. Decisions

1. **One evaluator per task.** Every *automated* DoD kind is enforced exactly
   once, inside dream's evaluator turn-loop. chorus resolves the typed DoD,
   passes it down, and lands the **single** verdict. The chorus-side Reviewer
   beat is **deleted**.
2. **The Reviewer becomes the evaluator's persona, not a second employee.** For
   judgment kinds chorus passes the Reviewer role manifest (brief + read-only
   toolset + the rubric) down as an **evaluator-head override**. dream's
   evaluator head — already a *distinct head from the generator, with its own
   fresh context* ([05 §2](05-dream-seam.md)) — adopts that persona and renders
   the verdict in the same loop. Independence is **dream-native head
   separation**, not a second beat.
3. **Independence ladder, not independence-by-default.** A genuinely *separate
   employee* review is reserved for the existing DoD-failure escalation
   ([04 §1](04-outcomes-and-governance.md) rung 2, *reviewer escalation*) and for
   explicit high-stakes opt-in — **never** the per-task default. Routine work
   pays for one eval, not two.
4. **`HumanApproval` stays a governance gate.** A person is, by definition, not
   an in-process eval; it remains a post-beat acceptance approval
   ([04 §5](04-outcomes-and-governance.md)), unchanged. So **3 of 4** kinds
   collapse into the evaluator; `HumanApproval` is carved out on principle.
5. **The objective floor is preserved.** `Command` and `ReviewedBuild` still run
   a **real subprocess** inside the evaluator (the oracle). A `ReviewedBuild` =
   the evaluator *discovers + runs* the project command **and** *judges* the diff
   against the rubric, both in the one loop — so `done` still means "the command
   exits 0 **and** the reviewer-persona approved." No pass ever rests on the
   author model's own word.

---

## 3. Architecture

### 3.1 chorus — the Verifier renders one evaluation directive

Generalize the kind-specific `verification_steps()` into a single
`evaluation_directive()` that renders **every** automated kind into one
structured payload the evaluator consumes:

| DoD kind | command(s) | rubric | evaluator persona | objective floor |
|---|---|---|---|---|
| `Command` | the command | — | default | command exits 0 |
| `AgentReview` | — | yes | reviewer manifest | — (verdict only) |
| `ReviewedBuild` | reviewer-discovered | yes | reviewer manifest | discovered command exits 0 |
| `HumanApproval` | — | — | — | *not an eval — governance gate (§2.4)* |

`HumanApproval` renders an **empty** directive (it is enforced by chorus's
acceptance gate, not dream).

### 3.2 dream — a DoD-aware evaluator (the one new wire)

- Extend `run_task` to accept the directive: `commands` (already, as
  `verification_steps`) **plus** an optional `rubric` and an optional
  `evaluator_head` manifest override.
- dream's evaluator head: runs the commands (unchanged), and when a rubric +
  persona is supplied, **adopts that persona/brief** and renders an approve/block
  verdict against the rubric **in the same turn-loop**, returning one `passed` +
  verdict + score.
- This is a **richer payload into the head dream already runs** — not a new
  phase, not a new engine. The evaluator was always the right home (04/05); it
  was just under-fed.

### 3.3 chorus — delete the second path

Remove from [`chorus/heartbeat/_scheduler.py`](../../../src/chorus/heartbeat/_scheduler.py):
`_run_review`, `_REVIEWER_GATED_DODS`, `_reviewer_role_and_rubric`,
`_resolve_reviewer`, the `_ReviewRunnerFor` review-runner seam,
`_reviewed_build_passes`, `_review_intent`, `_worktree_file_manifest`, and
`_run_verify_command` (the objective floor moves into dream's evaluator).
`_land_passed` then finalizes from the **single** beat verdict for all automated
kinds; only `HumanApproval` still branches to `open_task_gate`
(`ApprovalGate.ACCEPTANCE`).

### 3.4 Data flow (after)

```
beat ─► dream.run_task(intent, dod = commands + rubric + evaluator-persona)
          planner → generator (writes artifact) → EVALUATOR
                                                    ├─ run command(s)     (Command · ReviewedBuild)
                                                    └─ judge vs rubric    (AgentReview · ReviewedBuild)
          ── one verdict ──► passed?
   └─► chorus _land_passed:  done  /  DoD-failure ladder (04 §1)
        └─ HumanApproval only ─► acceptance gate (unchanged)
```

---

## 4. What this preserves (what the separate Reviewer beat bought us)

| The beat gave us | Where it lives now |
|---|---|
| read-only discipline (`read_file` + `submit_verdict`, `READ_ONLY` tier) | the evaluator-head **persona** carries the same manifest ([`reviewer/_harness.py`](../../../src/chorus_employee/reviewer/_harness.py)) |
| the rubric | the DoD spec, rendered into the directive (§3.1) |
| the objective floor (run the discovered command) | dream's evaluator runs it in-loop (§2.5) |
| a second pair of eyes | **head separation** within `run_task` (evaluator head ≠ generator head, fresh context) |
| separate-employee independence | reserved for the **escalation ladder** rung 2 + opt-in, not the default (§2.3) |
| no-verdict ⇒ recovery card | dream returns `needs-changes` / `errored`; the chorus DoD-failure + recovery ladder ([04 §1](04-outcomes-and-governance.md)) is unchanged |

The one genuine reduction is **default cross-employee independence**, traded for
half the cost. The spec's position (04/05): head separation *is* the dream-native
independence boundary; a different employee is an **escalation**, not the floor.

---

## 5. Touchpoints

**dream** (the seam owner):
- `run_task` signature — accept `rubric` + an optional `evaluator_head` manifest
  alongside `verification_steps`.
- the evaluator head — consume the rubric/persona; for `ReviewedBuild`, discover
  + run the project command as the objective floor.
- `RunTaskResult` — surface the evaluator's verdict (approve/block + reason) so
  the adapter can land it.

**chorus** (`src/`):
- [`chorus/outcomes/_verifier.py`](../../../src/chorus/outcomes/_verifier.py) —
  replace `verification_steps()` with `evaluation_directive()` covering all four
  kinds.
- [`chorus/adapters/dream_beat.py`](../../../src/chorus/adapters/dream_beat.py) —
  render the directive into `run_task` (rubric + persona, not just commands); land
  the single verdict into `BeatOutcome`.
- [`chorus/heartbeat/_beat.py`](../../../src/chorus/heartbeat/_beat.py) —
  `BeatRunner.run_task` carries the directive, not just `verification`.
- [`chorus/heartbeat/_scheduler.py`](../../../src/chorus/heartbeat/_scheduler.py) —
  delete the review path (§3.3); `_land_passed` lands from one verdict.
- [`chorus_employee/reviewer/`](../../../src/chorus_employee/reviewer/) — the
  manifest **stays**; it is now consumed as the evaluator persona, not run as a
  standalone beat.
- `chorus_employee/*/_dod.py` — **unchanged**. The four role DoD generators
  (engineer → `reviewed_build`, PM/analyst → `agent_review`, manager →
  `agent_review`) emit the same kinds; only enforcement converges.

---

## 6. Test plan (TDD)

**Unit (deterministic):**
- `evaluation_directive()` renders each of the four kinds correctly (commands +
  rubric + persona + empty for `HumanApproval`).
- dream evaluator with a rubric: `block` on a failing fixture, `pass` on a clean
  one; `reviewed_build` runs the discovered command **and** judges the diff.
- scheduler: a judgment-class task lands `done` from a **single** verdict with
  **no second `rev_…` run row**; `HumanApproval` still opens the acceptance gate;
  a block still enters the DoD-failure ladder (04 §1).

**Keyed e2e (live model):** re-run the `governance` / `analyst` feature drivers
(`standup-app/feature_tests.py`) — tasks that today spawn a Reviewer beat now
complete in **one** `run_task`. Assert exactly one `run` row per task (no `rev_`
run) **and** that the evaluator still blocks deliberately bad work.

**Gate:** `uv run ruff check .` · `uv run mypy --strict src` · `uv run pytest -q`
(chorus) + dream's gate for the seam change.

---

## 7. Out of scope (YAGNI)

- Cross-employee independent review **as the default** (reserved for the
  escalation ladder + explicit opt-in).
- Removing or changing `HumanApproval` (it is not an eval).
- Multi-reviewer / consensus / quorum evaluation.
- The *content* of the manager coherence DoD ([15](15-cross-child-coherence.md)) —
  it simply rides this same unified evaluator path.
- Re-pricing / budget changes — the budget gates ([04 §3](04-outcomes-and-governance.md))
  are untouched; they just meter one beat instead of two.

---

## 8. Success criteria

Every task that completes does so on **exactly one `run_task` / one evaluator
verdict**; no task produces a second `rev_…` run in the default path. `done` for
judgment-class work still requires an **independent** (head-separated) approve,
and `reviewed_build` still requires the discovered command to exit 0. The double
eval — and its ~2× cost/latency on every judgment-class task — is gone, and the
codebase has **one** DoD enforcement engine (dream's evaluator) instead of two.

---

## 9. Implementation status (what shipped)

**Shipped — `agent_review` collapsed (the bulk of the cost win).** A `rubric`
field threads end-to-end:

- **dream** (additive, gated green): `SprintContract.rubric`
  ([`_contract.py`](../../../../dream/src/dream/sprint/_contract.py),
  `to_dict`/`from_dict`), `build_contract_from_negotiation(rubric=…)`
  ([`_negotiation.py`](../../../../dream/src/dream/sprint/_negotiation.py)),
  `run_task(rubric=…)` → `_run_generator_phase`
  ([`_run.py`](../../../../dream/src/dream/runner/_run.py)),
  `harness.run_task(rubric=…)`, and the evaluator renders a **REVIEW RUBRIC**
  block in its contract prompt ([`_evaluator_head.py`](../../../../dream/src/dream/runner/_evaluator_head.py)).
- **chorus**: `Verifier.rubric()`
  ([`_verifier.py`](../../../src/chorus/outcomes/_verifier.py)) returns the
  `agent_review` / `reviewed_build` rubric; the scheduler passes an
  `agent_review` rubric **in-beat** (`run_beat` → `_run_beat_with_retry` →
  `BeatRunner.run_task` → `DreamBeatRunner` → dream). An `agent_review` task now
  lands `done` from the **single in-beat verdict** — no second Reviewer beat, no
  `rev_…` run row, no separate verdict artifact.
- **`_REVIEWER_GATED_DODS`** narrowed from `{AGENT_REVIEW, REVIEWED_BUILD}` to
  `{REVIEWED_BUILD}`.
- **Manager coherence preserved:** an `agent_review` block formerly reached the
  manager via the Reviewer beat (`_run_review` → `_route_block`). With the beat
  collapsed the child block now surfaces in-beat, so `run_beat`'s DoD-failure
  branch routes a **manager-parented** leaf through `_route_block` (mark
  `REJECTED`, wake the manager on `children_done`) and a standalone leaf through
  `_climb_repair_ladder` — keeping the Slice-2 integrate loop ([15](15-cross-child-coherence.md))
  intact.

**Deferred — `reviewed_build` keeps its Reviewer beat (deliberate deviation from
§2.5 / §3.3 / §5).** Its rubric is **withheld** in-beat; `reviewed_build` still
runs through `_run_review` → `_reviewed_build_passes`, which discovers the
reviewer-reported `verify_command` and runs it as the **objective command floor**.
Collapsing it fully would require dream's *read-only, no-shell* evaluator to
discover **and run** the verify command in-loop and surface `build_passed` on
`RunTaskResult` — a change to the dream evaluator/oracle seam that risks
regressing the deterministic floor (the rigor the system exists to protect). The
reviewer-path code (`_run_review`, `_resolve_reviewer`, `_reviewed_build_passes`,
`_route_block`, `_worktree_file_manifest`, …) is therefore **retained**, now
reached only for `reviewed_build`. The unifying `evaluation_directive()` method
(§2.5) was **not** introduced; an additive `rubric()` accessor alongside the
existing `verification_steps()` was used instead (lower-risk, no signature churn
on the seam). Completing the `reviewed_build` collapse + deleting the reviewer
path remains follow-up work.

**Tests.** `tests/heartbeat/test_m3_review.py` updated: the `agent_review`
approve/block/manager-escalation tests assert the in-beat verdict (done, no
`rev_` run); the Reviewer-beat machinery tests (lease, silent-reviewer,
concurrent-recover, run_forever) were **repointed to `reviewed_build`**, which
keeps the beat. The repointed tests use a POSIX `verify_command` (`true`), so
they fail on Windows for the **pre-existing** shell reason (`'true' is not
recognized`) alongside the rest of the `reviewed_build` / `test_verify_runner`
suite, and pass on CI. `uv run ruff check .` and `uv run mypy --strict src` are
green.
