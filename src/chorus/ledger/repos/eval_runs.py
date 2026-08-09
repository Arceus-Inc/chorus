"""EvalRunRepo — append-only, revision-pinned evaluation records."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from chorus.ledger._models import (
    AgentConfigRevisionRef,
    EvalInputSnapshot,
    EvalOutputSnapshot,
    EvalRun,
    EvalRunStatus,
    EvalRunUsage,
)
from chorus.ledger.repos._base import (
    LedgerConnection,
    LedgerInvariantError,
    LedgerRow,
    from_iso,
    require_persisted,
    to_iso,
    utcnow_iso,
)


class EvalRunRepo:
    """Create and read immutable evaluation-run records."""

    def __init__(self, conn: LedgerConnection) -> None:
        self._conn = conn

    def create(self, run: EvalRun) -> EvalRun:
        pinned_config = self._conn.execute(
            "SELECT provider, model FROM agent_config_revision WHERE id = ?",
            (run.agent_config_revision.value,),
        ).fetchone()
        if pinned_config is not None and (
            run.provider != pinned_config["provider"] or run.model != pinned_config["model"]
        ):
            raise ValueError(
                "eval run provider/model must match its pinned agent config revision"
            )
        try:
            self._conn.execute(
                "INSERT INTO eval_run ("
                "id, eval_suite_id, skill_revision_id, agent_config_revision, provider, model, "
                "input_snapshot, output_snapshot, input_tokens, output_tokens, cost_usd, status, "
                "started_at, completed_at, created_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run.id,
                    run.eval_suite_id,
                    run.skill_revision_id,
                    run.agent_config_revision.value,
                    run.provider,
                    run.model,
                    run.input_snapshot.text,
                    run.output_snapshot.text,
                    run.usage.input_tokens,
                    run.usage.output_tokens,
                    run.usage.cost_usd,
                    run.status.value,
                    to_iso(run.started_at),
                    to_iso(run.completed_at),
                    utcnow_iso(),
                ),
            )
            for position, artifact_revision_id in enumerate(run.artifact_revision_ids):
                self._conn.execute(
                    "INSERT INTO eval_run_artifact_revision "
                    "(eval_run_id, artifact_revision_id, position) VALUES (?, ?, ?)",
                    (run.id, artifact_revision_id, position),
                )
        except Exception:
            self._conn.rollback()
            raise
        self._conn.commit()
        return require_persisted(self.get(run.id), run.id)

    def get(self, run_id: str) -> EvalRun | None:
        row = self._conn.execute("SELECT * FROM eval_run WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        artifact_rows = self._conn.execute(
            "SELECT artifact_revision_id FROM eval_run_artifact_revision "
            "WHERE eval_run_id = ? ORDER BY position",
            (run_id,),
        ).fetchall()
        return _row_to_eval_run(
            row, tuple(artifact_row["artifact_revision_id"] for artifact_row in artifact_rows)
        )

    def list(self, eval_suite_id: str) -> list[EvalRun]:
        rows = self._conn.execute(
            "SELECT id FROM eval_run WHERE eval_suite_id = ? ORDER BY created_at, id",
            (eval_suite_id,),
        ).fetchall()
        return [require_persisted(self.get(row["id"]), row["id"]) for row in rows]


def _row_to_eval_run(row: LedgerRow, artifact_revision_ids: tuple[str, ...]) -> EvalRun:
    return EvalRun(
        id=row["id"],
        eval_suite_id=row["eval_suite_id"],
        skill_revision_id=row["skill_revision_id"],
        agent_config_revision=AgentConfigRevisionRef(row["agent_config_revision"]),
        provider=row["provider"],
        model=row["model"],
        input_snapshot=EvalInputSnapshot(row["input_snapshot"]),
        output_snapshot=EvalOutputSnapshot(row["output_snapshot"]),
        usage=EvalRunUsage(
            input_tokens=row["input_tokens"],
            output_tokens=row["output_tokens"],
            cost_usd=Decimal(row["cost_usd"]),
        ),
        artifact_revision_ids=artifact_revision_ids,
        status=EvalRunStatus(row["status"]),
        started_at=_required_datetime(from_iso(row["started_at"]), "started_at"),
        completed_at=_required_datetime(from_iso(row["completed_at"]), "completed_at"),
        created_at=from_iso(row["created_at"]),
    )


def _required_datetime(value: datetime | None, field_name: str) -> datetime:
    if value is None:
        raise LedgerInvariantError(f"persisted eval run has no {field_name}")
    return value
