"""DodRepo — the definition-of-done + verification record (spec 01 Cluster F, spec 04).

Serialises a typed :class:`~chorus.outcomes.Verifier` into the 1:1 ``dod`` row (the ``dod_task_uq``
index enforces one per task) and records the verdict — the authoritative pass/fail the task status
is later derived from (spec 01 Cluster F invariant).
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import asdict
from typing import cast

from chorus.ledger._models import Dod, DodStatus
from chorus.ledger.repos._base import dumps, loads, utcnow_iso
from chorus.outcomes import AgentReview, Command, DoDKind, HumanApproval, Verifier


class DodRepo:
    """Create + read + verdict on ``dod`` rows."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(self, task_id: str, verifier: Verifier, *, dod_id: str | None = None) -> Dod:
        now = utcnow_iso()
        did = dod_id or f"dod_{uuid.uuid4().hex[:12]}"
        spec: dict[str, object] = asdict(verifier.spec)
        kind = verifier.kind.value
        self._conn.execute(
            "INSERT INTO dod (id, task_id, kind, spec, artifact_class, revision, status, verdict, "
            "verified_by_run_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                did,
                task_id,
                kind,
                dumps(spec),
                verifier.artifact_class,
                1,
                DodStatus.PENDING.value,
                None,
                None,
                now,
                now,
            ),
        )
        self._conn.commit()
        return Dod(
            id=did,
            task_id=task_id,
            kind=kind,
            spec=spec,
            artifact_class=verifier.artifact_class,
        )

    def get_for_task(self, task_id: str) -> Dod | None:
        row = self._conn.execute("SELECT * FROM dod WHERE task_id = ?", (task_id,)).fetchone()
        return _row_to_dod(row) if row is not None else None

    def verifier_for_task(self, task_id: str) -> Verifier | None:
        """The typed :class:`~chorus.outcomes.Verifier` for a task's DoD — the reverse of ``create``.

        The beat passes a ``Command`` verifier's checks into dream's evaluator for enforcement
        (spec 04 §1); ``None`` when the task has no DoD.
        """
        dod = self.get_for_task(task_id)
        return _verifier_from_dod(dod) if dod is not None else None

    def record_verdict(
        self,
        dod_id: str,
        status: DodStatus,
        *,
        verdict: dict[str, object] | None = None,
        run_id: str | None = None,
    ) -> None:
        now = utcnow_iso()
        self._conn.execute(
            "UPDATE dod SET status = ?, verdict = ?, "
            "verified_by_run_id = COALESCE(?, verified_by_run_id), updated_at = ? WHERE id = ?",
            (
                status.value,
                dumps(verdict) if verdict is not None else None,
                run_id,
                now,
                dod_id,
            ),
        )
        self._conn.commit()


def _verifier_from_dod(dod: Dod) -> Verifier:
    """Rebuild the typed verifier from a persisted ``dod`` row (the reverse of serialisation)."""
    kind = DoDKind(dod.kind)
    spec = dod.spec
    artifact_class = dod.artifact_class or ""
    if kind is DoDKind.COMMAND:
        return Verifier(
            kind, Command(str(spec["command"]), cast("int", spec["timeout_s"])), artifact_class
        )
    if kind is DoDKind.AGENT_REVIEW:
        return Verifier(
            kind, AgentReview(str(spec["reviewer_role"]), str(spec["rubric"])), artifact_class
        )
    return Verifier(kind, HumanApproval(str(spec["approver"])), artifact_class)


def _row_to_dod(row: sqlite3.Row) -> Dod:
    return Dod(
        id=row["id"],
        task_id=row["task_id"],
        kind=row["kind"],
        spec=loads(row["spec"]) or {},
        artifact_class=row["artifact_class"],
        revision=row["revision"],
        status=DodStatus(row["status"]),
        verdict=loads(row["verdict"]),
        verified_by_run_id=row["verified_by_run_id"],
    )
