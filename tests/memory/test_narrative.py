"""``narrative`` — extracts the model's own prose from a raw_record JSONL body.

The raw_record mixes three event kinds (role.text, role.tool.start, role.tool.result); only
role.text is the model's own words. narrative() keeps just that, for indexing (BM25) and display.
"""

from __future__ import annotations

import json

from chorus.memory import narrative


def _line(kind: str, **fields: object) -> str:
    return json.dumps({"kind": kind, **fields})


def test_keeps_only_role_text_events() -> None:
    body = "\n".join(
        [
            _line("role.text", role="generator", text="implementing subtract"),
            _line("role.tool.start", role="generator", tool="write_file", input={"path": "a.py"}),
            _line(
                "role.tool.result",
                role="generator",
                tool="write_file",
                is_error=False,
                content_preview="ok",
            ),
            _line("role.text", role="evaluator", text="looks correct, approving"),
        ]
    )
    assert narrative(body) == "implementing subtract\nlooks correct, approving"


def test_empty_body_is_empty_narrative() -> None:
    assert narrative("") == ""


def test_body_with_no_role_text_events_is_empty() -> None:
    body = _line("role.tool.start", role="generator", tool="git", input={})
    assert narrative(body) == ""


def test_ignores_blank_lines() -> None:
    body = "\n\n" + _line("role.text", role="generator", text="hello") + "\n\n"
    assert narrative(body) == "hello"


def test_malformed_line_is_skipped_not_raised() -> None:
    body = "\n".join(["not json", _line("role.text", role="generator", text="hello")])
    assert narrative(body) == "hello"
