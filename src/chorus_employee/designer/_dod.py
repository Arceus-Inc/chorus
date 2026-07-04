"""The Designer's Definition of Done — intent -> typed :class:`~chorus.outcomes.Verifier` (designer §09).

The Designer's failure mode is mostly *mechanical* — off-token, non-system, inaccessible — so unlike the
PM, its DoD **leads with a deterministic floor** (exactly as the Marketer's does), and it holds TWO
artifacts, not one: a **``DESIGN.md``** design system (the project's own, or one the Designer authored
when the project had none) that is substantive and carries a real design-system anchor; AND a
**``design_spec.md``** that is substantive and documents the three evidence sections that make
"on-system + accessible" checkable at all — its **tokens/components**, its **states**
(empty/loading/error), and its **accessibility** notes (focus order, ARIA, contrast, touch targets).
Requiring both keeps them SEPARATE — the token system lives in ``DESIGN.md``, never folded into the
spec. A screen that looks great but omits its system, its states, or its a11y notes is not done.

Above the floor, taste and flow are a judgment call. The design doc envisions a second **AgentReview**
layer — a Reviewer judges hierarchy/affordance/flow against the intent — but that arrives with the
Design-Critic slice (it can be upgraded to :meth:`Verifier.reviewed_build` then). For this slice, quality
is enforced *inside the beat* by the Design-Critic subagent (§06, §10) and the ``design_lint`` tool;
landing a reversible spec must be **deterministic**, and auditing "did the critic run" from a tool-less
evaluator is not. The artifact class is ``design``.
"""

from __future__ import annotations

from chorus.outcomes import Verifier
from chorus_employee.designer._brief import DESIGN_SPEC_DOC, DESIGN_SYSTEM_DOC

# Deterministic floor, run by the kernel's verification oracle in the worktree (not by Dara's toolset —
# she has no run_command). TWO artifacts must land, not one:
#   (1) DESIGN.md — the design SYSTEM the spec is built to. It is either the project's own (present in
#       the worktree) or, when the project had none, one the Designer AUTHORED this beat. Either way the
#       floor requires it to exist, be substantive (>= 150 words), and carry a real design-system anchor
#       (a colour/palette/tokens/visual-theme section) — a stub is not a system. This forces the two
#       files to stay SEPARATE: the token system lives in DESIGN.md, never folded into the spec.
#   (2) design_spec.md — the surface built to that system: substantive (>= 150 words) AND carrying the
#       three evidence sections that make on-system + a11y auditable — a tokens/components section, a
#       states section (empty/loading/error), and an accessibility section (focus/aria/keyboard/contrast).
# The in-beat Design-Critic owns taste and flow; the DoD owns "a real system + a real, on-system,
# accessible spec both landed, as separate artifacts".
_DOD_COMMAND = (
    f"test -s {DESIGN_SYSTEM_DOC} "
    f'&& test "$(wc -w < {DESIGN_SYSTEM_DOC})" -ge 150 '
    f"&& grep -qiE '^#+[[:space:]]*([0-9]+[.)][[:space:]]*)?(color|colour|palette|tokens|visual|theme)' {DESIGN_SYSTEM_DOC} "
    f"&& test -s {DESIGN_SPEC_DOC} "
    f'&& test "$(wc -w < {DESIGN_SPEC_DOC})" -ge 150 '
    f"&& grep -qiE '^#+[[:space:]]*([0-9]+[.)][[:space:]]*)?(tokens|components|component|design system|system)' {DESIGN_SPEC_DOC} "
    f"&& grep -qiE '^#+[[:space:]]*([0-9]+[.)][[:space:]]*)?(states|state|empty|loading|error)' {DESIGN_SPEC_DOC} "
    f"&& grep -qiE '^#+[[:space:]]*([0-9]+[.)][[:space:]]*)?(accessibility|a11y|focus|aria|keyboard|contrast)' {DESIGN_SPEC_DOC}"
)


def designer_dod(intent: str) -> Verifier:
    """The Designer's DoD generator (designer §09): a deterministic Command floor for the design spec."""
    del intent  # the deliverable check is the same regardless of the specific surface asked for
    return Verifier.command(_DOD_COMMAND, artifact_class="design")


__all__ = ["designer_dod"]
