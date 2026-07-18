"""The PM's Definition of Done — intent → typed :class:`~chorus.outcomes.Verifier`.

The PM's signature elevation is its **grounding floor** (pm design doc §01/§09/§10): *a decision that
states no decision, or cites no evidence, never clears "done".* With the Decision OS (§10) the decision
is a recorded ledger object, mirrored to ``decision.json`` by the gated ``record_decision`` tool. The
floor verifies that record — defense-in-depth over the tool's own confidence gate — plus the presence of
the human-readable plan the lander snapshots.

Like the Marketer, the floor is a deterministic **Command**, not a stochastic ``AgentReview``: the
kernel's verification oracle runs it in the worktree (``subprocess`` with ``shell=True``). It asserts:

1. ``plan.md`` exists and is non-empty (the human-readable deliverable), and
2. ``decision.json`` exists and records a decision that **states an option**, **meets the confidence
   floor**, and **cites at least one source** — the §10 policy, re-checked out of beat.

The confidence threshold is imported from the single-source policy (:mod:`._decision`) so the DoD and
the in-tool gate can never drift. The artifact class is ``spec``.
"""

from __future__ import annotations

import sys

from chorus.outcomes import Verifier
from chorus_employee.pm._brief import PM_PLAN_DOC
from chorus_employee.pm._decision import CONFIDENCE_FLOOR

_DECISION_DOC = "decision.json"

# A Python check the oracle runs in the worktree: both artifacts are non-empty and the recorded
# decision states an option, meets the confidence floor, and cites at least one source.
_DECISION_CHECK = (
    "import json,sys; from pathlib import Path; "
    "plan=Path('" + PM_PLAN_DOC + "'); decision=Path('" + _DECISION_DOC + "'); "
    "d=json.loads(decision.read_text()) if decision.is_file() else {}; "
    "sys.exit(0 if plan.is_file() and plan.stat().st_size > 0 "
    "and decision.stat().st_size > 0 and bool(d.get('option')) "
    "and float(d.get('confidence',0)) >= " + repr(CONFIDENCE_FLOOR) + " "
    "and any(c.get('source_url') for c in d.get('claims',[])) else 1)"
)

# The interpreter that runs the oracle runs the floor — bare `python` does not exist on every
# host (macOS ships python3 only); `python_check` (._platform) makes the same choice.
_INTERPRETER = sys.executable or "python3"
_GROUNDING_FLOOR = f'"{_INTERPRETER}" -c "{_DECISION_CHECK}"'


def pm_dod(intent: str) -> Verifier:
    """The PM's DoD generator (pm design doc §09): the deterministic grounding floor for a decision."""
    del intent  # the floor is the same regardless of the specific decision asked for
    return Verifier.command(_GROUNDING_FLOOR, artifact_class="spec")


__all__ = ["pm_dod"]
