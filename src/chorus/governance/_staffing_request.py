"""Lead-raised staffing gaps constrained by active delegation authority."""

from __future__ import annotations

from collections import Counter

from chorus.heartbeat._invokability import invokability_block
from chorus.ids import mint_id
from chorus.ledger import (
    ActivityVerb,
    DelegationContractStatus,
    SqliteLedger,
    StaffingNeed,
    StaffingRequest,
    StaffingRequestStatus,
    TeamStatus,
)
from chorus.lifecycle._audit import record_activity
from chorus.workforce import LedgerWorkforce


class StaffingRequestService:
    """Persist staffing gaps that fit an active contract's existing authority envelope."""

    def __init__(self, ledger: SqliteLedger) -> None:
        self._ledger = ledger
        self._workforce = LedgerWorkforce(ledger.employees)

    def request(
        self,
        *,
        task_id: str,
        requested_by_employee_id: str,
        rationale: str,
        needs: tuple[StaffingNeed, ...],
    ) -> StaffingRequest:
        task = self._ledger.tasks.get(task_id)
        contract = self._ledger.delegation_contracts.active_for_task(task_id)
        if task is None or contract is None or task.goal_id is None:
            raise ValueError("staffing requests require an active goal delegation contract")
        if contract.status is not DelegationContractStatus.DELEGATED:
            raise ValueError("staffing requests are only allowed during delegated kickoff")
        if contract.lead_employee_id != requested_by_employee_id:
            raise ValueError("staffing request actor must be the contract lead")
        if task.team_id != contract.team_id:
            raise ValueError("staffing request task and contract Teams differ")
        team = self._ledger.teams.get(contract.team_id)
        if team is None or team.status is not TeamStatus.ACTIVE:
            raise ValueError("staffing requests require an active Mission Team")
        profile = self._ledger.management_profiles.get(requested_by_employee_id)
        if (
            profile is None
            or not profile.active
            or profile.version != contract.management_profile_version
        ):
            raise ValueError("staffing requests require the contract's pinned management profile")

        counts = Counter[str]()
        for need in needs:
            counts[need.profession] += need.count
        normalized = tuple(StaffingNeed(profession, count) for profession, count in sorted(counts.items()))
        if profile.allowed_professions and not set(counts).issubset(profile.allowed_professions):
            raise ValueError("staffing request names a profession outside approved profession authority")
        current_members = self._ledger.team_members.members_of(contract.team_id)
        if len(current_members) + sum(counts.values()) > contract.max_team_size:
            raise ValueError("staffing request exceeds the pinned contract Team size")

        existing_candidates = Counter(
            employee.role
            for employee in self._workforce.list()
            if employee.reports_to == requested_by_employee_id
            and employee.id not in {member.employee_id for member in current_members}
            and invokability_block(self._workforce, employee.id) is None
        )
        if all(existing_candidates[profession] >= count for profession, count in counts.items()):
            raise ValueError("existing legal Team candidates already cover the staffing request")

        candidate = StaffingRequest(
            id=mint_id("staffing-request"),
            task_id=task.id,
            goal_id=task.goal_id,
            team_id=contract.team_id,
            requested_by_employee_id=requested_by_employee_id,
            rationale=rationale,
            needs=normalized,
        )
        for existing in self._ledger.staffing_requests.list(status=StaffingRequestStatus.OPEN):
            if (
                existing.task_id == candidate.task_id
                and existing.requested_by_employee_id == candidate.requested_by_employee_id
                and existing.needs == candidate.needs
            ):
                return existing
        with self._ledger.transaction():
            persisted = self._ledger.staffing_requests.create(candidate)
            record_activity(
                self._ledger,
                verb=ActivityVerb.STAFFING_REQUESTED,
                subject_kind="staffing_request",
                subject_id=persisted.id,
                actor_employee_id=requested_by_employee_id,
                payload={
                    "task_id": task.id,
                    "goal_id": task.goal_id,
                    "needs": dict(counts),
                },
            )
        return persisted


__all__ = ["StaffingRequestService"]