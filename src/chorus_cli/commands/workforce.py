"""Workforce verbs — hire/terminate/pause/resume/workforce/employee/export/import/company."""

from __future__ import annotations

import os

from chorus.errors import OrgInvariantViolation, UnknownEmployee
from chorus.workforce import EmployeeStatus, GitWorkforce, LedgerWorkforce, copy_org
from chorus.workspace import CompanyWorkspace, WorkspaceError, default_work_root
from chorus_cli._context import CommandContext, LoopSignal
from chorus_cli.commands._base import REGISTRY
from chorus_cli.commands._shared import (
    _fmt,
)

_HIRE = "hire <name> <role> [reports_to]"


@REGISTRY.command("hire", summary="add an employee to the workforce", usage=_HIRE, hidden=True)
def _hire(ctx: CommandContext) -> LoopSignal:
    if not 2 <= len(ctx.args) <= 3:
        ctx.out.error(f"usage: {_HIRE}")
        return LoopSignal.CONTINUE
    name, role = ctx.args[0], ctx.args[1]
    reports_to = ctx.args[2] if len(ctx.args) == 3 else None
    workforce = LedgerWorkforce(ctx.session.ledger.employees)
    try:
        created = workforce.hire(name=name, role=role, reports_to=reports_to)
    except (OrgInvariantViolation, UnknownEmployee) as exc:
        ctx.out.error(str(exc))
        return LoopSignal.CONTINUE
    ctx.out.line(f"hired {created.id} ({created.role}) -- status {created.status.value}")
    return LoopSignal.CONTINUE


_TERMINATE = "terminate <id>"


@REGISTRY.command(
    "terminate", summary="irreversibly terminate an employee", usage=_TERMINATE, hidden=True
)
def _terminate(ctx: CommandContext) -> LoopSignal:
    if len(ctx.args) != 1:
        ctx.out.error(f"usage: {_TERMINATE}")
        return LoopSignal.CONTINUE
    employee_id = ctx.args[0]
    ledger = ctx.session.ledger
    try:
        LedgerWorkforce(ledger.employees).terminate(employee_id)
    except (OrgInvariantViolation, UnknownEmployee) as exc:
        ctx.out.error(str(exc))
        return LoopSignal.CONTINUE
    ledger.runs.cancel_running(employee_id=employee_id)
    ledger.wakes.drop_queued(employee_id=employee_id)
    ctx.out.line(f"terminated {employee_id} -- cancelled its runs + dropped queued wakes")
    return LoopSignal.CONTINUE


_PAUSE = "pause <id>"


@REGISTRY.command(
    "pause", summary="pause an employee (the gate holds its wakes)", usage=_PAUSE, hidden=True
)
def _pause(ctx: CommandContext) -> LoopSignal:
    if len(ctx.args) != 1:
        ctx.out.error(f"usage: {_PAUSE}")
        return LoopSignal.CONTINUE
    employee_id = ctx.args[0]
    employees = ctx.session.ledger.employees
    if employees.get(employee_id) is None:
        ctx.out.error(f"no such employee: {employee_id!r}")
        return LoopSignal.CONTINUE
    employees.set_status(employee_id, EmployeeStatus.PAUSED)
    ctx.out.line(f"paused {employee_id}")
    return LoopSignal.CONTINUE


_RESUME = "resume <id>"


@REGISTRY.command("resume", summary="resume a paused employee", usage=_RESUME, hidden=True)
def _resume(ctx: CommandContext) -> LoopSignal:
    if len(ctx.args) != 1:
        ctx.out.error(f"usage: {_RESUME}")
        return LoopSignal.CONTINUE
    employee_id = ctx.args[0]
    employees = ctx.session.ledger.employees
    employee = employees.get(employee_id)
    if employee is None:
        ctx.out.error(f"no such employee: {employee_id!r}")
        return LoopSignal.CONTINUE
    if employee.status is EmployeeStatus.TERMINATED:
        ctx.out.error(f"{employee_id!r} is terminated -- termination is irreversible")
        return LoopSignal.CONTINUE
    employees.set_status(employee_id, EmployeeStatus.IDLE)
    ctx.out.line(f"resumed {employee_id} -- status idle")
    return LoopSignal.CONTINUE


_WORKFORCE = "workforce"


@REGISTRY.command(
    "workforce", summary="list the org (every employee + status)", usage=_WORKFORCE, hidden=True
)
def _workforce(ctx: CommandContext) -> LoopSignal:
    if ctx.args:
        ctx.out.error(f"usage: {_WORKFORCE}")
        return LoopSignal.CONTINUE
    employees = ctx.session.ledger.employees.list()
    ctx.out.table(
        ("id", "name", "role", "reports_to", "status"),
        [(e.id, e.name, e.role, _fmt(e.reports_to), e.status.value) for e in employees],
    )
    return LoopSignal.CONTINUE


_EMPLOYEE = "employee <id>"


@REGISTRY.command("employee", summary="show one employee", usage=_EMPLOYEE, hidden=True)
def _employee(ctx: CommandContext) -> LoopSignal:
    if len(ctx.args) != 1:
        ctx.out.error(f"usage: {_EMPLOYEE}")
        return LoopSignal.CONTINUE
    employee = ctx.session.ledger.employees.get(ctx.args[0])
    if employee is None:
        ctx.out.error(f"no such employee: {ctx.args[0]!r}")
        return LoopSignal.CONTINUE
    ctx.out.kv(
        {
            "id": employee.id,
            "name": employee.name,
            "role": employee.role,
            "reports_to": _fmt(employee.reports_to),
            "status": employee.status.value,
            "spent_cents": employee.spent_monthly_cents,
        }
    )
    return LoopSignal.CONTINUE


_EXPORT = "export <dir>"


@REGISTRY.command(
    "export", summary="serialize the org to a git-markdown tree", usage=_EXPORT, hidden=True
)
def _export(ctx: CommandContext) -> LoopSignal:
    if len(ctx.args) != 1:
        ctx.out.error(f"usage: {_EXPORT}")
        return LoopSignal.CONTINUE
    org_repo = ctx.args[0]
    live = LedgerWorkforce(ctx.session.ledger.employees)
    count = copy_org(live, GitWorkforce(org_repo))
    ctx.out.line(f"exported {count} employees to {org_repo}/employees/")
    return LoopSignal.CONTINUE


_IMPORT = "import <dir>"


@REGISTRY.command(
    "import", summary="materialize a git-markdown org into the ledger", usage=_IMPORT, hidden=True
)
def _import(ctx: CommandContext) -> LoopSignal:
    if len(ctx.args) != 1:
        ctx.out.error(f"usage: {_IMPORT}")
        return LoopSignal.CONTINUE
    org_repo = ctx.args[0]
    live = LedgerWorkforce(ctx.session.ledger.employees)
    try:
        count = copy_org(GitWorkforce(org_repo), live)
    except (OrgInvariantViolation, UnknownEmployee) as exc:
        ctx.out.error(f"import failed: {exc}")
        return LoopSignal.CONTINUE
    ctx.out.line(f"imported {count} employees from {org_repo}")
    return LoopSignal.CONTINUE


# -- company workspace ------------------------------------------------------------------------------

_COMPANY = "company [init [seed]]"


@REGISTRY.command(
    "company",
    summary="show or create the company workspace (the shared git root)",
    usage=_COMPANY,
    hidden=True,
)
def _company(ctx: CommandContext) -> LoopSignal:
    """Show or create ``.chorus/work/{company}/repo`` — the ``main`` employees' worktrees branch from.

    ``company`` shows the workspace status; ``company init [seed]`` creates it (idempotent). ``tick`` /
    ``chat`` create it lazily anyway, but this makes it explicit and lets you seed from a real repo up
    front. ``seed`` is a git repo path, a clone URL, or a plain directory; it falls back to
    ``CHORUS_COMPANY_SEED`` when omitted, matching what ``tick`` / ``chat`` read.
    """
    company_id = ctx.session.company_id
    root = default_work_root() / company_id
    sub = ctx.args[0] if ctx.args else "show"
    if sub == "show":
        repo = root / "repo"
        ctx.out.kv(
            {
                "company": company_id,
                "root": str(root),
                "created": "yes" if (repo / ".git").exists() else "no",
            }
        )
        return LoopSignal.CONTINUE
    if sub == "init":
        seed = ctx.args[1] if len(ctx.args) > 1 else (os.environ.get("CHORUS_COMPANY_SEED") or None)
        try:
            repo = CompanyWorkspace(root, seed=seed).ensure_repo()
        except WorkspaceError as exc:
            ctx.out.error(f"company init failed: {exc}")
            return LoopSignal.CONTINUE
        seeded = f", seeded from {seed}" if seed else ""
        ctx.out.line(f"company {company_id!r} ready at {repo} (branch main{seeded})")
        return LoopSignal.CONTINUE
    ctx.out.error(f"usage: {_COMPANY}")
    return LoopSignal.CONTINUE


# -- tasks ------------------------------------------------------------------------------------------
