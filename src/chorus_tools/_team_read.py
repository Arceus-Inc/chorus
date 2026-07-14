"""Read-only roster context for the current delegation contract."""

from __future__ import annotations

from collections import Counter

from dream.contracts.tool import ToolResult
from dream.tools._base import BaseTool, ToolDeclaration
from dream.tools._context import ToolExecutionContext
from pydantic import BaseModel

from chorus.heartbeat import BeatContext
from chorus.heartbeat._invokability import invokability_block
from chorus.ledger import ExecutionMode, SqliteLedger, TeamStatus
from chorus.workforce._ledger import LedgerWorkforce

_TERMINAL_TASK_STATUSES = {"cancelled", "done", "rejected"}


class TeamReadInput(BaseModel):
    """``team_read`` takes no arguments; beat context selects the contract."""


class TeamReadTool(BaseTool):
    """Expose safe team-building facts to the current delegation lead."""

    name = "team_read"
    description = (
        "Read the current delegation Team, contract limits, members, legal direct reports, "
        "candidate reports, and observed task load. This is a read-only snapshot for the current beat."
    )
    declaration = ToolDeclaration(risk="safe", tier_required=0, timeout_seconds=10.0)
    input_model = TeamReadInput

    def __init__(self, ledger: SqliteLedger) -> None:
        self._ledger = ledger
        self._workforce = LedgerWorkforce(ledger.employees)

    async def execute(
        self, input: dict[str, object], ctx: ToolExecutionContext
    ) -> ToolResult:
        TeamReadInput.model_validate(input)
        beat = BeatContext.read(ctx.working_dir)
        task = self._ledger.tasks.get(beat.task_id)
        if task is None:
            return _refused("the beat task was not found")
        contract = self._ledger.delegation_contracts.active_for_task(task.id)
        if task.execution_mode is not ExecutionMode.DELEGATION or contract is None:
            return _refused("the beat has no active delegation contract")
        if contract.lead_employee_id != beat.employee_id:
            return _refused("the actor is not the delegation contract lead")
        team = self._ledger.teams.get(contract.team_id)
        if (
            team is None
            or team.status is not TeamStatus.ACTIVE
            or task.team_id != team.id
            or team.lead_employee_id != beat.employee_id
        ):
            return _refused("the active delegation Team is invalid")
        profile = self._ledger.management_profiles.get(beat.employee_id)
        if (
            profile is None
            or not profile.active
            or profile.version != contract.management_profile_version
        ):
            return _refused("the management profile is missing, inactive, or stale")

        members = self._ledger.team_members.members_of(team.id)
        member_ids = {member.employee_id for member in members}
        load = Counter(
            candidate.assignee_employee_id
            for candidate in self._ledger.tasks.all()
            if candidate.assignee_employee_id is not None
            and candidate.status.value not in _TERMINAL_TASK_STATUSES
        )
        legal_reports = [
            employee
            for employee in self._workforce.list()
            if employee.reports_to == beat.employee_id
            and (
                not profile.allowed_professions
                or employee.role in profile.allowed_professions
            )
            and invokability_block(self._workforce, employee.id) is None
        ]
        report_views = [
            {
                "employee_id": employee.id,
                "profession": employee.role,
                "status": employee.status.value,
                "observed_load": load[employee.id],
            }
            for employee in sorted(legal_reports, key=lambda item: item.id)
        ]
        current_member_views = []
        for member in sorted(
            members,
            key=lambda item: (item.employee_id != team.lead_employee_id, item.employee_id),
        ):
            employee = self._ledger.employees.get(member.employee_id)
            if employee is None:
                return _refused("a current Team member is missing from the workforce")
            current_member_views.append(
                {
                    "employee_id": employee.id,
                    "profession": employee.role,
                    "membership_role": member.membership_role.value,
                    "can_subdelegate": member.can_subdelegate,
                    "observed_load": load[employee.id],
                }
            )
        relevant_ids = member_ids | {employee.id for employee in legal_reports}
        structured = {
            "task_id": task.id,
            "team": {
                "id": team.id,
                "name": team.name,
                "status": team.status.value,
                "lead_employee_id": team.lead_employee_id,
            },
            "contract": {
                "task_id": contract.task_id,
                "status": contract.status.value,
                "can_subdelegate": contract.can_subdelegate,
                "max_depth": contract.max_depth,
                "max_team_size": contract.max_team_size,
                "spend_limit_cents": contract.spend_limit_cents,
            },
            "current_members": current_member_views,
            "legal_direct_reports": report_views,
            "team_candidates": [
                report for report in report_views if report["employee_id"] not in member_ids
            ],
            "observed_load": {
                employee_id: load[employee_id] for employee_id in sorted(relevant_ids)
            },
            "management_limits": {
                "management_profile_version": contract.management_profile_version,
                "can_subdelegate": contract.can_subdelegate,
                "max_depth": contract.max_depth,
                "max_team_size": contract.max_team_size,
                "spend_limit_cents": contract.spend_limit_cents,
                "allowed_professions": sorted(profile.allowed_professions),
            },
        }
        return ToolResult(
            content=(
                f"Team {team.id}: {len(current_member_views)} current members, "
                f"{len(structured['team_candidates'])} legal candidates"
            ),
            structured=structured,
        )


def _refused(reason: str) -> ToolResult:
    return ToolResult(
        content=f"refused: {reason}",
        structured={"reason": reason},
        is_error=True,
    )


__all__ = ["TeamReadInput", "TeamReadTool"]