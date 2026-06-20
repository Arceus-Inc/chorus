"""Tools & event-stream view — what the workforce actually *did*, witnessed not guessed (spec 08 §2).

Replays ``events.jsonl`` — dream's structured ``run.*`` stream bridged verbatim into chorus — and rolls
up the ``run.tool_use`` events into a tool-call histogram (overall and per role), alongside the full
event-kind taxonomy for the run. chorus never parses prose to learn a tool call; this reads the typed
events the engine emitted.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from chorus.events import Event, EventKind
from chorus.observability import EventBus
from experiments.insights import _render as r
from experiments.insights._sources import ExperimentSources

# dream stamps the tool name under one of these payload keys depending on version — try them in order.
_TOOL_NAME_KEYS = ("tool", "name", "tool_name")


def render(sources: ExperimentSources) -> str:
    """The event-kind histogram + the tool-call rollup (overall and by role)."""
    if sources.events_path is None:
        return r.header("TOOLS & EVENTS") + "\n  (no events.jsonl found next to the ledger)"

    events = list(EventBus(log_path=sources.events_path).replay())
    if not events:
        return r.header("TOOLS & EVENTS") + f"\n  (empty event log at {sources.events_path})"

    roles = _task_roles(sources)
    kinds: Counter[str] = Counter()
    tools: Counter[str] = Counter()
    tools_by_role: Counter[tuple[str, str]] = Counter()
    for event in events:
        kinds[event.kind.value] += 1
        if event.kind is EventKind.RUN_TOOL_USE:
            name = _tool_name(event.payload)
            tools[name] += 1
            tools_by_role[(roles.get(event.task_id or "", "—"), name)] += 1

    span = _span(events)
    sections = [
        r.header("TOOLS & EVENTS"),
        r.kv("events", f"{len(events)}  ·  {span}"),
        "",
        r.paint("  event stream", "bold"),
        _histogram(kinds, colorizer=r.status),
    ]
    if tools:
        sections += [
            "",
            r.paint(f"  tool calls ({sum(tools.values())})", "bold"),
            _histogram(tools),
            "",
            _by_role_table(tools_by_role),
        ]
    else:
        sections += ["", "  (no run.tool_use events recorded)"]
    return "\n".join(sections)


def _histogram(counts: Counter[str], *, colorizer: Any = None) -> str:
    """A right-padded ``label  ▏bar▕  n`` block, ordered by count."""
    if not counts:
        return "    (none)"
    total = max(counts.values())
    label_width = max(len(name) for name in counts)
    lines = []
    for name, count in counts.most_common():
        shown = colorizer(name) if colorizer else name
        pad = " " * (label_width - len(name))
        lines.append(f"    {shown}{pad}  {r.bar(count, total)}  {count}")
    return "\n".join(lines)


def _by_role_table(tools_by_role: Counter[tuple[str, str]]) -> str:
    rows = [
        (role, tool, str(count))
        for (role, tool), count in sorted(tools_by_role.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    return r.table(("role", "tool", "calls"), rows)


def _task_roles(sources: ExperimentSources) -> dict[str, str]:
    """Map ``task_id -> assignee role`` so tool calls (tagged by task) attribute to a role."""
    roles = {e.id: e.role for e in sources.ledger.employees.list()}
    return {
        task.id: roles.get(task.assignee_employee_id or "", "—")
        for task in sources.ledger.tasks.all()
    }


def _tool_name(payload: Any) -> str:
    if isinstance(payload, dict):
        for key in _TOOL_NAME_KEYS:
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
    return "unknown"


def _span(events: list[Event]) -> str:
    first, last = events[0].at, events[-1].at
    seconds = (last - first).total_seconds()
    if seconds < 90:
        return f"{seconds:.0f}s span"
    return f"{seconds / 60:.1f}m span"


__all__ = ["render"]
