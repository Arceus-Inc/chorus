"""DreamObserverBridge — verdict-text normalization + subagent lifecycle events (design doc §06, §10).

The bridge translates dream's typed ``RunTaskEvent`` stream into chorus ``Event``s. Two behaviours
covered here:

- ``RoleToolResult.content`` is exposed under the stable ``content`` key; a bounded
  ``content_preview`` mirrors it for legacy consumers.
- ``spawn_subagent`` start/result are surfaced as ``SUBAGENT_SPAWNED`` / ``SUBAGENT_COMPLETED``
  events, correlating the subagent name from the start's ``input`` onto the result.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from tests.adapters._dream_events import (
    planner_started,
    role_session_closed,
    role_session_recovered,
    role_tool_result,
    role_tool_start,
    spawn_subagent_result,
    spawn_subagent_start,
)

from chorus.adapters._dream_events import session_recovery_notice_from_dream_event
from chorus.adapters._observer import DreamObserverBridge
from chorus.events import Event, EventKind
from chorus.heartbeat import SessionRecoveryAction, SessionRecoveryNotice, SessionRecoveryReason
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
            role_tool_result(tool="write_file", content="PASS — on brand")
        )
        result = next(e for e in sink if e.kind is EventKind.RUN_TOOL_RESULT)
        assert result.payload["content"] == "PASS — on brand"
        assert result.payload["content_preview"] == "PASS — on brand"

    def test_tool_result_preserves_full_content_when_dream_supplies_it(self) -> None:
        sink: list[Event] = []
        full_content = "complete output " + ("x" * 400)
        _bridge(sink).on_event(
            role_tool_result(tool="read_file", content=full_content)
        )
        result = next(e for e in sink if e.kind is EventKind.RUN_TOOL_RESULT)
        assert result.payload["content"] == full_content
        assert result.payload["content_preview"] == full_content[:240]

    def test_tool_result_without_content_has_empty_content(self) -> None:
        sink: list[Event] = []
        _bridge(sink).on_event(role_tool_result(tool="read_file"))
        result = next(e for e in sink if e.kind is EventKind.RUN_TOOL_RESULT)
        assert result.payload["content"] == ""


class TestSubagentLifecycle:
    def test_spawn_subagent_start_emits_subagent_spawned(self) -> None:
        sink: list[Event] = []
        _bridge(sink).on_event(
            spawn_subagent_start(name="brand_critic", prompt="Review content_draft.md")
        )
        assert EventKind.SUBAGENT_SPAWNED in _kinds(sink)
        spawned = next(e for e in sink if e.kind is EventKind.SUBAGENT_SPAWNED)
        assert spawned.payload["subagent_name"] == "brand_critic"

    def test_spawn_subagent_result_emits_subagent_completed_with_verdict(self) -> None:
        sink: list[Event] = []
        bridge = _bridge(sink)
        bridge.on_event(spawn_subagent_start(name="brand_critic", prompt="Review"))
        bridge.on_event(
            spawn_subagent_result(
                content="FAIL: line 3 'best-in-class' is an unsubstantiated superlative"
            )
        )
        completed = next(e for e in sink if e.kind is EventKind.SUBAGENT_COMPLETED)
        assert completed.payload["subagent_name"] == "brand_critic"
        assert "FAIL" in completed.payload["content"]
        assert completed.payload["is_error"] is False

    def test_spawn_subagent_completion_preserves_full_typed_output(self) -> None:
        sink: list[Event] = []
        bridge = _bridge(sink)
        full_content = '{"cleared": false, "evidence": "' + ("x" * 400) + '"}'
        bridge.on_event(spawn_subagent_start(name="code_reviewer", prompt="Review"))
        bridge.on_event(spawn_subagent_result(content=full_content))

        completed = next(e for e in sink if e.kind is EventKind.SUBAGENT_COMPLETED)
        assert completed.payload["content"] == full_content

    def test_non_subagent_tools_emit_no_subagent_events(self) -> None:
        sink: list[Event] = []
        bridge = _bridge(sink)
        bridge.on_event(role_tool_start(tool="write_file", input={"path": "x"}))
        bridge.on_event(role_tool_result(tool="write_file", content="ok"))
        assert EventKind.SUBAGENT_SPAWNED not in _kinds(sink)
        assert EventKind.SUBAGENT_COMPLETED not in _kinds(sink)

    def test_unmapped_dream_kind_is_dropped(self) -> None:
        sink: list[Event] = []
        _bridge(sink).on_event(planner_started(task_id=uid("t1")))
        assert sink == []


class TestMemoryRetrieved:
    """Retrieval is instrumented at the moment of use (OBS P5) — synthesized from the recall
    tool's structured result; a miss (zero hits) is signal, not silence."""

    def test_recall_result_synthesizes_memory_retrieved(self) -> None:
        sink: list[Event] = []
        _bridge(sink).on_event(
            role_tool_result(
                tool="recall",
                content="2 hits",
                structured={
                    "hits": [
                        {"run_id": uid("r_a"), "score": 0.9},
                        {"run_id": uid("r_b"), "score": 0.4},
                    ],
                    "mode": "keyword",
                },
            )
        )
        assert EventKind.MEMORY_RETRIEVED in _kinds(sink)
        retrieved = next(e for e in sink if e.kind is EventKind.MEMORY_RETRIEVED)
        assert retrieved.payload["tool"] == "recall"
        assert retrieved.payload["hit_run_ids"] == [uid("r_a"), uid("r_b")]
        assert retrieved.payload["empty"] is False

    def test_empty_retrieval_is_still_an_event(self) -> None:
        sink: list[Event] = []
        _bridge(sink).on_event(
            role_tool_result(
                tool="recall",
                content="no matches",
                structured={"hits": [], "mode": "recency"},
            )
        )
        retrieved = next(e for e in sink if e.kind is EventKind.MEMORY_RETRIEVED)
        assert retrieved.payload["empty"] is True
        assert retrieved.payload["hit_run_ids"] == []

    def test_non_memory_tools_do_not_synthesize(self) -> None:
        sink: list[Event] = []
        _bridge(sink).on_event(
            role_tool_result(
                tool="write_file",
                content="ok",
                structured={"hits": [{"run_id": "x"}]},
            )
        )
        assert EventKind.MEMORY_RETRIEVED not in _kinds(sink)


class TestLlmCall:
    """dream's per-role-session usage frame becomes the llm.call event (OBS §4) — model,
    tokens, cache reads, cost — instead of being dropped by the closed vocabulary."""

    def test_session_closed_maps_to_llm_call(self) -> None:
        sink: list[Event] = []
        _bridge(sink).on_event(
            role_session_closed(
                role="generator",
                model="gpt-x",
                input_tokens=1200,
                output_tokens=340,
                cache_read_tokens=800,
                cost_usd=0.0123,
            )
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
    @pytest.mark.parametrize(
        ("action", "expected"),
        (
            ("reset", SessionRecoveryAction.RESET),
            ("bypass", SessionRecoveryAction.BYPASS),
            ("resume", SessionRecoveryAction.RESUME),
        ),
    )
    def test_session_recovery_maps_to_a_closed_chorus_event(
        self, action: str, expected: SessionRecoveryAction
    ) -> None:
        sink: list[Event] = []
        _bridge(sink).on_event(
            role_session_recovered(
                session_id="fresh-session",
                requested_session_id="stale-session",
                reason="schema_mismatch",
                action=action,
                snapshot_preserved=False,
            )
        )

        assert _kinds(sink) == [EventKind.SESSION_RECOVERED]
        assert sink[0].payload == {
            "role": "generator",
            "session_id": "fresh-session",
            "requested_session_id": "stale-session",
            "reason": "schema_mismatch",
            "action": expected.value,
            "snapshot_preserved": False,
        }

    def test_decoder_accepts_resume_action(self) -> None:
        notice = session_recovery_notice_from_dream_event(
            role_session_recovered(reason="missing", action="resume", snapshot_preserved=True)
        )
        assert notice == SessionRecoveryNotice(
            role="generator",
            session_id="fresh-session",
            requested_session_id="stale-session",
            reason=SessionRecoveryReason.MISSING,
            action=SessionRecoveryAction.RESUME,
            snapshot_preserved=True,
        )

    def test_decoder_rejects_dict_events(self) -> None:
        notice = session_recovery_notice_from_dream_event(
            {
                "kind": "role.session.recovered",
                "role": "generator",
                "session_id": "fresh-session",
                "requested_session_id": "stale-session",
                "reason": "missing",
                "action": "resume",
                "snapshot_preserved": True,
            }
        )
        assert notice is None

    def test_observer_drops_dict_recovery_events(self) -> None:
        sink: list[Event] = []
        event: object = {
            "kind": "role.session.recovered",
            "role": "generator",
            "session_id": "fresh-session",
            "requested_session_id": "stale-session",
            "reason": "missing",
            "action": "resume",
            "snapshot_preserved": True,
        }
        _bridge(sink).on_event(event)  # type: ignore[arg-type]
        assert sink == []

    def test_malformed_session_recovery_is_dropped(self) -> None:
        sink: list[Event] = []
        _bridge(sink).on_event(role_session_recovered(reason="unknown", action="reset"))
        _bridge(sink).on_event(role_session_recovered(reason="missing", action="wipe"))
        assert sink == []

    def test_decoder_accepts_dream_role_session_recovered_type(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from dataclasses import dataclass

        from dream.runner import events as dream_events

        from chorus.adapters import _dream_events

        expected = SessionRecoveryNotice(
            role="generator",
            session_id="fresh-session",
            requested_session_id="stale-session",
            reason=SessionRecoveryReason.CORRUPT,
            action=SessionRecoveryAction.RESUME,
            snapshot_preserved=True,
        )
        DreamType = getattr(dream_events, "RoleSessionRecovered", None)
        if isinstance(DreamType, type):
            notice = session_recovery_notice_from_dream_event(
                DreamType(
                    role="generator",
                    session_id="fresh-session",
                    requested_session_id="stale-session",
                    reason="corrupt",
                    action="resume",
                    snapshot_preserved=True,
                )
            )
            assert notice == expected
            return

        @dataclass(frozen=True, slots=True, kw_only=True)
        class DreamRoleSessionRecovered:
            role: str
            session_id: str
            requested_session_id: str
            reason: str
            action: str
            snapshot_preserved: bool

        monkeypatch.setattr(_dream_events, "_DREAM_ROLE_SESSION_RECOVERED", DreamRoleSessionRecovered)
        notice = session_recovery_notice_from_dream_event(
            DreamRoleSessionRecovered(
                role="generator",
                session_id="fresh-session",
                requested_session_id="stale-session",
                reason="corrupt",
                action="resume",
                snapshot_preserved=True,
            )
        )
        assert notice == expected
