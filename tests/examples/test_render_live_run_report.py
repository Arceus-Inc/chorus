from __future__ import annotations

import json
from pathlib import Path

from examples.render_live_run_report import parse_report, render

from chorus.testing import uid


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
            "task_id": uid("task-1"),
            "trace_id": "trace-1",
        },
        {
            "at": "2026-07-15T01:00:00.001000+00:00",
            "employee_id": "bex",
            "kind": "run.text",
            "payload": {"role": "generator", "text": "lo"},
            "run_id": "run-1",
            "task_id": uid("task-1"),
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
            "task_id": uid("task-1"),
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
            "task_id": uid("task-1"),
            "trace_id": "trace-1",
        },
    )
    path.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
    return path


def _artifact_events(path: Path) -> Path:
    events = (
        {
            "at": "2026-07-15T01:00:00+00:00",
            "kind": "run.tool_use",
            "payload": {
                "role": "generator",
                "tool": "write_file",
                "input": {"path": "links.py", "content": "old body"},
            },
            "task_id": uid("links-task"),
        },
        {
            "at": "2026-07-15T01:00:01+00:00",
            "kind": "run.tool_result",
            "payload": {
                "role": "generator",
                "tool": "write_file",
                "is_error": False,
                "content": "Wrote links.py",
            },
            "task_id": uid("links-task"),
        },
        {
            "at": "2026-07-15T01:00:02+00:00",
            "kind": "run.tool_use",
            "payload": {
                "role": "generator",
                "tool": "write_file",
                "input": {"path": "links.py", "content": "final <body>"},
            },
            "task_id": uid("links-task"),
        },
        {
            "at": "2026-07-15T01:00:03+00:00",
            "kind": "run.tool_result",
            "payload": {
                "role": "generator",
                "tool": "write_file",
                "is_error": False,
                "content": "Wrote links.py",
            },
            "task_id": uid("links-task"),
        },
        {
            "at": "2026-07-15T01:00:04+00:00",
            "kind": "run.tool_use",
            "payload": {
                "role": "generator",
                "tool": "write_file",
                "input": {"path": "scratch.py", "content": "must not appear"},
            },
            "task_id": uid("links-task"),
        },
        {
            "at": "2026-07-15T01:00:05+00:00",
            "kind": "run.tool_result",
            "payload": {
                "role": "generator",
                "tool": "write_file",
                "is_error": True,
                "content": "write denied",
            },
            "task_id": uid("links-task"),
        },
        {
            "at": "2026-07-15T01:00:06+00:00",
            "kind": "run.tool_use",
            "payload": {
                "role": "generator",
                "tool": "write_file",
                "input": {"path": "review.json", "content": '{"cleared": true}'},
            },
            "task_id": uid("review-task"),
        },
        {
            "at": "2026-07-15T01:00:07+00:00",
            "kind": "run.tool_result",
            "payload": {
                "role": "generator",
                "tool": "write_file",
                "is_error": False,
                "content": "Wrote review.json",
            },
            "task_id": uid("review-task"),
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


def test_artifacts_show_latest_successful_code_and_landing_state(tmp_path: Path) -> None:
    source = _report(tmp_path / "T1-latest.md", "T1", "PASS")
    with source.open("a", encoding="utf-8") as stream:
        stream.write(
            """

## Deliverables

### Tracked files
```text
links.py
generated/report.json
```

### Artifacts
```json
{"artifact_type": "merged_pr", "commit": "abc123", "unsafe": "<value>"}
```
"""
        )

    report = parse_report("T1", source, events_path=_artifact_events(tmp_path / "events.jsonl"))
    output = render((report,))

    artifacts = {(item.task_id, item.path): item for item in report.artifacts}
    assert set(artifacts) == {
        (uid("links-task"), "links.py"),
        (uid("review-task"), "review.json"),
        ("final-workspace", "generated/report.json"),
    }
    assert artifacts[(uid("links-task"), "links.py")].content == "final <body>"
    assert artifacts[(uid("links-task"), "links.py")].write_count == 2
    assert artifacts[(uid("links-task"), "links.py")].state == "landed"
    assert artifacts[(uid("review-task"), "review.json")].state == "transient"
    assert artifacts[("final-workspace", "generated/report.json")].content is None
    artifact_output = output.split('<section class="event-explorer"', 1)[0]
    assert "must not appear" not in artifact_output
    assert 'class="artifact-explorer"' in output
    assert "final &lt;body&gt;" in output
    assert "Content body was not captured" in output
    assert "Landed" in output
    assert "Transient / not landed" in output
    assert len(report.artifact_records) == 1
    assert report.artifact_records[0].title == "Artifacts"
    assert '"commit": "abc123"' in report.artifact_records[0].content
    assert 'class="artifact-record"' in output
    assert "&quot;unsafe&quot;: &quot;&lt;value&gt;&quot;" in output
