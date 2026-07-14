"""The Analyst employee config — a complete dream harness, every component declared.

These tests pin the Analyst as a research role that **reads broadly, runs analysis code in its own
worktree, and writes a findings doc** — and that its authority stays narrow: no ``git``, no
network/system-of-record writes. They also assert the Analyst the kernel registers by default is
exactly the one defined here (single source — no drift between the two).
"""

from __future__ import annotations

import pytest

from chorus.roles import default_roles, role_beat_config
from chorus_employee import default_employees
from chorus_employee.analyst import analyst_plugin

pytestmark = pytest.mark.unit


def test_analyst_declares_its_analysis_toolset() -> None:
    manifest = analyst_plugin().manifest
    # Capability components: read evidence, run analysis code, persist findings, keep working notes.
    assert manifest.tools == (
        "read_file",
        "write_file",
        "todo_write",
        "run_command",
        "repo_search",
        "warehouse_query",
        "web_search",
        "web_extract",
        "read_offloaded",
        "notebook_run",
        "chart_render",
        "skill",
        "memory_search",
        "memory_get",
        "working_memory_read",
        "working_memory_write",
        "working_memory_append",
        "recall",
    )
    assert (
        manifest.permission_mode.value == "acceptEdits"
    )  # writes its findings under its own posture
    assert manifest.memory_scope.value == "project"
    assert manifest.system_prompt  # a real operating brief, not a placeholder


def test_analyst_authority_stays_narrow() -> None:
    """Read the world, write only the worktree: no commit/push, no system-of-record writes."""
    manifest = analyst_plugin().manifest
    assert "git" not in manifest.tools  # the lander commits the finding, never the model
    # Engine scalars — a real investigation is multi-step and multi-sprint.
    assert manifest.working_memory is True  # an in-task scratchpad across turns
    assert manifest.max_turns >= 8  # deeper than dream's default for read→script→run→conclude
    assert manifest.max_sprints > 1  # one beat runs the investigation to a finding
    assert manifest.model is None  # uses the deployment model the composition root supplies
    assert manifest.mcp is False and manifest.plugins is False  # opt-in surfaces, off by default


def test_analyst_runs_code_in_an_unrestricted_worktree_sandbox() -> None:
    """It must run analysis commands (python, etc.); dream otherwise gates non-path commands."""
    manifest = analyst_plugin().manifest
    assert manifest.sandbox.value == "unrestricted"
    assert manifest.isolation.value == "worktree"  # confined to its own branch-isolated tree


def test_analyst_projects_to_a_beat_config_carrying_the_scalars() -> None:
    config = role_beat_config(analyst_plugin().manifest)
    assert "run_command" in config.tools
    assert "working_memory_write" in config.tools
    assert "git" not in config.tools
    assert config.permission_mode == "acceptEdits"
    assert config.working_memory is True
    assert config.max_sprints > 1
    assert config.sandbox == "unrestricted"


def test_analyst_ships_its_dod_and_outcome() -> None:
    plugin = analyst_plugin()
    assert plugin.name == "analyst"
    assert plugin.outcome_kind == "finding"
    verifier = plugin.dod_generator("analyse the churn data")
    assert verifier is not None  # a typed Verifier, not None/str
    assert verifier.artifact_class == "finding"


def test_analyst_dod_is_action_class_aware() -> None:
    """The DoD bends to the beat: predict → Command, recommend → HumanApproval, else AgentReview."""
    from chorus.outcomes import DoDKind
    from chorus_employee.analyst import ActionClass, classify_action

    dod = analyst_plugin().dod_generator

    # A prediction/model beat gets an objective, ungameable held-out scorer (Command).
    assert classify_action("train a model to predict churn") is ActionClass.PREDICT
    predict = dod("train a model to predict churn")
    assert predict.kind is DoDKind.COMMAND
    assert predict.artifact_class == "prediction"
    assert "score.py" in predict.spec.command  # the held-out scorer, not a self-reported metric

    # A recommendation a human will act on is a governance gate (HumanApproval).
    assert classify_action("recommend which plan we should pick") is ActionClass.RECOMMEND
    recommend = dod("recommend which plan we should pick")
    assert recommend.kind is DoDKind.HUMAN_APPROVAL
    assert recommend.artifact_class == "recommendation"

    # The default research beat is reviewed findings (AgentReview).
    assert classify_action("analyse the churn drivers") is ActionClass.FINDINGS
    findings = dod("analyse the churn drivers")
    assert findings.kind is DoDKind.AGENT_REVIEW
    assert findings.artifact_class == "finding"


def test_analyst_dod_classify_ignores_substring_false_matches() -> None:
    """Whole-word cues must not trip the predict gate on ordinary research/analysis prose."""
    from chorus_employee.analyst import ActionClass, classify_action

    assert classify_action("summarise last quarter's profit") is ActionClass.FINDINGS
    assert classify_action("write up the remodel budget breakdown") is ActionClass.FINDINGS
    # The bare word "model" (esp. inside hyphenated compounds) must NOT force a prediction beat —
    # a research/analysis task about models is still FINDINGS. Regression guard for the live run where
    # "large-language-model inference servers" was mis-routed to a Command DoD.
    assert (
        classify_action(
            "compare open-source large-language-model inference servers by adoption and tradeoffs"
        )
        is ActionClass.FINDINGS
    )
    assert classify_action("document our data model and its business model") is ActionClass.FINDINGS
    assert classify_action("assess the goodness of fit of last year's plan") is ActionClass.FINDINGS
    # But a genuine predictive beat still routes to PREDICT via unambiguous cues.
    assert classify_action("build a classifier to predict churn") is ActionClass.PREDICT
    assert classify_action("forecast next quarter's revenue") is ActionClass.PREDICT


def test_analyst_declares_a_tier1_subagent_swarm() -> None:
    """The Analyst owns specialist subagents it can dispatch mid-beat (data/modeling/critic/narrative/scout)."""
    manifest = analyst_plugin().manifest
    names = {sa.name for sa in manifest.subagents}
    assert {"data", "modeling", "critic", "narrative", "scout"} <= names


def test_analyst_scout_is_a_read_only_web_researcher() -> None:
    manifest = analyst_plugin().manifest
    scout = next(sa for sa in manifest.subagents if sa.name == "scout")
    assert set(scout.tools) == {"web_search", "web_extract", "read_file", "read_offloaded"}
    assert "write_file" not in scout.tools and "warehouse_query" not in scout.tools


def test_analyst_subagent_tools_are_a_subset_of_the_analyst() -> None:
    """Capability minimisation: a subagent can only ever narrow the parent's toolset, never widen it."""
    manifest = analyst_plugin().manifest
    parent_tools = set(manifest.tools)
    for sa in manifest.subagents:
        assert set(sa.tools) <= parent_tools, f"subagent {sa.name!r} widens beyond the Analyst"
    # The critic may read and recompute (read/query/notebook) but must not write the deliverable.
    critic = next(sa for sa in manifest.subagents if sa.name == "critic")
    assert "read_file" in critic.tools and "notebook_run" in critic.tools
    assert "write_file" not in critic.tools


def test_analyst_data_subagents_carry_the_analysis_tools() -> None:
    """The data/modeling specialists can pull from the warehouse and compute in the notebook."""
    manifest = analyst_plugin().manifest
    data = next(sa for sa in manifest.subagents if sa.name == "data")
    modeling = next(sa for sa in manifest.subagents if sa.name == "modeling")
    assert "warehouse_query" in data.tools and "notebook_run" in data.tools
    assert "notebook_run" in modeling.tools and "chart_render" in modeling.tools


def test_analyst_beat_config_carries_the_subagents() -> None:
    config = role_beat_config(analyst_plugin().manifest)
    assert {sa.name for sa in config.subagents} >= {"data", "critic"}


def test_analyst_declares_authored_skills() -> None:
    manifest = analyst_plugin().manifest
    # A distinguished-analyst library: the investigation spine + rigor/causal/modeling/research/
    # experiment/tradeoff/communication methods, on top of the data-mechanics playbooks.
    assert set(manifest.skills) >= {
        "analytics-diagnostic-method",
        "exploratory-data-analysis",
        "sql-investigation",
        "trend-and-correlation",
        "statistical-rigor",
        "causal-inference",
        "predictive-modeling",
        "web-research",
        "experiment-analysis",
        "metric-definition-and-benchmarks",
        "technical-tradeoff-analysis",
        "findings-communication",
    }
    assert manifest.skills_root is not None
    assert "skill" in manifest.tools  # the skill tool must be present to load skill bodies


def test_analyst_skills_root_holds_valid_skill_files() -> None:
    """Every declared skill resolves to a discoverable SKILL.md with valid frontmatter."""
    from pathlib import Path

    from dream.skills import load_skill_registry

    manifest = analyst_plugin().manifest
    registry, _shadows = load_skill_registry(project_dirs=[Path(manifest.skills_root)])
    discovered = {m.name for m in registry.list_meta()}
    assert set(manifest.skills) <= discovered


def test_default_roles_sources_the_analyst_from_its_package() -> None:
    # The kernel's default analyst IS the one defined in chorus_employee (single source).
    kernel_analyst = next(r for r in default_roles() if r.name == "analyst")
    assert kernel_analyst.manifest == analyst_plugin().manifest


def test_default_employees_includes_the_analyst_plus_the_rest() -> None:
    names = {r.name for r in default_employees()}
    assert "analyst" in names
    assert {"backend_engineer", "frontend_engineer", "pm"} <= names
    assert names.isdisjoint({"engineer", "reviewer"})
    assert "manager" not in names
