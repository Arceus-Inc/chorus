from __future__ import annotations

import json
from pathlib import Path

from examples.render_live_run_report import parse_report, render


def _report(path: Path, label: str, result: str) -> Path:
    path.write_text(
        f"""# {label} report

**Result:** {result}
**Model deployment:** `gpt-5.2`
**Run directory:** `runs/{label.lower()}`
**Scope:** {label} acceptance

## Invariants

| Check | Result | Evidence |
| --- | --- | --- |
| exact behavior | {"PASS" if result == "PASS" else "FAIL"} | <unsafe> & complete |

## Full Detail

Every source line is preserved.
""",
        encoding="utf-8",
    )
    return path


def _events(path: Path) -> Path:
    events = (
        {
            "at": "2026-07-15T01:00:00+00:00",
            "employee_id": "bex",
            "kind": "run.text",
            "payload": {"role": "generator", "text": "Hel"},
            "run_id": "run-1",
            "task_id": "task-1",
            "trace_id": "trace-1",
        },
        {
            "at": "2026-07-15T01:00:00.001000+00:00",
            "employee_id": "bex",
            "kind": "run.text",
            "payload": {"role": "generator", "text": "lo"},
            "run_id": "run-1",
            "task_id": "task-1",
            "trace_id": "trace-1",
        },
        {
            "at": "2026-07-15T01:00:01+00:00",
            "employee_id": "bex",
            "kind": "run.tool_use",
            "payload": {
                "role": "generator",
                "tool": "bash",
                "input": {"command": "python gate_check.py"},
            },
            "run_id": "run-1",
            "task_id": "task-1",
            "trace_id": "trace-1",
        },
        {
            "at": "2026-07-15T01:00:02+00:00",
            "employee_id": "bex",
            "kind": "run.tool_result",
            "payload": {
                "role": "generator",
                "tool": "bash",
                "is_error": True,
                "content": "gate failed <unsafe>",
            },
            "run_id": "run-1",
            "task_id": "task-1",
            "trace_id": "trace-1",
        },
    )
    path.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
    return path


def test_render_preserves_all_reports_and_builds_collapsible_dashboard(tmp_path: Path) -> None:
    sources = (
        _report(tmp_path / "T1-latest.md", "T1", "PASS"),
        _report(tmp_path / "T2-latest.md", "T2", "PASS"),
        _report(tmp_path / "T3-latest.md", "T3", "STOPPED / NEEDS FIX"),
    )
    reports = tuple(parse_report(f"T{index}", source) for index, source in enumerate(sources, 1))

    output = render(reports)

    assert output.count('class="run-panel"') == 3
    assert output.count('class="source-report"') == 3
    assert 'id="run-t3" open' in output
    assert "2/3</strong> runs passed" in output
    assert "&lt;unsafe&gt; &amp; complete" in output
    assert "Every source line is preserved." in output
    assert f'href="{tmp_path.name}/T1-latest.md"' in output
    assert "5vw" not in output
    assert 'new URLSearchParams(window.location.search).get("scoutTheme")' in output
    assert "--cp-accent: #b11f4b" in output


def test_event_stream_is_parsed_coalesced_and_filterable(tmp_path: Path) -> None:
    source = _report(tmp_path / "T1-latest.md", "T1", "PASS")
    events = _events(tmp_path / "events.jsonl")

    report = parse_report("T1", source, events_path=events)
    output = render((report,))

    assert report.event_count == 4
    assert len(report.events) == 3
    assert report.events[0].kind == "run.text"
    assert report.events[0].summary == "Hello"
    assert report.events[0].source_count == 2
    assert 'class="event-explorer"' in output
    assert 'data-kind="run.tool_use"' in output
    assert "generator called bash" in output
    assert "bash returned error" in output
    assert "4 raw events" in output
    assert "3 readable timeline entries" in output
    assert "gate failed &lt;unsafe&gt;" in output
    assert 'class="event-search"' in output
    assert 'search.addEventListener("input", apply);\n  });' in output


def test_report_recovers_events_from_embedded_markdown(tmp_path: Path) -> None:
    source = _report(tmp_path / "T1-latest.md", "T1", "PASS")
    with source.open("a", encoding="utf-8") as stream:
        stream.write(
            """

## Chronological Runtime Events

### 1. `run.text` at 2026-07-15T01:00:00+00:00

task=`task-1` employee=`bex` run=`run-1` trace=`trace-1`

```json
{
    "role": "generator",
    "text": "Hel"
}
```

### 2. `run.text` at 2026-07-15T01:00:00.001000+00:00

task=`task-1` employee=`bex` run=`run-1` trace=`trace-1`

````json
{
    "role": "generator",
    "text": "lo```"
}
````
"""
        )

    report = parse_report("T1", source)

    assert report.event_count == 2
    assert len(report.events) == 1
    assert report.events[0].summary == "Hello```"
    assert report.events[0].raw_events[0]["trace_id"] == "trace-1"
