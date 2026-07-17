"""Persistence for versioned management authority profiles (M8 §5.2)."""

from __future__ import annotations

import builtins
import sqlite3

from chorus.errors import ActiveDelegationConflict
from chorus.ledger._models import ManagementProfile
from chorus.ledger.repos._base import dumps, from_iso, loads, require_persisted, utcnow_iso


class ManagementProfileRepo:
    """Create revisions and query the current profile keyed by employee."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def upsert(self, profile: ManagementProfile) -> ManagementProfile:
        current = self.get(profile.employee_id)
        if current is None and profile.version != 1:
            raise ValueError("a new management profile must start at version 1")
        if current is not None and profile.version <= current.version:
            raise ValueError(f"management profile version must increase beyond {current.version}")
        if current is not None and _weakens(current, profile):
            refs = self._active_contract_refs(profile.employee_id)
            if refs:
                raise ActiveDelegationConflict(contract_refs=refs)
        now = utcnow_iso()
        self._conn.execute(
            "INSERT INTO management_profile (employee_id, active, can_lead, can_subdelegate, "
            "max_delegation_depth, max_team_size, allowed_professions, spend_limit_cents, version, "
            "granted_by_user_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(employee_id) DO UPDATE SET active = excluded.active, "
            "can_lead = excluded.can_lead, can_subdelegate = excluded.can_subdelegate, "
            "max_delegation_depth = excluded.max_delegation_depth, "
            "max_team_size = excluded.max_team_size, "
            "allowed_professions = excluded.allowed_professions, "
            "spend_limit_cents = excluded.spend_limit_cents, version = excluded.version, "
            "granted_by_user_id = excluded.granted_by_user_id, updated_at = excluded.updated_at",
            (
                profile.employee_id,
                int(profile.active),
                int(profile.can_lead),
                int(profile.can_subdelegate),
                profile.max_delegation_depth,
                profile.max_team_size,
                dumps(list(profile.allowed_professions)),
                profile.spend_limit_cents,
                profile.version,
                profile.granted_by_user_id,
                now,
                now,
            ),
        )
        self._conn.commit()
        return require_persisted(self.get(profile.employee_id), profile.employee_id)

    def get(self, employee_id: str) -> ManagementProfile | None:
        row = self._conn.execute(
            "SELECT * FROM management_profile WHERE employee_id = ?", (employee_id,)
        ).fetchone()
        return _row_to_profile(row) if row is not None else None

    def for_employee(self, employee_id: str) -> ManagementProfile | None:
        return self.get(employee_id)

    def active_profiles(self) -> builtins.list[ManagementProfile]:
        rows = self._conn.execute(
            "SELECT * FROM management_profile WHERE active = 1 ORDER BY employee_id"
        ).fetchall()
        return [_row_to_profile(row) for row in rows]

    def list(self) -> builtins.list[ManagementProfile]:
        """Every current profile, including inactive authority history."""
        rows = self._conn.execute(
            "SELECT * FROM management_profile ORDER BY employee_id"
        ).fetchall()
        return [_row_to_profile(row) for row in rows]

    def deactivate(self, employee_id: str) -> ManagementProfile:
        current = self.get(employee_id)
        if current is None:
            raise KeyError(employee_id)
        return self.upsert(
            ManagementProfile(
                **{
                    **current.__dict__,
                    "active": False,
                    "version": current.version + 1,
                }
            )
        )

    def _active_contract_refs(self, employee_id: str) -> builtins.list[tuple[str, str]]:
        rows = self._conn.execute(
            "SELECT task_id, team_id FROM delegation_contract "
            "WHERE lead_employee_id = ? AND status <> 'done' ORDER BY task_id",
            (employee_id,),
        ).fetchall()
        return [(row["task_id"], row["team_id"]) for row in rows]


def _row_to_profile(row: sqlite3.Row) -> ManagementProfile:
    return ManagementProfile(
        employee_id=row["employee_id"],
        active=bool(row["active"]),
        can_lead=bool(row["can_lead"]),
        can_subdelegate=bool(row["can_subdelegate"]),
        max_delegation_depth=row["max_delegation_depth"],
        max_team_size=row["max_team_size"],
        allowed_professions=tuple(loads(row["allowed_professions"]) or ()),
        spend_limit_cents=row["spend_limit_cents"],
        version=row["version"],
        granted_by_user_id=row["granted_by_user_id"],
        created_at=from_iso(row["created_at"]),
        updated_at=from_iso(row["updated_at"]),
    )


def _weakens(current: ManagementProfile, candidate: ManagementProfile) -> bool:
    professions_narrowed = (
        not current.allowed_professions and bool(candidate.allowed_professions)
    ) or (
        bool(current.allowed_professions)
        and bool(candidate.allowed_professions)
        and not set(current.allowed_professions).issubset(candidate.allowed_professions)
    )
    spend_narrowed = (
        current.spend_limit_cents is None and candidate.spend_limit_cents is not None
    ) or (
        current.spend_limit_cents is not None
        and candidate.spend_limit_cents is not None
        and candidate.spend_limit_cents < current.spend_limit_cents
    )
    return (
        (current.active and not candidate.active)
        or (current.can_lead and not candidate.can_lead)
        or (current.can_subdelegate and not candidate.can_subdelegate)
        or candidate.max_delegation_depth < current.max_delegation_depth
        or candidate.max_team_size < current.max_team_size
        or professions_narrowed
        or spend_narrowed
    )
