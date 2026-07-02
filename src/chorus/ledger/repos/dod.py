"""DodRepo — the definition-of-done + verification record (spec 01 Cluster F, spec 04).

Serialises a typed :class:`~chorus.outcomes.Verifier` into the 1:1 ``dod`` row (the ``dod_task_uq``
index enforces one per task) and records the verdict — the authoritative pass/fail the task status
is later derived from (spec 01 Cluster F invariant).
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict
from typing import cast

from chorus.ids import mint_id
from chorus.ledger._models import Dod, DodStatus
from chorus.ledger.repos._base import dumps, loads, utcnow_iso
from chorus.outcomes import AgentReview, Command, DoDKind, HumanApproval, ReviewedBuild, Verifier


class DodRepo:
    """Create + read + verdict on ``dod`` rows."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(self, task_id: str, verifier: Verifier, *, dod_id: str | None = None) -> Dod:
        now = utcnow_iso()
        did = dod_id or mint_id("dod")
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

    # -- revisability (spec 04 §1) ----------------------------------------------------------------

    def apply_revision(self, task_id: str, verifier: Verifier) -> None:
        """Swap the in-force verifier and bump ``revision`` — leaves the recorded verdict untouched.

        The verdict/run evidence is preserved (the in-flight invariant: a revision never re-judges an
        already-recorded evaluation); the next evaluator pass uses the new verifier (spec 04 §1)."""
        self._conn.execute(
            "UPDATE dod SET kind = ?, spec = ?, artifact_class = ?, revision = revision + 1, "
            "proposed_revision = NULL, updated_at = ? WHERE task_id = ?",
            (
                verifier.kind.value,
                dumps(asdict(verifier.spec)),
                verifier.artifact_class,
                utcnow_iso(),
                task_id,
            ),
        )
        self._conn.commit()

    def propose_revision(self, task_id: str, verifier: Verifier) -> None:
        """Stage a *loosen* verifier for approval — the in-force verifier and revision are unchanged."""
        self._conn.execute(
            "UPDATE dod SET proposed_revision = ?, updated_at = ? WHERE task_id = ?",
            (dumps(_verifier_to_payload(verifier)), utcnow_iso(), task_id),
        )
        self._conn.commit()

    def apply_proposed_revision(self, task_id: str) -> None:
        """Promote the staged loosen to in-force (bump revision, clear the staging) — §5 grant path."""
        dod = self.get_for_task(task_id)
        if dod is None or dod.proposed_revision is None:
            return
        self.apply_revision(task_id, _verifier_from_payload(dod.proposed_revision))

    def clear_proposed(self, task_id: str) -> None:
        """Drop a staged loosen without applying it (a denied / withdrawn revision)."""
        self._conn.execute(
            "UPDATE dod SET proposed_revision = NULL, updated_at = ? WHERE task_id = ?",
            (utcnow_iso(), task_id),
        )
        self._conn.commit()


def _verifier_to_payload(verifier: Verifier) -> dict[str, object]:
    """Serialise a full verifier to ``{kind, spec, artifact_class}`` (the staged-revision shape)."""
    return {
        "kind": verifier.kind.value,
        "spec": asdict(verifier.spec),
        "artifact_class": verifier.artifact_class,
    }


def _verifier_from_payload(payload: dict[str, object]) -> Verifier:
    """Rebuild a verifier from a :func:`_verifier_to_payload` blob (the staged proposed revision)."""
    return _verifier_from_parts(
        str(payload["kind"]),
        cast("dict[str, object]", payload["spec"]),
        str(payload.get("artifact_class") or ""),
    )


def _verifier_from_dod(dod: Dod) -> Verifier:
    """Rebuild the typed verifier from a persisted ``dod`` row (the reverse of serialisation)."""
    return _verifier_from_parts(dod.kind, dod.spec, dod.artifact_class or "")


def _verifier_from_parts(kind_value: str, spec: dict[str, object], artifact_class: str) -> Verifier:
    kind = DoDKind(kind_value)
    if kind is DoDKind.COMMAND:
        return Verifier(
            kind, Command(str(spec["command"]), cast("int", spec["timeout_s"])), artifact_class
        )
    if kind is DoDKind.AGENT_REVIEW:
        return Verifier(
            kind, AgentReview(str(spec["reviewer_role"]), str(spec["rubric"])), artifact_class
        )
    if kind is DoDKind.REVIEWED_BUILD:
        return Verifier(
            kind,
            ReviewedBuild(
                str(spec["reviewer_role"]),
                str(spec["rubric"]),
                int(cast("int", spec["verify_timeout_s"])),
            ),
            artifact_class,
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
        proposed_revision=loads(row["proposed_revision"]),
    )
