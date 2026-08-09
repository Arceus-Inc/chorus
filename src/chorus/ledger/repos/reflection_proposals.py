"""Append-only, reviewable Reflection Coach proposal artifacts."""

from __future__ import annotations

from chorus.ledger._errors import LedgerIntegrityError
from chorus.ledger._models import (
    ReflectionProposal,
    ReflectionProposalTarget,
    ReflectionTargetKind,
    TrajectoryRef,
)
from chorus.ledger.repos._base import (
    LedgerConnection,
    LedgerRow,
    from_iso,
    require_persisted,
    utcnow_iso,
)


class ReflectionProposalRepo:
    """Persist proposal-only Reflection Coach artifacts and their evidence."""

    def __init__(self, conn: LedgerConnection) -> None:
        self._conn = conn

    def create(self, proposal: ReflectionProposal) -> ReflectionProposal:
        """Atomically append the artifact, its revision, typed proposal, and evidence references."""
        source_task_id = self._require_completed_reflection_source(proposal)
        now = utcnow_iso()
        try:
            self._conn.execute(
                "INSERT INTO artifact (id, task_id, type, provider, review_state, is_primary, "
                "created_at, updated_at) VALUES (?, ?, 'artifact', 'reflection_coach', "
                "'proposed', true, ?, ?)",
                (proposal.artifact_id, source_task_id, now, now),
            )
            self._conn.execute(
                "INSERT INTO artifact_revision "
                "(id, artifact_id, revision, summary, created_by_run_id, created_at) "
                "VALUES (?, ?, 1, ?, ?, ?)",
                (
                    proposal.artifact_revision_id,
                    proposal.artifact_id,
                    _summary(proposal.target),
                    proposal.source_run_id,
                    now,
                ),
            )
            self._conn.execute(
                "INSERT INTO reflection_proposal "
                "(artifact_id, artifact_revision_id, target_kind, target_owner_employee_id, "
                "target_id, target_revision, diff, rationale, source_routine_run_id, source_run_id, "
                "source_employee_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    proposal.artifact_id,
                    proposal.artifact_revision_id,
                    proposal.target.kind.value,
                    proposal.target.owner_employee_id,
                    proposal.target.target_id,
                    proposal.target.target_revision,
                    proposal.diff,
                    proposal.rationale,
                    proposal.source_routine_run_id,
                    proposal.source_run_id,
                    proposal.source_employee_id,
                    now,
                ),
            )
            for position, evidence_artifact_revision_id in enumerate(
                proposal.evidence_artifact_revision_ids
            ):
                self._conn.execute(
                    "INSERT INTO reflection_proposal_evidence "
                    "(proposal_artifact_revision_id, evidence_artifact_revision_id, position) "
                    "VALUES (?, ?, ?)",
                    (proposal.artifact_revision_id, evidence_artifact_revision_id, position),
                )
            for position, trajectory_ref in enumerate(proposal.trajectory_refs):
                self._conn.execute(
                    "INSERT INTO reflection_proposal_trajectory "
                    "(proposal_artifact_revision_id, trajectory_run_id, trajectory_task_id, position) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        proposal.artifact_revision_id,
                        trajectory_ref.run_id,
                        trajectory_ref.task_id,
                        position,
                    ),
                )
        except Exception:
            self._conn.rollback()
            raise
        self._conn.commit()
        return require_persisted(self.get(proposal.artifact_revision_id), proposal.artifact_revision_id)

    def get(self, artifact_revision_id: str) -> ReflectionProposal | None:
        row = self._conn.execute(
            "SELECT * FROM reflection_proposal WHERE artifact_revision_id = ?", (artifact_revision_id,)
        ).fetchone()
        if row is None:
            return None
        return _row_to_proposal(
            row,
            self._trajectory_refs(artifact_revision_id),
            self._evidence_ids(artifact_revision_id),
        )

    def by_target(self, target: ReflectionProposalTarget) -> list[ReflectionProposal]:
        rows = self._conn.execute(
            "SELECT artifact_revision_id FROM reflection_proposal "
            "WHERE target_kind = ? AND target_owner_employee_id = ? AND target_id = ? "
            "AND target_revision = ? "
            "ORDER BY created_at, artifact_revision_id",
            (
                target.kind.value,
                target.owner_employee_id,
                target.target_id,
                target.target_revision,
            ),
        ).fetchall()
        return [
            require_persisted(self.get(row["artifact_revision_id"]), row["artifact_revision_id"])
            for row in rows
        ]

    def _evidence_ids(self, artifact_revision_id: str) -> tuple[str, ...]:
        rows = self._conn.execute(
            "SELECT evidence_artifact_revision_id FROM reflection_proposal_evidence "
            "WHERE proposal_artifact_revision_id = ? ORDER BY position",
            (artifact_revision_id,),
        ).fetchall()
        return tuple(row["evidence_artifact_revision_id"] for row in rows)

    def _trajectory_refs(self, artifact_revision_id: str) -> tuple[TrajectoryRef, ...]:
        rows = self._conn.execute(
            "SELECT trajectory_run_id, trajectory_task_id FROM reflection_proposal_trajectory "
            "WHERE proposal_artifact_revision_id = ? ORDER BY position",
            (artifact_revision_id,),
        ).fetchall()
        return tuple(TrajectoryRef(row["trajectory_run_id"], row["trajectory_task_id"]) for row in rows)

    def _require_completed_reflection_source(self, proposal: ReflectionProposal) -> str:
        row = self._conn.execute(
            "SELECT r.task_id, r.employee_id, r.status, rr.status AS routine_run_status, "
            "rr.linked_task_id, routine.employee_id "
            "AS routine_employee_id, employee.role "
            "FROM run r JOIN routine_run rr ON rr.id = ? "
            "JOIN routine ON routine.id = rr.routine_id "
            "JOIN employee ON employee.id = routine.employee_id "
            "WHERE r.id = ?",
            (proposal.source_routine_run_id, proposal.source_run_id),
        ).fetchone()
        if row is None:
            raise LedgerIntegrityError("reflection proposal source references are missing or cross-tenant")
        if row["status"] != "succeeded":
            raise ValueError("reflection proposal source run must be succeeded")
        if row["routine_run_status"] != "completed":
            raise ValueError("reflection proposal source routine run must be completed")
        if row["linked_task_id"] != row["task_id"]:
            raise ValueError("reflection proposal source routine run must own the source task")
        if (
            row["employee_id"] != proposal.source_employee_id
            or row["routine_employee_id"] != proposal.source_employee_id
            or row["role"] != "reflection_coach"
        ):
            raise ValueError("reflection proposal source must be a Reflection Coach run")
        return str(row["task_id"])


def _summary(target: ReflectionProposalTarget) -> str:
    return (
        f"Reflection proposal for {target.kind.value}:{target.target_id}@{target.target_revision} "
        f"owned by {target.owner_employee_id}"
    )


def _row_to_proposal(
    row: LedgerRow,
    trajectory_refs: tuple[TrajectoryRef, ...],
    evidence_artifact_revision_ids: tuple[str, ...],
) -> ReflectionProposal:
    return ReflectionProposal(
        artifact_id=row["artifact_id"],
        artifact_revision_id=row["artifact_revision_id"],
        target=ReflectionProposalTarget(
            kind=ReflectionTargetKind(row["target_kind"]),
            owner_employee_id=row["target_owner_employee_id"],
            target_id=row["target_id"],
            target_revision=row["target_revision"],
        ),
        diff=row["diff"],
        rationale=row["rationale"],
        trajectory_refs=trajectory_refs,
        evidence_artifact_revision_ids=evidence_artifact_revision_ids,
        source_routine_run_id=row["source_routine_run_id"],
        source_run_id=row["source_run_id"],
        source_employee_id=row["source_employee_id"],
        created_at=from_iso(row["created_at"]),
    )


__all__ = ["ReflectionProposalRepo"]
