"""Credential delivery policy over the durable ledger credential rows.

The repo stores; this decides. Ownership, ask expiry, grant liveness, and the broker's host /
method / path allowlist are all enforced here, and the secret is read from the
:class:`~chorus.credentials.SecretSource` only at the last possible moment — at header-stamping or
sandbox-injection time, never on a path that returns to the caller.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol
from urllib.parse import urlsplit

from dream.contracts.credentials import (
    CredentialAskId,
    CredentialBrokerPort,
    CredentialDelivery,
    CredentialEnvironmentTarget,
    CredentialGrant,
    CredentialGrantId,
    CredentialGrantMode,
    CredentialLease,
    CredentialName,
    CredentialOwner,
    CredentialProxyHeader,
    CredentialProxyRequest,
    CredentialProxyResponse,
    CredentialRequest,
    CredentialRequestResult,
    CredentialRequestStatus,
    CredentialSession,
)

from chorus.credentials import _records
from chorus.credentials._source import SecretSource
from chorus.ledger import (
    CredentialGrantMode as GrantMode,
)
from chorus.ledger import (
    CredentialGrantStatus as GrantStatus,
)
from chorus.ledger import (
    CredentialGrantView as GrantRow,
)
from chorus.ledger import (
    CredentialRegistration as RegistrationRow,
)
from chorus.ledger.repos.credentials import CredentialRepo

ASK_TTL = timedelta(hours=24)


class CredentialHttpClient(Protocol):
    async def request(
        self,
        method: str,
        url: str,
        headers: tuple[CredentialProxyHeader, ...],
        body: str | None,
    ) -> CredentialProxyResponse: ...


class PostgresCredentialBroker(CredentialBrokerPort):
    """Broker policy with all state persisted by :class:`CredentialRepo`."""

    def __init__(
        self,
        repo: CredentialRepo,
        source: SecretSource,
        *,
        now: Callable[[], datetime] | None = None,
        http_client: CredentialHttpClient | None = None,
    ) -> None:
        self._repo = repo
        self._source = source
        self._now = now or (lambda: datetime.now(UTC))
        self._http_client = http_client

    def register(self, *, request: CredentialRequest, source_name: CredentialName) -> None:
        self._repo.register(_records.to_registration(request, source_name))

    async def request_access(self, request: CredentialRequest) -> CredentialRequestResult:
        registration = self._registration(request.credential)
        if registration.owner != request.owner.value:
            raise PermissionError("credential owner mismatch")
        standing = self._repo.standing_grant(
            request.credential.value, request.audience.value, self._now()
        )
        if standing is not None:
            return CredentialRequestResult(
                CredentialRequestStatus.GRANTED, grant=_records.to_grant(standing)
            )
        ask = self._repo.create_ask(
            credential=request.credential.value,
            audience=request.audience.value,
            purpose=request.purpose,
            requested_at=request.requested_at,
            expires_at=self._now() + ASK_TTL,
        )
        return CredentialRequestResult(
            CredentialRequestStatus.APPROVAL_REQUIRED,
            ask=_records.to_ask(ask, registration),
        )

    async def approve(
        self, ask: CredentialAskId, owner: CredentialOwner, mode: CredentialGrantMode
    ) -> CredentialGrant:
        pending = self._repo.ask(ask.value)
        if pending is None:
            raise LookupError(f"credential ask {ask.value!r} was not found")
        registration = self._registration(CredentialName(pending.credential))
        if registration.owner != owner.value:
            raise PermissionError("only the credential owner may approve an ask")
        if self._now() >= pending.expires_at:
            raise PermissionError("credential ask expired")
        granted = self._repo.approve(pending, GrantMode(mode.value), self._now())
        return _records.to_grant(granted)

    async def materialize(
        self, grant: CredentialGrantId, session: CredentialSession
    ) -> CredentialLease:
        view = self._live_grant(grant)
        if await self._source.get(CredentialName(view.registration.source_name)) is None:
            raise LookupError("credential secret is unavailable")
        lease = self._repo.materialize(grant.value, session.value, self._now())
        return _records.to_lease(lease, view.registration)

    async def revoke(self, grant: CredentialGrantId, owner: CredentialOwner) -> bool:
        view = self._grant(grant)
        if view.registration.owner != owner.value:
            raise PermissionError("only the credential owner may revoke a grant")
        return self._repo.revoke(grant.value)

    async def grant(self, grant: CredentialGrantId) -> CredentialGrant:
        return _records.to_grant(self._grant(grant))

    async def proxy(
        self, lease: CredentialLease, request: CredentialProxyRequest
    ) -> CredentialProxyResponse:
        if self._http_client is None:
            raise RuntimeError("credential broker proxy is not configured")
        if lease.delivery is not CredentialDelivery.BROKER:
            raise PermissionError("credential lease is not a broker delivery")
        registration = self._lease_registration(lease)
        self._authorize(registration, request)
        secret = await self._secret(registration)
        value = (
            f"{registration.injection_scheme} {secret}" if registration.injection_scheme else secret
        )
        headers = (
            *(
                h
                for h in request.headers
                if h.name.lower() != registration.injection_header.lower()
            ),
            CredentialProxyHeader(registration.injection_header, value),
        )
        return await self._http_client.request(
            request.method.value, request.url, headers, request.body
        )

    async def inject_environment(
        self, lease: CredentialLease, target: CredentialEnvironmentTarget
    ) -> None:
        if lease.delivery is not CredentialDelivery.ENVIRONMENT or not lease.env_key:
            raise PermissionError("credential lease is not an environment delivery")
        registration = self._lease_registration(lease)
        await target.set_credential(lease.env_key, await self._secret(registration))

    def _registration(self, credential: CredentialName) -> RegistrationRow:
        registration = self._repo.registration(credential.value)
        if registration is None:
            raise LookupError(f"credential {credential.value!r} is not registered")
        return registration

    def _grant(self, grant: CredentialGrantId) -> GrantRow:
        view = self._repo.grant(grant.value)
        if view is None:
            raise LookupError(f"credential grant {grant.value!r} was not found")
        return view

    def _live_grant(self, grant: CredentialGrantId) -> GrantRow:
        """A grant that may still be used: active, and not past its expiry."""
        view = self._grant(grant)
        if view.grant.status is not GrantStatus.ACTIVE:
            raise PermissionError(f"credential grant was {view.grant.status.value}")
        if view.grant.expires_at is not None and self._now() >= view.grant.expires_at:
            raise PermissionError("credential grant expired")
        return view

    def _lease_registration(self, lease: CredentialLease) -> RegistrationRow:
        """Resolve a lease handle back to a live grant — the handle alone authorises nothing."""
        issued = self._repo.lease(lease.opaque_handle)
        if (
            issued is None
            or issued.session != lease.session.value
            or issued.grant_id != lease.grant.value
        ):
            raise PermissionError("credential lease is invalid")
        return self._live_grant(lease.grant).registration

    def _authorize(self, registration: RegistrationRow, request: CredentialProxyRequest) -> None:
        """Pin the outbound call to the registered host, methods, and path prefixes."""
        parsed = urlsplit(request.url)
        host = parsed.hostname.lower() if parsed.hostname else ""
        pinned = registration.allowed_host.lower() if registration.allowed_host else ""
        if (
            parsed.scheme != "https"
            or not pinned
            or not (host == pinned or host.endswith(f".{pinned}"))
        ):
            raise PermissionError("credential proxy host is not allowed")
        if request.method.value not in registration.allowed_methods:
            raise PermissionError("credential proxy method is not allowed")
        path = parsed.path or "/"
        if not any(
            path == prefix or path.startswith(f"{prefix}/")
            for prefix in registration.allowed_path_prefixes
        ):
            raise PermissionError("credential proxy path is not allowed")

    async def _secret(self, registration: RegistrationRow) -> str:
        secret = await self._source.get(CredentialName(registration.source_name))
        if secret is None:
            raise LookupError("credential secret is unavailable")
        return secret.value


__all__ = ["ASK_TTL", "CredentialHttpClient", "PostgresCredentialBroker"]
