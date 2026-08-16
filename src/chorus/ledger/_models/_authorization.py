"""Immutable evidence that an authenticated human resolved an approval."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from chorus.ledger._models._enums import AuthenticationMethod, AuthorizationVerdict


def require_utc_datetime(name: str, value: datetime) -> datetime:
    """Reject naive and non-UTC timestamps; return a ``datetime.UTC``-normalized value."""
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be a UTC datetime")
    return value.replace(tzinfo=UTC)


def _require_nonblank(name: str, value: str) -> None:
    """Reject empty evidence fields at the typed boundary."""
    if not value.strip():
        raise ValueError(f"{name} must not be blank")


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
        for name, value in (
            ("decision_id", self.decision_id),
            ("approval_id", self.approval_id),
            ("user_id", self.user_id),
            ("nonce", self.nonce),
            ("request_id", self.request_id),
            ("request_hash", self.request_hash),
        ):
            _require_nonblank(name, value)
        object.__setattr__(
            self, "authenticated_at", require_utc_datetime("authenticated_at", self.authenticated_at)
        )
        object.__setattr__(
            self, "decided_at", require_utc_datetime("decided_at", self.decided_at)
        )
        if self.authenticated_at > self.decided_at:
            raise ValueError("authenticated_at must be at or before decided_at")


__all__ = ["HumanAuthorizationProof", "require_utc_datetime"]
