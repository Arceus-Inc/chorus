"""Persistence for immutable workforce-plan revisions and their typed children."""

from __future__ import annotations

from dataclasses import replace

from chorus.ledger._models import (
    ManagementGrantDraft,
    PlannedEmployee,
    WorkforcePlan,
    WorkforcePlanDraft,
    WorkforcePlanStatus,
)
from chorus.ledger.repos._base import (
    LedgerConnection,
    LedgerRow,
    dumps,
    from_iso,
    require_persisted,
    utcnow_iso,
)


class WorkforcePlanRepo:
    """Store and retrieve complete normalized plan revisions."""

    def __init__(self, conn: LedgerConnection) -> None:
        self._conn = conn

    def create(self, plan: WorkforcePlan) -> WorkforcePlan:
        now = utcnow_iso()
        self._conn.execute(
            "INSERT INTO workforce_plan (id, revision, status, proposed_by_employee_id, "
            "rationale, confidence, source_goal_ids, revised_by_user_id, decided_by_user_id, "
            "staffing_request_id, created_at, decided_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                plan.id,
                plan.revision,
                plan.status.value,
                plan.proposed_by_employee_id,
                plan.draft.rationale,
                plan.draft.confidence,
                dumps(list(plan.draft.source_goal_ids)),
                plan.revised_by_user_id,
                plan.decided_by_user_id,
                plan.staffing_request_id,
                now,
                plan.decided_at.isoformat() if plan.decided_at is not None else None,
            ),
        )
        for position, employee in enumerate(plan.draft.employees):
            self._conn.execute(
                "INSERT INTO workforce_plan_employee (plan_id, plan_revision, employee_ref, name, "
                "profession, reports_to_ref, responsibilities, budget_cents, position) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    plan.id,
                    plan.revision,
                    employee.ref,
                    employee.name,
                    employee.profession,
                    employee.reports_to_ref,
                    dumps(list(employee.responsibilities)),
                    employee.budget_cents,
                    position,
                ),
            )
        for position, grant in enumerate(plan.draft.management_grants):
            self._conn.execute(
                "INSERT INTO workforce_plan_management_grant (plan_id, plan_revision, employee_ref, "
                "can_lead, can_subdelegate, max_delegation_depth, max_team_size, "
                "allowed_professions, spend_limit_cents, position) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    plan.id,
                    plan.revision,
                    grant.employee_ref,
                    grant.can_lead,
                    grant.can_subdelegate,
                    grant.max_delegation_depth,
                    grant.max_team_size,
                    dumps(list(grant.allowed_professions)),
                    grant.spend_limit_cents,
                    position,
                ),
            )
        self._conn.commit()
        return require_persisted(self.get(plan.id, revision=plan.revision), plan.id)

    def get(self, plan_id: str, *, revision: int) -> WorkforcePlan | None:
        row = self._conn.execute(
            "SELECT * FROM workforce_plan WHERE id = ? AND revision = ?",
            (plan_id, revision),
        ).fetchone()
        return self._row_to_plan(row) if row is not None else None

    def latest(self, plan_id: str) -> WorkforcePlan | None:
        row = self._conn.execute(
            "SELECT * FROM workforce_plan WHERE id = ? ORDER BY revision DESC LIMIT 1",
            (plan_id,),
        ).fetchone()
        return self._row_to_plan(row) if row is not None else None

    def list(self) -> list[WorkforcePlan]:
        rows = self._conn.execute("SELECT * FROM workforce_plan ORDER BY id, revision").fetchall()
        return [self._row_to_plan(row) for row in rows]

    def update_status(
        self,
        plan_id: str,
        revision: int,
        status: WorkforcePlanStatus,
        *,
        decided_by_user_id: str | None = None,
    ) -> WorkforcePlan:
        decided_at = utcnow_iso() if decided_by_user_id is not None else None
        self._conn.execute(
            "UPDATE workforce_plan SET status = ?, decided_by_user_id = ?, decided_at = ? "
            "WHERE id = ? AND revision = ?",
            (status.value, decided_by_user_id, decided_at, plan_id, revision),
        )
        self._conn.commit()
        persisted = require_persisted(self.get(plan_id, revision=revision), plan_id)
        return replace(persisted, status=status)

    def _row_to_plan(self, row: LedgerRow) -> WorkforcePlan:
        from chorus.ledger.repos._base import loads

        employee_rows = self._conn.execute(
            "SELECT * FROM workforce_plan_employee WHERE plan_id = ? AND plan_revision = ? "
            "ORDER BY position",
            (row["id"], row["revision"]),
        ).fetchall()
        grant_rows = self._conn.execute(
            "SELECT * FROM workforce_plan_management_grant WHERE plan_id = ? AND plan_revision = ? "
            "ORDER BY position",
            (row["id"], row["revision"]),
        ).fetchall()
        draft = WorkforcePlanDraft(
            rationale=row["rationale"],
            confidence=row["confidence"],
            source_goal_ids=tuple(loads(row["source_goal_ids"]) or ()),
            employees=tuple(
                PlannedEmployee(
                    ref=item["employee_ref"],
                    name=item["name"],
                    profession=item["profession"],
                    reports_to_ref=item["reports_to_ref"],
                    responsibilities=tuple(loads(item["responsibilities"]) or ()),
                    budget_cents=item["budget_cents"],
                )
                for item in employee_rows
            ),
            management_grants=tuple(
                ManagementGrantDraft(
                    employee_ref=item["employee_ref"],
                    can_lead=bool(item["can_lead"]),
                    can_subdelegate=bool(item["can_subdelegate"]),
                    max_delegation_depth=item["max_delegation_depth"],
                    max_team_size=item["max_team_size"],
                    allowed_professions=tuple(loads(item["allowed_professions"]) or ()),
                    spend_limit_cents=item["spend_limit_cents"],
                )
                for item in grant_rows
            ),
        )
        return WorkforcePlan(
            id=row["id"],
            revision=row["revision"],
            status=WorkforcePlanStatus(row["status"]),
            proposed_by_employee_id=row["proposed_by_employee_id"],
            draft=draft,
            revised_by_user_id=row["revised_by_user_id"],
            decided_by_user_id=row["decided_by_user_id"],
            staffing_request_id=row["staffing_request_id"],
            created_at=from_iso(row["created_at"]),
            decided_at=from_iso(row["decided_at"]),
        )


__all__ = ["WorkforcePlanRepo"]
