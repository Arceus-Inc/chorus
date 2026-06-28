"""The Growth Marketer (Mira) — registrable deep employee, action-class DoD, trust-scoped reach."""

from __future__ import annotations

import pytest

from chorus.outcomes import DoDKind
from chorus.roles import RoleRegistry, default_roles
from chorus.webplugins import Capability
from chorus_employee.growth_marketer import (
    ActionClass,
    classify_action,
    growth_marketer_dod,
    growth_marketer_plugin,
    growth_marketer_webplugins,
    subagent_grants,
)
from chorus_employee.growth_marketer._subagents import GROWTH_SUBAGENTS

pytestmark = pytest.mark.unit


def test_plugin_is_a_metric_owning_role_with_routines() -> None:
    plugin = growth_marketer_plugin()
    assert plugin.name == "growth_marketer"
    assert plugin.outcome_kind == "growth_outcome"
    assert plugin.manifest.system_prompt  # a real operating brief
    assert "write_file" in plugin.manifest.tools and "read_file" in plugin.manifest.tools
    keys = {r.routine_key for r in plugin.declared_routines}
    assert keys == {"growth-weekly-funnel-review", "growth-daily-experiment-watch"}


def test_registers_cleanly_alongside_the_v0_roster() -> None:
    # Adds a sixth role the kernel never knew about — no kernel change (spec 09 §1).
    reg = RoleRegistry.from_plugins([*default_roles(), growth_marketer_plugin()])
    assert "growth_marketer" in reg
    # …and the kernel default set is untouched (still exactly the v0 five).
    assert set(RoleRegistry.from_plugins(default_roles()).names()) == {
        "engineer", "reviewer", "manager", "pm", "analyst",
    }


@pytest.mark.parametrize(
    ("intent", "action", "kind"),
    [
        ("run a backtest of 6 subject-line variants", ActionClass.BACKTEST, DoDKind.COMMAND),
        ("draft a campaign brief to lift activation", ActionClass.BRIEF, DoDKind.AGENT_REVIEW),
        ("launch the live A/B test and send to 40k users", ActionClass.LAUNCH, DoDKind.HUMAN_APPROVAL),
        ("allocate ad budget to the winning set", ActionClass.LAUNCH, DoDKind.HUMAN_APPROVAL),
    ],
)
def test_dod_bends_to_the_action_class(intent: str, action: ActionClass, kind: DoDKind) -> None:
    assert classify_action(intent) is action
    assert growth_marketer_dod(intent).kind is kind


def test_dod_defaults_to_a_reviewed_brief() -> None:
    # An ambiguous intent is the reversible default — a reviewed brief, not a spend.
    verifier = growth_marketer_dod("think about positioning")
    assert verifier.kind is DoDKind.AGENT_REVIEW
    assert verifier.artifact_class == "campaign_brief"


def test_dod_generator_returns_a_typed_verifier_for_the_probe_intent() -> None:
    # The role registry validates the DoD on a probe intent — it must not raise / must be typed.
    probe = growth_marketer_dod("probe: does this role generate a typed DoD?")
    assert probe.kind is DoDKind.AGENT_REVIEW


def test_integrations_are_secret_bound_and_gated_correctly() -> None:
    reg = growth_marketer_webplugins()
    assert set(reg.names()) == {"warehouse", "analytics", "experimentation", "crm", "ads", "dam"}
    # reads are ungated; spend/send are gated and carry a cap (validated at registration).
    assert reg.get("warehouse").gated is False
    assert reg.get("ads").gated is True and reg.get("ads").spend_cap is not None
    assert reg.get("ads").capability is Capability.SPEND
    # every auth is a ref handle, never inline.
    assert all(reg.get(n).auth_ref.startswith("ref:") for n in reg.names())


def test_only_channel_holds_a_write_or_spend_grant() -> None:
    grants = subagent_grants()
    reg = growth_marketer_webplugins()
    gated_holders = {
        sub for sub, names in grants.items() if any(reg.get(n).gated for n in names)
    }
    assert gated_holders == {"channel"}


def test_subagents_cover_the_five_specialists() -> None:
    assert {s.name for s in GROWTH_SUBAGENTS} == {
        "segment", "creative", "experiment", "channel", "monitor",
    }
    # narrower-wins: every subagent grant resolves to a registered web plugin.
    reg = growth_marketer_webplugins()
    for sub in GROWTH_SUBAGENTS:
        assert all(name in reg for name in sub.webplugins)
