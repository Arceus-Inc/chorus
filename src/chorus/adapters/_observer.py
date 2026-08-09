"""DreamObserverBridge — translate dream's event stream into chorus ``Event``s (spec 05 §4, spec 08 §2).

chorus passes ``event_bus.emit`` (a ``Callable[[Event], None]``); dream's ``run_task`` calls
``on_event(dict)``. This bridge sits between them so chorus *witnesses* dream's typed ``role.*``
stream instead of parsing prose. Kinds without a chorus ``run.*`` equivalent are dropped — the closed
vocabulary stays closed.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from chorus.events import Event, EventKind
from chorus.heartbeat._beat import (
    SessionRecoveryAction,
    SessionRecoveryNotice,
    SessionRecoveryReason,
)

# dream's observer emits plain dicts with a stable ``"kind"``; chorus witnesses the liveness subset
# that maps 1:1 onto its closed ``run.*`` vocabulary. Macro lifecycle kinds (planner/sprint/contract)
# have no chorus equivalent yet and are skipped rather than mislabelled.
_DREAM_TO_CHORUS_KIND: dict[str, EventKind] = {
    "task.started": EventKind.RUN_STARTED,
    "task.completed": EventKind.RUN_DONE,
    "role.text": EventKind.RUN_TEXT,
    "role.tool.start": EventKind.RUN_TOOL_USE,
    "role.tool.result": EventKind.RUN_TOOL_RESULT,
    "evaluator.completed": EventKind.RUN_EVALUATED,
}

# The dream builtin whose start/result frame an intra-beat subagent (dream.swarm). Its ``role.tool.*``
# events are ALSO surfaced as first-class SUBAGENT_* events so a consumer sees the swarm lifecycle
# without pattern-matching tool names.
_SPAWN_TOOL = "spawn_subagent"

# In-beat memory readers: their structured hits become first-class memory.retrieved events
# (OBS P5 — silent memory feeding a beat is invisible work; an empty result is signal too).
_MEMORY_TOOLS = frozenset({"recall", "lattice_context"})


def session_recovery_notice_from_dream_event(
    event: Mapping[str, object],
) -> SessionRecoveryNotice | None:
    """Decode Dream's recovery event without letting malformed observer data affect a beat."""
    if event.get("kind") != "role.session.recovered":
        return None
    role = event.get("role")
    session_id = event.get("session_id")
    requested_session_id = event.get("requested_session_id")
    reason = event.get("reason")
    action = event.get("action")
    snapshot_preserved = event.get("snapshot_preserved")
    if not (
        isinstance(role, str)
        and role
        and isinstance(session_id, str)
        and session_id
        and isinstance(requested_session_id, str)
        and requested_session_id
        and isinstance(reason, str)
        and isinstance(action, str)
        and type(snapshot_preserved) is bool
    ):
        return None
    try:
        return SessionRecoveryNotice(
            role=role,
            session_id=session_id,
            requested_session_id=requested_session_id,
            reason=SessionRecoveryReason(reason),
            action=SessionRecoveryAction(action),
            snapshot_preserved=snapshot_preserved,
        )
    except ValueError:
        return None


class DreamObserverBridge:
    """Adapt a chorus ``emit`` callable to dream's ``on_event(dict)`` observer (spec 05 §4).

    Two normalizations beyond the 1:1 kind map:

    - dream's ``role.tool.result`` carries the tool's text under ``content_preview`` (a bounded
      preview); the bridge mirrors it onto the stable ``content`` key so consumers read one
      vocabulary regardless of tool.
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
        # spawn_subagent start/result correlate FIFO: dream's result event drops the subagent name,
        # and spawns are bounded + sequential within a beat, so a queue recovers the pairing.
        self._pending_subagents: list[str] = []

    def on_event(self, event: dict[str, Any]) -> None:
        dream_kind = str(event.get("kind", ""))
        recovery_notice = session_recovery_notice_from_dream_event(event)
        if recovery_notice is not None:
            self._emit(
                Event(
                    kind=EventKind.SESSION_RECOVERED,
                    at=self._clock(),
                    task_id=self._task_id,
                    payload={
                        "role": recovery_notice.role,
                        "session_id": recovery_notice.session_id,
                        "requested_session_id": recovery_notice.requested_session_id,
                        "reason": recovery_notice.reason.value,
                        "action": recovery_notice.action.value,
                        "snapshot_preserved": recovery_notice.snapshot_preserved,
                    },
                )
            )
            return
        if dream_kind == "role.session.closed":
            self._emit_llm_call(event)
            return
        kind = _DREAM_TO_CHORUS_KIND.get(dream_kind)
        if kind is None:
            return
        payload: dict[str, Any] = {k: v for k, v in event.items() if k != "kind"}
        payload["dream_kind"] = dream_kind
        # Stable verdict/output key: dream previews tool output under ``content_preview``.
        if kind is EventKind.RUN_TOOL_RESULT and "content" not in payload:
            payload["content"] = payload.get("content_preview", "")
        self._emit(Event(kind=kind, at=self._clock(), task_id=self._task_id, payload=payload))
        self._maybe_emit_subagent(dream_kind, event)
        self._maybe_emit_memory(dream_kind, event)

    def _emit_llm_call(self, event: dict[str, Any]) -> None:
        """One role session's spend as a first-class llm.call event (OBS §4)."""
        usage = dict(event.get("usage") or {})
        self._emit(
            Event(
                kind=EventKind.LLM_CALL,
                at=self._clock(),
                task_id=self._task_id,
                payload={
                    "source": "dream",
                    "role": str(event.get("role", "")),
                    "model": str(event.get("model", "")),
                    "input_tokens": int(usage.get("input_tokens", 0)),
                    "output_tokens": int(usage.get("output_tokens", 0)),
                    "cache_read_tokens": int(usage.get("cache_read_tokens", 0)),
                    "cost_usd": float(event.get("cost_usd", 0.0)),
                },
            )
        )

    def _maybe_emit_subagent(self, dream_kind: str, event: dict[str, Any]) -> None:
        """Surface the ``spawn_subagent`` lifecycle as first-class SUBAGENT_* events."""
        if event.get("tool") != _SPAWN_TOOL:
            return
        if dream_kind == "role.tool.start":
            name = str(dict(event.get("input") or {}).get("name", "subagent"))
            self._pending_subagents.append(name)
            self._emit_subagent(
                EventKind.SUBAGENT_SPAWNED,
                {"subagent_name": name, "prompt": dict(event.get("input") or {}).get("prompt", "")},
            )
        elif dream_kind == "role.tool.result":
            name = self._pending_subagents.pop(0) if self._pending_subagents else "subagent"
            self._emit_subagent(
                EventKind.SUBAGENT_COMPLETED,
                {
                    "subagent_name": name,
                    "content": event.get("content", event.get("content_preview", "")),
                    "is_error": bool(event.get("is_error", False)),
                },
            )

    def _maybe_emit_memory(self, dream_kind: str, event: dict[str, Any]) -> None:
        """Lift a memory tool's structured result to a first-class MEMORY_RETRIEVED event."""
        if dream_kind != "role.tool.result" or event.get("tool") not in _MEMORY_TOOLS:
            return
        structured = event.get("structured")
        hits = list(structured.get("hits") or []) if isinstance(structured, dict) else []
        self._emit(
            Event(
                kind=EventKind.MEMORY_RETRIEVED,
                at=self._clock(),
                task_id=self._task_id,
                payload={
                    "tool": str(event.get("tool")),
                    "hit_run_ids": [
                        str(hit["run_id"])
                        for hit in hits
                        if isinstance(hit, dict) and "run_id" in hit
                    ],
                    "empty": not hits,
                    "is_error": bool(event.get("is_error", False)),
                },
            )
        )

    def _emit_subagent(self, kind: EventKind, payload: dict[str, Any]) -> None:
        self._emit(Event(kind=kind, at=self._clock(), task_id=self._task_id, payload=payload))


__all__ = ["DreamObserverBridge"]
