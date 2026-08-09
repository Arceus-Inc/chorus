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
from chorus.testing import uid


def _bridge(sink: list[Event]) -> DreamObserverBridge:
    return DreamObserverBridge(
        sink.append, task_id=uid("task-1"), clock=lambda: datetime(2026, 7, 1, tzinfo=UTC)
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


class TestMemoryRetrieved:
    """Retrieval is instrumented at the moment of use (OBS P5) — synthesized from the recall
    tool's structured result; a miss (zero hits) is signal, not silence."""

    def test_recall_result_synthesizes_memory_retrieved(self) -> None:
        sink: list[Event] = []
        _bridge(sink).on_event(
            {
                "kind": "role.tool.result",
                "tool": "recall",
                "is_error": False,
                "content_preview": "2 hits",
                "structured": {
                    "hits": [
                        {"run_id": uid("r_a"), "score": 0.9},
                        {"run_id": uid("r_b"), "score": 0.4},
                    ],
                    "mode": "keyword",
                },
            }
        )
        assert EventKind.MEMORY_RETRIEVED in _kinds(sink)
        retrieved = next(e for e in sink if e.kind is EventKind.MEMORY_RETRIEVED)
        assert retrieved.payload["tool"] == "recall"
        assert retrieved.payload["hit_run_ids"] == [uid("r_a"), uid("r_b")]
        assert retrieved.payload["empty"] is False

    def test_empty_retrieval_is_still_an_event(self) -> None:
        sink: list[Event] = []
        _bridge(sink).on_event(
            {
                "kind": "role.tool.result",
                "tool": "recall",
                "is_error": False,
                "content_preview": "no matches",
                "structured": {"hits": [], "mode": "recency"},
            }
        )
        retrieved = next(e for e in sink if e.kind is EventKind.MEMORY_RETRIEVED)
        assert retrieved.payload["empty"] is True
        assert retrieved.payload["hit_run_ids"] == []

    def test_non_memory_tools_do_not_synthesize(self) -> None:
        sink: list[Event] = []
        _bridge(sink).on_event(
            {
                "kind": "role.tool.result",
                "tool": "write_file",
                "is_error": False,
                "content_preview": "ok",
                "structured": {"hits": [{"run_id": "x"}]},
            }
        )
        assert EventKind.MEMORY_RETRIEVED not in _kinds(sink)


class TestLlmCall:
    """dream's per-role-session usage frame becomes the llm.call event (OBS §4) — model,
    tokens, cache reads, cost — instead of being dropped by the closed vocabulary."""

    def test_session_closed_maps_to_llm_call(self) -> None:
        sink: list[Event] = []
        _bridge(sink).on_event(
            {
                "kind": "role.session.closed",
                "role": "generator",
                "session_id": "s1",
                "model": "gpt-x",
                "usage": {
                    "input_tokens": 1200,
                    "output_tokens": 340,
                    "cache_read_tokens": 800,
                    "cache_write_tokens": 0,
                },
                "cost_usd": 0.0123,
            }
        )
        assert _kinds(sink) == [EventKind.LLM_CALL]
        call = sink[0]
        assert call.payload["source"] == "dream"
        assert call.payload["role"] == "generator"
        assert call.payload["model"] == "gpt-x"
        assert call.payload["input_tokens"] == 1200
        assert call.payload["output_tokens"] == 340
        assert call.payload["cache_read_tokens"] == 800
        assert call.payload["cost_usd"] == 0.0123


class TestSessionRecovery:
    def test_session_recovery_maps_to_a_closed_chorus_event(self) -> None:
        sink: list[Event] = []
        _bridge(sink).on_event(
            {
                "kind": "role.session.recovered",
                "role": "generator",
                "session_id": "fresh-session",
                "requested_session_id": "stale-session",
                "reason": "schema_mismatch",
                "action": "bypass",
                "snapshot_preserved": False,
            }
        )

        assert _kinds(sink) == [EventKind.SESSION_RECOVERED]
        assert sink[0].payload == {
            "role": "generator",
            "session_id": "fresh-session",
            "requested_session_id": "stale-session",
            "reason": "schema_mismatch",
            "action": "bypass",
            "snapshot_preserved": False,
        }
