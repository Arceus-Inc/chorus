"""The Growth Marketer (Mira) — a deep employee that owns a metric and closes the loop (spec GM).

A *deep employee* is not a process: it is a standing composition of chorus primitives — a goal, a
routine, a memory scope, and an open task subtree — wired into an experimentation loop. Each beat
still rehydrates, runs one ``run_task``, and dissolves; depth lives in the ledger, not in a running
thing. This package gathers everything that makes Mira that harness, one component per module:

- :mod:`._brief`        — Mira's standing identity (the system prompt) + her voice contract.
- :mod:`._harness`      — the :class:`~chorus.roles.RoleManifest`: every ``build_harness`` component.
- :mod:`._dod`          — the action-class-aware DoD: Command | AgentReview | HumanApproval (swipe).
- :mod:`._lander`       — lands backtest_report | campaign_brief | campaign_content | experiment_launched.
- :mod:`._routines`     — weekly funnel review · daily experiment watch · daily channel optimize.
- :mod:`._subagents`    — the five Tier-1 specialist overlays (Segment/Creative/Experiment/Channel/Monitor).
- :mod:`._integrations` — the trust-scoped WebPlugin grants per subagent (read/write/gated + secret-refs).

She is **registrable, not a kernel default** (spec GM §13 / spec 09 §1): a consumer adds her with
``org.workforce.register_role(growth_marketer_plugin())`` and wires her lander via
``growth_marketer_lander(company_root)`` — the kernel's v0 role set is untouched. The net-new
primitives she forces (``chorus.webplugins``, ``chorus.swarm``) are role-agnostic, so the rest of the
workforce inherits them.
"""

from __future__ import annotations

from chorus.roles._plugin import RolePlugin
from chorus_employee.growth_marketer._brief import (
    BACKTEST_REPORT_DOC,
    CAMPAIGN_BRIEF_DOC,
    CAMPAIGN_CONTENT_DOC,
    EXPERIMENT_LAUNCH_DOC,
    GROWTH_MARKETER_BRIEF,
)
from chorus_employee.growth_marketer._dod import (
    ActionClass,
    classify_action,
    growth_marketer_dod,
)
from chorus_employee.growth_marketer._harness import growth_marketer_manifest
from chorus_employee.growth_marketer._integrations import (
    growth_marketer_webplugins,
    subagent_grants,
)
from chorus_employee.growth_marketer._lander import (
    GROWTH_OUTCOME_KIND,
    GrowthMarketerLander,
    growth_marketer_lander,
)
from chorus_employee.growth_marketer._routines import GROWTH_MARKETER_ROUTINES
from chorus_employee.growth_marketer._subagents import GROWTH_SUBAGENTS, GrowthSubagent


def growth_marketer_plugin() -> RolePlugin:
    """The registrable Growth Marketer role — manifest + action-class DoD + outcome + routines."""
    return RolePlugin(
        name="growth_marketer",
        manifest=growth_marketer_manifest(),
        dod_generator=growth_marketer_dod,
        outcome_kind=GROWTH_OUTCOME_KIND,
        declared_routines=GROWTH_MARKETER_ROUTINES,
    )


__all__ = [
    "BACKTEST_REPORT_DOC",
    "CAMPAIGN_BRIEF_DOC",
    "CAMPAIGN_CONTENT_DOC",
    "EXPERIMENT_LAUNCH_DOC",
    "GROWTH_MARKETER_BRIEF",
    "GROWTH_MARKETER_ROUTINES",
    "GROWTH_OUTCOME_KIND",
    "GROWTH_SUBAGENTS",
    "ActionClass",
    "GrowthMarketerLander",
    "GrowthSubagent",
    "classify_action",
    "growth_marketer_dod",
    "growth_marketer_lander",
    "growth_marketer_manifest",
    "growth_marketer_plugin",
    "growth_marketer_webplugins",
    "subagent_grants",
]
