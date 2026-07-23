"""CEO-facing typed workforce catalog and proposal tools."""

from __future__ import annotations

import json
import os
from tempfile import NamedTemporaryFile

from dream.contracts.tool import ToolResult
from dream.tools._base import BaseTool, ToolDeclaration
from dream.tools._context import ToolExecutionContext
from pydantic import BaseModel, Field, ValidationError

from chorus.governance import WorkforcePlanService
from chorus.heartbeat import BeatContext
from chorus.ledger import (
    Ledger,
    ManagementGrantDraft,
    PlannedEmployee,
    StaffingRequestStatus,
    WorkforcePlanDraft,
)
from chorus.roles import RoleRegistry
from chorus.workforce import LedgerWorkforce
from chorus_tools._governance import _audit

_HIREABLE_PROFESSIONS = (
    "analyst",
    "backend_engineer",
    "designer",
    "frontend_engineer",
    "marketer",
    "pm",
)


class WorkforceCatalogReadInput(BaseModel):
    """The workforce catalog read takes no arguments."""


class WorkforceCatalogReadTool(BaseTool):
    """Read fixed hireable professions and the current permanent line organization."""

    name = "workforce_catalog_read"
    description = (
        "Read the fixed hireable profession catalog and current permanent workforce. Professions "
        "are execution identities; management is proposed separately as a bounded grant."
    )
    declaration = ToolDeclaration(risk="safe", tier_required=0, timeout_seconds=10.0)
    input_model = WorkforceCatalogReadInput

    def __init__(self, ledger: Ledger, roles: RoleRegistry) -> None:
        self._ledger = ledger
        self._roles = roles

    async def execute(self, input: dict[str, object], ctx: ToolExecutionContext) -> ToolResult:
        WorkforceCatalogReadInput.model_validate(input)
        professions = [name for name in _HIREABLE_PROFESSIONS if name in self._roles]
        employees = [
            {
                "employee_id": employee.id,
                "name": employee.name,
                "profession": employee.role,
                "reports_to": employee.reports_to,
                "status": employee.status.value,
                "has_management_profile": (
                    self._ledger.management_profiles.get(employee.id) is not None
                ),
            }
            for employee in self._ledger.employees.list()
        ]
        existing_ids = [str(employee["employee_id"]) for employee in employees]
        requests = [
            {
                "request_id": request.id,
                "task_id": request.task_id,
                "goal_id": request.goal_id,
                "team_id": request.team_id,
                "requested_by_employee_id": request.requested_by_employee_id,
                "rationale": request.rationale,
                "needs": [
                    {"profession": need.profession, "count": need.count} for need in request.needs
                ],
            }
            for request in self._ledger.staffing_requests.list(status=StaffingRequestStatus.OPEN)
        ]
        return ToolResult(
            content=(
                f"{len(professions)} hireable professions; "
                f"{len(employees)} current permanent employees. `employees` accepts NEW HIRES "
                "ONLY; omit current employees and use existing ids directly in "
                f"`reports_to_ref` or management grants. Existing ids: {existing_ids}"
            ),
            structured={
                "hireable_professions": professions,
                "current_employees": employees,
                "open_staffing_requests": requests,
                "max_org_depth_below_ceo": 2,
                "management_is_separate_grant": True,
                "mission_teams_are_goal_scoped": True,
                "proposal_contract": {
                    "employees": "new hires only; omit current permanent employees",
                    "existing_employee_references": existing_ids,
                    "existing_employee_reference_fields": [
                        "employees[].reports_to_ref",
                        "management_grants[].employee_ref",
                    ],
                },
            },
        )


class PlannedEmployeeInput(BaseModel):
    ref: str = Field(description="stable id for this new hire; never copy a current employee")
    name: str = Field(description="human-readable employee name")
    profession: str = Field(description="one profession from workforce_catalog_read")
    reports_to_ref: str = Field(
        description="exact current manager employee id or another new-hire ref"
    )
    responsibilities: list[str] = Field(default_factory=list)
    budget_cents: int | None = Field(default=None, ge=0)


class ManagementGrantInput(BaseModel):
    employee_ref: str = Field(
        description="exact current employee id or new-hire ref receiving this grant"
    )
    can_lead: bool
    can_subdelegate: bool
    max_delegation_depth: int = Field(ge=0, le=2)
    max_team_size: int = Field(ge=1)
    allowed_professions: list[str] = Field(default_factory=list)
    spend_limit_cents: int | None = Field(default=None, ge=0)


class WorkforcePlanProposeInput(BaseModel):
    """One complete, typed workforce proposal; the tool never applies it."""

    rationale: str
    confidence: float = Field(ge=0.0, le=1.0)
    source_goal_ids: list[str] = Field(min_length=1)
    staffing_request_id: str | None = Field(
        default=None,
        description="open request id when this proposal is an exact staffing amendment",
    )
    employees: list[PlannedEmployeeInput] = Field(
        min_length=1,
        description="new hires only; omit all current permanent employees",
    )
    management_grants: list[ManagementGrantInput]


class WorkforcePlanProposeTool(BaseTool):
    """Persist one CEO workforce proposal for human revision or approval."""

    name = "workforce_plan_propose"
    description = (
        "Propose one complete permanent workforce plan from the fixed catalog. This stores a typed "
        "proposal only: it does not hire, change reporting lines, grant authority, or form Mission "
        "Teams. A human must revise or approve the plan through Chorus governance. On success it "
        "writes canonical `workforce_plan.json`; inspect that evidence instead of proposing again."
    )
    declaration = ToolDeclaration(risk="mutating", tier_required=1, timeout_seconds=30.0)
    input_model = WorkforcePlanProposeInput

    def __init__(self, ledger: Ledger, roles: RoleRegistry) -> None:
        self._service = WorkforcePlanService(
            ledger,
            workforce=LedgerWorkforce(ledger.employees),
            roles=roles,
            max_org_depth=2,
        )

    async def execute(self, input: dict[str, object], ctx: ToolExecutionContext) -> ToolResult:
        try:
            args = WorkforcePlanProposeInput.model_validate(input)
            beat = BeatContext.read(ctx.working_dir)
            plan = self._service.propose(
                WorkforcePlanDraft(
                    rationale=args.rationale,
                    confidence=args.confidence,
                    source_goal_ids=tuple(args.source_goal_ids),
                    employees=tuple(
                        PlannedEmployee(
                            ref=employee.ref,
                            name=employee.name,
                            profession=employee.profession,
                            reports_to_ref=employee.reports_to_ref,
                            responsibilities=tuple(employee.responsibilities),
                            budget_cents=employee.budget_cents,
                        )
                        for employee in args.employees
                    ),
                    management_grants=tuple(
                        ManagementGrantDraft(
                            employee_ref=grant.employee_ref,
                            can_lead=grant.can_lead,
                            can_subdelegate=grant.can_subdelegate,
                            max_delegation_depth=grant.max_delegation_depth,
                            max_team_size=grant.max_team_size,
                            allowed_professions=tuple(grant.allowed_professions),
                            spend_limit_cents=grant.spend_limit_cents,
                        )
                        for grant in args.management_grants
                    ),
                ),
                proposed_by_employee_id=beat.employee_id,
                # A proposal task is done when its proposal is decided — the plan carries its
                # origin beat task so approval can complete it (free-run, found live).
                proposed_in_task_id=beat.task_id,
                staffing_request_id=args.staffing_request_id,
            )
        except (ValidationError, ValueError) as exc:
            return ToolResult(
                content=(
                    f"refused: invalid workforce plan — {exc}. Correction: employees "
                    "contains new hires only; omit current employees and reference current "
                    "employee ids directly in `reports_to_ref` and management grants"
                ),
                structured={
                    "error": str(exc),
                    "correction": (
                        "employees contains new hires only; use current employee ids directly "
                        "in reference fields"
                    ),
                },
                is_error=True,
            )
        evidence = {
            "plan_id": plan.id,
            "revision": plan.revision,
            "status": plan.status.value,
            "proposed_by_employee_id": plan.proposed_by_employee_id,
            "requires_human_approval": True,
            "rationale": plan.draft.rationale,
            "confidence": plan.draft.confidence,
            "source_goal_ids": list(plan.draft.source_goal_ids),
            "staffing_request_id": plan.staffing_request_id,
            "employees": [
                {
                    "ref": employee.ref,
                    "name": employee.name,
                    "profession": employee.profession,
                    "reports_to_ref": employee.reports_to_ref,
                    "responsibilities": list(employee.responsibilities),
                    "budget_cents": employee.budget_cents,
                }
                for employee in plan.draft.employees
            ],
            "management_grants": [
                {
                    "employee_ref": grant.employee_ref,
                    "can_lead": grant.can_lead,
                    "can_subdelegate": grant.can_subdelegate,
                    "max_delegation_depth": grant.max_delegation_depth,
                    "max_team_size": grant.max_team_size,
                    "allowed_professions": list(grant.allowed_professions),
                    "spend_limit_cents": grant.spend_limit_cents,
                }
                for grant in plan.draft.management_grants
            ],
        }
        ctx.working_dir.mkdir(parents=True, exist_ok=True)
        # The DoD reviewer's ground truth is the run-stamped governance ledger; without this line
        # a formation beat's propose is invisible to a read-only reviewer and the beat re-runs.
        _audit(
            ctx,
            f"workforce_plan_propose: proposed workforce plan {plan.id} "
            f"revision {plan.revision} ({len(plan.draft.employees)} new hires, "
            f"{len(plan.draft.management_grants)} management grants) — pending human approval",
        )
        target = ctx.working_dir / "workforce_plan.json"
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=ctx.working_dir,
            prefix=".workforce-plan-",
            suffix=".tmp",
            delete=False,
        ) as stream:
            json.dump(evidence, stream, indent=2, sort_keys=True)
            stream.write("\n")
            temporary = stream.name
        os.replace(temporary, target)
        return ToolResult(
            content=(
                f"proposed workforce plan {plan.id} revision {plan.revision}; "
                "no employees or authority grants were applied; canonical evidence is at "
                "workforce_plan.json — read it and do not submit another proposal"
            ),
            structured={
                "plan_id": plan.id,
                "revision": plan.revision,
                "status": plan.status.value,
                "requires_human_approval": True,
                "evidence_path": "workforce_plan.json",
                "proposal": evidence,
            },
        )


__all__ = [
    "ManagementGrantInput",
    "PlannedEmployeeInput",
    "WorkforceCatalogReadInput",
    "WorkforceCatalogReadTool",
    "WorkforcePlanProposeInput",
    "WorkforcePlanProposeTool",
]
