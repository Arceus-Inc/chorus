"""Per-goal Mission Team lifecycle policy for M8 delegation."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from chorus.ledger._models import (
    ActivityVerb,
    Team,
    TeamMember,
    TeamMembershipRole,
    TeamStatus,
)
from chorus.lifecycle._audit import record_activity
from chorus.workforce import Employee, EmployeeStatus

if TYPE_CHECKING:
    from chorus.ledger import SqliteLedger

_UNAVAILABLE = frozenset({EmployeeStatus.PENDING, EmployeeStatus.TERMINATED})


class MissionTeamPolicyDenied(ValueError):
    """The requested Team lifecycle mutation is outside the mission-Team policy."""


class MissionTeamPolicy:
    """Create, validate, activate, and archive one durable Team per delegated goal."""

    def __init__(self, ledger: SqliteLedger) -> None:
        self._ledger = ledger

    def create_for_root(self, lead: Employee, goal_id: str) -> Team:
        goal_id = goal_id.strip()
        if not goal_id:
            raise MissionTeamPolicyDenied("mission Teams require a goal_id")
        persisted_lead = self._eligible_lead(lead.id)
        existing = self._ledger.teams.for_goal(goal_id)
        if existing is not None:
            if existing.lead_employee_id != persisted_lead.id:
                raise MissionTeamPolicyDenied(
                    f"goal {goal_id!r} already belongs to lead {existing.lead_employee_id!r}"
                )
            return existing

        team = Team(
            id=_team_id(goal_id),
            name=f"Mission: {goal_id}",
            lead_employee_id=persisted_lead.id,
            goal_id=goal_id,
            status=TeamStatus.FORMING,
            created_by="mission_team_policy",
        )
        lead_member = TeamMember(
            team_id=team.id,
            employee_id=persisted_lead.id,
            membership_role=TeamMembershipRole.LEAD,
            source_manager_id=persisted_lead.reports_to or persisted_lead.id,
        )
        with self._ledger.transaction():
            created = self._ledger.teams.create(team)
            self._ledger.team_members.add(lead_member)
            self._audit_team(ActivityVerb.TEAM_FORMED, created.id)
            self._audit_member(ActivityVerb.TEAM_MEMBER_ADDED, lead_member)
        return created

    def create_for_delegation(
        self,
        lead: Employee,
        *,
        goal_id: str,
        parent_team_id: str,
        delegation_task_id: str,
    ) -> Team:
        """Create the nested Team owned by one delegation-mode child task."""
        persisted_lead = self._eligible_lead(lead.id)
        parent = self._require_team(parent_team_id)
        if parent.status is not TeamStatus.ACTIVE:
            raise MissionTeamPolicyDenied("nested Teams require an active parent Team")
        team_id = _nested_team_id(parent_team_id, delegation_task_id)
        existing = self._ledger.teams.get(team_id)
        if existing is not None:
            if existing.lead_employee_id != persisted_lead.id:
                raise MissionTeamPolicyDenied(
                    f"delegation {delegation_task_id!r} already belongs to another lead"
                )
            return existing

        team = Team(
            id=team_id,
            name=f"Mission delegation: {delegation_task_id}",
            lead_employee_id=persisted_lead.id,
            goal_id=goal_id,
            parent_team_id=parent.id,
            status=TeamStatus.FORMING,
            created_by="mission_team_policy",
        )
        lead_member = TeamMember(
            team_id=team.id,
            employee_id=persisted_lead.id,
            membership_role=TeamMembershipRole.LEAD,
            source_manager_id=parent.lead_employee_id,
        )
        with self._ledger.transaction():
            created = self._ledger.teams.create(team)
            self._ledger.team_members.add(lead_member)
            self._audit_team(ActivityVerb.TEAM_FORMED, created.id)
            self._audit_member(ActivityVerb.TEAM_MEMBER_ADDED, lead_member)
        return created

    def validate_membership(self, team_id: str, candidate_employee_id: str) -> bool:
        team = self._ledger.teams.get(team_id)
        candidate = self._ledger.employees.get(candidate_employee_id)
        if team is None or candidate is None:
            return False
        if team.status not in {TeamStatus.FORMING, TeamStatus.ACTIVE}:
            return False
        try:
            self._eligible_lead(team.lead_employee_id)
        except MissionTeamPolicyDenied:
            return False
        if candidate.status in _UNAVAILABLE:
            return False
        if candidate.id == team.lead_employee_id:
            return True
        if candidate.reports_to != team.lead_employee_id:
            return False
        profile = self._ledger.management_profiles.get(team.lead_employee_id)
        return profile is not None and (
            not profile.allowed_professions or candidate.role in profile.allowed_professions
        )

    def add_member(
        self,
        team_id: str,
        candidate_employee_id: str,
        *,
        can_subdelegate: bool = False,
    ) -> TeamMember:
        if not self.validate_membership(team_id, candidate_employee_id):
            raise MissionTeamPolicyDenied(
                f"employee {candidate_employee_id!r} is not eligible for Team membership"
            )
        existing = self._ledger.team_members.get(team_id, candidate_employee_id)
        if existing is not None and existing.left_at is None:
            if existing.can_subdelegate != can_subdelegate:
                raise MissionTeamPolicyDenied(
                    "active Team membership has a different subdelegation grant"
                )
            return existing
        team = self._require_team(team_id)
        member = TeamMember(
            team_id=team_id,
            employee_id=candidate_employee_id,
            can_subdelegate=can_subdelegate,
            source_manager_id=team.lead_employee_id,
        )
        with self._ledger.transaction():
            added = self._ledger.team_members.add(member)
            self._audit_member(ActivityVerb.TEAM_MEMBER_ADDED, added)
        return added

    def activate(self, team_id: str) -> Team:
        team = self._require_team(team_id)
        if team.status is TeamStatus.ACTIVE:
            return team
        if team.status is not TeamStatus.FORMING:
            raise MissionTeamPolicyDenied(
                f"Team {team_id!r} cannot activate from {team.status.value!r}"
            )
        with self._ledger.transaction():
            activated = self._ledger.teams.activate(team_id)
            self._audit_team(ActivityVerb.TEAM_ACTIVATED, team_id)
        return activated

    def archive(self, team_id: str) -> Team:
        team = self._require_team(team_id)
        if team.status is TeamStatus.ARCHIVED:
            return team
        with self._ledger.transaction():
            archived = self._ledger.teams.archive(team_id)
            self._audit_team(ActivityVerb.TEAM_ARCHIVED, team_id)
        return archived

    def _eligible_lead(self, employee_id: str) -> Employee:
        lead = self._ledger.employees.get(employee_id)
        profile = self._ledger.management_profiles.get(employee_id)
        if (
            lead is None
            or lead.status in _UNAVAILABLE
            or profile is None
            or not profile.active
            or not profile.can_lead
        ):
            raise MissionTeamPolicyDenied(
                f"employee {employee_id!r} requires an active lead profile"
            )
        return lead

    def _require_team(self, team_id: str) -> Team:
        team = self._ledger.teams.get(team_id)
        if team is None:
            raise MissionTeamPolicyDenied(f"no such Team: {team_id!r}")
        return team

    def _audit_team(self, verb: ActivityVerb, team_id: str) -> None:
        record_activity(
            self._ledger,
            verb=verb,
            subject_kind="team",
            subject_id=team_id,
        )

    def _audit_member(self, verb: ActivityVerb, member: TeamMember) -> None:
        record_activity(
            self._ledger,
            verb=verb,
            subject_kind="team_member",
            subject_id=f"{member.team_id}/{member.employee_id}",
        )


def _team_id(goal_id: str) -> str:
    digest = hashlib.sha1(goal_id.encode()).hexdigest()[:16]
    return f"team_{digest}"


def _nested_team_id(parent_team_id: str, delegation_task_id: str) -> str:
    digest = hashlib.sha1(f"{parent_team_id}::{delegation_task_id}".encode()).hexdigest()[:16]
    return f"team_{digest}"


__all__ = ["MissionTeamPolicy", "MissionTeamPolicyDenied"]
