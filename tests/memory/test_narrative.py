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


def test_distilled_body_keeps_only_prose_and_bounds_it() -> None:
    """A 100k+ raw record is reduced to bounded role.text; tool I/O is dropped (F3)."""
    import json as _json

    from chorus.memory.episodic.narrative import distilled_body, narrative

    lines = []
    lines.append(_json.dumps({"kind": "role.text", "text": "Chose a split-pane editor."}))
    # a huge tool-result event that used to bloat the body to 100k+ chars
    lines.append(_json.dumps({"kind": "role.tool.result", "text": "x" * 200_000}))
    lines.append(_json.dumps({"kind": "role.text", "text": "Wired autosave to localStorage."}))
    raw = "\n".join(lines)

    body = distilled_body(raw, summary="", max_chars=6000)

    assert len(body) < 6000  # the 200k tool result is gone
    assert "Chose a split-pane editor." in narrative(body)
    assert "Wired autosave to localStorage." in narrative(body)
    assert "xxxxx" not in body  # tool I/O dropped


def test_distilled_body_falls_back_to_summary_as_role_text() -> None:
    from chorus.memory.episodic.narrative import distilled_body, narrative

    body = distilled_body("", summary="Delegated the build to three ICs.", max_chars=6000)
    assert narrative(body) == "Delegated the build to three ICs."
