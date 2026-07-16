"""Classifying a DoD edit — tighten vs loosen, fail-closed (§1 DoD revisability, spec 04 §1).

A worker that can weaken the gate verifying its own work is back to self-report. So a DoD edit is only a
**tighten** (applied immediately by a manager) when it provably *raises* the bar; anything the engine
cannot prove stricter is a **loosen** (which needs the same sign-off the artifact class demands).

Strictness is decided structurally: each :class:`Verifier` reduces to a set of *obligations*, and a
tighten is a strict superset. Shell ``&&`` is conjunction — every conjunct must pass — so each conjunct
is its own obligation and adding one can only make a command harder. A different *kind* of gate, a
dropped check, or a swapped command text is not a provable superset, so it reads as a loosen.
"""

from __future__ import annotations

from enum import StrEnum

from chorus.outcomes._verifier import (
    AgentReview,
    Command,
    HumanApproval,
    ReviewedBuild,
    Verifier,
)

# An obligation is a typed ``(kind, detail)`` pair; the set of them is the verifier's strictness.
Obligation = tuple[str, str]


class RevisionDirection(StrEnum):
    """The direction of a DoD edit (spec 04 §1)."""

    TIGHTEN = "tighten"  # strict superset of obligations — a manager may apply it immediately
    LOOSEN = "loosen"  # not provably stricter — needs the artifact class's approval
    NO_CHANGE = "no_change"  # identical obligations — nothing to revise


def _obligations(verifier: Verifier) -> frozenset[Obligation]:
    """The set of obligations a verifier imposes — its strictness as a comparable value."""
    spec = verifier.spec
    if isinstance(spec, Command):
        # `&&` is conjunction: each conjunct must pass, so each is an obligation. Split conservatively
        # on `&&` only — anything else (||, ;, pipes) stays one opaque obligation, so it can't be
        # mistaken for a superset of a finer split.
        return frozenset(("cmd", part.strip()) for part in spec.command.split("&&") if part.strip())
    if isinstance(spec, AgentReview):
        return frozenset({("review", spec.reviewer_role)})
    if isinstance(spec, HumanApproval):
        return frozenset({("human", spec.approver)})
    if isinstance(spec, ReviewedBuild):
        # a reviewed build is a review *plus* the kernel-run objective build — strictly more than review.
        obligations = {("review", spec.reviewer_role), ("build", "")}
        if spec.evidence_profile is not None:
            obligations.add(("evidence", spec.evidence_profile.value))
        return frozenset(obligations)
    return frozenset()  # unknown spec → empty → any change reads as a loosen (fail-closed)


def classify(old: Verifier, new: Verifier) -> RevisionDirection:
    """Whether replacing ``old`` with ``new`` raises (tighten), lowers (loosen), or doesn't move the bar."""
    old_obligations = _obligations(old)
    new_obligations = _obligations(new)
    if old_obligations == new_obligations:
        return RevisionDirection.NO_CHANGE
    if old_obligations < new_obligations:  # strict superset → only added obligations
        return RevisionDirection.TIGHTEN
    return RevisionDirection.LOOSEN


__all__ = ["Obligation", "RevisionDirection", "classify"]
