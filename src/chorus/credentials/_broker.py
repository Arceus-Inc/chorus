"""Credential delivery policy over the durable ledger credential repository."""

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
    CredentialGrantStatus,
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

from chorus.credentials._source import SecretSource
from chorus.ledger.repos.credentials import CredentialRepo

ASK_TTL = timedelta(hours=24)


class CredentialHttpClient(Protocol):
    async def request(self, method: str, url: str, headers: tuple[CredentialProxyHeader, ...], body: str | None) -> CredentialProxyResponse: ...


class PostgresCredentialBroker(CredentialBrokerPort):
    """Broker policy with all state persisted by :class:`CredentialRepo`."""

    def __init__(self, repo: CredentialRepo, source: SecretSource, *, now: Callable[[], datetime] | None = None, http_client: CredentialHttpClient | None = None) -> None:
        self._repo = repo
        self._source = source
        self._now = now or (lambda: datetime.now(UTC))
        self._http_client = http_client

    def register(self, *, request: CredentialRequest, source_name: CredentialName) -> None:
        self._repo.register(request, source_name)

    async def request_access(self, request: CredentialRequest) -> CredentialRequestResult:
        registered, _ = self._repo.registration(request.credential)
        if registered.owner != request.owner:
            raise PermissionError("credential owner mismatch")
        grant = self._repo.standing_grant(request, self._now())
        if grant is not None:
            return CredentialRequestResult(CredentialRequestStatus.GRANTED, grant=grant)
        ask = self._repo.create_ask(request, self._now() + ASK_TTL)
        return CredentialRequestResult(CredentialRequestStatus.APPROVAL_REQUIRED, ask=ask)

    async def approve(self, ask: CredentialAskId, owner: CredentialOwner, mode: CredentialGrantMode) -> CredentialGrant:
        return self._repo.approve(ask, owner, mode, self._now())

    async def materialize(self, grant: CredentialGrantId, session: CredentialSession) -> CredentialLease:
        current = self._repo.grant(grant)
        if current.status is not CredentialGrantStatus.ACTIVE:
            raise PermissionError(f"credential grant was {current.status.value}")
        _, source_name = self._repo.registration(current.request.credential)
        if await self._source.get(source_name) is None:
            raise LookupError("credential secret is unavailable")
        return self._repo.materialize(grant, session, self._now())

    async def revoke(self, grant: CredentialGrantId, owner: CredentialOwner) -> bool:
        current = self._repo.grant(grant)
        if current.request.owner != owner:
            raise PermissionError("only the credential owner may revoke a grant")
        return self._repo.revoke(grant)

    async def grant(self, grant: CredentialGrantId) -> CredentialGrant:
        return self._repo.grant(grant)

    async def proxy(self, lease: CredentialLease, request: CredentialProxyRequest) -> CredentialProxyResponse:
        if self._http_client is None:
            raise RuntimeError("credential broker proxy is not configured")
        if lease.delivery is not CredentialDelivery.BROKER:
            raise PermissionError("credential lease is not a broker delivery")
        grant = self._repo.lease_grant(lease)
        policy = grant.request
        parsed = urlsplit(request.url)
        host = parsed.hostname.lower() if parsed.hostname else ""
        pinned = policy.allowed_host.lower() if policy.allowed_host else ""
        if parsed.scheme != "https" or not pinned or not (host == pinned or host.endswith(f".{pinned}")):
            raise PermissionError("credential proxy host is not allowed")
        if request.method not in policy.allowed_methods:
            raise PermissionError("credential proxy method is not allowed")
        path = parsed.path or "/"
        if not any(path == prefix or path.startswith(f"{prefix}/") for prefix in policy.allowed_path_prefixes):
            raise PermissionError("credential proxy path is not allowed")
        _, source_name = self._repo.registration(policy.credential)
        secret = await self._source.get(source_name)
        if secret is None:
            raise LookupError("credential secret is unavailable")
        value = f"{policy.injection.scheme} {secret.value}" if policy.injection.scheme else secret.value
        headers = (*tuple(h for h in request.headers if h.name.lower() != policy.injection.header.lower()), CredentialProxyHeader(policy.injection.header, value))
        return await self._http_client.request(request.method.value, request.url, headers, request.body)

    async def inject_environment(self, lease: CredentialLease, target: CredentialEnvironmentTarget) -> None:
        if lease.delivery is not CredentialDelivery.ENVIRONMENT or not lease.env_key:
            raise PermissionError("credential lease is not an environment delivery")
        grant = self._repo.lease_grant(lease)
        _, source_name = self._repo.registration(grant.request.credential)
        secret = await self._source.get(source_name)
        if secret is None:
            raise LookupError("credential secret is unavailable")
        await target.set_credential(lease.env_key, secret.value)


__all__ = ["ASK_TTL", "CredentialHttpClient", "PostgresCredentialBroker"]
