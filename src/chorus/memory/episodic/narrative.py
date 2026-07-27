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
import re

_NARRATIVE_KIND = "role.text"
_SUMMARY_MAX = 160
_TAG_RE = re.compile(r"</?[A-Za-z][^>]*>")
_WS_RE = re.compile(r"\s+")


def narrative(raw_record: str) -> str:
    """The ``role.text`` events in ``raw_record``, joined in order. Malformed lines are skipped."""
    lines: list[str] = []
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


def distilled_body(raw_record: str, *, summary: str = "", max_chars: int) -> str:
    """The recall-worthy slice of a beat, bounded — the persisted episodic body.

    A full ``raw_record`` is 100k+ chars: ``role.text`` prose plus tool-argument JSON and truncated
    stdout previews. Only the prose is worth recalling (see module docstring), and the full stream is
    already durable in the run log + trace, so the episodic body keeps only the ``role.text`` lines,
    in the same JSONL shape :func:`narrative`/:func:`beat_summary` read, capped to ``max_chars`` by
    whole lines. Falls back to the beat's ``summary`` as one ``role.text`` line when the record
    carries no prose.
    """
    kept: list[str] = []
    total = 0
    for line in raw_record.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("kind") != _NARRATIVE_KIND:
            continue
        if total + len(line) + 1 > max_chars:
            break
        kept.append(line)
        total += len(line) + 1
    if kept:
        return "\n".join(kept)
    prose = summary.strip()
    return json.dumps({"kind": _NARRATIVE_KIND, "text": prose[:max_chars]}) if prose else ""


def normalize_for_fts(text: str) -> str:
    """Strip XML-like tags and collapse whitespace before BM25 indexing."""
    if not text:
        return ""
    return _WS_RE.sub(" ", _TAG_RE.sub(" ", text)).strip()


def beat_summary(body: str, *, intent: str) -> str:
    """Deterministic one-liner for slim recall hits — first narrative sentence or intent."""
    prose = normalize_for_fts(narrative(body))
    if prose:
        sentence = prose[: prose.index(".") + 1].strip() if "." in prose else prose
    else:
        sentence = normalize_for_fts(intent).split(".", 1)[0].strip()
    if not sentence:
        return ""
    if len(sentence) <= _SUMMARY_MAX:
        return sentence
    return sentence[: _SUMMARY_MAX - 1].rstrip() + "…"


__all__ = ["beat_summary", "distilled_body", "narrative", "normalize_for_fts"]
