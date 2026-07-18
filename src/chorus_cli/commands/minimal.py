"""Minimal-surface verbs — help/quit/assign-task/check + the heartbeat-backed demo loop."""

from __future__ import annotations

from pathlib import Path

from chorus.ids import mint_id
from chorus.ledger import (
    Task,
)
from chorus.lifecycle import (
    assign_task,
)
from chorus.observability import LedgerInspector
from chorus.roles import role_beat_config
from chorus.workspace import default_work_root
from chorus_cli._context import CommandContext, LoopSignal
from chorus_cli.commands._base import REGISTRY
from chorus_cli.commands._shared import (
    _CHECK_LEDGER_LIMIT,
    _employee_base_path,
    _ensure_heartbeat,
    _fmt,
    _latest_task_for_employee,
    _maybe_bootstrap_employee,
    _minimal_file_dod,
    _preview,
    _resolve_employee,
    _roles_from_env,
    _stop_heartbeat,
)

_HELP = "help [command]"


@REGISTRY.command("help", summary="list commands, or show usage for one", usage=_HELP)
def _help(ctx: CommandContext) -> LoopSignal:
    _maybe_bootstrap_employee(ctx)
    _ensure_heartbeat(ctx)
    if ctx.args:
        target = REGISTRY.get(ctx.args[0])
        if target is None:
            ctx.out.error(f"unknown command: {ctx.args[0]!r}")
            return LoopSignal.CONTINUE
        ctx.out.kv({"command": target.name, "usage": target.usage, "summary": target.summary})
        return LoopSignal.CONTINUE
    if ctx.session.minimal_mode:
        minimal = ("assign-task", "check", "help", "quit")
        rows = [
            (name, REGISTRY.get(name).summary)  # type: ignore[union-attr]
            for name in minimal
            if REGISTRY.get(name) is not None
        ]
        ctx.out.table(("command", "summary"), rows)
    else:
        ctx.out.table(
            ("command", "summary"),
            [(command.name, command.summary) for command in REGISTRY.visible(include_hidden=True)],
        )
    return LoopSignal.CONTINUE


_QUIT = "quit"


@REGISTRY.command("quit", summary="leave the console", usage=_QUIT)
def _quit(ctx: CommandContext) -> LoopSignal:
    _stop_heartbeat(ctx)
    return LoopSignal.QUIT


_ASSIGN_TASK = "assign-task <employee_name> <task prompt...>"


@REGISTRY.command(
    "assign-task",
    summary="assign a prompt as a task to an employee (minimal demo path)",
    usage=_ASSIGN_TASK,
)
def _assign_task_minimal(ctx: CommandContext) -> LoopSignal:
    _maybe_bootstrap_employee(ctx)
    _ensure_heartbeat(ctx)
    if len(ctx.args) < 2:
        ctx.out.error(f"usage: {_ASSIGN_TASK}")
        return LoopSignal.CONTINUE
    employee_ref, prompt = ctx.args[0], " ".join(ctx.args[1:])
    try:
        employee_id = _resolve_employee(ctx.session.ledger, employee_ref)
    except ValueError as exc:
        ctx.out.error(str(exc))
        return LoopSignal.CONTINUE
    if employee_id is None:
        ctx.out.error(f"no such employee or role: {employee_ref!r}")
        return LoopSignal.CONTINUE
    task_id = mint_id()
    created = ctx.session.ledger.tasks.submit(Task(id=task_id, intent=prompt))
    dod = _minimal_file_dod(prompt)
    if dod is not None:
        ctx.session.ledger.dod.create(task_id, dod)
    wake = assign_task(ctx.session.ledger, task_id, employee_id)
    if wake is None:
        ctx.out.error("could not queue task")
        return LoopSignal.CONTINUE
    ctx.out.line(f"assigned {created.id} -> {employee_id}; queued {wake.id}; heartbeat running")
    return LoopSignal.CONTINUE


_CHECK = "check memory | check ledger | check org | check scrum <task_id> | check <employee_name>"


@REGISTRY.command(
    "check", summary="inspect memory, ledger, or employee latest-task actions", usage=_CHECK
)
def _check(ctx: CommandContext) -> LoopSignal:
    _maybe_bootstrap_employee(ctx)
    _ensure_heartbeat(ctx)
    if not 1 <= len(ctx.args) <= 2:
        ctx.out.error(f"usage: {_CHECK}")
        return LoopSignal.CONTINUE
    target = ctx.args[0]
    ledger = ctx.session.ledger
    if target == "scrum":
        if len(ctx.args) != 2:
            ctx.out.error(f"usage: {_CHECK}")
            return LoopSignal.CONTINUE
        try:
            packet = LedgerInspector(ledger).scrum_packet(ctx.args[1])
        except KeyError:
            ctx.out.error(f"no such task: {ctx.args[1]!r}")
            return LoopSignal.CONTINUE
        ctx.out.kv(
            {
                "parent_task": packet.parent_task_id,
                "manager": _fmt(packet.manager_id),
                "children": packet.child_count,
                "completed_children": packet.completed_children,
                "completion_rate": f"{packet.completion_rate:.0%}",
                "dependency_edges": packet.dependency_edges,
                "assignments": packet.assignment_count,
                "reassignments": packet.reassignments,
            }
        )
        ctx.out.table(
            ("label", "task", "assignee", "status", "blockers", "dod", "run", "artifact"),
            [
                (
                    child.label,
                    child.task_id,
                    _fmt(child.assignee),
                    child.status,
                    ",".join(child.blockers) if child.blockers else "-",
                    _fmt(child.dod_status),
                    _fmt(child.latest_run_status),
                    _fmt(child.artifact_type),
                )
                for child in packet.children
            ],
        )
        return LoopSignal.CONTINUE
    if len(ctx.args) != 1:
        ctx.out.error(f"usage: {_CHECK}")
        return LoopSignal.CONTINUE
    if target == "memory":
        employees = ledger.employees.list()
        if not employees:
            ctx.out.line("no employees")
            return LoopSignal.CONTINUE
        company_root = default_work_root() / ctx.session.company_id
        ctx.out.kv(
            {
                "company_root": str(company_root),
                "company_repo": str(company_root / "repo"),
                "launched_from": str(Path.cwd()),
            }
        )
        rows = []
        for e in employees:
            base = _employee_base_path(ctx.session.company_id, e.id)
            rows.append((e.id, e.role, str(base), "yes" if base.exists() else "no"))
        ctx.out.table(("employee", "role", "base_path", "exists"), rows)
        return LoopSignal.CONTINUE
    if target == "ledger":
        tasks = ledger.tasks.list_eligible(limit=_CHECK_LEDGER_LIMIT)
        wakes = ledger.wakes.queued()
        running = ledger.runs.running_employee_ids()
        ctx.out.kv(
            {
                "employees": len(ledger.employees.list()),
                "eligible_tasks": len(tasks),
                "queued_wakes": len(wakes),
                "running_employees": len(running),
            }
        )
        recent = ledger.activity.recent(limit=_CHECK_LEDGER_LIMIT)
        if recent:
            ctx.out.table(
                ("at", "verb", "subject", "id"),
                [(str(a.occurred_at), a.verb.value, a.subject_kind, a.subject_id) for a in recent],
            )
        return LoopSignal.CONTINUE
    if target == "org":
        report = LedgerInspector(ledger).org_report()
        ctx.out.kv(
            {
                "employees": report.employees,
                "managers": report.managers,
                "leaves": report.leaves,
                "tasks_total": report.tasks_total,
                "tasks_done": report.tasks_done,
                "tasks_blocked": report.tasks_blocked,
                "completion_rate": f"{report.completion_rate:.0%}",
                "running_beats": report.running_beats,
                "failed_runs": report.failed_runs,
                "decomposition_count": report.decomposition_count,
                "assignment_count": report.assignment_count,
                "reassignment_count": report.reassignment_count,
                "dependency_edges": report.dependency_edges,
            }
        )
        if report.manager_packets:
            ctx.out.table(
                ("manager", "parent_task", "children", "completion", "deps", "reassignments"),
                [
                    (
                        _fmt(packet.manager_id),
                        packet.parent_task_id,
                        packet.child_count,
                        f"{packet.completion_rate:.0%}",
                        packet.dependency_edges,
                        packet.reassignments,
                    )
                    for packet in report.manager_packets
                ],
            )
        return LoopSignal.CONTINUE

    try:
        employee_id = _resolve_employee(ledger, target)
    except ValueError as exc:
        ctx.out.error(str(exc))
        return LoopSignal.CONTINUE
    if employee_id is None:
        ctx.out.error(f"no such employee or role: {target!r}")
        return LoopSignal.CONTINUE
    employee = ledger.employees.get(employee_id)
    if employee is None:
        ctx.out.error(f"no such employee: {employee_id!r}")
        return LoopSignal.CONTINUE
    profile = None
    roles = _roles_from_env()
    if employee.role in roles:
        profile = role_beat_config(roles.get(employee.role).manifest)
    task = _latest_task_for_employee(ledger, employee_id)
    if task is None:
        ctx.out.kv(
            {
                "employee": employee_id,
                "role": employee.role,
                "base_path": str(_employee_base_path(ctx.session.company_id, employee_id)),
                "tools": ", ".join(profile.tools) if profile is not None else "-",
                "skills": ", ".join(profile.skills) if profile is not None else "-",
                "mcp": "on" if (profile is not None and profile.mcp) else "off",
                "permission": profile.permission_mode if profile is not None else "-",
                "memory": profile.memory_scope if profile is not None else "-",
                "isolation": profile.isolation if profile is not None else "-",
            }
        )
        ctx.out.line(f"{employee_id}: no task yet")
        return LoopSignal.CONTINUE
    runs = ledger.runs.for_task(task.id)
    run = runs[-1] if runs else None
    ctx.out.kv(
        {
            "employee": employee_id,
            "role": employee.role,
            "base_path": str(_employee_base_path(ctx.session.company_id, employee_id)),
            "tools": ", ".join(profile.tools) if profile is not None else "-",
            "skills": ", ".join(profile.skills) if profile is not None else "-",
            "mcp": "on" if (profile is not None and profile.mcp) else "off",
            "permission": profile.permission_mode if profile is not None else "-",
            "memory": profile.memory_scope if profile is not None else "-",
            "isolation": profile.isolation if profile is not None else "-",
            "task": task.id,
            "intent": _preview(task.intent),
            "task_status": task.status.value,
            "run": run.id if run is not None else "-",
            "run_status": run.status.value if run is not None else "-",
        }
    )
    subject_activity = ledger.activity.by_subject("task", task.id)
    if subject_activity:
        ctx.out.table(
            ("at", "verb", "actor", "payload"),
            [
                (
                    str(a.occurred_at),
                    a.verb.value,
                    _fmt(a.actor_employee_id or a.actor_user_id),
                    _preview(str(dict(a.payload))),
                )
                for a in subject_activity[-_CHECK_LEDGER_LIMIT:]
            ],
        )
    return LoopSignal.CONTINUE


# -- workforce --------------------------------------------------------------------------------------
