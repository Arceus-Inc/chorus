# The load-bearing Reviewer — closing M3

Status: implemented on `dev/m3-reviewer` (branched off `main` after Slice 2 merged). Gate green —
ruff + mypy `--strict` + full pytest.

## What it is

The Reviewer was declared but **inert**: the `AGENT_REVIEW` DoD kind existed and PM/Analyst roles
generated an `agent_review` DoD, but nothing dispatched a reviewer beat, the verdict gated nothing, and
there was no `verdict` lander. This slice makes it **load-bearing**: a leaf judgment deliverable is gated
by a real reviewer beat whose verdict decides completion.

## The shape

```
worker (pm/analyst) beat passes, DoD = agent_review, task has NO children
  → kernel dispatches a READ-ONLY reviewer beat at the WORKER's worktree (review in place)
  → reviewer calls submit_verdict(approve|block, feedback)   ← Path-A capability tool
       → records the work task's DoD verdict (approve→PASSED, block→FAILED) + REVIEW_VERDICT activity
  → kernel reads the recorded verdict:
       approve → land the worker's deliverable + finalize done + ReviewerLander records a `verdict` artifact
       block   → _route_block (subsidiarity):
                   • manager parent → child becomes REJECTED (terminal); once the subtree is wholly
                     terminal the manager is woken and its Slice-2 integrate reacts (recommend=react →
                     submit_task/assign_task). The reviewer judges; the manager reacts.
                   • standalone → bounded author self-repair (max_review_rounds) then a recovery card.
       no verdict (reviewer rendered none) → BLOCKED + recovery card (never a silent pass, never a loop)
  no reviewer hired → recovery card
```

A manager's own `agent_review` DoD (a delegated subtree) is **excluded** — `_run_review` only fires on a
leaf task (`not has_children`), so the manager integrates mechanically and there is no recursion.

## Key pieces

| Layer | What |
|---|---|
| `chorus/lifecycle/_capability.py` | `CapabilityService.record_verdict` — the dream-free verdict seam (approve→PASSED/block→FAILED, self-review + non-agent_review guards) |
| `chorus_tools/_submit_verdict.py` | `submit_verdict` dream `BaseTool` (Path A) |
| `chorus_employee/reviewer/` | brief (read the worktree, call `submit_verdict`), manifest (`tools=(read_file, submit_verdict)`, **DEFAULT** permission + READ_ONLY sandbox), `ReviewerLander` (`verdict` artifact) |
| `chorus/heartbeat/_scheduler.py` | `_run_review` + `_route_block` + `_resolve_reviewer`; `_ReviewRunnerFor` seam; `max_review_rounds`; the dependency-gate exception so a parent integrates on a rejected child |
| `chorus_harness/_factory.py` | `review_runner_for` / `materialize(review_worktree_of=…)` — a read-only reviewer at the author's worktree |
| data model | `TaskStatus.REJECTED` (terminal), `ArtifactType.VERDICT`, `ActivityVerb.REVIEW_VERDICT` (no migration — these columns have no DB CHECK) |

## Tested

`tests/heartbeat/test_m3_review.py` (deterministic, no model) covers every branch:
approve→done+verdict, no-reviewer→recovery, standalone block→bounded self-repair→recovery,
no-verdict→recovery, and the headline **manager-parented block → child REJECTED → manager reacts
(submit fix) → fix approved → goal done**. Plus unit/integration tests for the verdict seam, the tool,
the factory registration + cross-worktree materialization, and the lander.

`examples/m3_reviewer_keyed.py` is the keyed live e2e.

## Live reviewer: the sandbox-tier fix

Early keyed runs showed the live reviewer beat running + inspecting the worktree but never recording a
verdict (the task fell to the safe `no_verdict` recovery). Root cause was **two sandbox bugs** in
`submit_verdict`'s tool declaration — both about dream's *sandbox* axis, not the reviewer's logic:

1. **`tier_required=1`** — dream's per-role toolset filter keeps only tools with
   `tier_required <= sandbox_tier`. The reviewer's `READ_ONLY` sandbox is tier **0**, so `submit_verdict`
   (tier 1) was **filtered out of the reviewer's toolset entirely** — the model never had the tool.
2. **`risk="mutating"`** — even once in the toolset, a `mutating` tool is **denied at execution** under a
   read-only sandbox (the model emits the call, dream refuses it).

The fix: `submit_verdict` is `risk="safe", tier_required=0`. `risk` is dream's *repo/system* axis, and
the verdict touches **only the ledger** — no files, commands, or network — exactly like dream's
`working_memory` journaling tools (also `safe`, tier 0, explicitly allowed under a read-only repo tier).
A read-only reviewer must always be able to record its verdict.

After the fix the live reviewer works end to end: `examples/m3_reviewer_keyed.py` — the PM writes a spec,
the **live** reviewer reads it, approves with real feedback, the verdict records, and the task reaches
`done` in one tick. (The kernel still fails safe to a recovery card if a reviewer ever renders no verdict.)

## Live reviewer: the worktree-manifest fix

A second live failure surfaced on a real code task: the reviewer ran, but judged a *non-empty* worktree
"empty" and blocked clean code. Root cause is the reviewer's toolset — `(read_file, submit_verdict)` —
has **no directory-listing tool**. It can read a file *by path* but cannot enumerate the worktree, so it
guessed standard filenames (`pyproject.toml`, `package.json`, `tests/…`), missed the author's actual
files (`app.py`, `test_app.py`), and concluded there was nothing there.

The fix: the kernel embeds the worktree's **file manifest** in the review intent
(`_worktree_file_manifest` in `chorus/heartbeat/_scheduler.py`) — a sorted listing of the author's files
with harness/VCS plumbing (`.git`, `.dream`, `.harness`) excluded. A code review *is* a diff review; the
kernel already holds the worktree, so it hands the reviewer the authoritative inventory rather than making
a list-less model guess.

Two follow-on review-intent tunings (both general, not demo-specific):

- **Trust the kernel's build.** The reviewer is read-only and *cannot* run the tests, so it was blocking
  correct code "because I could not verify the build." The intent now states plainly: do not block merely
  because you could not execute the tests — judge the diff by reading it; the kernel runs the
  `verify_command` and fails the build if the tests fail. Reserve `approve=false` for a nameable defect.
- **Flag/feedback consistency** (reviewer brief): the live model sometimes wrote approving prose then set
  `approve=false`. The brief now requires the `approve` flag to match the assessment.

`examples/m3_org_reviewed_live.py` (manager + 2 engineers + **live** reviewer over 3 goals) exercises the
whole suite for real: clean code approved first pass → built → `done`; buggy + stub work blocked →
`REJECTED` → manager reacts → fix approved + built → `done`. Report: `reports/m3-org-reviewed-live.html`.
