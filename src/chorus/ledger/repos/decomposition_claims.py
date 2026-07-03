"""DecompositionClaimRepo — exact-once fan-out (spec 01 Cluster A ``decomposition_claim``).

``open`` records the claim *before* any child is created; the ``decomp_source_revision_uq`` index
makes it exact-once per ``(source_task_id, accepted_plan_revision_id)`` — a second open against the
same accepted plan raises ``IntegrityError``. A retry instead calls ``by_source_revision`` to resume
the existing claim. ``add_child`` appends one child id durably (idempotent, so a re-created child does
not duplicate the partial result); ``complete`` seals the claim.
"""

from __future__ import annotations

import sqlite3

from chorus.ledger._models import DecompositionClaim, DecompositionStatus
from chorus.ledger.repos._base import (
    dumps,
    from_iso,
    loads_list,
    require_persisted,
    utcnow_iso,
)


class DecompositionClaimRepo:
    """Open, resume, accumulate, and complete ``decomposition_claim`` rows."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def open(self, claim: DecompositionClaim) -> DecompositionClaim:
        """Record an in-flight claim before fan-out; the exact-once index rejects a second tree.

        ``child_task_ids`` is always initialized empty — fan-out is "open before any child is
        created", so only :meth:`add_child` may populate it. The accepted plan revision must belong
        to the source task (lineage guard) so a claim can't decompose task A with task B's plan.
        """
        self._require_revision_lineage(claim.source_task_id, claim.accepted_plan_revision_id)
        now = utcnow_iso()
        self._conn.execute(
            "INSERT INTO decomposition_claim (id, source_task_id, accepted_plan_revision_id, "
            "status, request_fingerprint, requested_children, child_task_ids, owner_run_id, "
            "completed_at, created_at) VALUES (?, ?, ?, ?, ?, ?, '[]', ?, NULL, ?)",
            (
                claim.id,
                claim.source_task_id,
                claim.accepted_plan_revision_id,
                DecompositionStatus.IN_FLIGHT.value,
                claim.request_fingerprint,
                dumps(claim.requested_children),
                claim.owner_run_id,
                now,
            ),
        )
        self._conn.commit()
        opened = require_persisted(self.get(claim.id), claim.id)
        return opened

    def _require_revision_lineage(self, source_task_id: str, revision_id: str) -> None:
        """Reject a plan revision that belongs to a different task than ``source_task_id``."""
        row = self._conn.execute(
            "SELECT a.task_id AS task_id FROM artifact_revision ar "
            "JOIN artifact a ON a.id = ar.artifact_id WHERE ar.id = ?",
            (revision_id,),
        ).fetchone()
        if row is not None and row["task_id"] != source_task_id:
            raise ValueError(
                f"plan revision {revision_id} belongs to task {row['task_id']}, "
                f"not source task {source_task_id}"
            )

    def get(self, claim_id: str) -> DecompositionClaim | None:
        row = self._conn.execute(
            "SELECT * FROM decomposition_claim WHERE id = ?", (claim_id,)
        ).fetchone()
        return _row_to_claim(row) if row is not None else None

    def by_source_revision(
        self, source_task_id: str, accepted_plan_revision_id: str
    ) -> DecompositionClaim | None:
        """The resume lookup: the existing claim for this accepted plan, or ``None``."""
        row = self._conn.execute(
            "SELECT * FROM decomposition_claim "
            "WHERE source_task_id = ? AND accepted_plan_revision_id = ?",
            (source_task_id, accepted_plan_revision_id),
        ).fetchone()
        return _row_to_claim(row) if row is not None else None

    def add_child(self, claim_id: str, child_task_id: str) -> DecompositionClaim:
        """Append one created child id to the durable partial result (idempotent).

        Rejected once the claim is ``completed`` — a sealed claim's child set is immutable.
        """
        claim = self.get(claim_id)
        if claim is None:
            raise KeyError(claim_id)
        if claim.status is not DecompositionStatus.IN_FLIGHT:
            raise ValueError(f"claim {claim_id} is {claim.status.value}, not in_flight")
        if child_task_id not in claim.child_task_ids:
            children = [*claim.child_task_ids, child_task_id]
            self._conn.execute(
                "UPDATE decomposition_claim SET child_task_ids = ? WHERE id = ?",
                (dumps(children), claim_id),
            )
            self._conn.commit()
        updated = require_persisted(self.get(claim_id), claim_id)
        return updated

    def complete(self, claim_id: str) -> None:
        now = utcnow_iso()
        self._conn.execute(
            "UPDATE decomposition_claim SET status = 'completed', completed_at = ? "
            "WHERE id = ? AND status = 'in_flight'",
            (now, claim_id),
        )
        self._conn.commit()

    def active_for_owner(self, owner_run_id: str) -> list[DecompositionClaim]:
        """In-flight claims held by a run (the ``decomp_active_owner_idx`` query)."""
        rows = self._conn.execute(
            "SELECT * FROM decomposition_claim WHERE owner_run_id = ? AND status = 'in_flight' "
            "ORDER BY created_at, id",
            (owner_run_id,),
        ).fetchall()
        return [_row_to_claim(row) for row in rows]


def _row_to_claim(row: sqlite3.Row) -> DecompositionClaim:
    return DecompositionClaim(
        id=row["id"],
        source_task_id=row["source_task_id"],
        accepted_plan_revision_id=row["accepted_plan_revision_id"],
        owner_run_id=row["owner_run_id"],
        status=DecompositionStatus(row["status"]),
        request_fingerprint=row["request_fingerprint"],
        requested_children=loads_list(row["requested_children"]),
        child_task_ids=loads_list(row["child_task_ids"]),
        completed_at=from_iso(row["completed_at"]),
        created_at=from_iso(row["created_at"]),
    )
