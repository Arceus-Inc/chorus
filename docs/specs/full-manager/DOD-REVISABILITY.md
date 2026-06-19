# §1 DoD revisability — tighten freely, loosen only with sign-off

Status: spec (to implement on `dev/m1-dod-revisability`, branched off `main` — §5 governance now
merged). Closes the §1 "DoD revisability" deferral in
[06.5-deferred-from-spec04.md](../divo/06.5-deferred-from-spec04.md). Builds on the §5 governed-action
seam (`chorus/governance/_actions/`).

## The one-line goal

A task's Definition-of-Done is set once at intake and frozen. This makes it **revisable through a
typed, audited path**: the assignee's **manager may raise the bar (tighten) freely**, but **lowering it
(loosen) requires the same approval the artifact class demands** — a worker (or its manager acting
alone) can never quietly weaken the gate that verifies its own work (spec 04 §1).

## The rule (spec 04 §1 "Revisability")

| Edit | Who | How |
|---|---|---|
| **tighten** (add an obligation) | the assignee's manager | applied immediately + audited; next evaluator pass uses it |
| **loosen** (remove/relax/swap) | nobody unilaterally | opens a `loosen_dod` §5 gate; old DoD stays in force until a human approves |
| **no change** | — | rejected (nothing to revise) |

Invariant — **in-flight**: a revision never re-judges a beat that already ran. The DoD in force is the
one persisted when the evaluator last ran; a revision takes effect on the next disposition.

## 1. Classifying an edit — the obligation set (the crux)

Strictness is decided structurally, **fail-closed**: turn each `Verifier` into a set of obligations and
compare. `new ⊋ old` (strict superset) → **tighten**; equal → **no change**; anything else → **loosen**.

```python
def _obligations(v: Verifier) -> frozenset[tuple[str, str]]:
    kind = v.kind
    if kind is DoDKind.COMMAND:
        # shell `&&` is conjunction — *all* conjuncts must pass, so each is an obligation and adding
        # one can only make the gate stricter. Split conservatively on `&&` only.
        return frozenset(("cmd", part.strip()) for part in v.command.split("&&") if part.strip())
    if kind is DoDKind.AGENT_REVIEW:
        return frozenset({("review", v.reviewer_role)})
    if kind is DoDKind.HUMAN_APPROVAL:
        return frozenset({("human", "")})
    if kind is DoDKind.REVIEWED_BUILD:
        return frozenset({("review", v.reviewer_role), ("build", "")})
    return frozenset()  # unknown kind → empty → any change reads as loosen (fail-closed)

class RevisionDirection(StrEnum):
    TIGHTEN = "tighten"
    LOOSEN = "loosen"
    NO_CHANGE = "no_change"

def classify(old: Verifier, new: Verifier) -> RevisionDirection:
    o, n = _obligations(old), _obligations(new)
    if o == n:
        return RevisionDirection.NO_CHANGE
    if o < n:                     # strict superset of obligations
        return RevisionDirection.TIGHTEN
    return RevisionDirection.LOOSEN
```

Consequences (intended): adding an `&&` check is a clean tighten; **swapping a command's text, dropping a
check, or changing the *kind* of gate is a loosen** — the engine can't prove the new form is stricter, so
it demands sign-off. You can only ever *add* obligations without approval.

This is one pure, dependency-free function — `chorus/outcomes/_revision.py`. Easiest to TDD first.

## 2. Data model

`dod.revision` already exists (bump on every applied revision). One new column holds the **staged
proposed verifier** for a loosen awaiting approval (the old DoD stays in the in-force columns until the
gate is granted):

```sql
-- migration 0016 (rename-rebuild parity, cf. 0014/0015)
ALTER TABLE dod ADD proposed_revision TEXT   -- JSON {kind, spec, artifact_class} | NULL
```

- `Dod.proposed_revision: dict[str, object] | None = None`.
- New `ApprovalAction.LOOSEN_DOD` (enum value — no DDL; the `action` column has no CHECK).
- New `ActivityVerb.DOD_REVISED` (the audit row; activity has no CHECK).

## 3. The revise path — `chorus/lifecycle/_revise_dod.py`

```python
@dataclass(frozen=True)
class ReviseOutcome:
    direction: RevisionDirection
    applied: bool           # True = in force now (tighten); False = staged behind a gate (loosen)
    approval_id: str | None # the loosen_dod gate, when one was opened

def revise_dod(ledger, *, task_id, new_verifier, revised_by) -> ReviseOutcome:
    1. authority: revised_by must be the assignee's manager (assignee.reports_to). else RevisionAuthorityError.
    2. old = ledger.dod.verifier_for_task(task_id); classify(old, new_verifier)
    3. NO_CHANGE → raise NoRevision (nothing to do)
       TIGHTEN   → ledger.dod.apply_revision(task_id, new_verifier)  # bump revision + swap + audit DOD_REVISED
                   → ReviseOutcome(TIGHTEN, applied=True, approval_id=None)
       LOOSEN    → ledger.dod.propose_revision(task_id, new_verifier)  # stage into proposed_revision
                   → GovernanceResolver(ledger).open(action=LOOSEN_DOD, subject_kind=TASK, subject_id=task_id, …)
                   → ReviseOutcome(LOOSEN, applied=False, approval_id=gate.id)
```

**Authority.** Only the assignee's manager (`employee.reports_to` of the task's assignee) may revise —
the worker can't touch its own gate, and an unmanaged/unassigned task rejects fail-closed.

**In-flight.** `apply_revision` only mutates the `dod` row; the kernel evaluates at *disposition*, so the
next pass naturally uses the new row and an already-recorded verdict is never re-judged. Asserted by test.

## 4. The §5 `loosen_dod` governed action — `chorus/governance/_actions/_loosen_dod.py`

```python
class LoosenDodAction:                       # registered in default_actions
    action = ApprovalAction.LOOSEN_DOD
    def on_open(self, approval):  ...         # audit only — the task keeps running under the OLD DoD
    def on_approve(self, approval):           # promote the staged verifier to in-force
        ledger.dod.apply_proposed_revision(approval.subject_id)   # swap + bump revision + clear proposed + audit
        return ActionOutcome("loosened")
    def on_deny(self, approval):              # keep the stricter DoD
        ledger.dod.clear_proposed(approval.subject_id)
        return ActionOutcome("unchanged")
    def on_revise(self, approval):            # send the request back; clear the staged proposal
        ledger.dod.clear_proposed(approval.subject_id)
        return ActionOutcome("withdrawn")
```

The loosen rides the exact §5 machinery hire/plan/board use: one atomic, audited resolution that performs
the org mutation. (The spec's "same approval the artifact class demands" is the policy that decides *who*
resolves it; the default is a human via the CLI `approval` verbs.)

## 5. Facade + CLI

- `Chorus.revise_dod(task_id, verifier, *, revised_by) -> ReviseOutcome`.
- CLI: `dod revise <task_id> <kind> <spec…>` (minimal — build the `Verifier` from typed args); a loosen
  prints the opened gate id, resolved later with `approval approve|deny|revise <id>`.

## 6. Build order (TDD; e2e at each checkpoint)

1. **Classifier** — `RevisionDirection` + `_obligations` + `classify` (pure). Unit tests: add-`&&`→tighten,
   drop/swap→loosen, cross-kind→loosen, equal→no_change, reviewed_build superset. *(no deps)*
2. **Data model** — migration 0016 (`dod.proposed_revision`), `Dod.proposed_revision`, repo
   `apply_revision` / `propose_revision` / `apply_proposed_revision` / `clear_proposed`; round-trip +
   parity. `ApprovalAction.LOOSEN_DOD`, `ActivityVerb.DOD_REVISED`.
3. **revise_dod (tighten + authority + in-flight)** — apply-now path, manager-authority guard,
   no-change reject, in-flight invariant. *(e2e: manager tightens → new DoD in force, verdict not re-judged)*
4. **loosen_dod §5 action** — `LoosenDodAction` + register; revise_dod LOOSEN branch opens the gate.
   *(e2e: loosen → gate open + old DoD in force; approve → new in force; deny → unchanged + proposal cleared)*
5. **Facade + CLI + final e2e + HTML report** — `Chorus.revise_dod`, CLI verb, full scenario suite →
   `reports/m1-dod-revisability.html`; gate (ruff + mypy --strict + full pytest). Update 06.5 §1.

Each checkpoint runs the gate.

## Out of scope

DoD auto-generation at intake (gated on spec 10 §5 `submit()`), AgentReview/ladder rung-2 routing
(separate §1 items), and any change to *who* the loosen policy routes to beyond "a human via the CLI."
