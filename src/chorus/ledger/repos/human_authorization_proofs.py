"""Append-only repository for authenticated human approval decisions."""

from __future__ import annotations

from chorus.ledger._models import (
    AuthenticationMethod,
    AuthorizationVerdict,
    HumanAuthorizationProof,
)
from chorus.ledger.repos._base import (
    LedgerConnection,
    LedgerRow,
    from_iso,
    require_persisted,
    to_iso,
)


class HumanAuthorizationProofRepo:
    """Persist and read immutable human authorization proof rows.

    There is intentionally no update or delete surface: the database trigger enforces that same
    rule for every writer, not only this repository.
    """

    def __init__(self, conn: LedgerConnection) -> None:
        self._conn = conn

    def record(self, proof: HumanAuthorizationProof) -> HumanAuthorizationProof:
        """Append a proof for its approval; unique approval and nonce constraints reject replay.

        Returns the inserted decision row, not :meth:`get`'s terminal-or-newest-hold projection.
        """
        cursor = self._conn.execute(
            "INSERT INTO human_authorization_proof "
            "(decision_id, approval_id, user_id, method, authenticated_at, nonce, decided_at, "
            "request_id, request_hash, verdict) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "RETURNING *",
            (
                proof.decision_id,
                proof.approval_id,
                proof.user_id,
                proof.method.value,
                to_iso(proof.authenticated_at),
                proof.nonce,
                to_iso(proof.decided_at),
                proof.request_id,
                proof.request_hash,
                proof.verdict.value,
            ),
        )
        row = cursor.fetchone()
        self._conn.commit()
        return require_persisted(
            _row_to_proof(row) if row is not None else None, proof.decision_id
        )

    def get(self, approval_id: str) -> HumanAuthorizationProof | None:
        """Return an approval's terminal proof, or its newest hold when still pending."""
        row = self._conn.execute(
            "SELECT * FROM human_authorization_proof WHERE approval_id = ? "
            "ORDER BY (verdict <> 'hold') DESC, decided_at DESC, decision_id DESC LIMIT 1",
            (approval_id,),
        ).fetchone()
        return _row_to_proof(row) if row is not None else None

    def for_approval(self, approval_id: str) -> list[HumanAuthorizationProof]:
        """Read an approval's immutable hold history and, if present, its terminal proof."""
        rows = self._conn.execute(
            "SELECT * FROM human_authorization_proof WHERE approval_id = ? "
            "ORDER BY decided_at, decision_id",
            (approval_id,),
        ).fetchall()
        return [_row_to_proof(row) for row in rows]

    def get_by_nonce(self, nonce: str) -> HumanAuthorizationProof | None:
        """Read prior immutable evidence for this tenant's derived Idempotency-Key nonce."""
        row = self._conn.execute(
            "SELECT * FROM human_authorization_proof WHERE nonce = ?", (nonce,)
        ).fetchone()
        return _row_to_proof(row) if row is not None else None


def _row_to_proof(row: LedgerRow) -> HumanAuthorizationProof:
    authenticated_at = from_iso(row["authenticated_at"])
    decided_at = from_iso(row["decided_at"])
    if authenticated_at is None or decided_at is None:
        raise ValueError("human authorization proof timestamps must be present")
    return HumanAuthorizationProof(
        decision_id=str(row["decision_id"]),
        approval_id=str(row["approval_id"]),
        user_id=str(row["user_id"]),
        method=AuthenticationMethod(str(row["method"])),
        authenticated_at=authenticated_at,
        nonce=str(row["nonce"]),
        decided_at=decided_at,
        request_id=str(row["request_id"]),
        request_hash=str(row["request_hash"]),
        verdict=AuthorizationVerdict(str(row["verdict"])),
    )


__all__ = ["HumanAuthorizationProofRepo"]
