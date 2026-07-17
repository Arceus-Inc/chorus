"""The event taxonomy + envelope (spec 08 §1).

Every meaningful transition is published to an in-process bus and appended to a
durable ``events.jsonl`` per workforce. The bus is the one thing the inspector,
the audit trail, and (in Arceus) the realtime board consume.

chorus's ``run.*`` events come straight from **dream's** engine event stream —
chorus never parses prose to learn a tool call or a verdict (spec 08 §2). The
rest (``task.*``, ``wake.*``, ``cron.*``, ``recovery.*``, ``budget.*``,
``org.*``) are chorus's own org transitions.

The public ``Event`` is the *envelope* — a single frozen shape every transition
shares (spec 10 §1: ``events()`` yields this verbatim). The ``kind`` discriminates;
typed details live in ``payload`` plus the resolved entity refs.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class EventKind(StrEnum):
    """The closed event vocabulary (spec 08 §1 taxonomy table)."""

    # task — ledger mutations
    TASK_CREATED = "task.created"
    TASK_ASSIGNED = "task.assigned"
    TASK_STATUS = "task.status"
    TASK_DEPENDENCY_RESOLVED = "task.dependency_resolved"
    TASK_CHILDREN_DONE = "task.children_done"
    # wake — scheduler
    WAKE_ENQUEUED = "wake.enqueued"
    WAKE_COALESCED = "wake.coalesced"
    WAKE_CLAIMED = "wake.claimed"
    # run (beat) — dream event stream
    RUN_QUEUED = "run.queued"
    RUN_STARTED = "run.started"
    RUN_TEXT = "run.text"
    RUN_TOOL_USE = "run.tool_use"
    RUN_TOOL_RESULT = "run.tool_result"
    RUN_TURN = "run.turn"
    RUN_EVALUATED = "run.evaluated"
    RUN_DONE = "run.done"
    # subagents — dream's intra-beat swarm (spawn_subagent)
    SUBAGENT_SPAWNED = "run.subagent_spawned"
    SUBAGENT_COMPLETED = "run.subagent_completed"
    # memory — retrieval at the moment of use (OBS P5); learning events come with their taps
    MEMORY_RETRIEVED = "memory.retrieved"
    # model calls — one role session's spend (model, tokens, cache, cost)
    LLM_CALL = "llm.call"
    # cron — tick
    ROUTINE_FIRED = "routine.fired"
    ROUTINE_SUPPRESSED = "routine.suppressed"
    # recovery
    RECOVERY_OPENED = "recovery.opened"
    RECOVERY_ESCALATED = "recovery.escalated"
    RECOVERY_RESOLVED = "recovery.resolved"
    MONITOR_DUE = "monitor.due"
    # budget
    BUDGET_SOFT_THRESHOLD = "budget.soft_threshold"
    BUDGET_HARD_STOP = "budget.hard_stop"
    BUDGET_RESUMED = "budget.resumed"
    # org — governance
    EMPLOYEE_HIRED = "employee.hired"
    EMPLOYEE_PAUSED = "employee.paused"
    EMPLOYEE_TERMINATED = "employee.terminated"
    APPROVAL_DECIDED = "approval.decided"


@dataclass(frozen=True)
class Event:
    """One published transition.

    The envelope is uniform so a consumer binds to a single typed shape and
    switches on ``kind``. ``trace_id`` threads the causal chain
    ``tick → wake → run → … → evaluated → cost_event → activity`` (spec 08 §6).
    """

    kind: EventKind
    at: datetime
    trace_id: str | None = None
    task_id: str | None = None
    employee_id: str | None = None
    run_id: str | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)


__all__ = [
    "Event",
    "EventKind",
]
