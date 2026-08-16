"""Analyst mid-beat specialists — lean cut.

Craft personas (data / modeling / narrative / scout) live as skills on the main
employee. The critic stays: independent recomputation needs its own context
window and must not write the findings doc. Shared ``web_research`` arrives via
:func:`with_web_research`. Dream ``explore`` / ``verify`` cover ad-hoc isolation.
"""

from __future__ import annotations

from chorus.roles._subagent import IsolationMode, SubagentSpec

ANALYST_CRITIC = SubagentSpec(
    name="critic",
    description=(
        "Independently red-team the analysis. You work in the same directory as the data and the "
        "analysis: read the source file(s) with `read_file`, then independently recompute the key "
        "numbers from scratch with `notebook_run`. Report whether each figure matches, with exact "
        "recomputed values, and flag any discrepancy, arithmetic slip, or unsupported claim. Do not "
        "write the findings doc."
    ),
    tools=("read_file", "warehouse_query", "notebook_run", "read_offloaded"),
    # Must see the parent's files to recompute; filesystem isolation would hide the evidence.
    isolation=IsolationMode.SHARED,
)

ANALYST_SUBAGENTS: tuple[SubagentSpec, ...] = (ANALYST_CRITIC,)

__all__ = ["ANALYST_CRITIC", "ANALYST_SUBAGENTS"]
