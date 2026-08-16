"""IsolationMode: Chorus SubagentSpec callers + Dream projection (Dream PR #111).

``web_research`` is the filesystem-isolation earner (ephemeral worktree). Critics stay
``SHARED`` so they can read the parent's draft. The factory always projects
``dream.subagents.IsolationMode``.
"""

from __future__ import annotations

import pytest

from chorus.roles import IsolationMode, RoleBeatConfig, SubagentSpec
from chorus_employee.analyst._subagents import ANALYST_CRITIC
from chorus_employee.marketer import BRAND_CRITIC_SUBAGENT
from chorus_harness._factory import _subagent_set
from swarm.web_research_orchestrator import WEB_RESEARCH_ORCHESTRATOR

pytestmark = pytest.mark.unit


def test_web_research_declares_worktree_isolation() -> None:
    assert WEB_RESEARCH_ORCHESTRATOR.isolation is IsolationMode.WORKTREE


def test_critics_share_the_parent_worktree() -> None:
    assert ANALYST_CRITIC.isolation is IsolationMode.SHARED
    assert BRAND_CRITIC_SUBAGENT.isolation is IsolationMode.SHARED


def test_subagent_spec_defaults_to_shared() -> None:
    spec = SubagentSpec(name="leaf", description="a leaf")
    assert spec.isolation is IsolationMode.SHARED


def test_factory_projects_worktree_isolation_onto_dream() -> None:
    from dream.subagents import IsolationMode as DreamIsolation

    config = RoleBeatConfig(
        system_prompt="s",
        tools=("browser_run", "web_fetch", "spawn_subagent"),
        subagents=(WEB_RESEARCH_ORCHESTRATOR,),
    )
    projected = _subagent_set(config)
    assert projected is not None
    child = projected.get("web_research")
    assert child is not None
    assert child.isolation is DreamIsolation.WORKTREE
