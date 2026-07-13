"""The CEO's Definition of Done — a decisive, evidence-grounded directive a reviewer can judge.

A CEO writes a directive a Reviewer verifies for executive quality — but a beat that asks the CEO to
*commit* to something irreversible (spend, hire, sign, ship to production) crosses a governance gate a
person must sign, not a quality gate. So the DoD bends to the action class inferred from the intent:

- an **advise / decide / review** beat is an :class:`~chorus.outcomes.AgentReview` — a Reviewer reads
  the committed ``directive.md`` and judges whether it makes a clear, evidence-grounded, prioritized,
  risk-aware call (the CEO's default deliverable).
- a **commit** beat (an irreversible, real-world act the directive would trigger) is a
  :class:`~chorus.outcomes.HumanApproval` — a person (the board) signs off on the commitment itself.

The lander still commits ``directive.md`` in every case — the action class chooses *how* done is
proven, not *what* is landed.
"""

from __future__ import annotations

import re
from enum import StrEnum

from chorus.outcomes import Verifier


class ActionClass(StrEnum):
    """What a CEO beat produces — the axis its DoD bends to."""

    COMMIT = "commit"  # an irreversible real-world commitment -> HumanApproval (board sign-off)
    DIRECTIVE = "directive"  # the default: a decisive, reviewed executive directive -> AgentReview


# Only UNAMBIGUOUS commitment verbs — acts the directive would actually trigger in the world, gated by
# a human. Ordinary governance/decision prose ("decide where to focus", "recommend a direction") stays
# a reviewed directive, not a human gate.
_COMMIT_CUES = (
    "spend",
    "hire",
    "fire",
    "terminate",
    "lay off",
    "acquire",
    "acquisition",
    "sign the",
    "sign a",
    "wire",
    "pay out",
    "ship to production",
    "go live",
    "raise capital",
    "fundraise",
)


def _cue_matcher(cues: tuple[str, ...]) -> re.Pattern[str]:
    """Compile cues into a whole-word matcher (optional plural ``s``) so substrings don't false-match."""
    alternation = "|".join(re.escape(cue) for cue in cues)
    return re.compile(rf"\b(?:{alternation})s?\b")


_COMMIT_RE = _cue_matcher(_COMMIT_CUES)

_DIRECTIVE_RUBRIC = (
    "You are judging a FINISHED artifact: the file `directive.md` produced by the CEO. Use `read_file` "
    "to read `directive.md` (you have read_file). PASS it when `directive.md` is present, non-empty, "
    "and it (1) states a CLEAR decision up top — one call, not a menu of options; (2) grounds that call "
    "in the company's actual state and evidence, citing the specific ids / numbers / sources it relied "
    "on; (3) names the material RISKS of the call and a guardrail or mitigation for each; and (4) gives "
    "a RANKED list of concrete next actions the org should take. You are read-only by design: you do "
    "NOT have, and do NOT need, a shell / subagents / data tools, and you must NOT require re-running "
    "anything — the committed `directive.md` IS the evidence. You also have NO web tool and CANNOT open "
    "cited URLs — that is by design; a citation you cannot personally fetch is NOT grounds to fail. "
    "Judge by SUBSTANCE, not format. Hold a CONVERGENCE bar: PASS as soon as the directive makes a "
    "clear, supported, prioritized, risk-aware call — approve work that is materially complete even if "
    "it could be marginally sharper, and do NOT withhold approval for stylistic polish or extra "
    "belt-and-suspenders evidence. FAIL only for a CONCRETE defect: `directive.md` missing; NO clear "
    "decision (it hedges or only lists options); a load-bearing claim with no basis in the state or any "
    "source; risks ignored entirely; or a self-contradiction (e.g. an impossible or future-dated "
    "claim). When you fail, name the specific fix so the next attempt can converge.\n\n"
    "CRUCIAL — how to read the tree AFTER the CEO has acted: the moment a proposal is approved or "
    "rejected it LEAVES the open-proposal list, so `governance_read` will show OPEN PROPOSALS as empty "
    "and the decided ones under RECENTLY DECIDED (an approval also becomes a new DECISION). An empty "
    "OPEN PROPOSALS list is therefore EXPECTED and CORRECT — it is proof the queue was worked, NOT "
    "evidence the actions never happened. Verify the proposal ids the directive cites against the "
    "RECENTLY DECIDED and DECISIONS sections, and NEVER fail a directive on the grounds that "
    "governance_read shows no open proposals or that a cited proposal is 'no longer present' — that is "
    "the expected post-adjudication state.\n\n"
    "GROUND TRUTH for what the CEO actually did: read `governance-ledger.md` in the worktree (use "
    "read_file). Every approval, rejection, re-prioritisation, and archive the CEO performed this beat is "
    "recorded there as an append-only line. That ledger + `directive.md` are the COMPLETE evidence — the "
    "actions ARE auditable from artifacts. Do NOT fail the directive for lack of proof that the tool "
    "calls happened; the ledger is that proof."
)


def classify_action(intent: str) -> ActionClass:
    """Infer the action class from a beat's intent — an irreversible commitment wins the human gate."""
    if _COMMIT_RE.search(intent.lower()):
        return ActionClass.COMMIT
    return ActionClass.DIRECTIVE


def ceo_dod(intent: str) -> Verifier:
    """The CEO's DoD generator (spec 04): the verifier kind for the beat's action class."""
    if classify_action(intent) is ActionClass.COMMIT:
        # An irreversible real-world commitment is a governance gate, not a quality gate.
        return Verifier.human_approval(approver="board", artifact_class="commitment")
    return Verifier.agent_review(rubric=_DIRECTIVE_RUBRIC, artifact_class="directive")


__all__ = ["ActionClass", "ceo_dod", "classify_action"]
