# Reviewed Build — a language-agnostic, review-gated engineer DoD

Status: **design approved, not yet implemented.** Builds on the load-bearing Reviewer
([REVIEWER.md](REVIEWER.md)). Target branch: continue on `dev/m3-reviewer` (or a follow-on).

## Problem

The engineer's Definition of Done is a hardcoded command gate:

```python
# chorus_employee/engineer/_dod.py (today)
Verifier.command("pytest -q && ruff check .", artifact_class="pr")
```

Two defects:

1. **Language-lock.** `pytest -q && ruff check .` only passes for a Python project. A Go, Rust, or Node
   deliverable can *never* satisfy it. The execution plane is supposed to be language-agnostic; this one
   string nails it to Python.
2. **No judgment.** A command gate only checks "tests green." It never asks "is this diff actually good,
   does it meet the intent, is the approach sound?" — the things a human reviewer catches.

## Decision

Replace the hardcoded command with a **reviewed build**: an agent discovers the project's real verify
command and judges the diff; the **kernel** runs that command deterministically as the objective floor.

The key insight that makes this clean: **because the kernel runs the command, the reviewer never needs
to.** The reviewer only *reads* — it reads `package.json` / `Cargo.toml` / `pyproject.toml` / `Makefile`
to **discover** the command, and reads the diff to **judge** quality. So the reviewer **stays read-only**
(no `bash`, no execution rights, no contamination of the author's worktree). Discovery is agentic;
"tests pass" is deterministic and un-rationalizable.

## The flow

```
engineer produces code in its worktree     (DoD = reviewed_build, no self-test command)
  → kernel dispatches a READ-ONLY reviewer beat at the engineer's worktree
       → reviewer reads the project + the diff, then submit_verdict(
             approve        = <quality judgment on the diff>,
             verify_command = "npm ci && npm test"    ← discovered, language-agnostic
             feedback       = "...")
  → kernel decides (model picks the command, kernel judges the result):
       • reviewer quality-blocked            → BLOCK   (no command run; quality alone fails it)
       • reviewer quality-approved → kernel RUNS verify_command in the author's worktree:
             exit 0   → DONE   (quality + objective gate both pass; EngineerLander lands the PR)
             exit ≠ 0 → BLOCK  (the captured test output becomes the feedback)
       • reviewer rendered no verdict        → recovery card  (never a silent pass — existing guard)
  → BLOCK routes through the machinery already built (REVIEWER.md):
       manager parent → child REJECTED → manager's Slice-2 integrate reacts (submit_task / assign_task)
       standalone     → bounded author self-repair (max_review_rounds) → recovery card
```

So `manager + 2 engineers + 1 reviewer` becomes a real **code-review-and-CI loop**: engineers build, the
reviewer reviews + names the test command, the kernel runs CI, and the manager handles rejections —
entirely on the Slice-2 + Reviewer machinery already in place.

## Why this shape

- **Language-lock dies** — the *agent* discovers the toolchain per project; no hardcoded string.
- **Determinism kept** — "tests pass" is the *kernel* running the discovered command and checking the
  exit code. The model only chooses *what* to run and judges *quality*; it cannot rationalize a green.
- **Reviewer stays read-only** — discovery + judgment are both reads. No execution rights, no worktree
  pollution, no new trust posture for the reviewer.
- **Composition is free** — a quality block *or* a failed kernel run becomes a `REJECTED` child the
  Slice-2 manager already reacts to.

## Low-level design

### New DoD kind: `reviewed_build`

```python
# chorus/outcomes/_verifier.py
class DoDKind(StrEnum):
    COMMAND = "command"
    AGENT_REVIEW = "agent_review"
    HUMAN_APPROVAL = "human_approval"
    REVIEWED_BUILD = "reviewed_build"          # new

@dataclass(frozen=True)
class ReviewedBuild:
    """A reviewer discovers + judges; the kernel runs the discovered command as the objective floor."""
    reviewer_role: str = "reviewer"
    rubric: str = ""
    verify_timeout_s: int = 600                 # the kernel's cap on the discovered command

DoDSpec = Command | AgentReview | HumanApproval | ReviewedBuild

# Verifier.reviewed_build(*, reviewer_role="reviewer", rubric="", artifact_class="pr") -> Verifier
# verification_steps() -> ()   # nothing runs at the engineer's own beat; the gate is review + kernel-run
```

`engineer_dod` returns `Verifier.reviewed_build(...)` instead of `Verifier.command(...)`. The hardcoded
`_GATE_COMMAND` is deleted.

### `submit_verdict` carries the command

```python
class SubmitVerdictInput(BaseModel):
    approve: bool
    feedback: str
    verify_command: str = ""    # the project's verify command (required when approving a reviewed_build)
```

`CapabilityService.record_verdict(..., verify_command: str | None = None)` stores it in the verdict dict:
`{"approve", "feedback", "reviewer", "verify_command"}`.

### Verdict status semantics (reuses PASSED / FAILED / PENDING)

| Reviewer renders | DoD status after `record_verdict` | Kernel then |
|---|---|---|
| quality-approve (+command) | `PASSED` (provisional) | runs the command; exit 0 → keep `PASSED` → done; exit ≠ 0 → overwrite `FAILED` → block |
| quality-block | `FAILED` | route block (no command run) |
| nothing (no tool call) | `PENDING` | recovery card (existing no-verdict guard — unchanged) |

For a plain `agent_review` DoD (PM / analyst), `record_verdict` keeps today's behaviour
(approve → `PASSED` → done immediately). The kernel only inserts the command-run step when the DoD kind
is `reviewed_build`.

### Kernel verify-runner

```python
# chorus/heartbeat/_scheduler.py
def _run_verify(self, worktree: Path, command: str, *, timeout_s: int) -> tuple[int, str]:
    """Run the reviewer-discovered verify command in the author's worktree. Returns (exit_code, output tail).
    A timeout or spawn failure is a non-zero exit (treated as a test failure)."""
```

`_run_review`, for a `reviewed_build` DoD where the reviewer quality-approved, calls `_run_verify` on the
author's worktree (`runner.working_dir`), then:
- exit 0 → `finalize_beat(PASSED)` + `_land_outcome(author)` (EngineerLander lands the PR) → done.
- exit ≠ 0 → overwrite the DoD verdict to `FAILED` with the output tail as feedback → `_route_block`.

The `ReviewerLander` verdict artifact records the full evidence: `verify_command`, exit code, output tail,
and the quality verdict.

## Trust / security

- The kernel runs a **model-chosen shell command** for the first time. It runs in the engineer's
  **isolated, already-unrestricted worktree** — the same trust tier the engineer itself executes at — so
  it is not new attack surface relative to the existing execution plane. It is bounded by
  `verify_timeout_s` and its output is captured (tail) as durable evidence on the verdict artifact.
- **Worktree contamination**: the verify command may write build artifacts (`node_modules`, `target/`,
  `__pycache__`). These are conventionally git-ignored, so `EngineerLander`'s `git add` snapshot won't
  commit them. (If a project doesn't ignore them, they'd land in the PR — acceptable, documented.)
- A command-deny-list / network policy for the verify-runner is **out of scope** here (a follow-up);
  today's engineer execution has the same exposure.

## Rollout

**Replace, not opt-in.** `reviewed_build` becomes the engineer default; hardcoded `pytest+ruff` is
retired entirely (keeping it for "default" engineers just preserves the language-lock). Consequences:

- Every engineer task now also spawns one reviewer beat + one kernel verify-run (more latency/cost per
  task). Acceptable: it is the price of language-agnostic CI + code review.
- The org **must have a reviewer hired** for engineer work to complete. No reviewer → recovery card
  (already handled by the Reviewer slice). Default org bootstraps / examples should hire a reviewer.
- Tests that assert the engineer's `pytest+ruff` command DoD (e.g. the DoD-at-intake e2e, CLI smoke)
  must move to asserting `reviewed_build`.

## Build order (TDD)

1. **`ReviewedBuild` verifier** — `DoDKind.REVIEWED_BUILD` + dataclass + `Verifier.reviewed_build` +
   `verification_steps() -> ()` + DoD row round-trip (`_verifier_from_dod`). (dream-free, TDD)
2. **`verify_command` plumbing** — `submit_verdict` input field + `record_verdict` stores it in the
   verdict dict. (TDD on the tool + service)
3. **Kernel verify-runner** — `_run_verify(worktree, command, timeout_s)`; deterministic tests with
   `true` / `false` / a sleep-past-timeout. (TDD)
4. **`_run_review` reviewed_build branch** — quality-approve → run command → done / block; quality-block
   → block; verdict artifact records command + exit + output. Deterministic test: fake reviewer that
   returns a passing (`true`) vs failing (`false`) command. (TDD)
5. **Engineer default → reviewed_build** — swap `engineer_dod`; update the affected intake/CLI/smoke
   tests; gate. (TDD)
6. **Keyed live e2e** — a real engineer builds a tiny project; the reviewer discovers the verify command
   (`pytest` / `npm test`), the kernel runs it → done; plus a deliberately-failing variant → block →
   (manager reacts when the child is manager-parented). HTML/console report.

## Test plan

- Unit: `ReviewedBuild` round-trip; `record_verdict` stores `verify_command`; `_run_verify` exit codes +
  timeout.
- Integration (deterministic, no model): reviewed_build approve+passing-command → done + PR artifact +
  verdict artifact with the command; approve+failing-command → block (+ output as feedback);
  quality-block → block without running; no-verdict → recovery; **manager-parented failing build →
  REJECTED → manager reacts → fix passes → goal done**.
- Keyed e2e: the live loop above.

## Out of scope / follow-ups

- Caching the discovered command per project (re-discovered each review today — cheap, but cacheable).
- A verify-runner command-deny-list / network sandbox.
- Reviewer-verifying the **manager's** integrate decision (still excluded to avoid recursion;
  tracked in REVIEWER.md).
