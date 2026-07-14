"""CEO-facing typed workforce catalog and proposal tools."""

from __future__ import annotations

from dream.contracts.tool import ToolResult
from dream.tools._base import BaseTool, ToolDeclaration
from dream.tools._context import ToolExecutionContext
from pydantic import BaseModel, Field, ValidationError

from chorus.governance import WorkforcePlanService
from chorus.heartbeat import BeatContext
from chorus.ledger import (
    ManagementGrantDraft,
    PlannedEmployee,
    SqliteLedger,
    StaffingRequestStatus,
    WorkforcePlanDraft,
)
from chorus.roles import RoleRegistry
from chorus.workforce import LedgerWorkforce

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

    def __init__(self, ledger: SqliteLedger, roles: RoleRegistry) -> None:
        self._ledger = ledger
        self._roles = roles

    async def execute(
        self, input: dict[str, object], ctx: ToolExecutionContext
    ) -> ToolResult:
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
        requests = [
            {
                "request_id": request.id,
                "task_id": request.task_id,
                "goal_id": request.goal_id,
                "team_id": request.team_id,
                "requested_by_employee_id": request.requested_by_employee_id,
                "rationale": request.rationale,
                "needs": [
                    {"profession": need.profession, "count": need.count}
                    for need in request.needs
                ],
            }
            for request in self._ledger.staffing_requests.list(
                status=StaffingRequestStatus.OPEN
            )
        ]
        return ToolResult(
            content=(
                f"{len(professions)} hireable professions; "
                f"{len(employees)} current permanent employees"
            ),
            structured={
                "hireable_professions": professions,
                "current_employees": employees,
                "open_staffing_requests": requests,
                "max_org_depth_below_ceo": 2,
                "management_is_separate_grant": True,
                "mission_teams_are_goal_scoped": True,
            },
        )


class PlannedEmployeeInput(BaseModel):
    ref: str = Field(description="stable employee id proposed for the permanent workforce")
    name: str = Field(description="human-readable employee name")
    profession: str = Field(description="one profession from workforce_catalog_read")
    reports_to_ref: str = Field(description="permanent manager employee id or plan ref")
    responsibilities: list[str] = Field(default_factory=list)
    budget_cents: int | None = Field(default=None, ge=0)


class ManagementGrantInput(BaseModel):
    employee_ref: str
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
    employees: list[PlannedEmployeeInput] = Field(min_length=1)
    management_grants: list[ManagementGrantInput]


class WorkforcePlanProposeTool(BaseTool):
    """Persist one CEO workforce proposal for human revision or approval."""

    name = "workforce_plan_propose"
    description = (
        "Propose one complete permanent workforce plan from the fixed catalog. This stores a typed "
        "proposal only: it does not hire, change reporting lines, grant authority, or form Mission "
        "Teams. A human must revise or approve the plan through Chorus governance."
    )
    declaration = ToolDeclaration(risk="mutating", tier_required=1, timeout_seconds=30.0)
    input_model = WorkforcePlanProposeInput

    def __init__(self, ledger: SqliteLedger, roles: RoleRegistry) -> None:
        self._service = WorkforcePlanService(
            ledger,
            workforce=LedgerWorkforce(ledger.employees),
            roles=roles,
            max_org_depth=2,
        )

    async def execute(
        self, input: dict[str, object], ctx: ToolExecutionContext
    ) -> ToolResult:
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
                staffing_request_id=args.staffing_request_id,
            )
        except (ValidationError, ValueError) as exc:
            return ToolResult(
                content=f"refused: invalid workforce plan — {exc}",
                structured={"error": str(exc)},
                is_error=True,
            )
        return ToolResult(
            content=(
                f"proposed workforce plan {plan.id} revision {plan.revision}; "
                "no employees or authority grants were applied"
            ),
            structured={
                "plan_id": plan.id,
                "revision": plan.revision,
                "status": plan.status.value,
                "requires_human_approval": True,
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