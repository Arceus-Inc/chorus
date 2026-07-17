"""ApprovalRepo — the human gate (spec 01 Cluster G ``approval``, spec 04 §5).

``request`` opens a ``pending`` gate; the partial-unique ``approval_subject_pending_uq`` index makes
it exact-once — a second pending request for the same subject raises ``IntegrityError``. ``approve``
/ ``deny`` stamp the resolving user + timestamp, which frees the subject for a future gate.
"""

from __future__ import annotations

from chorus.ledger._models import (
    Approval,
    ApprovalAction,
    ApprovalGate,
    ApprovalStatus,
    ApprovalSubjectKind,
)
from chorus.ledger.repos._base import (
    LedgerConnection,
    LedgerRow,
    from_iso,
    require_persisted,
    utcnow_iso,
)


class ApprovalRepo:
    """Open, resolve, and read ``approval`` rows."""

    def __init__(self, conn: LedgerConnection) -> None:
        self._conn = conn

    def request(self, approval: Approval) -> Approval:
        """Open a pending gate; the exact-once index rejects a duplicate open subject."""
        now = utcnow_iso()
        self._conn.execute(
            "INSERT INTO approval (id, subject_kind, subject_id, reason, action, status, gate_kind, "
            "decided_by_user_id, decided_at, expires_at, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)",
            (
                approval.id,
                approval.subject_kind.value,
                approval.subject_id,
                approval.reason,
                approval.action.value,
                ApprovalStatus.PENDING.value,
                approval.gate_kind.value if approval.gate_kind else None,
                approval.expires_at.isoformat() if approval.expires_at else None,
                now,
            ),
        )
        self._conn.commit()
        opened = require_persisted(self.get(approval.id), approval.id)
        return opened

    def approve(self, approval_id: str, *, decided_by_user_id: str) -> None:
        self.set_status(approval_id, ApprovalStatus.APPROVED, decided_by_user_id=decided_by_user_id)

    def deny(self, approval_id: str, *, decided_by_user_id: str) -> None:
        self.set_status(approval_id, ApprovalStatus.DENIED, decided_by_user_id=decided_by_user_id)

    def set_status(
        self, approval_id: str, status: ApprovalStatus, *, decided_by_user_id: str
    ) -> None:
        """Resolve a pending gate to any terminal status (approved / denied / revision_requested).

        Stamps the decider + timestamp and only acts on a still-``pending`` row, so the resolution is
        idempotent and frees the subject's exact-once gate (spec 04 §5)."""
        now = utcnow_iso()
        self._conn.execute(
            "UPDATE approval SET status = ?, decided_by_user_id = ?, decided_at = ? "
            "WHERE id = ? AND status = 'pending'",
            (status.value, decided_by_user_id, now, approval_id),
        )
        self._conn.commit()

    def get(self, approval_id: str) -> Approval | None:
        row = self._conn.execute("SELECT * FROM approval WHERE id = ?", (approval_id,)).fetchone()
        return _row_to_approval(row) if row is not None else None

    def for_subject(self, subject_id: str) -> list[Approval]:
        """Every gate ever opened on ``subject_id``, newest first — any status.

        The go-live executor resolves a task's gate with this (fail-closed on its status), so the
        model never has to remember an approval id across beats.
        """
        rows = self._conn.execute(
            "SELECT * FROM approval WHERE subject_id = ? ORDER BY created_at DESC, id DESC",
            (subject_id,),
        ).fetchall()
        return [_row_to_approval(row) for row in rows]

    def pending(self) -> list[Approval]:
        """Open gates that have not lapsed, oldest first.

        A pending row whose ``expires_at`` is in the past is treated as lapsed and excluded — it no
        longer holds the subject's exact-once gate open.
        """
        now = utcnow_iso()
        rows = self._conn.execute(
            "SELECT * FROM approval WHERE status = 'pending' "
            "AND (expires_at IS NULL OR expires_at > ?) ORDER BY created_at, id",
            (now,),
        ).fetchall()
        return [_row_to_approval(row) for row in rows]


def _row_to_approval(row: LedgerRow) -> Approval:
    return Approval(
        id=row["id"],
        subject_kind=ApprovalSubjectKind(row["subject_kind"]),
        subject_id=row["subject_id"],
        reason=row["reason"],
        action=ApprovalAction(row["action"]),
        status=ApprovalStatus(row["status"]),
        gate_kind=ApprovalGate(row["gate_kind"]) if row["gate_kind"] else None,
        decided_by_user_id=row["decided_by_user_id"],
        decided_at=from_iso(row["decided_at"]),
        expires_at=from_iso(row["expires_at"]),
        created_at=from_iso(row["created_at"]),
    )
