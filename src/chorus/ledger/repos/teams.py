"""Persistence for durable Teams and their membership history (M8 §5.4)."""

from __future__ import annotations

import sqlite3

from chorus.ledger._models import Team, TeamMember, TeamMembershipRole, TeamStatus
from chorus.ledger.repos._base import from_iso, require_persisted, utcnow_iso


class TeamRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(self, team: Team) -> Team:
        now = utcnow_iso()
        self._conn.execute(
            "INSERT INTO team (id, name, lead_employee_id, goal_id, parent_team_id, status, "
            "policy_version, created_by, created_at, activated_at, archived_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                team.id,
                team.name,
                team.lead_employee_id,
                team.goal_id,
                team.parent_team_id,
                team.status.value,
                team.policy_version,
                team.created_by,
                now,
                now if team.status is TeamStatus.ACTIVE else None,
                None,
            ),
        )
        self._conn.commit()
        return require_persisted(self.get(team.id), team.id)

    def get(self, team_id: str) -> Team | None:
        row = self._conn.execute("SELECT * FROM team WHERE id = ?", (team_id,)).fetchone()
        return _row_to_team(row) if row is not None else None

    def for_goal(self, goal_id: str) -> Team | None:
        row = self._conn.execute(
            "SELECT * FROM team WHERE goal_id = ? ORDER BY created_at, id LIMIT 1", (goal_id,)
        ).fetchone()
        return _row_to_team(row) if row is not None else None

    def activate(self, team_id: str) -> Team:
        self._conn.execute(
            "UPDATE team SET status = 'active', activated_at = COALESCE(activated_at, ?) "
            "WHERE id = ?",
            (utcnow_iso(), team_id),
        )
        self._conn.commit()
        return require_persisted(self.get(team_id), team_id)

    def archive(self, team_id: str) -> Team:
        self._conn.execute(
            "UPDATE team SET status = 'archived', archived_at = ? WHERE id = ?",
            (utcnow_iso(), team_id),
        )
        self._conn.commit()
        return require_persisted(self.get(team_id), team_id)

    def list_active(self) -> list[Team]:
        rows = self._conn.execute(
            "SELECT * FROM team WHERE status <> 'archived' ORDER BY created_at, id"
        ).fetchall()
        return [_row_to_team(row) for row in rows]

    def list(self) -> list[Team]:
        """Every Team, including archived history, in creation order."""
        rows = self._conn.execute("SELECT * FROM team ORDER BY created_at, id").fetchall()
        return [_row_to_team(row) for row in rows]


class TeamMemberRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def add(self, member: TeamMember) -> TeamMember:
        self._conn.execute(
            "INSERT INTO team_member (team_id, employee_id, membership_role, can_subdelegate, "
            "source_manager_id, joined_at, left_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                member.team_id,
                member.employee_id,
                member.membership_role.value,
                int(member.can_subdelegate),
                member.source_manager_id,
                utcnow_iso(),
                None,
            ),
        )
        self._conn.commit()
        return require_persisted(
            self.get(member.team_id, member.employee_id),
            f"{member.team_id}/{member.employee_id}",
        )

    def get(self, team_id: str, employee_id: str) -> TeamMember | None:
        row = self._conn.execute(
            "SELECT * FROM team_member WHERE team_id = ? AND employee_id = ?",
            (team_id, employee_id),
        ).fetchone()
        return _row_to_member(row) if row is not None else None

    def remove(self, team_id: str, employee_id: str) -> TeamMember:
        self._conn.execute(
            "UPDATE team_member SET left_at = ? WHERE team_id = ? AND employee_id = ? "
            "AND left_at IS NULL",
            (utcnow_iso(), team_id, employee_id),
        )
        self._conn.commit()
        return require_persisted(self.get(team_id, employee_id), f"{team_id}/{employee_id}")

    def members_of(self, team_id: str) -> list[TeamMember]:
        rows = self._conn.execute(
            "SELECT * FROM team_member WHERE team_id = ? AND left_at IS NULL "
            "ORDER BY joined_at, employee_id",
            (team_id,),
        ).fetchall()
        return [_row_to_member(row) for row in rows]

    def teams_for_employee(self, employee_id: str) -> list[TeamMember]:
        rows = self._conn.execute(
            "SELECT * FROM team_member WHERE employee_id = ? AND left_at IS NULL "
            "ORDER BY joined_at, team_id",
            (employee_id,),
        ).fetchall()
        return [_row_to_member(row) for row in rows]


def _row_to_team(row: sqlite3.Row) -> Team:
    return Team(
        id=row["id"],
        name=row["name"],
        lead_employee_id=row["lead_employee_id"],
        goal_id=row["goal_id"],
        parent_team_id=row["parent_team_id"],
        status=TeamStatus(row["status"]),
        policy_version=row["policy_version"],
        created_by=row["created_by"],
        created_at=from_iso(row["created_at"]),
        activated_at=from_iso(row["activated_at"]),
        archived_at=from_iso(row["archived_at"]),
    )


def _row_to_member(row: sqlite3.Row) -> TeamMember:
    return TeamMember(
        team_id=row["team_id"],
        employee_id=row["employee_id"],
        membership_role=TeamMembershipRole(row["membership_role"]),
        can_subdelegate=bool(row["can_subdelegate"]),
        source_manager_id=row["source_manager_id"],
        joined_at=from_iso(row["joined_at"]),
        left_at=from_iso(row["left_at"]),
    )
