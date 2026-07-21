"""The CEO's FORMATION directive — the incantation that frames a founder objective as an org-building
task (spec 06 §2, one-mind-one-ledger).

Why this lives HERE and not in the conductor: a prompt is an EMPLOYEE concern. A raw founder objective
sent to the CEO as-is (live 2026-07-18) made the CEO build the whole product itself instead of proposing
an organization. The fix is to reframe the objective as a formation task — and that framing is part of
what it means to be *this* employee (the CEO), so it belongs in the CEO's own module alongside its brief
and DoD. The composition root (podium's conductor) only decides WHEN a run is a formation run; it asks
the CEO employee for the words.
"""

from __future__ import annotations

# The formation framing prepended to a founder objective when a run is a formation run. It reframes the
# objective as "propose the org + author the roadmap", states the worktree-judged DoD, and stops the CEO
# from building the product itself. The founder's objective is appended after the trailing header.
CEO_FORMATION_CONTRACT = (
    "This is a FORMATION directive: form the permanent organization for the objective below — "
    "do NOT build the product yourself and do NOT write code. Process guidance (not acceptance "
    "criteria): consult workforce_catalog_read for the valid professions, then submit one "
    "complete typed workforce plan via workforce_plan_propose. THEN author the company's ROADMAP: "
    "read the reality digest with governance_read (note what is already done, blocked, and the "
    "capacity by profession), follow the how-to-plan-a-roadmap skill, and propose the roadmap the "
    "workforce will build via roadmap_propose — the few outcome-shaped goals that discharge the "
    "objective, each with a measurable metric and target, sized to the workforce you just proposed.\n\n"
    "DONE means exactly this, judged from worktree artifacts alone: `workforce_plan.json` "
    "contains one proposed plan in which every hire names a catalog profession, a reporting "
    "line, and 2-3 concrete 'when I'm relevant' responsibility statements (e.g. 'owns the "
    "parser module' — leads later use these to pick assignees); the org is NOT flat — when the "
    "objective needs more than one specialist, at least one hire holds a bounded management "
    "grant (can_lead=true, max_delegation_depth >= 1, max_team_size covering itself plus its "
    "reports) and the other hires report to that lead rather than to the CEO; every budget "
    "allocation is bounded; "
    "`governance-ledger.md` records the workforce proposal line; AND you have proposed a ROADMAP — "
    "a `PROPOSED roadmap` line in `governance-ledger.md` and a proposed decision whose goals each "
    "name a measurable metric and target, sized to the proposed workforce. Tool-call ordering is NOT "
    "observable and is never an acceptance criterion. The plan and roadmap stay pending for a human "
    "decision; never claim anyone was hired. Then stop.\n\n## Objective\n"
)


def formation_directive(objective: str) -> str:
    """Wrap a founder ``objective`` in the CEO's formation framing (the org-building incantation)."""
    return CEO_FORMATION_CONTRACT + objective


__all__ = ["CEO_FORMATION_CONTRACT", "formation_directive"]
