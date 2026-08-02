"""Minimal org-owned credential broker implementation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Protocol
from urllib.parse import urlsplit
from uuid import uuid4

from dream.contracts.credentials import (
    CredentialAsk,
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
    CredentialUse,
)

from chorus.credentials._source import SecretSource

ASK_TTL = timedelta(hours=24)


class CredentialHttpClient(Protocol):
    async def request(
        self,
        method: str,
        url: str,
        headers: tuple[CredentialProxyHeader, ...],
        body: str | None,
    ) -> CredentialProxyResponse: ...


@dataclass(frozen=True)
class _Registration:
    request: CredentialRequest
    source_name: CredentialName


@dataclass
class _GrantState:
    grant: CredentialGrant
    owner: CredentialOwner


class InMemoryCredentialBroker(CredentialBrokerPort):
    """Reference broker for the Chorus composition root.

    It stores only credential references and grant metadata. Secret material is fetched just long
    enough to validate that a lease can be delivered, then discarded; the returned lease is opaque.
    """

    def __init__(
        self,
        source: SecretSource,
        *,
        now: Callable[[], datetime] | None = None,
        http_client: CredentialHttpClient | None = None,
    ) -> None:
        self._source = source
        self._now = now or (lambda: datetime.now(UTC))
        self._http_client = http_client
        self._registrations: dict[CredentialName, _Registration] = {}
        self._asks: dict[CredentialAskId, CredentialAsk] = {}
        self._grants: dict[CredentialGrantId, _GrantState] = {}
        self._leases: dict[str, CredentialLease] = {}

    def register(self, *, request: CredentialRequest, source_name: CredentialName) -> None:
        self._registrations[request.credential] = _Registration(request, source_name)

    async def request_access(self, request: CredentialRequest) -> CredentialRequestResult:
        registration = self._registrations.get(request.credential)
        if registration is None or registration.request.owner != request.owner:
            raise LookupError(f"credential {request.credential.value!r} is not registered")
        now = self._now()
        for state in self._grants.values():
            grant = state.grant
            if (
                grant.status is CredentialGrantStatus.ACTIVE
                and grant.request.credential == request.credential
                and grant.request.audience == request.audience
                and grant.expires_at is not None
                and grant.expires_at <= now
            ):
                state.grant = CredentialGrant(
                    id=grant.id,
                    request=grant.request,
                    status=CredentialGrantStatus.REVOKED,
                    granted_at=grant.granted_at,
                    expires_at=grant.expires_at,
                    uses=grant.uses,
                )
        for state in self._grants.values():
            grant = state.grant
            if (
                grant.status is CredentialGrantStatus.ACTIVE
                and grant.request.credential == request.credential
                and grant.request.audience == request.audience
                and grant.request.mode is CredentialGrantMode.STANDING
            ):
                return CredentialRequestResult(CredentialRequestStatus.GRANTED, grant=grant)
        ask = CredentialAsk(
            id=CredentialAskId(uuid4().hex),
            request=request,
            expires_at=now + ASK_TTL,
        )
        self._asks[ask.id] = ask
        return CredentialRequestResult(CredentialRequestStatus.APPROVAL_REQUIRED, ask=ask)

    async def approve(
        self,
        ask: CredentialAskId,
        owner: CredentialOwner,
        mode: CredentialGrantMode,
    ) -> CredentialGrant:
        record = self._asks.get(ask)
        if record is None:
            raise LookupError(f"credential ask {ask.value!r} was not found")
        if record.request.owner != owner:
            raise PermissionError("only the credential owner may approve an ask")
        if self._now() >= record.expires_at:
            raise PermissionError("credential ask expired")
        approved_request = replace(record.request, mode=mode)
        grant = CredentialGrant(
            id=CredentialGrantId(uuid4().hex),
            request=approved_request,
            status=CredentialGrantStatus.ACTIVE,
            granted_at=self._now(),
            uses=(),
        )
        self._grants[grant.id] = _GrantState(grant, owner)
        return grant

    async def materialize(
        self,
        grant: CredentialGrantId,
        session: CredentialSession,
    ) -> CredentialLease:
        state = self._grants.get(grant)
        if state is None:
            raise LookupError(f"credential grant {grant.value!r} was not found")
        current = state.grant
        now = self._now()
        if current.status is CredentialGrantStatus.REVOKED:
            raise PermissionError("credential grant was revoked")
        if current.status is CredentialGrantStatus.USED:
            raise PermissionError("one-time credential grant was already used")
        if current.expires_at is not None and now >= current.expires_at:
            raise PermissionError("credential grant expired")
        registration = self._registrations[current.request.credential]
        if await self._source.get(registration.source_name) is None:
            raise LookupError("credential secret is unavailable")
        use = CredentialUse(session=session, used_at=now)
        status = (
            CredentialGrantStatus.USED
            if current.request.mode is CredentialGrantMode.ONCE
            else CredentialGrantStatus.ACTIVE
        )
        state.grant = CredentialGrant(
            id=current.id,
            request=current.request,
            status=status,
            granted_at=current.granted_at,
            expires_at=current.expires_at,
            uses=(*current.uses, use),
        )
        lease = CredentialLease(
            grant=grant,
            session=session,
            delivery=current.request.delivery,
            opaque_handle=f"lease:{uuid4().hex}",
            env_key=current.request.environment_key,
        )
        self._leases[lease.opaque_handle] = lease
        return lease

    async def revoke(self, grant: CredentialGrantId, owner: CredentialOwner) -> bool:
        state = self._grants.get(grant)
        if state is None:
            return False
        if state.owner != owner:
            raise PermissionError("only the credential owner may revoke a grant")
        current = state.grant
        if current.status is CredentialGrantStatus.REVOKED:
            return False
        state.grant = CredentialGrant(
            id=current.id,
            request=current.request,
            status=CredentialGrantStatus.REVOKED,
            granted_at=current.granted_at,
            expires_at=current.expires_at,
            uses=current.uses,
        )
        return True

    async def grant(self, grant: CredentialGrantId) -> CredentialGrant:
        state = self._grants.get(grant)
        if state is None:
            raise LookupError(f"credential grant {grant.value!r} was not found")
        return state.grant

    async def proxy(
        self,
        lease: CredentialLease,
        request: CredentialProxyRequest,
    ) -> CredentialProxyResponse:
        if self._http_client is None:
            raise RuntimeError("credential broker proxy is not configured")
        if lease.delivery is not CredentialDelivery.BROKER:
            raise PermissionError("credential lease is not a broker delivery")
        if self._leases.get(lease.opaque_handle) != lease:
            raise PermissionError("credential lease is invalid")
        state = self._grants.get(lease.grant)
        if state is None or state.grant.status is CredentialGrantStatus.REVOKED:
            raise PermissionError("credential grant is not active")
        registration = self._registrations[state.grant.request.credential]
        policy = state.grant.request
        parsed = urlsplit(request.url)
        if parsed.scheme != "https" or not parsed.hostname or not policy.allowed_host:
            raise PermissionError("credential proxy requires an HTTPS URL and pinned host")
        host = parsed.hostname.lower()
        pinned = policy.allowed_host.lower()
        if host != pinned and not host.endswith(f".{pinned}"):
            raise PermissionError("credential proxy host is not allowed")
        if request.method not in policy.allowed_methods:
            raise PermissionError("credential proxy method is not allowed")
        path = parsed.path or "/"
        if not any(
            path == prefix or path.startswith(f"{prefix}/")
            for prefix in policy.allowed_path_prefixes
        ):
            raise PermissionError("credential proxy path is not allowed")
        secret = await self._source.get(registration.source_name)
        if secret is None:
            raise LookupError("credential secret is unavailable")
        scheme = policy.injection.scheme
        auth_value = f"{scheme} {secret.value}" if scheme else secret.value
        headers = (
            *tuple(
                header
                for header in request.headers
                if header.name.lower() != policy.injection.header.lower()
            ),
            CredentialProxyHeader(policy.injection.header, auth_value),
        )
        return await self._http_client.request(
            request.method.value,
            request.url,
            headers,
            request.body,
        )

    async def inject_environment(
        self,
        lease: CredentialLease,
        target: CredentialEnvironmentTarget,
    ) -> None:
        if self._leases.get(lease.opaque_handle) != lease:
            raise PermissionError("credential lease is invalid")
        state = self._grants.get(lease.grant)
        if state is None or state.grant.status is CredentialGrantStatus.REVOKED:
            raise PermissionError("credential grant is not active")
        if lease.delivery is not CredentialDelivery.ENVIRONMENT or not lease.env_key:
            raise PermissionError("credential lease is not an environment delivery")
        registration = self._registrations[state.grant.request.credential]
        secret = await self._source.get(registration.source_name)
        if secret is None:
            raise LookupError("credential secret is unavailable")
        await target.set_credential(lease.env_key, secret.value)


__all__ = ["ASK_TTL", "CredentialHttpClient", "InMemoryCredentialBroker"]
