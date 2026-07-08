"""Extract the model's own prose from a raw_record JSONL body.

The raw_record (:attr:`~chorus.heartbeat.BeatOutcome.raw_record`, persisted as
:attr:`~chorus.memory.SprintDelta.body`) mixes three event kinds per beat: ``role.text`` (the
model's own generated prose — its ``<spec>``, ``<proposal>``, reasoning), ``role.tool.start``
(tool name + arguments), and ``role.tool.result`` (a truncated output preview). Only ``role.text``
is worth indexing for BM25 search or showing back to an agent as its "own account" — the other two
kinds are structured I/O logs (tool-argument JSON, truncated stdout) that dilute both relevance
ranking and readability. This keeps the full raw_record intact elsewhere (the durable audit trail);
it only narrows the text used for search + display.
"""

from __future__ import annotations

import json

_NARRATIVE_KIND = "role.text"


def narrative(raw_record: str) -> str:
    """The ``role.text`` events in ``raw_record``, joined in order. Malformed lines are skipped."""
    lines = []
    for line in raw_record.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("kind") == _NARRATIVE_KIND:
            lines.append(str(event.get("text", "")))
    return "\n".join(lines)


__all__ = ["narrative"]
