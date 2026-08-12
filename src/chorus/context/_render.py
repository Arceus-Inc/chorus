"""Audience-safe deterministic rendering for a :class:`TaskContextPacket`."""

from __future__ import annotations

from enum import StrEnum

from chorus.context._packet import TaskContextPacket


class ContextAudience(StrEnum):
    PLANNER = "planner"
    GENERATOR = "generator"
    EVALUATOR = "evaluator"


def render_task_context(packet: TaskContextPacket, audience: ContextAudience) -> str:
    """Render only the facts this Dream role may use."""
    sections = [_contract(packet)]
    if audience is not ContextAudience.EVALUATOR:
        sections.append(_ancestry(packet))
        sections.append(_prior_beats(packet))
        sections.append(_sibling_failures(packet))
        sections.append(_reports(packet))
    if audience is ContextAudience.GENERATOR:
        sections.append(_inbox(packet))
        sections.append(_budget(packet))
        sections.append(_runtime(packet))
        sections.append(_lattice_wake(packet))
    sections.append(_citations(packet, audience))
    visible = [section for section in sections if section]
    return "\n\n".join(("## Task context", *visible))


def _contract(packet: TaskContextPacket) -> str:
    lines = ["### Contract", packet.contract.intent]
    if not packet.contract.dod:
        lines.extend(("", "Definition of done: none recorded."))
    else:
        lines.append("")
        lines.extend(
            f"Definition of done ({requirement.kind}): {requirement.detail}"
            for requirement in packet.contract.dod
        )
    lines.extend(
        (
            "",
            "Stay inside this assigned task. Ancestry supplies intent, never permission to widen scope.",
        )
    )
    return "\n".join(lines)


def _ancestry(packet: TaskContextPacket) -> str:
    if not packet.ancestry:
        return ""
    lines = ["### Goal and task ancestry"]
    lines.extend(
        f"- {link.kind.value} `{link.id}` — {link.title} ({link.status})" for link in packet.ancestry
    )
    return "\n".join(lines)


def _prior_beats(packet: TaskContextPacket) -> str:
    if not packet.prior_beats:
        return "### Same-task carryover\nNo prior landed beat is recorded."
    lines = ["### Same-task carryover"]
    for beat in packet.prior_beats:
        lines.append(f"- `{beat.run_id}`: {beat.phase.value}; next: {beat.recovery_hint.value}")
        lines.extend(f"  - evaluator: {note}" for note in beat.evaluator_notes)
        if beat.files_touched:
            lines.append("  - files: " + ", ".join(f"`{path}`" for path in beat.files_touched))
        if beat.todo_digest:
            lines.append(f"  - TODO: {beat.todo_digest}")
        if beat.summary:
            lines.append(f"  - summary: {beat.summary}")
    return "\n".join(lines)


def _sibling_failures(packet: TaskContextPacket) -> str:
    if not packet.sibling_failures:
        return ""
    lines = ["### Corrective sibling findings", "Fix these findings before repeating the scope."]
    for failure in packet.sibling_failures:
        lines.append(f"- `{failure.task_id}` ({failure.status})")
        lines.extend(f"  - evaluator: {note}" for note in failure.notes)
    return "\n".join(lines)


def _reports(packet: TaskContextPacket) -> str:
    if not packet.reports:
        return ""
    lines = [
        "### Reports",
        "Assign each subtask's `assignee` to one of these employee ids:",
    ]
    for report in packet.reports:
        lead = ", lead" if report.can_lead else ""
        lines.append(f"- {report.employee_id} ({report.role}{lead})")
    return "\n".join(lines)


def _inbox(packet: TaskContextPacket) -> str:
    if not packet.inbox:
        return ""
    lines = ["### Inbox"]
    lines.extend(
        f"- from {item.sender}" + (f" on `{item.task_id}`" if item.task_id else "") + f": {item.body}"
        for item in packet.inbox
    )
    return "\n".join(lines)


def _budget(packet: TaskContextPacket) -> str:
    budget = packet.budget
    if budget.limit_cents is None:
        limit = "no recorded limit"
    else:
        limit = f"{max(0, budget.limit_cents - budget.spent_cents)} cents remaining of {budget.limit_cents}"
    return f"### Budget\nBeat {budget.beat_count + 1}; {budget.spent_cents} cents spent; {limit}."


def _runtime(packet: TaskContextPacket) -> str:
    runtime = packet.runtime
    if runtime is None:
        return ""
    runtime_lines = "\n".join(f"- {line}" for line in runtime.path_runtimes)
    return (
        "### Operating environment\n"
        f"You are running on {runtime.os_label}. Commands you pass to `run_command` "
        f"execute through `{runtime.shell}` — write them in that shell's syntax (POSIX `sh` on "
        "Linux/macOS, `cmd.exe` on Windows), or invoke a cross-platform runtime "
        "(prefer `node`/`npx`/`python`) so the same command works everywhere. Runtimes on PATH:\n"
        f"{runtime_lines}\n"
        "Your Definition of Done is verified with a platform-agnostic Python check, so it evaluates "
        "identically on every OS — you do not need to author OS-specific verification yourself."
    )


def _lattice_wake(packet: TaskContextPacket) -> str:
    wake = packet.lattice_wake
    if wake is None or not wake.gate_open or not wake.teaser.strip():
        return ""
    return (
        "### Lattice wake\n"
        f"{wake.teaser.strip()}\n"
        "Load skill `lattice-consolidate` before other task work."
    )


def _citations(packet: TaskContextPacket, audience: ContextAudience) -> str:
    visible = {f"ledger.task:{packet.task_id}"}
    if audience is not ContextAudience.EVALUATOR:
        visible.update(beat.citation.source for beat in packet.prior_beats)
        visible.update(failure.citation.source for failure in packet.sibling_failures)
    if audience is ContextAudience.GENERATOR:
        visible.update(
            citation.source
            for citation in packet.citations
            if citation.detail == "recipient and budget scope"
        )
    lines = ["### Sources"]
    lines.extend(
        f"- `{citation.source}` — {citation.detail}"
        for citation in packet.citations
        if citation.source in visible
    )
    lines.extend(
        f"- context truncated: {item.section}, {item.omitted} omitted ({item.reason})"
        for item in packet.truncation
        if audience is not ContextAudience.EVALUATOR or item.section == "contract"
    )
    return "\n".join(lines)


__all__ = ["ContextAudience", "render_task_context"]
