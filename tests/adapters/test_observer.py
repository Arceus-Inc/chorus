"""DreamObserverBridge — verdict-text normalization + subagent lifecycle events (design doc §06, §10).

The bridge translates dream's ``on_event(dict)`` stream into chorus ``Event``s. Two behaviours
covered here:

- ``role.tool.result`` carries dream's ``content_preview``; the bridge exposes it under the stable
  ``content`` key so consumers read one vocabulary (the "empty verdict" bug was a key mismatch).
- ``spawn_subagent`` tool start/result are surfaced as ``SUBAGENT_SPAWNED`` / ``SUBAGENT_COMPLETED``
  events, correlating the subagent name from the start's ``input`` onto the result.
"""

from __future__ import annotations

from datetime import UTC, datetime

from chorus.adapters._observer import DreamObserverBridge
from chorus.events import Event, EventKind


def _bridge(sink: list[Event]) -> DreamObserverBridge:
    return DreamObserverBridge(
        sink.append, task_id="task-1", clock=lambda: datetime(2026, 7, 1, tzinfo=UTC)
    )


def _kinds(events: list[Event]) -> list[EventKind]:
    return [e.kind for e in events]


class TestVerdictNormalization:
    def test_tool_result_exposes_stable_content_key(self) -> None:
        sink: list[Event] = []
        _bridge(sink).on_event(
            {
                "kind": "role.tool.result",
                "tool": "write_file",
                "is_error": False,
                "content_preview": "PASS — on brand",
            }
        )
        result = next(e for e in sink if e.kind is EventKind.RUN_TOOL_RESULT)
        assert result.payload["content"] == "PASS — on brand"
        # the original key is preserved too (no data loss)
        assert result.payload["content_preview"] == "PASS — on brand"

    def test_tool_result_preserves_full_content_when_dream_supplies_it(self) -> None:
        sink: list[Event] = []
        full_content = "complete output " + ("x" * 400)
        _bridge(sink).on_event(
            {
                "kind": "role.tool.result",
                "tool": "read_file",
                "is_error": False,
                "content": full_content,
                "content_preview": full_content[:240],
            }
        )
        result = next(e for e in sink if e.kind is EventKind.RUN_TOOL_RESULT)
        assert result.payload["content"] == full_content
        assert result.payload["content_preview"] == full_content[:240]

    def test_tool_result_without_preview_has_empty_content(self) -> None:
        sink: list[Event] = []
        _bridge(sink).on_event({"kind": "role.tool.result", "tool": "read_file", "is_error": False})
        result = next(e for e in sink if e.kind is EventKind.RUN_TOOL_RESULT)
        assert result.payload["content"] == ""


class TestSubagentLifecycle:
    def test_spawn_subagent_start_emits_subagent_spawned(self) -> None:
        sink: list[Event] = []
        _bridge(sink).on_event(
            {
                "kind": "role.tool.start",
                "tool": "spawn_subagent",
                "input": {"name": "brand_critic", "prompt": "Review content_draft.md"},
            }
        )
        assert EventKind.SUBAGENT_SPAWNED in _kinds(sink)
        spawned = next(e for e in sink if e.kind is EventKind.SUBAGENT_SPAWNED)
        assert spawned.payload["subagent_name"] == "brand_critic"

    def test_spawn_subagent_result_emits_subagent_completed_with_verdict(self) -> None:
        sink: list[Event] = []
        bridge = _bridge(sink)
        bridge.on_event(
            {
                "kind": "role.tool.start",
                "tool": "spawn_subagent",
                "input": {"name": "brand_critic", "prompt": "Review"},
            }
        )
        bridge.on_event(
            {
                "kind": "role.tool.result",
                "tool": "spawn_subagent",
                "is_error": False,
                "content_preview": "FAIL: line 3 'best-in-class' is an unsubstantiated superlative",
            }
        )
        completed = next(e for e in sink if e.kind is EventKind.SUBAGENT_COMPLETED)
        assert completed.payload["subagent_name"] == "brand_critic"
        assert "FAIL" in completed.payload["content"]
        assert completed.payload["is_error"] is False

    def test_spawn_subagent_completion_preserves_full_typed_output(self) -> None:
        sink: list[Event] = []
        bridge = _bridge(sink)
        full_content = '{"cleared": false, "evidence": "' + ("x" * 400) + '"}'
        bridge.on_event(
            {
                "kind": "role.tool.start",
                "tool": "spawn_subagent",
                "input": {"name": "code_reviewer", "prompt": "Review"},
            }
        )
        bridge.on_event(
            {
                "kind": "role.tool.result",
                "tool": "spawn_subagent",
                "is_error": False,
                "content": full_content,
                "content_preview": full_content[:240],
            }
        )

        completed = next(e for e in sink if e.kind is EventKind.SUBAGENT_COMPLETED)
        assert completed.payload["content"] == full_content

    def test_non_subagent_tools_emit_no_subagent_events(self) -> None:
        sink: list[Event] = []
        bridge = _bridge(sink)
        bridge.on_event({"kind": "role.tool.start", "tool": "write_file", "input": {"path": "x"}})
        bridge.on_event(
            {
                "kind": "role.tool.result",
                "tool": "write_file",
                "is_error": False,
                "content_preview": "ok",
            }
        )
        assert EventKind.SUBAGENT_SPAWNED not in _kinds(sink)
        assert EventKind.SUBAGENT_COMPLETED not in _kinds(sink)

    def test_unmapped_dream_kind_is_dropped(self) -> None:
        sink: list[Event] = []
        _bridge(sink).on_event({"kind": "planner.started", "detail": "x"})
        assert sink == []
