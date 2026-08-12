"""DreamObserverBridge — translate dream's event stream into chorus ``Event``s (spec 05 §4, spec 08 §2).

chorus passes ``event_bus.emit`` (a ``Callable[[Event], None]``); dream's ``run_task`` calls
``on_event(RunTaskEvent)``. This bridge sits between them so chorus *witnesses* dream's typed
``role.*`` stream instead of parsing prose. Kinds without a chorus ``run.*`` equivalent are dropped
— the closed vocabulary stays closed.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime

from dream.runner.events import (
    EvaluatorCompleted,
    RoleSessionClosed,
    RoleText,
    RoleToolResult,
    RoleToolStart,
    RunTaskEvent,
    TaskCompleted,
    TaskStarted,
)

from chorus.adapters._dream_events import (
    SPAWN_SUBAGENT_TOOL,
    MemoryRetrieval,
    SpawnSubagentInput,
    tool_result_content_preview,
)
from chorus.events import Event, EventKind


class DreamObserverBridge:
    """Adapt a chorus ``emit`` callable to dream's ``RunTaskObserver`` (spec 05 §4).

    Two normalizations beyond the 1:1 kind map:

    - dream's ``RoleToolResult.content`` is mirrored onto the stable ``content`` payload key and a
      bounded ``content_preview`` for legacy consumers.
    - ``spawn_subagent`` start/result are additionally emitted as ``SUBAGENT_SPAWNED`` /
      ``SUBAGENT_COMPLETED``. dream's result event has no subagent name (only the tool), so the
      name is correlated from the start's ``input`` via a small FIFO of pending spawns.
    """

    def __init__(
        self, emit: Callable[[Event], None], *, task_id: str, clock: Callable[[], datetime]
    ) -> None:
        self._emit = emit
        self._task_id = task_id
        self._clock = clock
        self._pending_subagents: list[str] = []

    def on_event(self, event: RunTaskEvent) -> None:
        if isinstance(event, RoleSessionClosed):
            self._emit_llm_call(event)
            return
        if isinstance(event, TaskStarted):
            self._emit_run(EventKind.RUN_STARTED, _task_started_payload(event))
            return
        if isinstance(event, TaskCompleted):
            self._emit_run(
                EventKind.RUN_DONE,
                {
                    "task_id": event.task_id,
                    "sprint_count": event.sprint_count,
                    "dream_kind": "task.completed",
                },
            )
            return
        if isinstance(event, RoleText):
            self._emit_run(
                EventKind.RUN_TEXT,
                {"role": event.role, "text": event.text, "dream_kind": "role.text"},
            )
            return
        if isinstance(event, RoleToolStart):
            payload = {
                "role": event.role,
                "tool": event.tool,
                "input": dict(event.input),
                "dream_kind": "role.tool.start",
            }
            self._emit_run(EventKind.RUN_TOOL_USE, payload)
            self._maybe_emit_subagent_start(event)
            return
        if isinstance(event, RoleToolResult):
            payload = {
                "role": event.role,
                "tool": event.tool,
                "is_error": event.is_error,
                "content": event.content,
                "content_preview": tool_result_content_preview(event.content),
                "dream_kind": "role.tool.result",
            }
            if event.structured is not None:
                payload["structured"] = dict(event.structured)
            self._emit_run(EventKind.RUN_TOOL_RESULT, payload)
            self._maybe_emit_subagent_result(event)
            self._maybe_emit_memory(event)
            return
        if isinstance(event, EvaluatorCompleted):
            self._emit_run(
                EventKind.RUN_EVALUATED,
                {
                    "sprint_number": event.sprint_number,
                    "outcome": event.outcome,
                    "score": event.score,
                    "notes": event.notes,
                    "dream_kind": "evaluator.completed",
                },
            )

    def _emit_run(self, kind: EventKind, payload: Mapping[str, object]) -> None:
        self._emit(
            Event(kind=kind, at=self._clock(), task_id=self._task_id, payload=dict(payload))
        )

    def _emit_llm_call(self, event: RoleSessionClosed) -> None:
        usage = event.usage
        self._emit(
            Event(
                kind=EventKind.LLM_CALL,
                at=self._clock(),
                task_id=self._task_id,
                payload={
                    "source": "dream",
                    "role": event.role,
                    "model": event.model,
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "cache_read_tokens": usage.cache_read_tokens,
                    "cost_usd": event.cost_usd,
                },
            )
        )

    def _maybe_emit_subagent_start(self, event: RoleToolStart) -> None:
        if event.tool != SPAWN_SUBAGENT_TOOL:
            return
        spawn = SpawnSubagentInput.parse(event.input)
        self._pending_subagents.append(spawn.name)
        self._emit_subagent(
            EventKind.SUBAGENT_SPAWNED,
            {"subagent_name": spawn.name, "prompt": spawn.prompt},
        )

    def _maybe_emit_subagent_result(self, event: RoleToolResult) -> None:
        if event.tool != SPAWN_SUBAGENT_TOOL:
            return
        name = self._pending_subagents.pop(0) if self._pending_subagents else "subagent"
        self._emit_subagent(
            EventKind.SUBAGENT_COMPLETED,
            {
                "subagent_name": name,
                "content": event.content,
                "is_error": event.is_error,
            },
        )

    def _maybe_emit_memory(self, event: RoleToolResult) -> None:
        retrieval = MemoryRetrieval.from_tool_result(event)
        if retrieval is None:
            return
        self._emit(
            Event(
                kind=EventKind.MEMORY_RETRIEVED,
                at=self._clock(),
                task_id=self._task_id,
                payload={
                    "tool": retrieval.tool,
                    "hit_run_ids": [hit.run_id for hit in retrieval.hits],
                    "empty": retrieval.empty,
                    "is_error": retrieval.is_error,
                },
            )
        )

    def _emit_subagent(self, kind: EventKind, payload: Mapping[str, object]) -> None:
        self._emit(Event(kind=kind, at=self._clock(), task_id=self._task_id, payload=dict(payload)))


def _task_started_payload(event: TaskStarted) -> dict[str, object]:
    return {"task_id": event.task_id, "intent": event.intent, "dream_kind": "task.started"}


__all__ = ["DreamObserverBridge"]
