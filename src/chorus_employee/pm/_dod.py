"""The PM's Definition of Done — intent → typed :class:`~chorus.outcomes.Verifier`.

The PM's signature elevation over a thin doc-writer is its **grounding floor** (pm design doc
§01/§09/§10): *a decision that states no decision, or cites no evidence, never clears "done".* That is
the PM's "confidently wrong" defence made structural — the analog of the Marketer's Brand-Critic floor.

Like the Marketer, the floor is a deterministic **Command**, not a stochastic ``AgentReview``: a
reversible written artifact must land on an objective check the kernel's verification oracle runs in the
worktree, not on a tool-less evaluator re-reading the prose (which never reliably reaches ``done``). The
floor asserts three things about the plan doc:

1. it exists and is non-empty,
2. it states a **decision** (a ``## Decision`` — or any ``#`` heading naming a decision), and
3. it **cites at least one source** (a URL, a ``Source:`` line, or a ``[n]`` reference).

The richer §10 layers (a numeric confidence score, an immutable decision record, a claims ledger, and a
rubric reviewer) stack on top of this floor later; this is the smallest brick that makes "governed
against unfounded decisions" real today. The artifact class is ``spec``.
"""

from __future__ import annotations

from chorus.outcomes import Verifier
from chorus_employee.pm._brief import PM_PLAN_DOC

# The grounding floor, run by the kernel's verification oracle in the PM's worktree (the PM has no
# run_command of its own). A decision heading + a cited source are both required; either missing keeps
# the beat out of ``done`` and routes it back for more evidence.
_GROUNDING_FLOOR = (
    f"test -s {PM_PLAN_DOC} "
    f"&& grep -qiE '^#+[[:space:]]+.*decision' {PM_PLAN_DOC} "
    f"&& grep -qiE 'https?://|source:|\\[[0-9]+\\]' {PM_PLAN_DOC}"
)


def pm_dod(intent: str) -> Verifier:
    """The PM's DoD generator (pm design doc §09): the deterministic grounding floor for a plan."""
    del intent  # the floor is the same regardless of the specific decision asked for
    return Verifier.command(_GROUNDING_FLOOR, artifact_class="spec")


__all__ = ["pm_dod"]
