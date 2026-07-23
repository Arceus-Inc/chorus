"""T2 formation live run: CEO proposal, explicit human approval, no delivery work.

The CEO is a real employee materialized through EmployeeHarnessFactory. Its ledger-bound
``workforce_catalog_read`` and ``workforce_plan_propose`` tools create a typed, audited proposal but
cannot hire. The runner snapshots that pending state, independently checks the proposed org, and only
then applies it through the human-only WorkforcePlanService approval API.

Each isolated run retains the ledger, lossless event stream, Dream traces, console log, machine
summary, and a chronological Markdown report. No delivery task or scheduler is created.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
from dataclasses import asdict, dataclass, is_dataclass, replace
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from uuid import uuid4

from chorus.events import Event, EventKind
from chorus.governance import WorkforcePlanService
from chorus.ledger import ActivityVerb, Ledger, WorkforcePlan, WorkforcePlanStatus
from chorus.outcomes import AgentReview
from chorus.roles import RoleRegistry, default_roles
from chorus.workforce import Employee, LedgerWorkforce
from chorus_employee.ceo import ceo_plugin
from chorus_harness import EmployeeHarnessFactory

_CEO_ID = "ceo"
_FOUNDER_GOAL_ID = "founder-linkport"
_BUDGET_CEILING_CENTS = 700_000
_INTENT = (
    "Form the permanent engineering organization for the approved founder objective in "
    "`founder-intent.md`: build Linkport, a URL shortener with click analytics and a web dashboard. "
    "This is formation only; do not create or execute delivery tasks. First inspect the approved "
    "intent and call `workforce_catalog_read`. Then submit exactly one complete typed proposal through "
    "`workforce_plan_propose` using source goal id `founder-linkport`. The approved staffing envelope "
    "is exact: one engineering lead using the `backend_engineer` profession reports to `ceo`; three "
    "additional backend-engineer ICs and three frontend-engineer ICs report to that lead; no other "
    "hires. Grant lead authority separately to the CEO and engineering lead. The CEO may lead and "
    "subdelegate through depth 2; the engineering lead may lead through depth 1 and must have team "
    "capacity for itself plus all six ICs. Restrict each grant to the professions of its direct "
    "reports. Keep all employee budget allocations and each management spend limit at or below "
    f"{_BUDGET_CEILING_CENTS} cents. The proposal must remain pending for a human; never claim the "
    "employees were hired. Finally write `directive.md` with the proposed plan id, reporting tree, "
    "three outcome areas, budget guardrail, and the explicit founder-approval requirement."
)
_FOUNDER_INTENT = """# Founder-approved objective and formation envelope

## Objective
Build Linkport: a URL shortener with click analytics and a web dashboard.

## Outcome tree
- KR-A: links backend - base62 codes, durable store, collision safety, and TTL.
- KR-B: analytics backend - idempotent click ingestion and aggregate statistics.
- KR-C: web UI - create form, links dashboard, and per-link analytics.

## Formation envelope
- Exactly one engineering lead, three backend ICs, and three frontend ICs.
- The engineering lead reports to the CEO; all six ICs report to the engineering lead.
- Management is a separate bounded grant. Team-size limits include the lead itself.
- Maximum organization depth below the CEO: two.
- Employee budget allocations and each management spend limit: at most 700000 cents.
- This document approves only a proposal envelope. Nobody is hired until the founder explicitly
  approves the persisted workforce plan.
"""


@dataclass(frozen=True)
class Invariant:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class EmployeeView:
    id: str
    role: str
    reports_to: str | None


@dataclass(frozen=True)
class ManagementView:
    employee_id: str
    can_lead: bool
    max_delegation_depth: int
    max_team_size: int
    spend_limit_cents: int | None


@dataclass(frozen=True)
class T2Snapshot:
    ceo_outcome_passed: bool
    plan_status_before: str
    plan_status_after: str
    proposed_by_employee_id: str
    decided_by_user_id: str
    employees_before: tuple[EmployeeView, ...]
    profiles_before: tuple[ManagementView, ...]
    employees_after: tuple[EmployeeView, ...]
    profiles_after: tuple[ManagementView, ...]
    proposal_audit_actor: str
    approval_audit_actor: str
    employee_budget_allocations_cents: tuple[int, ...]
    budget_ceiling_cents: int
    task_count: int
    run_count: int
    tool_names: tuple[str, ...]
    tool_use_count: int
    tool_result_count: int
    all_tool_results_lossless: bool
    event_count: int
    trace_count: int
    secret_redaction_safe: bool


def _shape(snapshot: T2Snapshot) -> tuple[bool, str]:
    employees = {employee.id: employee for employee in snapshot.employees_after}
    leads = {profile.employee_id for profile in snapshot.profiles_after if profile.can_lead}
    candidates = [
        employee
        for employee in snapshot.employees_after
        if employee.id != _CEO_ID
        and employee.role == "backend_engineer"
        and employee.reports_to == _CEO_ID
        and employee.id in leads
    ]
    lead_id = candidates[0].id if len(candidates) == 1 else ""
    backend_ics = [
        employee
        for employee in snapshot.employees_after
        if employee.role == "backend_engineer" and employee.id not in {_CEO_ID, lead_id}
    ]
    frontend_ics = [
        employee for employee in snapshot.employees_after if employee.role == "frontend_engineer"
    ]
    expected_ids = {_CEO_ID, lead_id} | {employee.id for employee in backend_ics + frontend_ics}
    valid = (
        len(candidates) == 1
        and len(backend_ics) == 3
        and len(frontend_ics) == 3
        and len(employees) == 8
        and expected_ids == set(employees)
        and all(employee.reports_to == lead_id for employee in backend_ics + frontend_ics)
    )
    return (
        valid,
        f"engineering leads={tuple(employee.id for employee in candidates)}, "
        f"backend ICs={len(backend_ics)}, frontend ICs={len(frontend_ics)}, "
        f"employees={len(employees)}",
    )


def _authority(snapshot: T2Snapshot) -> tuple[bool, str]:
    managers = {profile.employee_id for profile in snapshot.profiles_after if profile.can_lead}
    violations = tuple(
        f"{employee.id}->{employee.reports_to}"
        for employee in snapshot.employees_after
        if employee.id != _CEO_ID and employee.reports_to not in managers
    )
    root = next(
        (employee for employee in snapshot.employees_after if employee.id == _CEO_ID),
        None,
    )
    valid = root is not None and root.reports_to is None and not violations
    return valid, f"active lead managers={tuple(sorted(managers))}, violations={violations}"


def _depth(snapshot: T2Snapshot) -> tuple[bool, str]:
    employees = {employee.id: employee for employee in snapshot.employees_after}
    depths: dict[str, int] = {}
    violations: list[str] = []

    def visit(employee_id: str, visiting: set[str]) -> int:
        if employee_id in depths:
            return depths[employee_id]
        if employee_id in visiting:
            raise ValueError("cycle")
        employee = employees.get(employee_id)
        if employee is None:
            raise ValueError("unknown employee")
        if employee.reports_to is None:
            depth = 0
        else:
            depth = visit(employee.reports_to, visiting | {employee_id}) + 1
        depths[employee_id] = depth
        return depth

    for employee_id in employees:
        try:
            visit(employee_id, set())
        except ValueError as exc:
            violations.append(f"{employee_id}: {exc}")
    maximum = max(depths.values(), default=0)
    return (
        not violations and maximum <= 2,
        f"maximum depth={maximum}, violations={tuple(violations)}",
    )


def _team_sizes(snapshot: T2Snapshot) -> tuple[bool, str]:
    reports: dict[str, int] = {}
    for employee in snapshot.employees_after:
        if employee.reports_to is not None:
            reports[employee.reports_to] = reports.get(employee.reports_to, 0) + 1
    profiles = {profile.employee_id: profile for profile in snapshot.profiles_after}
    violations = tuple(
        f"{manager}: required={1 + count}, granted="
        f"{profiles[manager].max_team_size if manager in profiles else 'missing'}"
        for manager, count in sorted(reports.items())
        if manager not in profiles or profiles[manager].max_team_size < 1 + count
    )
    return not violations, f"direct reports={reports}, violations={violations}"


def _budget(snapshot: T2Snapshot) -> tuple[bool, str]:
    excessive_allocations = tuple(
        allocation
        for allocation in snapshot.employee_budget_allocations_cents
        if allocation < 0 or allocation > snapshot.budget_ceiling_cents
    )
    excessive_grants = tuple(
        profile.employee_id
        for profile in snapshot.profiles_after
        if profile.spend_limit_cents is not None
        and profile.spend_limit_cents > snapshot.budget_ceiling_cents
    )
    valid = not excessive_allocations and not excessive_grants
    return (
        valid,
        f"employee allocations={snapshot.employee_budget_allocations_cents}, "
        f"total={sum(snapshot.employee_budget_allocations_cents)}, "
        f"per-allocation ceiling={snapshot.budget_ceiling_cents}, "
        f"excessive allocations={excessive_allocations}, excessive grants={excessive_grants}",
    )


def evaluate_invariants(snapshot: T2Snapshot) -> tuple[Invariant, ...]:
    """Judge T2 from immutable data without trusting model prose."""
    shape_ok, shape_detail = _shape(snapshot)
    authority_ok, authority_detail = _authority(snapshot)
    depth_ok, depth_detail = _depth(snapshot)
    team_ok, team_detail = _team_sizes(snapshot)
    budget_ok, budget_detail = _budget(snapshot)
    human_gated = (
        snapshot.plan_status_before == "proposed"
        and snapshot.plan_status_after == "applied"
        and snapshot.proposed_by_employee_id == _CEO_ID
        and snapshot.decided_by_user_id == "founder"
        and snapshot.employees_before == (EmployeeView(_CEO_ID, "ceo", None),)
        and not snapshot.profiles_before
    )
    tool_path = (
        snapshot.ceo_outcome_passed
        and "workforce_catalog_read" in snapshot.tool_names
        and "workforce_plan_propose" in snapshot.tool_names
    )
    return (
        Invariant(
            "CEO proposal beat",
            tool_path,
            f"passed={snapshot.ceo_outcome_passed}, tools={snapshot.tool_names}",
        ),
        Invariant(
            "human-gated formation",
            human_gated,
            f"before={snapshot.plan_status_before}, after={snapshot.plan_status_after}, "
            f"proposer={snapshot.proposed_by_employee_id!r}, decider={snapshot.decided_by_user_id!r}, "
            f"pre-approval employees={tuple(employee.id for employee in snapshot.employees_before)}, "
            f"profiles={len(snapshot.profiles_before)}",
        ),
        Invariant(
            "audited governance",
            snapshot.proposal_audit_actor == _CEO_ID and snapshot.approval_audit_actor == "founder",
            f"proposal actor={snapshot.proposal_audit_actor!r}, "
            f"approval actor={snapshot.approval_audit_actor!r}",
        ),
        Invariant("parallel-capable org shape", shape_ok, shape_detail),
        Invariant("reporting authority", authority_ok, authority_detail),
        Invariant("organization depth", depth_ok, depth_detail),
        Invariant("management team size", team_ok, team_detail),
        Invariant("budget ceiling", budget_ok, budget_detail),
        Invariant(
            "no delivery execution",
            snapshot.task_count == 0 and snapshot.run_count == 0,
            f"tasks={snapshot.task_count}, runs={snapshot.run_count}",
        ),
        Invariant(
            "tool stream complete",
            snapshot.tool_use_count > 0
            and snapshot.tool_use_count == snapshot.tool_result_count
            and snapshot.all_tool_results_lossless,
            f"uses={snapshot.tool_use_count}, results={snapshot.tool_result_count}, "
            f"lossless={snapshot.all_tool_results_lossless}",
        ),
        Invariant(
            "durable monitoring evidence",
            snapshot.event_count > 0 and snapshot.trace_count >= 1,
            f"events={snapshot.event_count}, Dream traces={snapshot.trace_count}",
        ),
        Invariant(
            "secret redaction audit",
            snapshot.secret_redaction_safe,
            f"persisted report/events/traces contain no configured secret="
            f"{snapshot.secret_redaction_safe}",
        ),
    )


def _jsonable(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _json(value: object) -> str:
    return json.dumps(_jsonable(value), indent=2, sort_keys=True, default=str)


def _code_block(text: str, language: str = "") -> str:
    return f"```{language}\n{text.rstrip()}\n```"


def _secret_values() -> tuple[str, ...]:
    markers = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")
    return tuple(
        value
        for name, value in os.environ.items()
        if value and any(marker in name.upper() for marker in markers)
    )


def redact_text(text: str, secret_values: tuple[str, ...]) -> str:
    redacted = text
    for secret in sorted(
        {value for value in secret_values if len(value) >= 8}, key=len, reverse=True
    ):
        redacted = redacted.replace(secret, "[REDACTED]")
    return redacted


def _event_record(event: Event) -> dict[str, object]:
    return {
        "at": event.at.isoformat(),
        "kind": event.kind.value,
        "task_id": event.task_id,
        "employee_id": event.employee_id,
        "run_id": event.run_id,
        "trace_id": event.trace_id,
        "payload": dict(event.payload),
    }


class _Recorder:
    def __init__(self, events_path: Path, console_path: Path, secrets: tuple[str, ...]) -> None:
        self.events_path = events_path
        self.console_path = console_path
        self.secrets = secrets
        self.events: list[Event] = []

    def log(self, message: str) -> None:
        clean = redact_text(message, self.secrets)
        print(clean, flush=True)
        with self.console_path.open("a", encoding="utf-8") as stream:
            stream.write(clean + "\n")

    def observe(self, event: Event) -> None:
        self.events.append(event)
        line = json.dumps(_event_record(event), sort_keys=True, default=str)
        with self.events_path.open("a", encoding="utf-8") as stream:
            stream.write(redact_text(line, self.secrets) + "\n")
        if event.kind is EventKind.RUN_TOOL_USE:
            self.log(
                f"[{event.at.isoformat()}] tool -> {event.payload.get('tool', '?')} "
                f"role={event.payload.get('role', '?')}"
            )
        elif event.kind is EventKind.RUN_TOOL_RESULT:
            result = "error" if event.payload.get("is_error") else "ok"
            self.log(
                f"[{event.at.isoformat()}] tool <- {event.payload.get('tool', '?')} [{result}]"
            )
        elif event.kind is EventKind.RUN_EVALUATED:
            self.log(f"[{event.at.isoformat()}] evaluated {dict(event.payload)}")
        elif event.kind is EventKind.RUN_DONE:
            self.log(f"[{event.at.isoformat()}] CEO beat done")


def _employee_views(ledger: Ledger) -> tuple[EmployeeView, ...]:
    return tuple(
        EmployeeView(employee.id, employee.role, employee.reports_to)
        for employee in ledger.employees.list()
    )


def _management_views(ledger: Ledger) -> tuple[ManagementView, ...]:
    return tuple(
        ManagementView(
            profile.employee_id,
            profile.can_lead,
            profile.max_delegation_depth,
            profile.max_team_size,
            profile.spend_limit_cents,
        )
        for profile in ledger.management_profiles.active_profiles()
    )


def _project_plan(
    plan: WorkforcePlan,
) -> tuple[tuple[EmployeeView, ...], tuple[ManagementView, ...], tuple[int, ...]]:
    draft = plan.draft
    employees = (
        EmployeeView(_CEO_ID, "ceo", None),
        *(
            EmployeeView(employee.ref, employee.profession, employee.reports_to_ref)
            for employee in draft.employees
        ),
    )
    profiles = tuple(
        ManagementView(
            grant.employee_ref,
            grant.can_lead,
            grant.max_delegation_depth,
            grant.max_team_size,
            grant.spend_limit_cents,
        )
        for grant in draft.management_grants
    )
    employee_budgets = tuple(employee.budget_cents or 0 for employee in draft.employees)
    return employees, profiles, employee_budgets


def _preapproval_errors(plan: WorkforcePlan) -> tuple[str, ...]:
    employees, profiles, employee_budgets = _project_plan(plan)
    projected = T2Snapshot(
        ceo_outcome_passed=True,
        plan_status_before="proposed",
        plan_status_after="applied",
        proposed_by_employee_id=_CEO_ID,
        decided_by_user_id="founder",
        employees_before=(EmployeeView(_CEO_ID, "ceo", None),),
        profiles_before=(),
        employees_after=employees,
        profiles_after=profiles,
        proposal_audit_actor=_CEO_ID,
        approval_audit_actor="founder",
        employee_budget_allocations_cents=employee_budgets,
        budget_ceiling_cents=_BUDGET_CEILING_CENTS,
        task_count=0,
        run_count=0,
        tool_names=("workforce_catalog_read", "workforce_plan_propose"),
        tool_use_count=2,
        tool_result_count=2,
        all_tool_results_lossless=True,
        event_count=1,
        trace_count=1,
        secret_redaction_safe=True,
    )
    names = {
        "parallel-capable org shape",
        "reporting authority",
        "organization depth",
        "management team size",
        "budget ceiling",
    }
    return tuple(
        f"{check.name}: {check.detail}"
        for check in evaluate_invariants(projected)
        if check.name in names and not check.passed
    )


def _snapshot_prompts(worktree: Path) -> dict[str, str]:
    role_dir = worktree / ".harness" / "roles"
    if not role_dir.is_dir():
        return {}
    return {
        path.relative_to(worktree).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(role_dir.glob("*.toml"))
    }


def _copy_traces(worktree: Path, destination: Path, secrets: tuple[str, ...]) -> list[Path]:
    copied: list[Path] = []
    for index, source in enumerate(
        sorted(worktree.glob(".dream/sidecars/*/logs/trace.jsonl")), start=1
    ):
        destination.mkdir(parents=True, exist_ok=True)
        target = destination / f"trace-{index:02d}-{source.parents[1].name}.jsonl"
        target.write_text(
            redact_text(source.read_text(encoding="utf-8"), secrets), encoding="utf-8"
        )
        copied.append(target)
    return copied


def _audit_redaction(paths: list[Path], secrets: tuple[str, ...]) -> tuple[bool, str]:
    leaks: list[str] = []
    for path in paths:
        if not path.is_file():
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        if any(secret in content for secret in secrets if len(secret) >= 8):
            leaks.append(path.name)
    return not leaks, f"files containing configured secrets={tuple(leaks)}"


def _render_org(employees: tuple[EmployeeView, ...]) -> str:
    by_manager: dict[str | None, list[EmployeeView]] = {}
    for employee in employees:
        by_manager.setdefault(employee.reports_to, []).append(employee)
    lines: list[str] = []

    def walk(manager: str | None, depth: int) -> None:
        for employee in sorted(by_manager.get(manager, []), key=lambda item: item.id):
            lines.append(f"{'  ' * depth}- {employee.id} ({employee.role})")
            walk(employee.id, depth + 1)

    walk(None, 0)
    return "\n".join(lines) or "(empty)"


def _render_report(
    *,
    run_root: Path,
    deployment: str,
    approval_actor: str,
    snapshot: T2Snapshot,
    invariants: tuple[Invariant, ...],
    outcome: object,
    execution_error: str,
    approval_error: str,
    plan_before: object,
    plan_after: object,
    employees_before_raw: object,
    profiles_before_raw: object,
    employees_after_raw: object,
    profiles_after_raw: object,
    activities: object,
    prompts: dict[str, str],
    events: list[Event],
    traces: list[Path],
    directive: str,
    preapproval_errors: tuple[str, ...],
) -> str:
    passed = all(check.passed for check in invariants)
    lines = [
        "# T2 Formation and Governance Live Run Report",
        "",
        f"**Result:** {'PASS' if passed else 'STOPPED / NEEDS FIX'}  ",
        f"**Model deployment:** `{deployment}`  ",
        f"**Run directory:** `{run_root}`  ",
        f"**Explicit human approval actor:** `{approval_actor}`  ",
        "**Scope:** one real CEO formation beat; no delivery tasks or scheduler runs",
        "",
        "## Invariants",
        "",
        "| Check | Result | Evidence |",
        "| --- | --- | --- |",
    ]
    for check in invariants:
        lines.append(
            f"| {check.name} | {'PASS' if check.passed else 'FAIL'} | "
            f"{check.detail.replace('|', chr(92) + '|')} |"
        )
    lines.extend(
        [
            "",
            "## Founder Intent and OKR Tree",
            "",
            _FOUNDER_INTENT,
            "",
            "## Task Split and Goals",
            "",
            "T2 performs formation only. The CEO reasons about staffing for three parallel outcome "
            "areas, but no implementation task, delegation root, or system-verifier run is created.",
            "",
            "```text",
            "Objective: Ship Linkport",
            "|- KR-A: Links backend",
            "|- KR-B: Analytics backend",
            "`- KR-C: Web UI",
            "```",
            "",
            "## CEO Decision",
            "",
            "### Effective intent",
            _INTENT,
            "",
            "### Beat outcome",
            _code_block(_json(outcome), "json"),
            "",
            f"Execution exception: `{execution_error or 'none'}`  ",
            f"Approval exception: `{approval_error or 'none'}`",
            "",
            "### Directive",
            directive or "(directive.md missing)",
            "",
            "## Human Approval Boundary",
            "",
            "The following snapshot was taken after the CEO tool returned and before the founder "
            "approval API was called. A target-shape audit runs at this boundary; a failed audit "
            "leaves the proposal pending and prevents materialization.",
            "",
            f"Pre-approval target audit: `{preapproval_errors or ('pass',)}`",
            "",
            "### Persisted proposal before approval",
            _code_block(_json(plan_before), "json"),
            "",
            "### Employees before approval",
            _code_block(_json(employees_before_raw), "json"),
            "",
            "### Management profiles before approval",
            _code_block(_json(profiles_before_raw), "json"),
            "",
            "### Applied plan after explicit approval",
            _code_block(_json(plan_after), "json"),
            "",
            "## Materialized Organization",
            "",
            _code_block(_render_org(snapshot.employees_after), "text"),
            "",
            "### Employees",
            _code_block(_json(employees_after_raw), "json"),
            "",
            "### Active management profiles",
            _code_block(_json(profiles_after_raw), "json"),
            "",
            "## Governance Audit Trail",
            "",
            _code_block(_json(activities), "json"),
            "",
            "## Effective Role Prompts",
            "",
        ]
    )
    for path, content in prompts.items():
        lines.extend([f"### `{path}`", "", _code_block(content, "toml"), ""])
    lines.extend(["## Chronological Runtime Events", ""])
    for index, event in enumerate(events, start=1):
        lines.extend(
            [
                f"### {index}. `{event.kind.value}` at {event.at.isoformat()}",
                "",
                f"task=`{event.task_id}` employee=`{event.employee_id}` run=`{event.run_id}` "
                f"trace=`{event.trace_id}`",
                "",
                _code_block(_json(dict(event.payload)), "json"),
                "",
            ]
        )
    lines.extend(["## Raw Dream Traces", ""])
    for trace in traces:
        lines.append(f"- [{trace.name}]({trace.relative_to(run_root).as_posix()})")
    lines.extend(
        [
            "",
            "## Evidence Inventory",
            "",
            "- `events.jsonl`: lossless chronological Dream event and tool stream.",
            "- `traces/`: raw, redacted Dream sidecar traces.",
            "- `company.db`: durable workforce plans, audit activities, employees, and grants.",
            "- `console.log`: concise live progress stream.",
            "- `summary.json`: machine-readable snapshot and invariant results.",
            "- `work/`: isolated CEO worktree, directive, role prompts, and sidecars.",
            "",
            "## Monitoring Boundary",
            "",
            f"The report renders all {snapshot.event_count} observable events and all "
            f"{snapshot.tool_use_count} tool calls with their arguments/results. Private model "
            "chain-of-thought is unavailable; decisions are reconstructed from model text, tool "
            "activity, typed plans, artifacts, and the append-only audit stream.",
            "",
        ]
    )
    return "\n".join(lines)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "reports" / "t2-live-runs",
    )
    parser.add_argument("--expect-model", default="gpt-5.2")
    parser.add_argument(
        "--approve-by",
        required=True,
        help="Explicit human actor recorded on the workforce-plan approval (use 'founder').",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    api_key = os.environ.get("AZURE_OPENAI_API_KEY", "")
    base_url = os.environ.get("AZURE_OPENAI_BASE_URL", "")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "")
    if not (api_key and base_url and deployment):
        print("missing AZURE_OPENAI_API_KEY, AZURE_OPENAI_BASE_URL, or AZURE_OPENAI_DEPLOYMENT")
        return 2
    if deployment != args.expect_model:
        print(f"refusing to run: expected model {args.expect_model!r}, configured {deployment!r}")
        return 2
    if args.approve_by != "founder":
        print("refusing to run: T2 acceptance requires explicit --approve-by founder")
        return 2

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_root = args.output_root.resolve() / f"t2-{stamp}-{uuid4().hex[:8]}"
    run_root.mkdir(parents=True)
    secrets = _secret_values()
    recorder = _Recorder(run_root / "events.jsonl", run_root / "console.log", secrets)
    ledger = Ledger.open(str(run_root / "company.db"))
    registry = RoleRegistry.from_plugins(default_roles())
    factory = EmployeeHarnessFactory(
        api_key=api_key,
        base_url=base_url,
        deployment=deployment,
        company_id=f"linkport-t2-{run_root.name}",
        roles=registry,
        ledger=ledger,
        work_root=run_root / "work",
        timeout_s=900.0,
    )

    outcome: object = None
    execution_error = ""
    approval_error = ""
    try:
        ceo = ledger.employees.create(Employee(id=_CEO_ID, name="Casey (CEO)", role="ceo"))
        materialized = factory.materialize(ceo)
        (materialized.working_dir / "founder-intent.md").write_text(
            _FOUNDER_INTENT, encoding="utf-8"
        )
        prompts = _snapshot_prompts(materialized.working_dir)
        recorder.log(f"T2 run directory: {run_root}")
        recorder.log(f"model: {deployment}; CEO: {_CEO_ID}; approval actor: {args.approve_by}")
        verifier = ceo_plugin().dod_generator(_INTENT)
        rubric = verifier.spec.rubric if isinstance(verifier.spec, AgentReview) else ""
        try:
            outcome = asyncio.run(
                materialized.runner.run_task(
                    task_id="t2-formation",
                    intent=_INTENT,
                    run_id=f"run-{uuid4().hex}",
                    rubric=rubric,
                    observer=recorder.observe,
                )
            )
        except Exception as exc:  # preserve a complete failed evidence bundle
            execution_error = f"{type(exc).__name__}: {exc}"
            recorder.log(f"CEO beat exception: {execution_error}")

        plans = ledger.workforce_plans.list()
        plan_before = plans[-1] if len(plans) == 1 else None
        employees_before_raw = ledger.employees.list()
        profiles_before_raw = ledger.management_profiles.active_profiles()
        employees_before = _employee_views(ledger)
        profiles_before = _management_views(ledger)
        preapproval_errors = (
            _preapproval_errors(plan_before) if plan_before is not None else ("one plan required",)
        )
        outcome_passed = bool(getattr(outcome, "passed", False)) and not execution_error
        recorder.log(
            f"pre-approval: plans={len(plans)}, employees={len(employees_before)}, "
            f"profiles={len(profiles_before)}, audit={preapproval_errors or ('pass',)}"
        )

        if (
            plan_before is not None
            and getattr(plan_before, "status", None) is WorkforcePlanStatus.PROPOSED
            and not preapproval_errors
            and outcome_passed
        ):
            recorder.log(f"human approval boundary: actor={args.approve_by}")
            service = WorkforcePlanService(
                ledger,
                workforce=LedgerWorkforce(ledger.employees),
                roles=registry,
                max_org_depth=2,
            )
            try:
                service.approve(plan_before.id, approved_by_user_id=args.approve_by)
            except Exception as exc:
                approval_error = f"{type(exc).__name__}: {exc}"
                recorder.log(f"approval exception: {approval_error}")
        else:
            recorder.log("human approval withheld: CEO outcome or pre-approval audit failed")

        plan_after = (
            ledger.workforce_plans.latest(plan_before.id) if plan_before is not None else None
        )
        employees_after_raw = ledger.employees.list()
        profiles_after_raw = ledger.management_profiles.active_profiles()
        employees_after = _employee_views(ledger)
        profiles_after = _management_views(ledger)
        activities = ledger.activity.all()
        proposal_activity = next(
            (
                activity
                for activity in activities
                if activity.verb is ActivityVerb.WORKFORCE_PLAN_PROPOSED
            ),
            None,
        )
        approval_activity = next(
            (
                activity
                for activity in activities
                if activity.verb is ActivityVerb.WORKFORCE_PLAN_APPLIED
            ),
            None,
        )
        tool_uses = [event for event in recorder.events if event.kind is EventKind.RUN_TOOL_USE]
        tool_results = [
            event for event in recorder.events if event.kind is EventKind.RUN_TOOL_RESULT
        ]
        tool_names = tuple(str(event.payload.get("tool", "")) for event in tool_uses)
        traces = _copy_traces(materialized.working_dir, run_root / "traces", secrets)
        directive_path = materialized.working_dir / "directive.md"
        directive = directive_path.read_text(encoding="utf-8") if directive_path.is_file() else ""
        employee_budgets = (
            tuple(employee.budget_cents or 0 for employee in plan_before.draft.employees)
            if plan_before is not None
            else ()
        )
        tasks = ledger.tasks.all()
        run_count = sum(len(ledger.runs.for_task(task.id)) for task in tasks)
        snapshot = T2Snapshot(
            ceo_outcome_passed=outcome_passed,
            plan_status_before=(plan_before.status.value if plan_before is not None else "missing"),
            plan_status_after=(plan_after.status.value if plan_after is not None else "missing"),
            proposed_by_employee_id=(
                plan_before.proposed_by_employee_id if plan_before is not None else ""
            ),
            decided_by_user_id=(
                plan_after.decided_by_user_id or "" if plan_after is not None else ""
            ),
            employees_before=employees_before,
            profiles_before=profiles_before,
            employees_after=employees_after,
            profiles_after=profiles_after,
            proposal_audit_actor=(
                proposal_activity.actor_employee_id or "" if proposal_activity else ""
            ),
            approval_audit_actor=(
                approval_activity.actor_user_id or "" if approval_activity else ""
            ),
            employee_budget_allocations_cents=employee_budgets,
            budget_ceiling_cents=_BUDGET_CEILING_CENTS,
            task_count=len(tasks),
            run_count=run_count,
            tool_names=tool_names,
            tool_use_count=len(tool_uses),
            tool_result_count=len(tool_results),
            all_tool_results_lossless=bool(tool_results)
            and all("content" in event.payload for event in tool_results),
            event_count=len(recorder.events),
            trace_count=len(traces),
            secret_redaction_safe=False,
        )
        invariants = evaluate_invariants(snapshot)
        report_path = run_root / "report.md"
        report = _render_report(
            run_root=run_root,
            deployment=deployment,
            approval_actor=args.approve_by,
            snapshot=snapshot,
            invariants=invariants,
            outcome=outcome,
            execution_error=execution_error,
            approval_error=approval_error,
            plan_before=plan_before,
            plan_after=plan_after,
            employees_before_raw=employees_before_raw,
            profiles_before_raw=profiles_before_raw,
            employees_after_raw=employees_after_raw,
            profiles_after_raw=profiles_after_raw,
            activities=activities,
            prompts=prompts,
            events=recorder.events,
            traces=traces,
            directive=directive,
            preapproval_errors=preapproval_errors,
        )
        report_path.write_text(redact_text(report, secrets), encoding="utf-8")
        redaction_safe, redaction_detail = _audit_redaction(
            [
                report_path,
                run_root / "events.jsonl",
                run_root / "console.log",
                *traces,
            ],
            secrets,
        )
        snapshot = replace(snapshot, secret_redaction_safe=redaction_safe)
        invariants = evaluate_invariants(snapshot)
        report = _render_report(
            run_root=run_root,
            deployment=deployment,
            approval_actor=args.approve_by,
            snapshot=snapshot,
            invariants=invariants,
            outcome=outcome,
            execution_error=execution_error,
            approval_error=approval_error,
            plan_before=plan_before,
            plan_after=plan_after,
            employees_before_raw=employees_before_raw,
            profiles_before_raw=profiles_before_raw,
            employees_after_raw=employees_after_raw,
            profiles_after_raw=profiles_after_raw,
            activities=activities,
            prompts=prompts,
            events=recorder.events,
            traces=traces,
            directive=directive,
            preapproval_errors=preapproval_errors,
        )
        report_path.write_text(redact_text(report, secrets), encoding="utf-8")
        summary_path = run_root / "summary.json"
        summary_path.write_text(
            redact_text(
                _json(
                    {
                        "snapshot": snapshot,
                        "invariants": invariants,
                        "redaction_audit": redaction_detail,
                        "preapproval_errors": preapproval_errors,
                    }
                ),
                secrets,
            ),
            encoding="utf-8",
        )
        final_redaction_safe, final_redaction_detail = _audit_redaction(
            [
                report_path,
                summary_path,
                run_root / "events.jsonl",
                run_root / "console.log",
                *traces,
            ],
            secrets,
        )
        if final_redaction_safe != snapshot.secret_redaction_safe:
            snapshot = replace(snapshot, secret_redaction_safe=final_redaction_safe)
            invariants = evaluate_invariants(snapshot)
        recorder.log(f"redaction audit: {final_redaction_detail}")
        latest = args.output_root.resolve() / "T2-latest.md"
        latest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(report_path, latest)
        shutil.copyfile(summary_path, args.output_root.resolve() / "T2-latest.json")
        for check in invariants:
            recorder.log(f"{'PASS' if check.passed else 'FAIL'} {check.name}: {check.detail}")
        recorder.log(f"report: {report_path}")
        recorder.log(f"latest: {latest}")
        return 0 if all(check.passed for check in invariants) else 1
    finally:
        ledger.close()


if __name__ == "__main__":
    raise SystemExit(main())
