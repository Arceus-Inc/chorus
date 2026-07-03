"""The Marketer's Definition of Done — intent -> typed :class:`~chorus.outcomes.Verifier`.

The Marketer's DoD is **action-class** (design doc §09): governed against spending or sending
recklessly, not against being wrong. The verifier tiers:

- A reversible draft (content, creative-set) -> **Command**: deterministic, in-process, no human.
- Anything going live (send/spend/publish) -> AgentReview + HumanApproval (a follow-up slice).

For Slice 1 the deliverable is a drafted content artifact, so "done" is a Command: the draft was
produced and is substantive. Crucially, brand fidelity is **not** gated here by a second, stochastic,
tool-less evaluator re-reviewing the draft — it is enforced *inside the beat* by the Brand-Critic
subagent (§06, §10), Mira's own adversarial self-review. Landing a reversible draft must be
deterministic; auditing "did the critic run" from a tool-less evaluator is not, and was what kept the
beat from ever reaching ``done``. The artifact class is ``content``.
"""

from __future__ import annotations

from chorus.outcomes import Verifier
from chorus_employee.marketer._brief import MARKETER_CONTENT_DOC

# Deterministic floor: the content doc exists, is non-empty, and is substantive (>= 300 words). The
# Brand-Critic (in-beat) owns brand quality; the DoD owns "a real draft landed". Run by the kernel's
# verification oracle in the worktree — not by Mira's toolset (she has no run_command).
_DOD_COMMAND = (
    f"test -s {MARKETER_CONTENT_DOC} "
    f'&& test "$(wc -w < {MARKETER_CONTENT_DOC})" -ge 300'
)


def marketer_dod(intent: str) -> Verifier:
    """The Marketer's DoD generator (design doc §09): a deterministic Command for a draft."""
    del intent  # the deliverable check is the same regardless of the specific content ask
    return Verifier.command(_DOD_COMMAND, artifact_class="content")


__all__ = ["marketer_dod"]
