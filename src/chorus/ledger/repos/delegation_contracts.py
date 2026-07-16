"""Persistence for delegation contracts with pinned authority (M8 §5.6)."""

from __future__ import annotations

import builtins
import sqlite3

from chorus.ledger._models import DelegationContract, DelegationContractStatus
from chorus.ledger.repos._base import from_iso, require_persisted, utcnow_iso


class DelegationContractRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(self, contract: DelegationContract) -> DelegationContract:
        now = utcnow_iso()
        self._conn.execute(
            "INSERT INTO delegation_contract (task_id, team_id, lead_employee_id, "
            "management_profile_version, parent_contract_task_id, can_subdelegate, max_depth, "
            "max_team_size, max_direct_children, spend_limit_cents, objective_rubric, status, "
            "accepted_run_id, accepted_at, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                contract.task_id,
                contract.team_id,
                contract.lead_employee_id,
                contract.management_profile_version,
                contract.parent_contract_task_id,
                int(contract.can_subdelegate),
                contract.max_depth,
                contract.max_team_size,
                contract.max_direct_children,
                contract.spend_limit_cents,
                contract.objective_rubric,
                contract.status.value,
                contract.accepted_run_id,
                None,
                now,
                now,
            ),
        )
        self._conn.commit()
        return require_persisted(self.get(contract.task_id), contract.task_id)

    def get(self, task_id: str) -> DelegationContract | None:
        row = self._conn.execute(
            "SELECT * FROM delegation_contract WHERE task_id = ?", (task_id,)
        ).fetchone()
        return _row_to_contract(row) if row is not None else None

    def list(self) -> builtins.list[DelegationContract]:
        """Every delegation contract, including completed history."""
        rows = self._conn.execute(
            "SELECT * FROM delegation_contract ORDER BY created_at, task_id"
        ).fetchall()
        return [_row_to_contract(row) for row in rows]

    def active_for_task(self, task_id: str) -> DelegationContract | None:
        contract = self.get(task_id)
        if contract is None or contract.status is DelegationContractStatus.DONE:
            return None
        return contract

    def active_for_employee(self, employee_id: str) -> builtins.list[DelegationContract]:
        rows = self._conn.execute(
            "SELECT DISTINCT dc.* FROM delegation_contract dc "
            "LEFT JOIN team_member tm ON tm.team_id = dc.team_id AND tm.left_at IS NULL "
            "WHERE dc.status <> 'done' AND (dc.lead_employee_id = ? OR tm.employee_id = ?) "
            "ORDER BY dc.created_at, dc.task_id",
            (employee_id, employee_id),
        ).fetchall()
        return [_row_to_contract(row) for row in rows]

    def active_contracts_involving(self, employee_id: str) -> builtins.list[DelegationContract]:
        return self.active_for_employee(employee_id)

    def landed_awaiting_closure(self) -> builtins.list[DelegationContract]:
        """Contracts whose verified parent landed before contract closure completed."""
        rows = self._conn.execute(
            "SELECT dc.* FROM delegation_contract dc "
            "JOIN task t ON t.id = dc.task_id "
            "WHERE dc.status = ? AND t.status = 'done' "
            "ORDER BY dc.created_at, dc.task_id",
            (DelegationContractStatus.VERIFYING.value,),
        ).fetchall()
        return [_row_to_contract(row) for row in rows]

    def update_status(self, task_id: str, status: DelegationContractStatus) -> DelegationContract:
        self._conn.execute(
            "UPDATE delegation_contract SET status = ?, updated_at = ? WHERE task_id = ?",
            (status.value, utcnow_iso(), task_id),
        )
        self._conn.commit()
        return require_persisted(self.get(task_id), task_id)

    def accept_for_verification(self, task_id: str, run_id: str) -> DelegationContract:
        """Persist explicit lead acceptance and enter independent verification."""
        now = utcnow_iso()
        self._conn.execute(
            "UPDATE delegation_contract SET status = ?, accepted_run_id = ?, accepted_at = ?, "
            "updated_at = ? WHERE task_id = ?",
            (DelegationContractStatus.VERIFYING.value, run_id, now, now, task_id),
        )
        self._conn.commit()
        return require_persisted(self.get(task_id), task_id)


def _row_to_contract(row: sqlite3.Row) -> DelegationContract:
    return DelegationContract(
        task_id=row["task_id"],
        team_id=row["team_id"],
        lead_employee_id=row["lead_employee_id"],
        management_profile_version=row["management_profile_version"],
        parent_contract_task_id=row["parent_contract_task_id"],
        can_subdelegate=bool(row["can_subdelegate"]),
        max_depth=row["max_depth"],
        max_team_size=row["max_team_size"],
        max_direct_children=row["max_direct_children"],
        spend_limit_cents=row["spend_limit_cents"],
        objective_rubric=row["objective_rubric"],
        status=DelegationContractStatus(row["status"]),
        accepted_run_id=row["accepted_run_id"],
        accepted_at=from_iso(row["accepted_at"]),
        created_at=from_iso(row["created_at"]),
        updated_at=from_iso(row["updated_at"]),
    )
