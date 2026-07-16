"""Workforce verbs — hire/terminate/pause/resume/workforce/employee/export/import/company."""

from __future__ import annotations

import json
import os
from pathlib import Path

from chorus.errors import ChorusError, OrgInvariantViolation, UnknownEmployee
from chorus.governance import ManagementAuthorityService
from chorus.ledger import ManagementProfile
from chorus.workforce import EmployeeStatus, GitWorkforce, LedgerWorkforce, copy_org
from chorus.workspace import CompanyWorkspace, WorkspaceError, default_work_root
from chorus_cli._context import CommandContext, LoopSignal
from chorus_cli.commands._base import REGISTRY
from chorus_cli.commands._shared import (
    _OPERATOR,
    _fmt,
    _roles_from_env,
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


_SPECIALIZE_MANAGER = (
    "workforce specialize-manager <employee_id> --profession <role> --profile <policy>"
)
_WORKFORCE = "workforce [specialize-manager <employee_id> --profession <role> --profile <policy>]"


def _management_profile(employee_id: str, raw_policy: str) -> ManagementProfile:
    policy_path = Path(raw_policy)
    raw = policy_path.read_text(encoding="utf-8") if policy_path.is_file() else raw_policy
    decoded = json.loads(raw)
    if not isinstance(decoded, dict):
        raise ValueError("management policy must be a JSON object")
    allowed_keys = {
        "active",
        "can_lead",
        "can_subdelegate",
        "max_delegation_depth",
        "max_team_size",
        "allowed_professions",
        "spend_limit_cents",
    }
    unknown = sorted(set(decoded) - allowed_keys)
    if unknown:
        raise ValueError(f"unknown management policy fields: {', '.join(unknown)}")

    def policy_bool(key: str, default: bool) -> bool:
        value = decoded.get(key, default)
        if not isinstance(value, bool):
            raise ValueError(f"management policy field {key!r} must be a boolean")
        return value

    def policy_int(key: str, default: int) -> int:
        value = decoded.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"management policy field {key!r} must be an integer")
        return value

    professions = decoded.get("allowed_professions", [])
    if not isinstance(professions, list) or not all(
        isinstance(item, str) for item in professions
    ):
        raise ValueError("management policy field 'allowed_professions' must be a string list")
    spend_limit = decoded.get("spend_limit_cents")
    if spend_limit is not None and (
        isinstance(spend_limit, bool) or not isinstance(spend_limit, int)
    ):
        raise ValueError("management policy field 'spend_limit_cents' must be an integer or null")
    return ManagementProfile(
        employee_id=employee_id,
        granted_by_user_id=_OPERATOR,
        active=policy_bool("active", False),
        can_lead=policy_bool("can_lead", False),
        can_subdelegate=policy_bool("can_subdelegate", False),
        max_delegation_depth=policy_int("max_delegation_depth", 0),
        max_team_size=policy_int("max_team_size", 1),
        allowed_professions=tuple(professions),
        spend_limit_cents=spend_limit,
    )


def _specialize_manager(ctx: CommandContext, args: tuple[str, ...]) -> LoopSignal:
    if len(args) != 5 or args[1] != "--profession" or args[3] != "--profile":
        ctx.out.error(f"usage: {_SPECIALIZE_MANAGER}")
        return LoopSignal.CONTINUE
    employee_id, profession, raw_policy = args[0], args[2], args[4]
    try:
        profile = _management_profile(employee_id, raw_policy)
        ManagementAuthorityService(ctx.session.ledger).specialize_manager(
            employee_id,
            profession=profession,
            profile=profile,
            roles=_roles_from_env(),
            actor_user_id=_OPERATOR,
        )
    except (ChorusError, OSError, ValueError) as exc:
        ctx.out.error(f"manager specialization failed: {exc}")
        return LoopSignal.CONTINUE
    ctx.out.line(f"specialized {employee_id} as {profession} with management profile v1")
    return LoopSignal.CONTINUE


@REGISTRY.command(
    "workforce", summary="list the org (every employee + status)", usage=_WORKFORCE, hidden=True
)
def _workforce(ctx: CommandContext) -> LoopSignal:
    if ctx.args:
        if ctx.args[0] == "specialize-manager":
            return _specialize_manager(ctx, ctx.args[1:])
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
