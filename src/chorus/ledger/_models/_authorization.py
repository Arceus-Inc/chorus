"""Immutable evidence that an authenticated human resolved an approval."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from chorus.ledger._models._enums import AuthenticationMethod, AuthorizationVerdict


def _require_utc(name: str, value: datetime) -> None:
    """Reject naive and non-UTC timestamps before they can become authorization evidence."""
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError(f"{name} must be a UTC datetime")


@dataclass(frozen=True)
class HumanAuthorizationProof:
    """Append-only, tenant-scoped proof for one authenticated human decision.

    The database makes this row immutable and ties it to the approval's terminal state.  The
    resolver records ``hold`` without resolving the approval; terminal verdicts resolve it in the
    same transaction as this proof.
    """

    decision_id: str
    approval_id: str
    user_id: str
    method: AuthenticationMethod
    authenticated_at: datetime
    nonce: str
    decided_at: datetime
    request_id: str
    request_hash: str
    verdict: AuthorizationVerdict

    def __post_init__(self) -> None:
        _require_utc("authenticated_at", self.authenticated_at)
        _require_utc("decided_at", self.decided_at)
        if self.authenticated_at > self.decided_at:
            raise ValueError("authenticated_at must be at or before decided_at")
