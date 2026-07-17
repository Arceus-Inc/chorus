"""BudgetIncidentRepo — budget breach records (spec 01 Cluster E ``budget_incident``, spec 04).

``open`` records a breach; the partial-unique ``budget_incident_window_uq`` index allows only one live
incident per policy/window/threshold (a ``dismiss`` frees the window). A hard breach gets an
:class:`Approval` via ``attach_approval`` — the gate a human resolves to release the blocked work.
"""

from __future__ import annotations

from chorus.ledger._models import BudgetIncident, BudgetIncidentStatus, BudgetThreshold
from chorus.ledger.repos._base import (
    LedgerConnection,
    LedgerRow,
    from_iso,
    require_persisted,
    to_iso,
    utcnow_iso,
)


class BudgetIncidentRepo:
    """Open, resolve, dismiss, and gate ``budget_incident`` rows."""

    def __init__(self, conn: LedgerConnection) -> None:
        self._conn = conn

    def open(self, incident: BudgetIncident) -> BudgetIncident:
        """Record a breach; the window index rejects a second live incident for the window."""
        now = utcnow_iso()
        self._conn.execute(
            "INSERT INTO budget_incident (id, policy_id, threshold_type, amount_limit, "
            "amount_observed, window_start, status, approval_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                incident.id,
                incident.policy_id,
                incident.threshold_type.value,
                incident.amount_limit,
                incident.amount_observed,
                to_iso(incident.window_start),
                BudgetIncidentStatus.OPEN.value,
                incident.approval_id,
                now,
            ),
        )
        self._conn.commit()
        opened = require_persisted(self.get(incident.id), incident.id)
        return opened

    def get(self, incident_id: str) -> BudgetIncident | None:
        row = self._conn.execute(
            "SELECT * FROM budget_incident WHERE id = ?", (incident_id,)
        ).fetchone()
        return _row_to_incident(row) if row is not None else None

    def attach_approval(self, incident_id: str, approval_id: str) -> None:
        """Point an *open hard* breach at the approval that gates its release."""
        incident = self.get(incident_id)
        if incident is None:
            raise KeyError(incident_id)
        if incident.status is not BudgetIncidentStatus.OPEN:
            raise ValueError(f"incident {incident_id} is {incident.status.value}, not open")
        if incident.threshold_type is not BudgetThreshold.HARD:
            raise ValueError("only hard incidents gate on an approval")
        self._conn.execute(
            "UPDATE budget_incident SET approval_id = ? WHERE id = ?", (approval_id, incident_id)
        )
        self._conn.commit()

    def resolve(self, incident_id: str) -> None:
        """Resolve an open incident; a hard incident needs an *approved* approval first."""
        incident = self.get(incident_id)
        if incident is None:
            raise KeyError(incident_id)
        if incident.threshold_type is BudgetThreshold.HARD and not self._is_approved(
            incident.approval_id
        ):
            raise ValueError(
                f"hard incident {incident_id} needs an approved approval before it can resolve"
            )
        self._conn.execute(
            "UPDATE budget_incident SET status = 'resolved' WHERE id = ? AND status = 'open'",
            (incident_id,),
        )
        self._conn.commit()

    def dismiss(self, incident_id: str) -> None:
        """Dismiss an *open* incident, freeing the window for a fresh one."""
        self._conn.execute(
            "UPDATE budget_incident SET status = 'dismissed' WHERE id = ? AND status = 'open'",
            (incident_id,),
        )
        self._conn.commit()

    def _is_approved(self, approval_id: str | None) -> bool:
        if approval_id is None:
            return False
        row = self._conn.execute(
            "SELECT status FROM approval WHERE id = ?", (approval_id,)
        ).fetchone()
        return row is not None and row["status"] == "approved"

    def open_for_policy(self, policy_id: str) -> list[BudgetIncident]:
        """Open incidents for a policy, oldest first."""
        rows = self._conn.execute(
            "SELECT * FROM budget_incident WHERE policy_id = ? AND status = 'open' "
            "ORDER BY created_at, id",
            (policy_id,),
        ).fetchall()
        return [_row_to_incident(row) for row in rows]


def _row_to_incident(row: LedgerRow) -> BudgetIncident:
    window_start = from_iso(row["window_start"])
    assert window_start is not None  # window_start is NOT NULL in the schema
    return BudgetIncident(
        id=row["id"],
        policy_id=row["policy_id"],
        threshold_type=BudgetThreshold(row["threshold_type"]),
        amount_limit=row["amount_limit"],
        amount_observed=row["amount_observed"],
        window_start=window_start,
        status=BudgetIncidentStatus(row["status"]),
        approval_id=row["approval_id"],
        created_at=from_iso(row["created_at"]),
    )
