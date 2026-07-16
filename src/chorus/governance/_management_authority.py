"""Human-governed mutation facade for persisted management authority."""

from __future__ import annotations

from dataclasses import replace

from chorus.errors import ActiveDelegationConflict
from chorus.ledger import (
    ActivityVerb,
    DelegationContract,
    DelegationContractStatus,
    ManagementProfile,
    SqliteLedger,
    Team,
    TeamMember,
)
from chorus.lifecycle._audit import record_activity
from chorus.roles import RoleRegistry


class ManagementAuthorityService:
    """Apply management-authority policy mutations atomically and audit the human decision."""

    def __init__(self, ledger: SqliteLedger) -> None:
        self._ledger = ledger

    def upsert_profile(
        self, profile: ManagementProfile, *, actor_user_id: str
    ) -> ManagementProfile:
        actor_user_id = _require_human_actor(actor_user_id)
        governed = replace(profile, granted_by_user_id=actor_user_id)
        with self._ledger.transaction():
            persisted = self._ledger.management_profiles.upsert(governed)
            record_activity(
                self._ledger,
                verb=ActivityVerb.PROFILE_GRANTED,
                subject_kind="management_profile",
                subject_id=persisted.employee_id,
                actor_user_id=actor_user_id,
                payload={"version": persisted.version},
            )
        return persisted

    def specialize_manager(
        self,
        employee_id: str,
        *,
        profession: str,
        profile: ManagementProfile,
        roles: RoleRegistry,
        actor_user_id: str,
    ) -> ManagementProfile:
        """Atomically migrate an ambiguous Manager row to an explicit profession and profile."""
        actor_user_id = _require_human_actor(actor_user_id)
        profession = profession.strip()
        if not profession or profession == "manager" or profession not in roles:
            raise ValueError(f"profession {profession!r} is not a valid specialist profession")
        employee = self._ledger.employees.get(employee_id)
        if employee is None:
            raise ValueError(f"no such employee: {employee_id!r}")
        if employee.role != "manager":
            raise ValueError(
                f"employee {employee_id!r} must have role='manager' before specialization"
            )
        if profile.employee_id != employee_id:
            raise ValueError("management profile employee_id must match the migrated employee")
        if self._ledger.tasks.has_unresolved_for_assignee(employee_id):
            raise ValueError(f"active work blocks specialization of {employee_id!r}")
        contract_refs = self._ledger.employees.active_contract_refs(employee_id)
        if contract_refs:
            from chorus.errors import ActiveDelegationConflict

            raise ActiveDelegationConflict(contract_refs=contract_refs)

        governed = replace(profile, granted_by_user_id=actor_user_id)
        with self._ledger.transaction():
            self._ledger.employees.set_role(employee_id, profession)
            persisted = self._ledger.management_profiles.upsert(governed)
            record_activity(
                self._ledger,
                verb=ActivityVerb.PROFILE_GRANTED,
                subject_kind="management_profile",
                subject_id=employee_id,
                actor_user_id=actor_user_id,
                payload={"profession": profession, "version": persisted.version},
            )
        return persisted

    def deactivate_profile(
        self, employee_id: str, *, actor_user_id: str
    ) -> ManagementProfile:
        actor_user_id = _require_human_actor(actor_user_id)
        try:
            with self._ledger.transaction():
                persisted = self._ledger.management_profiles.deactivate(employee_id)
                record_activity(
                    self._ledger,
                    verb=ActivityVerb.PROFILE_REVOKED,
                    subject_kind="management_profile",
                    subject_id=employee_id,
                    actor_user_id=actor_user_id,
                    payload={"version": persisted.version},
                )
        except ActiveDelegationConflict as conflict:
            record_activity(
                self._ledger,
                verb=ActivityVerb.REORG_REFUSED,
                subject_kind="management_profile",
                subject_id=employee_id,
                actor_user_id=actor_user_id,
                payload={
                    "operation": "deactivate_profile",
                    "contract_task_ids": list(conflict.task_ids),
                    "team_ids": list(conflict.team_ids),
                },
            )
            raise
        return persisted

    def create_team(self, team: Team, *, actor_user_id: str) -> Team:
        actor_user_id = _require_human_actor(actor_user_id)
        governed = replace(team, created_by=actor_user_id)
        with self._ledger.transaction():
            persisted = self._ledger.teams.create(governed)
            record_activity(
                self._ledger,
                verb=ActivityVerb.TEAM_FORMED,
                subject_kind="team",
                subject_id=persisted.id,
                actor_user_id=actor_user_id,
                payload={"policy_version": persisted.policy_version},
            )
        return persisted

    def archive_team(self, team_id: str, *, actor_user_id: str) -> Team:
        actor_user_id = _require_human_actor(actor_user_id)
        with self._ledger.transaction():
            persisted = self._ledger.teams.archive(team_id)
            record_activity(
                self._ledger,
                verb=ActivityVerb.TEAM_ARCHIVED,
                subject_kind="team",
                subject_id=team_id,
                actor_user_id=actor_user_id,
            )
        return persisted

    def add_team_member(
        self, member: TeamMember, *, actor_user_id: str
    ) -> TeamMember:
        actor_user_id = _require_human_actor(actor_user_id)
        subject_id = f"{member.team_id}/{member.employee_id}"
        with self._ledger.transaction():
            persisted = self._ledger.team_members.add(member)
            record_activity(
                self._ledger,
                verb=ActivityVerb.TEAM_MEMBER_ADDED,
                subject_kind="team_member",
                subject_id=subject_id,
                actor_user_id=actor_user_id,
            )
        return persisted

    def remove_team_member(
        self, team_id: str, employee_id: str, *, actor_user_id: str
    ) -> TeamMember:
        actor_user_id = _require_human_actor(actor_user_id)
        subject_id = f"{team_id}/{employee_id}"
        with self._ledger.transaction():
            persisted = self._ledger.team_members.remove(team_id, employee_id)
            record_activity(
                self._ledger,
                verb=ActivityVerb.TEAM_MEMBER_REMOVED,
                subject_kind="team_member",
                subject_id=subject_id,
                actor_user_id=actor_user_id,
            )
        return persisted

    def create_delegation_contract(
        self, contract: DelegationContract, *, actor_user_id: str
    ) -> DelegationContract:
        actor_user_id = _require_human_actor(actor_user_id)
        with self._ledger.transaction():
            persisted = self._ledger.delegation_contracts.create(contract)
            record_activity(
                self._ledger,
                verb=ActivityVerb.DELEGATION_CREATED,
                subject_kind="delegation_contract",
                subject_id=persisted.task_id,
                actor_user_id=actor_user_id,
                payload={
                    "management_profile_version": persisted.management_profile_version,
                    "team_id": persisted.team_id,
                },
            )
        return persisted

    def update_delegation_contract_status(
        self,
        task_id: str,
        status: DelegationContractStatus,
        *,
        actor_user_id: str,
    ) -> DelegationContract:
        actor_user_id = _require_human_actor(actor_user_id)
        with self._ledger.transaction():
            persisted = self._ledger.delegation_contracts.update_status(task_id, status)
            record_activity(
                self._ledger,
                verb=ActivityVerb.DELEGATION_STATUS_CHANGED,
                subject_kind="delegation_contract",
                subject_id=task_id,
                actor_user_id=actor_user_id,
                payload={"status": persisted.status.value},
            )
        return persisted


def _require_human_actor(actor_user_id: str) -> str:
    actor_user_id = actor_user_id.strip()
    if not actor_user_id:
        raise ValueError("actor_user_id must identify the governing human")
    return actor_user_id


__all__ = ["ManagementAuthorityService"]