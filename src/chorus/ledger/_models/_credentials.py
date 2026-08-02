"""Credential brokerage row models — registration, ask, grant, lease, and use (``0005_credentials``).

Policy and grant metadata only: no plaintext secret ever reaches these rows. The registration row
carries the delivery policy the broker enforces (host, methods, path prefixes, header injection);
a grant row carries only what approval decided (mode, purpose, audience, status), so a grant is
always read against its registration rather than copying the policy forward.

The typed seam consumers see (``dream.contracts.credentials``) is a different vocabulary; the
translation lives in ``chorus.credentials._records``, keeping repos free of runtime imports from
dream — the same boundary every other repo keeps.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from chorus.ledger._models._enums import (
    CredentialAskStatus,
    CredentialDelivery,
    CredentialGrantMode,
    CredentialGrantStatus,
)


@dataclass(frozen=True)
class CredentialRegistration:
    """The org's standing policy for one credential name (``credential_registration``).

    ``source_name`` names the entry in the external secret source; the value itself is fetched at
    materialization and never stored.
    """

    credential: str
    source_name: str
    owner: str
    audience: str
    purpose: str
    mode: CredentialGrantMode
    delivery: CredentialDelivery
    requested_at: datetime
    environment_key: str | None = None
    allowed_host: str | None = None
    injection_header: str = "Authorization"
    injection_scheme: str = "Bearer"
    allowed_methods: tuple[str, ...] = ()
    allowed_path_prefixes: tuple[str, ...] = ()


@dataclass(frozen=True)
class CredentialAsk:
    """A pending owner approval for an audience to use a registered credential."""

    id: str
    credential: str
    audience: str
    purpose: str
    requested_at: datetime
    expires_at: datetime
    status: CredentialAskStatus = CredentialAskStatus.PENDING
    grant_id: str | None = None


@dataclass(frozen=True)
class CredentialUse:
    """One session's materialization of a grant — the used-at trail an owner audits."""

    session: str
    used_at: datetime


@dataclass(frozen=True)
class CredentialGrant:
    """An approved grant: what the owner allowed, for whom, and whether it is still live.

    ``once`` grants flip to ``used`` on first materialization; ``standing`` grants stay ``active``
    until revoked or expired.
    """

    id: str
    credential: str
    audience: str
    mode: CredentialGrantMode
    purpose: str
    granted_at: datetime
    status: CredentialGrantStatus = CredentialGrantStatus.ACTIVE
    expires_at: datetime | None = None
    uses: tuple[CredentialUse, ...] = ()


@dataclass(frozen=True)
class CredentialLease:
    """An opaque, unguessable handle binding one grant to one session. Carries no secret."""

    handle: str
    grant_id: str
    session: str
    issued_at: datetime


@dataclass(frozen=True)
class CredentialGrantView:
    """A grant joined to the registration whose policy governs it — what the broker enforces on."""

    grant: CredentialGrant
    registration: CredentialRegistration = field(repr=False)


__all__ = [
    "CredentialAsk",
    "CredentialGrant",
    "CredentialGrantView",
    "CredentialLease",
    "CredentialRegistration",
    "CredentialUse",
]
