"""RolloutRepo — immutable eval candidates and append-only promotion decisions."""

from __future__ import annotations

from chorus.ledger._models import (
    PromotionGates,
    ReplayRegression,
    Rollout,
    RolloutDecision,
    RolloutStage,
    RolloutStatus,
)
from chorus.ledger.repos._base import (
    LedgerConnection,
    LedgerRow,
    from_iso,
    require_persisted,
    utcnow_iso,
)


class RolloutRepo:
    """Create immutable rollout candidates and record their valid promotion decisions."""

    def __init__(self, conn: LedgerConnection) -> None:
        self._conn = conn

    def create(self, rollout: Rollout) -> Rollout:
        try:
            self._conn.execute(
                "INSERT INTO rollout "
                "(id, skill_revision_id, eval_suite_id, eval_run_id, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    rollout.id,
                    rollout.skill_revision_id,
                    rollout.eval_suite_id,
                    rollout.eval_run_id,
                    utcnow_iso(),
                ),
            )
            for position, artifact_revision_id in enumerate(rollout.evidence_artifact_revision_ids):
                self._conn.execute(
                    "INSERT INTO rollout_evidence "
                    "(rollout_id, eval_run_id, artifact_revision_id, position) VALUES (?, ?, ?, ?)",
                    (rollout.id, rollout.eval_run_id, artifact_revision_id, position),
                )
        except Exception:
            self._conn.rollback()
            raise
        self._conn.commit()
        return require_persisted(self.get(rollout.id), rollout.id)

    def get(self, rollout_id: str) -> Rollout | None:
        row = self._conn.execute("SELECT * FROM rollout WHERE id = ?", (rollout_id,)).fetchone()
        if row is None:
            return None
        evidence_rows = self._conn.execute(
            "SELECT artifact_revision_id FROM rollout_evidence WHERE rollout_id = ? "
            "ORDER BY position",
            (rollout_id,),
        ).fetchall()
        return _row_to_rollout(
            row, tuple(evidence_row["artifact_revision_id"] for evidence_row in evidence_rows)
        )

    def by_skill_revision(self, skill_revision_id: str) -> list[Rollout]:
        rows = self._conn.execute(
            "SELECT id FROM rollout WHERE skill_revision_id = ? ORDER BY created_at, id",
            (skill_revision_id,),
        ).fetchall()
        return [require_persisted(self.get(row["id"]), row["id"]) for row in rows]

    def record_decision(self, decision: RolloutDecision) -> RolloutDecision:
        rollout = self.get(decision.rollout_id)
        if rollout is None:
            raise ValueError("rollout does not exist")
        prior = self.decisions(decision.rollout_id)
        if any(existing.stage is decision.stage for existing in prior):
            raise ValueError("rollout stage has already been decided")
        if decision.stage is RolloutStage.CANARY:
            if prior:
                raise ValueError("canary completion must be the first rollout decision")
            approval_id: str | None = None
            reviewer_user_id: str | None = None
            replay_regression: ReplayRegression | None = None
        else:
            if not any(
                existing.stage is RolloutStage.CANARY
                and existing.status is RolloutStatus.COMPLETED
                for existing in prior
            ):
                raise ValueError("full promotion requires a completed canary")
            gates = decision.gates
            if gates is None:  # guarded by the frozen model; keeps this boundary fail-closed.
                raise ValueError("full rollout decision must be promoted with gates")
            if gates.replay_regression is ReplayRegression.CRITICAL:
                raise ValueError("critical replay regression blocks full promotion")
            self._require_approved_rollout_reviewer(rollout.id, gates)
            approval_id = gates.approval_id
            reviewer_user_id = gates.reviewer_user_id
            replay_regression = gates.replay_regression
        self._conn.execute(
            "INSERT INTO rollout_decision "
            "(id, rollout_id, stage, status, approval_id, reviewer_user_id, replay_regression, "
            "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                decision.id,
                decision.rollout_id,
                decision.stage.value,
                decision.status.value,
                approval_id,
                reviewer_user_id,
                replay_regression.value if replay_regression is not None else None,
                utcnow_iso(),
            ),
        )
        self._conn.commit()
        return require_persisted(self._get_decision(decision.id), decision.id)

    def decisions(self, rollout_id: str) -> list[RolloutDecision]:
        rows = self._conn.execute(
            "SELECT * FROM rollout_decision WHERE rollout_id = ? ORDER BY created_at, id",
            (rollout_id,),
        ).fetchall()
        return [_row_to_rollout_decision(row) for row in rows]

    def _get_decision(self, decision_id: str) -> RolloutDecision | None:
        row = self._conn.execute(
            "SELECT * FROM rollout_decision WHERE id = ?", (decision_id,)
        ).fetchone()
        return _row_to_rollout_decision(row) if row is not None else None

    def _require_approved_rollout_reviewer(self, rollout_id: str, gates: PromotionGates) -> None:
        row = self._conn.execute(
            "SELECT subject_kind, subject_id, action, status, decided_by_user_id FROM approval "
            "WHERE id = ?",
            (gates.approval_id,),
        ).fetchone()
        if (
            row is None
            or row["subject_kind"] != "rollout"
            or row["subject_id"] != rollout_id
            or row["action"] != "promote_rollout"
            or row["status"] != "approved"
            or row["decided_by_user_id"] != gates.reviewer_user_id
        ):
            raise ValueError("full promotion requires an approved rollout approval")


def _row_to_rollout(
    row: LedgerRow, evidence_artifact_revision_ids: tuple[str, ...]
) -> Rollout:
    return Rollout(
        id=row["id"],
        skill_revision_id=row["skill_revision_id"],
        eval_suite_id=row["eval_suite_id"],
        eval_run_id=row["eval_run_id"],
        evidence_artifact_revision_ids=evidence_artifact_revision_ids,
        created_at=from_iso(row["created_at"]),
    )


def _row_to_rollout_decision(row: LedgerRow) -> RolloutDecision:
    gates = (
        PromotionGates(
            approval_id=row["approval_id"],
            reviewer_user_id=row["reviewer_user_id"],
            replay_regression=ReplayRegression(row["replay_regression"]),
        )
        if row["approval_id"] is not None
        else None
    )
    return RolloutDecision(
        id=row["id"],
        rollout_id=row["rollout_id"],
        stage=RolloutStage(row["stage"]),
        status=RolloutStatus(row["status"]),
        gates=gates,
        created_at=from_iso(row["created_at"]),
    )
