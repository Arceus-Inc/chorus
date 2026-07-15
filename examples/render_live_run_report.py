"""Render the latest T1/T2/T3 Markdown reports as one self-contained HTML dashboard."""

from __future__ import annotations

import argparse
import html
import json
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final


@dataclass(frozen=True)
class Invariant:
    check: str
    result: str
    evidence: str


@dataclass(frozen=True)
class EventEntry:
    sequence_start: int
    sequence_end: int
    at: str
    ended_at: str
    kind: str
    task_id: str
    employee_id: str
    run_id: str
    trace_id: str
    role: str
    summary: str
    raw_events: tuple[dict[str, Any], ...]

    @property
    def source_count(self) -> int:
        return len(self.raw_events)


@dataclass(frozen=True)
class ArtifactFile:
    path: str
    content: str | None
    state: str
    kind: str
    task_id: str
    employee_id: str
    role: str
    at: str
    sequence: int | None
    write_count: int


@dataclass(frozen=True)
class ArtifactRecord:
    title: str
    content: str


@dataclass(frozen=True)
class RunReport:
    label: str
    title: str
    result: str
    model: str
    run_directory: str
    scope: str
    source_path: Path
    markdown: str
    invariants: tuple[Invariant, ...]
    events_path: Path | None
    events: tuple[EventEntry, ...]
    artifacts: tuple[ArtifactFile, ...]
    artifact_records: tuple[ArtifactRecord, ...]
    has_tracked_inventory: bool

    @property
    def passed(self) -> bool:
        return self.result.upper() == "PASS"

    @property
    def event_count(self) -> int:
        return sum(event.source_count for event in self.events)

    @property
    def event_kind_counts(self) -> tuple[tuple[str, int], ...]:
        counts: Counter[str] = Counter()
        for event in self.events:
            counts[event.kind] += event.source_count
        return tuple(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


_REPORT_FILES: Final = (
    ("T1", Path("t1-live-runs/T1-latest.md")),
    ("T2", Path("t2-live-runs/T2-latest.md")),
    ("T3", Path("t3-live-runs/T3-latest.md")),
)

_ARTIFACT_RECORD_HEADINGS: Final = frozenset(
    {
        "Active management profiles",
        "Applied plan after explicit approval",
        "Artifacts",
        "Artifacts Written and Landed",
        "Employees",
        "Employees before approval",
        "Management profiles before approval",
        "Per-Child Quality Reconstruction",
        "Persisted proposal before approval",
    }
)

_EMBEDDED_EVENT: Final = re.compile(
    r"^### (?P<sequence>\d+)\. `(?P<kind>[^`]+)` at (?P<at>[^\r\n]+)\r?\n\r?\n"
    r"task=`(?P<task>[^`]*)` employee=`(?P<employee>[^`]*)` "
    r"run=`(?P<run>[^`]*)` trace=`(?P<trace>[^`]*)`\r?\n\r?\n"
    r"^(?P<fence>`{3,})json\r?\n(?P<payload>.*?)\r?\n^(?P=fence)\s*$",
    re.MULTILINE | re.DOTALL,
)


def _bold_value(markdown: str, label: str) -> str:
    match = re.search(rf"^\*\*{re.escape(label)}:\*\*\s*(.+?)\s*$", markdown, re.MULTILINE)
    return match.group(1).strip().strip("`") if match else "Not recorded"


def _invariants(markdown: str) -> tuple[Invariant, ...]:
    match = re.search(r"^## Invariants\s*$", markdown, re.MULTILINE)
    if match is None:
        return ()
    rows: list[Invariant] = []
    for line in markdown[match.end() :].splitlines():
        if line.startswith("## "):
            break
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|", 2)]
        if len(cells) != 3 or cells[0] in {"Check", "---"} or set(cells[0]) == {"-"}:
            continue
        rows.append(Invariant(*cells))
    return tuple(rows)


def _text(value: object) -> str:
    return "" if value is None else str(value)


def _one_line(value: object, *, limit: int = 320) -> str:
    if isinstance(value, str):
        rendered = value
    else:
        rendered = json.dumps(value, ensure_ascii=False, sort_keys=True)
    rendered = " ".join(rendered.split())
    return rendered if len(rendered) <= limit else f"{rendered[: limit - 3]}..."


def _preformatted(value: str) -> str:
    escaped = html.escape(value)
    return re.sub(
        r"[ \t]+$",
        lambda match: "".join("&#32;" if char == " " else "&#9;" for char in match[0]),
        escaped,
        flags=re.MULTILINE,
    )


def _event_summary(kind: str, payload: dict[str, Any]) -> str:
    role = _text(payload.get("role")) or "agent"
    if kind == "run.text":
        return _text(payload.get("text"))
    if kind == "run.tool_use":
        tool = _text(payload.get("tool")) or "unknown tool"
        detail = _one_line(payload.get("input", {}))
        return f"{role} called {tool}" + (f" - {detail}" if detail not in {"", "{}"} else "")
    if kind == "run.tool_result":
        tool = _text(payload.get("tool")) or "unknown tool"
        status = "error" if payload.get("is_error") is True else "ok"
        content = payload.get("content_preview", payload.get("content", ""))
        detail = _one_line(content)
        return f"{tool} returned {status}" + (f" - {detail}" if detail else "")
    if kind == "run.started":
        detail = _one_line(payload.get("intent", ""))
        return "run started" + (f" - {detail}" if detail else "")
    if kind == "run.done":
        return "run completed" + (f" - {_one_line(payload)}" if payload else "")
    if kind == "run.evaluated":
        outcome = _text(payload.get("outcome")) or "unknown outcome"
        notes = _one_line(payload.get("notes", ""))
        return f"evaluation: {outcome}" + (f" - {notes}" if notes else "")
    if kind == "run.subagent_spawned":
        name = _text(payload.get("name")) or "subagent"
        prompt = _one_line(payload.get("prompt", ""))
        return f"spawned {name}" + (f" - {prompt}" if prompt else "")
    if kind == "run.subagent_completed":
        name = _text(payload.get("name")) or "subagent"
        content = _one_line(payload.get("content", ""))
        return f"{name} completed" + (f" - {content}" if content else "")
    return _one_line(payload) or kind


def _event_entry(event: dict[str, Any], sequence: int) -> EventEntry:
    raw_payload = event.get("payload")
    payload = raw_payload if isinstance(raw_payload, dict) else {"value": raw_payload}
    at = _text(event.get("at"))
    return EventEntry(
        sequence_start=sequence,
        sequence_end=sequence,
        at=at,
        ended_at=at,
        kind=_text(event.get("kind")) or "unknown",
        task_id=_text(event.get("task_id") or payload.get("task_id")),
        employee_id=_text(event.get("employee_id")),
        run_id=_text(event.get("run_id")),
        trace_id=_text(event.get("trace_id")),
        role=_text(payload.get("role")),
        summary=_event_summary(_text(event.get("kind")) or "unknown", payload),
        raw_events=(event,),
    )


def _can_coalesce_text(previous: EventEntry, current: EventEntry) -> bool:
    return (
        previous.kind == current.kind == "run.text"
        and previous.task_id == current.task_id
        and previous.employee_id == current.employee_id
        and previous.run_id == current.run_id
        and previous.trace_id == current.trace_id
        and previous.role == current.role
    )


def _coalesce_events(events: Iterable[dict[str, Any]]) -> tuple[EventEntry, ...]:
    entries: list[EventEntry] = []
    for sequence, event in enumerate(events, 1):
        current = _event_entry(event, sequence)
        if entries and _can_coalesce_text(entries[-1], current):
            previous = entries[-1]
            entries[-1] = EventEntry(
                sequence_start=previous.sequence_start,
                sequence_end=current.sequence_end,
                at=previous.at,
                ended_at=current.ended_at,
                kind=previous.kind,
                task_id=previous.task_id,
                employee_id=previous.employee_id,
                run_id=previous.run_id,
                trace_id=previous.trace_id,
                role=previous.role,
                summary=previous.summary + current.summary,
                raw_events=(*previous.raw_events, *current.raw_events),
            )
        else:
            entries.append(current)
    return tuple(entries)


def parse_events(events_path: Path) -> tuple[EventEntry, ...]:
    events: list[dict[str, Any]] = []
    with events_path.open(encoding="utf-8") as stream:
        for line in stream:
            try:
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError("event is not a JSON object")
                event = value
            except (json.JSONDecodeError, ValueError) as exc:
                event = {
                    "at": "",
                    "kind": "parse.error",
                    "payload": {"error": str(exc), "raw_line": line.rstrip("\n")},
                }
            events.append(event)
    return _coalesce_events(events)


def _metadata_value(value: str) -> str | None:
    return None if value == "None" else value


def parse_embedded_events(markdown: str) -> tuple[EventEntry, ...]:
    events: list[dict[str, Any]] = []
    for expected_sequence, match in enumerate(_EMBEDDED_EVENT.finditer(markdown), 1):
        sequence = int(match.group("sequence"))
        try:
            payload = json.loads(match.group("payload"))
        except json.JSONDecodeError as exc:
            payload = {"error": str(exc), "raw_payload": match.group("payload")}
            kind = "parse.error"
        else:
            kind = match.group("kind")
        if sequence != expected_sequence:
            raise ValueError(
                f"embedded event sequence is not contiguous: expected "
                f"{expected_sequence}, found {sequence}"
            )
        events.append(
            {
                "at": match.group("at"),
                "employee_id": _metadata_value(match.group("employee")),
                "kind": kind,
                "payload": payload,
                "run_id": _metadata_value(match.group("run")),
                "task_id": _metadata_value(match.group("task")),
                "trace_id": _metadata_value(match.group("trace")),
            }
        )
    return _coalesce_events(events)


def _normalize_path(value: str) -> str:
    normalized = value.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.casefold()


def _tracked_files(markdown: str) -> tuple[tuple[str, ...], bool]:
    match = re.search(
        r"^### Tracked files\s*$\r?\n(?P<fence>`{3,})(?:text)?\r?\n"
        r"(?P<files>.*?)\r?\n(?P=fence)\s*$",
        markdown,
        re.MULTILINE | re.DOTALL,
    )
    if match is None:
        return (), False
    files = tuple(line.strip() for line in match.group("files").splitlines() if line.strip())
    return files, True


def _artifact_kind(path: str) -> str:
    normalized = _normalize_path(path)
    suffix = Path(normalized).suffix
    if normalized.startswith("tests/") or "/tests/" in normalized:
        return "test code"
    if suffix in {".py", ".js", ".jsx", ".ts", ".tsx"}:
        return "code"
    if suffix in {".json", ".jsonl"}:
        return "structured record"
    if suffix in {".md", ".txt"}:
        return "document"
    if suffix in {".toml", ".yaml", ".yml", ".ini"} or normalized.endswith(".gitignore"):
        return "configuration"
    return "file"


def _artifact_records(markdown: str) -> tuple[ArtifactRecord, ...]:
    heading_pattern = re.compile(r"^(?P<marks>#{2,6})\s+(?P<title>.+?)\s*$", re.MULTILINE)
    headings = tuple(heading_pattern.finditer(markdown))
    records: list[ArtifactRecord] = []
    for index, heading in enumerate(headings):
        title = heading.group("title")
        if title not in _ARTIFACT_RECORD_HEADINGS:
            continue
        level = len(heading.group("marks"))
        end = len(markdown)
        for next_heading in headings[index + 1 :]:
            if len(next_heading.group("marks")) <= level:
                end = next_heading.start()
                break
        content = markdown[heading.end() : end].strip()
        if content:
            records.append(ArtifactRecord(title=title, content=content))
    return tuple(records)


def _artifact_identity(event: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        _text(event.get("task_id")),
        _text(event.get("employee_id")),
        _text(event.get("run_id")),
        _text(event.get("trace_id")),
    )


def _artifacts(
    markdown: str, events: tuple[EventEntry, ...]
) -> tuple[tuple[ArtifactFile, ...], bool]:
    tracked_files, has_tracked_inventory = _tracked_files(markdown)
    tracked_paths = {_normalize_path(path) for path in tracked_files}
    pending: dict[
        tuple[str, str, str, str],
        list[tuple[int, dict[str, Any], str, str]],
    ] = {}
    latest: dict[tuple[str, str], ArtifactFile] = {}
    successful_writes: Counter[tuple[str, str]] = Counter()

    sequence = 0
    for entry in events:
        for event in entry.raw_events:
            sequence += 1
            raw_payload = event.get("payload")
            payload = raw_payload if isinstance(raw_payload, dict) else {}
            identity = _artifact_identity(event)
            if event.get("kind") == "run.tool_use" and payload.get("tool") == "write_file":
                tool_input = payload.get("input")
                if not isinstance(tool_input, dict):
                    continue
                path = tool_input.get("path")
                content = tool_input.get("content")
                if not isinstance(path, str) or not path.strip() or not isinstance(content, str):
                    continue
                pending.setdefault(identity, []).append((sequence, event, path.strip(), content))
                continue
            if event.get("kind") != "run.tool_result" or payload.get("tool") != "write_file":
                continue
            candidates = pending.get(identity)
            if not candidates:
                continue
            write_sequence, source_event, path, content = candidates.pop(0)
            if payload.get("is_error") is True:
                continue
            normalized_path = _normalize_path(path)
            key = (_text(source_event.get("task_id")), normalized_path)
            successful_writes[key] += 1
            source_payload = source_event.get("payload")
            source = source_payload if isinstance(source_payload, dict) else {}
            state = (
                "landed"
                if normalized_path in tracked_paths
                else "transient"
                if has_tracked_inventory
                else "authored"
            )
            latest[key] = ArtifactFile(
                path=path,
                content=content,
                state=state,
                kind=_artifact_kind(path),
                task_id=key[0] or "not recorded",
                employee_id=_text(source_event.get("employee_id")) or "not recorded",
                role=_text(source.get("role")) or "not recorded",
                at=_text(source_event.get("at")),
                sequence=write_sequence,
                write_count=successful_writes[key],
            )

    written_paths = {key[1] for key in latest}
    for path in tracked_files:
        if _normalize_path(path) in written_paths:
            continue
        latest[("final-workspace", _normalize_path(path))] = ArtifactFile(
            path=path,
            content=None,
            state="landed",
            kind=_artifact_kind(path),
            task_id="final-workspace",
            employee_id="not recorded",
            role="not recorded",
            at="",
            sequence=None,
            write_count=0,
        )

    state_order = {"landed": 0, "authored": 1, "transient": 2}
    artifacts = tuple(
        sorted(
            latest.values(),
            key=lambda item: (state_order[item.state], item.path.casefold(), item.task_id),
        )
    )
    return artifacts, has_tracked_inventory


def parse_report(label: str, source_path: Path, *, events_path: Path | None = None) -> RunReport:
    markdown = source_path.read_text(encoding="utf-8")
    title_match = re.search(r"^#\s+(.+)$", markdown, re.MULTILINE)
    events = (
        parse_events(events_path) if events_path is not None else parse_embedded_events(markdown)
    )
    artifacts, has_tracked_inventory = _artifacts(markdown, events)
    return RunReport(
        label=label,
        title=title_match.group(1).strip() if title_match else label,
        result=_bold_value(markdown, "Result"),
        model=_bold_value(markdown, "Model deployment"),
        run_directory=_bold_value(markdown, "Run directory"),
        scope=_bold_value(markdown, "Scope"),
        source_path=source_path,
        markdown=markdown,
        invariants=_invariants(markdown),
        events_path=events_path,
        events=events,
        artifacts=artifacts,
        artifact_records=_artifact_records(markdown),
        has_tracked_inventory=has_tracked_inventory,
    )


def _result_class(value: str) -> str:
    return "pass" if value.upper() == "PASS" else "fail"


def _summary_card(report: RunReport) -> str:
    passed = sum(item.result.upper() == "PASS" for item in report.invariants)
    return f"""
      <button class="summary-card" type="button" data-target="run-{report.label.lower()}">
        <span class="run-label">{html.escape(report.label)}</span>
        <strong>{html.escape(report.result)}</strong>
        <span>{passed}/{len(report.invariants)} invariants passed</span>
      </button>"""


def _invariant_rows(report: RunReport) -> str:
    return "\n".join(
        "<tr>"
        f"<td>{html.escape(item.check)}</td>"
        f'<td><span class="badge {_result_class(item.result)}">{html.escape(item.result)}</span></td>'
        f"<td>{html.escape(item.evidence)}</td>"
        "</tr>"
        for item in report.invariants
    )


def _sequence_label(event: EventEntry) -> str:
    if event.sequence_start == event.sequence_end:
        return f"#{event.sequence_start}"
    return f"#{event.sequence_start}-{event.sequence_end}"


def _event_rows(report: RunReport) -> str:
    rows: list[str] = []
    for event in report.events:
        raw_value: object = (
            event.raw_events[0] if event.source_count == 1 else list(event.raw_events)
        )
        raw_json = json.dumps(raw_value, indent=2, ensure_ascii=False, sort_keys=True)
        search_text = " ".join(
            (
                event.kind,
                event.task_id,
                event.employee_id,
                event.run_id,
                event.trace_id,
                event.role,
                event.summary,
            )
        ).casefold()
        count = f" x{event.source_count}" if event.source_count > 1 else ""
        sequence = _sequence_label(event)
        rows.append(
            f'<details class="event-row" data-kind="{html.escape(event.kind, quote=True)}" '
            f'data-search="{html.escape(search_text, quote=True)}">'
            "<summary>"
            '<span class="chevron" aria-hidden="true"></span>'
            f'<span class="event-sequence">{html.escape(sequence)}</span>'
            f"<time>{html.escape(event.at)}</time>"
            f'<span class="event-kind">{html.escape(event.kind)}{count}</span>'
            f'<span class="event-task">{html.escape(event.task_id or "no task")}</span>'
            f'<span class="event-summary">{html.escape(_one_line(event.summary))}</span>'
            "</summary>"
            '<div class="event-detail">'
            '<dl class="event-metadata">'
            f"<div><dt>Sequence</dt><dd>{html.escape(sequence)}</dd></div>"
            f"<div><dt>Time range</dt><dd>{html.escape(event.at)}"
            f"{f' to {html.escape(event.ended_at)}' if event.ended_at != event.at else ''}</dd></div>"
            f"<div><dt>Role / employee</dt><dd>{html.escape(event.role or 'not recorded')} / "
            f"{html.escape(event.employee_id or 'not recorded')}</dd></div>"
            f"<div><dt>Task / run</dt><dd>{html.escape(event.task_id or 'not recorded')} / "
            f"{html.escape(event.run_id or 'not recorded')}</dd></div>"
            f"<div><dt>Trace</dt><dd>{html.escape(event.trace_id or 'not recorded')}</dd></div>"
            f"<div><dt>Source events</dt><dd>{event.source_count}</dd></div>"
            "</dl>"
            f"<pre>{html.escape(raw_json)}</pre>"
            "</div>"
            "</details>"
        )
    return "\n".join(rows)


def _event_explorer(report: RunReport) -> str:
    if not report.events:
        return """
        <section class="event-explorer empty">
          <h3>Parsed event timeline</h3>
          <p class="muted">No JSONL event stream was supplied when this report was rendered.</p>
        </section>"""
    kind_buttons = "".join(
        f'<button type="button" class="event-kind-filter" data-event-kind="{html.escape(kind, quote=True)}">'
        f"{html.escape(kind)} <span>{count}</span></button>"
        for kind, count in report.event_kind_counts
    )
    source = (
        report.events_path.name
        if report.events_path is not None
        else "the committed Markdown chronology"
    )
    return f"""
      <section class="event-explorer" data-run="{report.label.lower()}">
        <div class="event-heading">
        <div>
          <h3>Parsed event timeline</h3>
          <p class="muted">{report.event_count} raw events from {html.escape(source)} become {len(report.events)} readable timeline entries. Consecutive text tokens are coalesced; every original JSON object remains in the entry details.</p>
        </div>
            <label>Search events<input class="event-search" type="search" placeholder="tool, task, role, text..."></label>
        </div>
        <div class="event-filters" aria-label="Event kind filters">
        <button type="button" class="event-kind-filter active" data-event-kind="*">All <span>{report.event_count}</span></button>
        {kind_buttons}
        </div>
        <p class="event-status" aria-live="polite">{len(report.events)} of {len(report.events)} timeline entries</p>
        <div class="event-list">{_event_rows(report)}</div>
      </section>"""


def _artifact_state_label(state: str) -> str:
    return {
        "authored": "Authored / landing not recorded",
        "landed": "Landed",
        "record": "Durable report record",
        "transient": "Transient / not landed",
    }[state]


def _artifact_rows(report: RunReport) -> str:
    rows: list[str] = []
    for record in report.artifact_records:
        search_text = f"{record.title} durable report record {record.content}".casefold()
        rows.append(
            f'<details class="artifact-record" data-artifact-item data-state="record" '
            f'data-search="{html.escape(search_text, quote=True)}">'
            "<summary>"
            '<span class="chevron" aria-hidden="true"></span>'
            f'<span class="artifact-path">{html.escape(record.title)}</span>'
            '<span class="artifact-kind">report evidence</span>'
            '<span class="artifact-state record">Durable report record</span>'
            "</summary>"
            '<div class="artifact-detail">'
            '<dl class="event-metadata">'
            "<div><dt>Provenance</dt><dd>Committed Markdown report section</dd></div>"
            "<div><dt>Representation</dt><dd>Complete escaped source content</dd></div>"
            "</dl>"
            f"<pre>{_preformatted(record.content)}</pre>"
            "</div>"
            "</details>"
        )
    for artifact in report.artifacts:
        state_label = _artifact_state_label(artifact.state)
        search_text = " ".join(
            (
                artifact.path,
                artifact.kind,
                state_label,
                artifact.task_id,
                artifact.employee_id,
                artifact.role,
                artifact.content or "",
            )
        ).casefold()
        provenance = (
            f"event #{artifact.sequence} at {artifact.at}"
            if artifact.sequence is not None
            else "final tracked-file inventory"
        )
        writes = (
            f"{artifact.write_count} successful write"
            f"{'s' if artifact.write_count != 1 else ''}; latest shown"
            if artifact.write_count
            else "No captured write body"
        )
        content = (
            f"<pre>{_preformatted(artifact.content)}</pre>"
            if artifact.content is not None
            else '<p class="artifact-unavailable">Content body was not captured in a successful <code>write_file</code> event. The path is retained because it appears in the final tracked-file inventory.</p>'
        )
        rows.append(
            f'<details class="artifact-row" data-artifact-item data-state="{artifact.state}" '
            f'data-search="{html.escape(search_text, quote=True)}">'
            "<summary>"
            '<span class="chevron" aria-hidden="true"></span>'
            f'<code class="artifact-path">{html.escape(artifact.path)}</code>'
            f'<span class="artifact-kind">{html.escape(artifact.kind)}</span>'
            f'<span class="artifact-state {artifact.state}">{html.escape(state_label)}</span>'
            "</summary>"
            '<div class="artifact-detail">'
            '<dl class="event-metadata">'
            f"<div><dt>Task</dt><dd>{html.escape(artifact.task_id)}</dd></div>"
            f"<div><dt>Role / employee</dt><dd>{html.escape(artifact.role)} / "
            f"{html.escape(artifact.employee_id)}</dd></div>"
            f"<div><dt>Provenance</dt><dd>{html.escape(provenance)}</dd></div>"
            f"<div><dt>Write history</dt><dd>{html.escape(writes)}</dd></div>"
            "</dl>"
            f"{content}"
            "</div>"
            "</details>"
        )
    return "\n".join(rows)


def _artifact_explorer(report: RunReport) -> str:
    if not report.artifacts and not report.artifact_records:
        return """<section class="artifact-explorer empty">
    <h3>Artifacts and code</h3>
    <p class="muted">No successful file writes or final tracked-file inventory were captured for this run.</p>
</section>"""

    counts = Counter(artifact.state for artifact in report.artifacts)
    counts["record"] = len(report.artifact_records)
    total = len(report.artifacts) + len(report.artifact_records)
    state_buttons = "".join(
        f'<button type="button" class="artifact-state-filter" data-artifact-state="{state}">'
        f"{html.escape(_artifact_state_label(state))} <span>{counts[state]}</span></button>"
        for state in ("record", "landed", "authored", "transient")
        if counts[state]
    )
    if report.label == "T2":
        context = "This was an organization-formation run. It produced workforce/governance records and a directive; production application code was not expected or landed."
    elif report.label == "T3":
        context = "The child code below is preserved as execution evidence. It did not land in the final workspace; only paths marked Landed were final deliverables."
    elif report.has_tracked_inventory:
        context = "Landed paths are reconciled against the report's final tracked-file inventory. For repeated writes, the latest successful complete body is shown."
    else:
        context = "The report did not record a final tracked-file inventory, so successful writes are shown without claiming they landed."

    return f"""<section class="artifact-explorer" data-run="{report.label.lower()}">
    <div class="event-heading">
        <div>
            <h3>Artifacts and code</h3>
            <p class="muted">{html.escape(context)}</p>
        </div>
        <label>Search artifacts<input class="artifact-search" type="search" placeholder="path, task, role, content..."></label>
    </div>
    <div class="artifact-filters" aria-label="Artifact state filters">
        <button type="button" class="artifact-state-filter active" data-artifact-state="*">All <span>{total}</span></button>
        {state_buttons}
    </div>
    <p class="artifact-status" aria-live="polite">{total} of {total} artifacts</p>
    <div class="artifact-list">{_artifact_rows(report)}</div>
</section>"""


def _run_section(report: RunReport, *, open_by_default: bool) -> str:
    relative_source = f"{report.source_path.parent.name}/{report.source_path.name}"
    open_attribute = " open" if open_by_default else ""
    return f"""
    <details class="run-panel" id="run-{report.label.lower()}"{open_attribute}>
      <summary>
        <span class="chevron" aria-hidden="true"></span>
        <span class="run-label">{html.escape(report.label)}</span>
        <span class="run-title">{html.escape(report.title)}</span>
        <span class="badge {_result_class(report.result)}">{html.escape(report.result)}</span>
      </summary>
      <div class="run-content">
        <dl class="metadata">
          <div><dt>Model</dt><dd>{html.escape(report.model)}</dd></div>
          <div><dt>Scope</dt><dd>{html.escape(report.scope)}</dd></div>
          <div><dt>Run directory</dt><dd><code>{html.escape(report.run_directory)}</code></dd></div>
          <div><dt>Source</dt><dd><a href="{html.escape(relative_source)}">{html.escape(relative_source)}</a></dd></div>
        </dl>
        <div class="table-wrap">
          <table>
            <thead><tr><th>Invariant</th><th>Result</th><th>Evidence</th></tr></thead>
            <tbody>{_invariant_rows(report)}</tbody>
          </table>
        </div>
            {_artifact_explorer(report)}
        {_event_explorer(report)}
        <details class="source-report">
          <summary><span class="chevron" aria-hidden="true"></span> Complete source report</summary>
          <p class="muted">Every line from the latest Markdown report is preserved below.</p>
          <pre>{html.escape(report.markdown)}</pre>
        </details>
      </div>
    </details>"""


def render(reports: tuple[RunReport, ...]) -> str:
    passed_runs = sum(report.passed for report in reports)
    total_invariants = sum(len(report.invariants) for report in reports)
    passed_invariants = sum(
        item.result.upper() == "PASS" for report in reports for item in report.invariants
    )
    cards = "".join(_summary_card(report) for report in reports)
    sections = "".join(
        _run_section(report, open_by_default=not report.passed) for report in reports
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>M8 Live Qualification Report</title>
  <script>
  (() => {{
    const param = new URLSearchParams(window.location.search).get("scoutTheme");
    const theme =
      param || (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    document.documentElement.setAttribute("data-theme", theme);
  }})();
  </script>
  <style>
  :root {{
    color-scheme: light;
    --cp-bg: #f7f4ef;
    --cp-bg-elevated: #fcfbf8;
    --cp-surface: #ffffff;
    --cp-surface-soft: #f5f5f5;
    --cp-border: #dedede;
    --cp-border-strong: #919191;
    --cp-text: #242424;
    --cp-text-muted: #5c5c5c;
    --cp-text-soft: #6f6f6f;
    --cp-accent: #b11f4b;
    --cp-accent-hover: #9a1a41;
    --cp-accent-soft: rgba(177, 31, 75, 0.08);
    --cp-accent-fg: #ffffff;
    --cp-success: #16a34a;
    --cp-danger: #dc2626;
    --cp-warning: #f59e0b;
    --cp-link: #0078d4;
    --cp-shadow: 0 18px 48px rgba(0, 0, 0, 0.12);
    --cp-overlay: rgba(255, 255, 255, 0.8);
    --cp-panel: rgba(255, 255, 255, 0.86);
    --cp-panel-strong: rgba(255, 255, 255, 0.96);
    --cp-sheen: rgba(255, 255, 255, 0.55);
    --cp-highlight: rgba(177, 31, 75, 0.12);
  }}
  html[data-theme="dark"] {{
    color-scheme: dark;
    --cp-bg: #3d3b3a;
    --cp-bg-elevated: #343231;
    --cp-surface: #292929;
    --cp-surface-soft: #2e2e2e;
    --cp-border: #474747;
    --cp-border-strong: #5f5f5f;
    --cp-text: #dedede;
    --cp-text-muted: #919191;
    --cp-text-soft: #b0b0b0;
    --cp-accent: #fd8ea1;
    --cp-accent-hover: #fb7b91;
    --cp-accent-soft: rgba(253, 142, 161, 0.14);
    --cp-accent-fg: #1a1a1a;
    --cp-success: #4ade80;
    --cp-danger: #f87171;
    --cp-warning: #fbbf24;
    --cp-link: #4da6ff;
    --cp-shadow: 0 18px 48px rgba(0, 0, 0, 0.32);
    --cp-overlay: rgba(41, 41, 41, 0.88);
    --cp-panel: rgba(41, 41, 41, 0.72);
    --cp-panel-strong: rgba(41, 41, 41, 0.96);
    --cp-sheen: rgba(255, 255, 255, 0.04);
    --cp-highlight: rgba(253, 142, 161, 0.12);
  }}
  * {{ box-sizing: border-box; }}
  html {{ scroll-behavior: smooth; }}
  body {{
    margin: 0;
    background: var(--cp-bg);
    color: var(--cp-text);
    font-family: "Segoe UI", Aptos, Calibri, -apple-system, BlinkMacSystemFont, sans-serif;
    letter-spacing: 0;
  }}
  body::before {{
    content: "";
    position: fixed;
    inset: 0;
    pointer-events: none;
    background: repeating-linear-gradient(90deg, var(--cp-bg), var(--cp-bg) 47px, var(--cp-sheen) 48px);
  }}
  main {{ position: relative; width: min(1180px, calc(100% - 32px)); margin: 0 auto; padding: 48px 0 80px; }}
  header {{ border-top: 4px solid var(--cp-accent); padding: 28px 0 24px; }}
  .eyebrow, .run-label {{ color: var(--cp-accent); font-weight: 700; text-transform: uppercase; }}
  .eyebrow {{ margin: 0 0 8px; font-size: 13px; }}
  h1 {{ margin: 0; font-size: 48px; line-height: 1; }}
  .lede {{ max-width: 760px; color: var(--cp-text-muted); font-size: 18px; line-height: 1.6; }}
  .toolbar {{ display: flex; gap: 8px; flex-wrap: wrap; margin-top: 20px; }}
  button {{ font: inherit; }}
  .command {{
    border: 1px solid var(--cp-border-strong);
    border-radius: 6px;
    background: var(--cp-surface);
    color: var(--cp-text);
    padding: 8px 12px;
    cursor: pointer;
  }}
  .command:hover {{ border-color: var(--cp-accent); color: var(--cp-accent); }}
  .overview {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin: 12px 0 28px; }}
  .summary-card {{
    display: grid;
    gap: 8px;
    min-height: 132px;
    padding: 18px;
    text-align: left;
    border: 1px solid var(--cp-border);
    border-radius: 8px;
    background: var(--cp-surface);
    color: var(--cp-text);
    cursor: pointer;
    box-shadow: 0 1px 2px var(--cp-border);
  }}
  .summary-card:hover {{ border-color: var(--cp-accent); background: var(--cp-accent-soft); }}
  .summary-card strong {{ font-size: 22px; }}
  .summary-card span:last-child, .muted {{ color: var(--cp-text-muted); }}
  .rollup {{
    display: flex;
    gap: 24px;
    flex-wrap: wrap;
    margin-bottom: 28px;
    padding: 14px 16px;
    border-left: 3px solid var(--cp-accent);
    background: var(--cp-surface-soft);
  }}
  .rollup strong {{ font-size: 20px; }}
  .run-panel {{ margin: 12px 0; border: 1px solid var(--cp-border); border-radius: 8px; background: var(--cp-surface); }}
  .run-panel > summary {{
    display: grid;
    grid-template-columns: 18px 48px minmax(0, 1fr) auto;
    align-items: center;
    gap: 12px;
    min-height: 64px;
    padding: 12px 16px;
    cursor: pointer;
    list-style: none;
  }}
  summary::-webkit-details-marker {{ display: none; }}
  .chevron {{ width: 9px; height: 9px; border-right: 2px solid var(--cp-text-muted); border-bottom: 2px solid var(--cp-text-muted); transform: rotate(-45deg); transition: transform 160ms ease; }}
  details[open] > summary .chevron {{ transform: rotate(45deg); }}
  .run-title {{ font-weight: 650; }}
  .badge {{ display: inline-block; width: max-content; padding: 4px 8px; border: 1px solid currentColor; border-radius: 6px; font-size: 12px; font-weight: 700; }}
  .badge.pass {{ color: var(--cp-success); }}
  .badge.fail {{ color: var(--cp-danger); }}
  .run-content {{ border-top: 1px solid var(--cp-border); padding: 18px; }}
  .metadata {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin: 0 0 20px; }}
  .metadata div {{ min-width: 0; padding: 12px; border: 1px solid var(--cp-border); background: var(--cp-surface-soft); }}
  dt {{ color: var(--cp-text-muted); font-size: 12px; font-weight: 700; text-transform: uppercase; }}
  dd {{ margin: 5px 0 0; overflow-wrap: anywhere; }}
  code, pre {{ font-family: Consolas, "Courier New", Courier, monospace; }}
  a {{ color: var(--cp-link); }}
  .table-wrap {{ overflow-x: auto; border: 1px solid var(--cp-border); }}
  table {{ width: 100%; border-collapse: collapse; }}
  th, td {{ padding: 11px 12px; border-bottom: 1px solid var(--cp-border); text-align: left; vertical-align: top; line-height: 1.45; }}
  th {{ background: var(--cp-surface-soft); font-size: 12px; text-transform: uppercase; }}
  td:first-child {{ width: 25%; font-weight: 650; }}
  td:nth-child(2) {{ width: 88px; }}
  .source-report {{ margin-top: 16px; border: 1px solid var(--cp-border); background: var(--cp-bg-elevated); }}
  .source-report > summary {{ display: flex; align-items: center; gap: 12px; padding: 14px; cursor: pointer; font-weight: 650; }}
  .source-report > p {{ margin: 0; padding: 0 14px 14px; }}
    .artifact-explorer, .event-explorer {{ margin-top: 20px; padding-top: 20px; border-top: 1px solid var(--cp-border); }}
  .event-heading {{ display: grid; grid-template-columns: minmax(0, 1fr) minmax(220px, 320px); gap: 20px; align-items: end; }}
  .event-heading h3 {{ margin: 0 0 4px; font-size: 22px; }}
  .event-heading p {{ margin: 0; line-height: 1.5; }}
  .event-heading label {{ display: grid; gap: 6px; color: var(--cp-text-muted); font-size: 12px; font-weight: 700; text-transform: uppercase; }}
    .event-search, .artifact-search {{ width: 100%; min-height: 38px; padding: 7px 10px; border: 1px solid var(--cp-border-strong); border-radius: 6px; background: var(--cp-surface); color: var(--cp-text); font: inherit; }}
    .event-search:focus, .artifact-search:focus {{ border-color: var(--cp-accent); outline: 2px solid var(--cp-highlight); }}
    .event-filters, .artifact-filters {{ display: flex; gap: 6px; flex-wrap: wrap; margin: 14px 0 8px; }}
    .event-kind-filter, .artifact-state-filter {{ padding: 5px 8px; border: 1px solid var(--cp-border); border-radius: 6px; background: var(--cp-surface); color: var(--cp-text-muted); cursor: pointer; }}
    .event-kind-filter span, .artifact-state-filter span {{ color: var(--cp-text-soft); }}
    .event-kind-filter:hover, .event-kind-filter.active, .artifact-state-filter:hover, .artifact-state-filter.active {{ border-color: var(--cp-accent); background: var(--cp-accent-soft); color: var(--cp-accent); }}
    .event-status, .artifact-status {{ margin: 8px 0; color: var(--cp-text-muted); font-size: 13px; }}
    .artifact-list {{ border: 1px solid var(--cp-border); }}
    .artifact-row, .artifact-record {{ border-bottom: 1px solid var(--cp-border); background: var(--cp-surface); }}
    .artifact-row:last-child, .artifact-record:last-child {{ border-bottom: 0; }}
    .artifact-row[hidden], .artifact-record[hidden] {{ display: none; }}
    .artifact-row > summary, .artifact-record > summary {{ display: grid; grid-template-columns: 16px minmax(240px, 1fr) 150px 190px; gap: 10px; align-items: center; min-height: 44px; padding: 9px 10px; cursor: pointer; list-style: none; }}
    .artifact-row > summary:hover, .artifact-record > summary:hover {{ background: var(--cp-accent-soft); }}
    .artifact-path {{ overflow-wrap: anywhere; }}
    .artifact-kind {{ color: var(--cp-text-muted); text-transform: capitalize; }}
    .artifact-state {{ font-size: 12px; font-weight: 700; }}
    .artifact-state.landed {{ color: var(--cp-success); }}
    .artifact-state.authored {{ color: var(--cp-warning); }}
    .artifact-state.record {{ color: var(--cp-link); }}
    .artifact-state.transient {{ color: var(--cp-danger); }}
    .artifact-detail {{ border-top: 1px solid var(--cp-border); background: var(--cp-bg-elevated); }}
    .artifact-detail .event-metadata {{ padding: 12px 16px 2px; }}
    .artifact-unavailable {{ margin: 10px 16px 16px; padding: 12px; border-left: 3px solid var(--cp-warning); background: var(--cp-surface-soft); color: var(--cp-text-muted); }}
  .event-list {{ border: 1px solid var(--cp-border); }}
  .event-row {{ border-bottom: 1px solid var(--cp-border); background: var(--cp-surface); }}
  .event-row:last-child {{ border-bottom: 0; }}
  .event-row[hidden] {{ display: none; }}
  .event-row > summary {{ display: grid; grid-template-columns: 16px 72px minmax(170px, 220px) 150px 150px minmax(240px, 1fr); gap: 10px; align-items: start; padding: 9px 10px; cursor: pointer; list-style: none; }}
  .event-row > summary:hover {{ background: var(--cp-accent-soft); }}
  .event-sequence, .event-row time, .event-kind, .event-task {{ font-family: Consolas, "Courier New", Courier, monospace; font-size: 12px; overflow-wrap: anywhere; }}
  .event-sequence, .event-row time, .event-task {{ color: var(--cp-text-muted); }}
  .event-kind {{ color: var(--cp-accent); font-weight: 700; }}
  .event-summary {{ line-height: 1.4; overflow-wrap: anywhere; }}
  .event-detail {{ padding: 12px 16px 16px 108px; border-top: 1px solid var(--cp-border); background: var(--cp-bg-elevated); }}
  .event-metadata {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; margin: 0 0 10px; }}
  .event-metadata div {{ min-width: 0; padding: 8px; border: 1px solid var(--cp-border); background: var(--cp-surface-soft); }}
  .event-metadata dd {{ font-family: Consolas, "Courier New", Courier, monospace; font-size: 12px; }}
  pre {{ margin: 0; padding: 16px; max-height: 70vh; overflow: auto; border-top: 1px solid var(--cp-border); background: var(--cp-surface-soft); color: var(--cp-text); font-size: 12px; line-height: 1.5; white-space: pre-wrap; overflow-wrap: anywhere; }}
  footer {{ margin-top: 32px; padding-top: 16px; border-top: 1px solid var(--cp-border); color: var(--cp-text-muted); }}
  @media (max-width: 760px) {{
    main {{ width: min(100% - 20px, 1180px); padding-top: 20px; }}
    h1 {{ font-size: 36px; }}
    .overview, .metadata {{ grid-template-columns: 1fr; }}
    .run-panel > summary {{ grid-template-columns: 18px 42px minmax(0, 1fr); }}
    .run-panel > summary .badge {{ grid-column: 3; }}
    .event-heading, .event-metadata {{ grid-template-columns: 1fr; }}
    .artifact-row > summary, .artifact-record > summary {{ grid-template-columns: 16px minmax(0, 1fr); }}
    .artifact-kind, .artifact-state {{ grid-column: 2; }}
    .event-row > summary {{ grid-template-columns: 16px 64px minmax(0, 1fr); }}
    .event-row time {{ grid-column: 3; }}
    .event-kind {{ grid-column: 2; }}
    .event-task, .event-summary {{ grid-column: 3; }}
    .event-detail {{ padding-left: 12px; }}
    th, td {{ min-width: 180px; }}
  }}
  </style>
</head>
<body>
  <main>
    <header>
      <p class="eyebrow">M8 management hierarchy and delegation</p>
      <h1>Live qualification</h1>
      <p class="lede">Three real Azure OpenAI gpt-5.2 runs. T1 proves atomic delivery, T2 proves human-gated formation, and T3 records the current parallel-delegation stopping point without hiding the failure.</p>
      <div class="toolbar">
        <button class="command" id="expand-all" type="button">Expand all runs</button>
        <button class="command" id="collapse-all" type="button">Collapse all runs</button>
      </div>
    </header>
    <section class="overview" aria-label="Run outcomes">{cards}
    </section>
    <div class="rollup">
      <span><strong>{passed_runs}/{len(reports)}</strong> runs passed</span>
      <span><strong>{passed_invariants}/{total_invariants}</strong> invariants passed</span>
      <span><strong>gpt-5.2</strong> live provider</span>
    </div>
    <section aria-label="Detailed run reports">{sections}
    </section>
    <footer>Generated from the committed T1-latest.md, T2-latest.md, and T3-latest.md reports. Full source details are embedded in this file.</footer>
  </main>
  <script>
  const runs = [...document.querySelectorAll(".run-panel")];
  document.getElementById("expand-all").addEventListener("click", () => runs.forEach(run => run.open = true));
  document.getElementById("collapse-all").addEventListener("click", () => runs.forEach(run => run.open = false));
  document.querySelectorAll("[data-target]").forEach(card => card.addEventListener("click", () => {{
    const run = document.getElementById(card.dataset.target);
    run.open = true;
    run.scrollIntoView({{ behavior: "smooth", block: "start" }});
  }}));
  document.querySelectorAll(".event-explorer").forEach(explorer => {{
    const rows = [...explorer.querySelectorAll(".event-row")];
    const search = explorer.querySelector(".event-search");
    const status = explorer.querySelector(".event-status");
    const filters = [...explorer.querySelectorAll(".event-kind-filter")];
    let activeKind = "*";
    const apply = () => {{
      const query = search.value.trim().toLowerCase();
      let visible = 0;
      rows.forEach(row => {{
        const matchesKind = activeKind === "*" || row.dataset.kind === activeKind;
        const matchesSearch = !query || row.dataset.search.includes(query);
        row.hidden = !(matchesKind && matchesSearch);
        if (!row.hidden) visible += 1;
      }});
      status.textContent = `${{visible}} of ${{rows.length}} timeline entries`;
    }};
    filters.forEach(filter => filter.addEventListener("click", () => {{
      activeKind = filter.dataset.eventKind;
      filters.forEach(item => item.classList.toggle("active", item === filter));
      apply();
    }}));
    search.addEventListener("input", apply);
  }});
    document.querySelectorAll(".artifact-explorer").forEach(explorer => {{
        const rows = [...explorer.querySelectorAll("[data-artifact-item]")];
        const search = explorer.querySelector(".artifact-search");
        const status = explorer.querySelector(".artifact-status");
        const filters = [...explorer.querySelectorAll(".artifact-state-filter")];
        if (!search || !status) return;
        let activeState = "*";
        const apply = () => {{
            const query = search.value.trim().toLowerCase();
            let visible = 0;
            rows.forEach(row => {{
                const matchesState = activeState === "*" || row.dataset.state === activeState;
                const matchesSearch = !query || row.dataset.search.includes(query);
                row.hidden = !(matchesState && matchesSearch);
                if (!row.hidden) visible += 1;
            }});
            status.textContent = `${{visible}} of ${{rows.length}} artifacts`;
        }};
        filters.forEach(filter => filter.addEventListener("click", () => {{
            activeState = filter.dataset.artifactState;
            filters.forEach(item => item.classList.toggle("active", item === filter));
            apply();
        }}));
        search.addEventListener("input", apply);
    }});
  </script>
</body>
</html>
"""


def _parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports-root", type=Path, default=root / "reports")
    parser.add_argument(
        "--events-root",
        type=Path,
        help="reports root containing the run directories and events.jsonl files",
    )
    parser.add_argument(
        "--output", type=Path, default=root / "reports" / "M8-live-qualification.html"
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    reports: list[RunReport] = []
    events_root = args.events_root or args.reports_root
    for label, relative_path in _REPORT_FILES:
        source_path = (args.reports_root / relative_path).resolve()
        markdown = source_path.read_text(encoding="utf-8")
        run_name = _bold_value(markdown, "Run directory").replace("\\", "/").rsplit("/", 1)[-1]
        events_path = (events_root / relative_path.parent / run_name / "events.jsonl").resolve()
        report = parse_report(
            label,
            source_path,
            events_path=events_path if events_path.is_file() else None,
        )
        if not report.events:
            raise FileNotFoundError(
                f"event stream is missing and no embedded events were found: {events_path}"
            )
        reports.append(report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(tuple(reports)), encoding="utf-8")
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
