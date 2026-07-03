"""Best-effort subagent trace reader — recovers dream's dropped counters (spec 08)."""

from __future__ import annotations

import json
from pathlib import Path

from chorus.adapters._trace import (
    beat_subagent_stats,
    newest_trace_since,
    read_subagent_stats,
    sidecar_traces,
)


def _write_trace(working_dir: Path, session: str, records: list[dict[str, object]]) -> Path:
    trace = working_dir / ".dream" / "sidecars" / session / "logs" / "trace.jsonl"
    trace.parent.mkdir(parents=True, exist_ok=True)
    trace.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return trace


def _complete(name: str, *, turns: int, calls: int, ok: bool = True) -> dict[str, object]:
    return {
        "event_type": "subagent.complete",
        "attributes": {
            "subagent_name": name, "success": ok, "turns_used": turns,
            "tool_calls": calls, "tool_errors": 0, "elapsed_seconds": 12.5,
        },
    }


class TestReadSubagentStats:
    def test_parses_completes_in_order(self, tmp_path: Path) -> None:
        trace = _write_trace(
            tmp_path, "s1",
            [{"event_type": "task.started", "attributes": {}},
             _complete("brand_critic", turns=2, calls=2),
             _complete("brand_critic", turns=3, calls=1)],
        )
        stats = read_subagent_stats(trace)
        assert [s.turns_used for s in stats] == [2, 3]
        assert stats[0].name == "brand_critic"
        assert stats[0].tool_calls == 2

    def test_missing_file_yields_empty(self, tmp_path: Path) -> None:
        assert read_subagent_stats(tmp_path / "nope.jsonl") == ()

    def test_malformed_lines_are_skipped(self, tmp_path: Path) -> None:
        trace = tmp_path / "t.jsonl"
        trace.write_text("not json\n" + json.dumps(_complete("c", turns=1, calls=1)) + "\n")
        stats = read_subagent_stats(trace)
        assert len(stats) == 1


class TestBeatIsolation:
    def test_newest_since_isolates_this_beats_trace(self, tmp_path: Path) -> None:
        old = _write_trace(tmp_path, "old", [_complete("x", turns=9, calls=9)])
        seen = sidecar_traces(tmp_path)
        assert old in seen
        _write_trace(tmp_path, "new", [_complete("brand_critic", turns=2, calls=2)])
        fresh = newest_trace_since(tmp_path, seen)
        assert fresh is not None and "new" in str(fresh)

    def test_beat_stats_reads_only_the_fresh_trace(self, tmp_path: Path) -> None:
        _write_trace(tmp_path, "old", [_complete("stale", turns=9, calls=9)])
        seen = sidecar_traces(tmp_path)
        _write_trace(tmp_path, "new", [_complete("brand_critic", turns=2, calls=2)])
        stats = beat_subagent_stats(tmp_path, seen)
        assert [s.name for s in stats] == ["brand_critic"]

    def test_no_fresh_trace_yields_empty(self, tmp_path: Path) -> None:
        _write_trace(tmp_path, "old", [_complete("x", turns=1, calls=1)])
        seen = sidecar_traces(tmp_path)
        assert beat_subagent_stats(tmp_path, seen) == ()

    def test_absent_sidecar_dir_is_safe(self, tmp_path: Path) -> None:
        assert sidecar_traces(tmp_path) == frozenset()
        assert beat_subagent_stats(tmp_path, frozenset()) == ()
