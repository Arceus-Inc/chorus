"""Typed dream ``RunTaskEvent`` fixtures for adapter tests."""

from __future__ import annotations

from collections.abc import Mapping

from dream.engine._cost import UsageSnapshot
from dream.runner.events import (
    ContractWritten,
    EvaluatorCompleted,
    PlannerStarted,
    RoleSessionClosed,
    RoleText,
    RoleToolResult,
    RoleToolStart,
    RunTaskEvent,
    TaskCompleted,
    TaskStarted,
)
from dream.sprint._evaluation import EvaluationOutcome

try:
    from dream.runner.events import RoleSessionRecovered
except ImportError:
    from chorus.adapters._dream_events import RoleSessionRecovered

__all__ = [
    "RoleSessionRecovered",
    "RunTaskEventFixture",
    "contract_written",
    "evaluator_completed",
    "planner_started",
    "role_session_closed",
    "role_session_recovered",
    "role_text",
    "role_tool_result",
    "role_tool_start",
    "spawn_subagent_result",
    "spawn_subagent_start",
    "task_completed",
    "task_started",
]

RunTaskEventFixture = RunTaskEvent


def role_text(*, role: str = "generator", text: str) -> RoleText:
    return RoleText(role=role, text=text)


def role_tool_start(
    *,
    role: str = "generator",
    tool: str,
    input: Mapping[str, object] | None = None,
) -> RoleToolStart:
    return RoleToolStart(role=role, tool=tool, input=dict(input or {}))


def role_tool_result(
    *,
    role: str = "generator",
    tool: str,
    content: str = "",
    is_error: bool = False,
    structured: Mapping[str, object] | None = None,
) -> RoleToolResult:
    return RoleToolResult(
        role=role,
        tool=tool,
        is_error=is_error,
        content=content,
        structured=dict(structured) if structured is not None else None,
    )


def spawn_subagent_start(
    *,
    name: str,
    prompt: str = "",
    role: str = "generator",
) -> RoleToolStart:
    return role_tool_start(
        role=role,
        tool="spawn_subagent",
        input={"name": name, "prompt": prompt},
    )


def spawn_subagent_result(
    *,
    content: str,
    is_error: bool = False,
    role: str = "generator",
) -> RoleToolResult:
    return role_tool_result(role=role, tool="spawn_subagent", content=content, is_error=is_error)


def role_session_closed(
    *,
    role: str = "generator",
    model: str = "gpt-x",
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cost_usd: float = 0.0,
) -> RoleSessionClosed:
    return RoleSessionClosed(
        role=role,
        session_id="s1",
        model=model,
        usage=UsageSnapshot(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
        ),
        cost_usd=cost_usd,
    )


def role_session_recovered(
    *,
    role: str = "generator",
    session_id: str = "fresh-session",
    requested_session_id: str = "stale-session",
    reason: str = "schema_mismatch",
    action: str = "bypass",
    snapshot_preserved: bool = False,
) -> RoleSessionRecovered:
    """Construct Dream #107's typed ``role.session.recovered`` event (or Chorus's copy)."""
    return RoleSessionRecovered(
        role=role,
        session_id=session_id,
        requested_session_id=requested_session_id,
        reason=reason,
        action=action,
        snapshot_preserved=snapshot_preserved,
    )


def task_started(*, task_id: str, intent: str = "x") -> TaskStarted:
    return TaskStarted(task_id=task_id, intent=intent)


def task_completed(*, task_id: str, sprint_count: int = 1) -> TaskCompleted:
    return TaskCompleted(task_id=task_id, sprint_count=sprint_count)


def evaluator_completed(
    *,
    sprint_number: int = 1,
    outcome: EvaluationOutcome = "pass",
    score: float = 1.0,
    notes: str = "",
) -> EvaluatorCompleted:
    return EvaluatorCompleted(
        sprint_number=sprint_number,
        outcome=outcome,
        score=score,
        notes=notes,
    )


def planner_started(*, task_id: str) -> PlannerStarted:
    return PlannerStarted(task_id=task_id)


def contract_written(*, sprint_number: int = 1, path: str = "c.json") -> ContractWritten:
    return ContractWritten(sprint_number=sprint_number, path=path)
