"""TDD coverage for Chorus's opaque credential broker."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from dream.contracts.credentials import (
    CredentialDelivery,
    CredentialGrantMode,
    CredentialGrantStatus,
    CredentialHttpMethod,
    CredentialName,
    CredentialOwner,
    CredentialProxyHeader,
    CredentialProxyRequest,
    CredentialProxyResponse,
    CredentialRequest,
    CredentialRequestStatus,
    CredentialSession,
)

from chorus.credentials import (
    AwsSecretsManagerSource,
    EnvironmentSecretSource,
    LayeredSecretSource,
    PostgresCredentialBroker,
    SecretValue,
)


def request(*, mode: CredentialGrantMode = CredentialGrantMode.ONCE) -> CredentialRequest:
    return CredentialRequest(
        credential=CredentialName("github"),
        owner=CredentialOwner("org:acme"),
        audience=CredentialOwner("employee:ada"),
        purpose="open the release pull request",
        mode=mode,
        delivery=CredentialDelivery.BROKER,
        allowed_host="api.github.com",
        allowed_methods=(CredentialHttpMethod.GET,),
        allowed_path_prefixes=("/repos/acme/app",),
        requested_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_missing_access_creates_expiring_owner_approval_ask(ledger) -> None:
    broker = PostgresCredentialBroker(ledger.credentials,
        LayeredSecretSource((EnvironmentSecretSource({"GITHUB_TOKEN": "never-in-model"}),))
    )
    broker.register(request=request(), source_name=CredentialName("GITHUB_TOKEN"))

    result = await broker.request_access(request())

    assert result.status is CredentialRequestStatus.APPROVAL_REQUIRED
    assert result.ask is not None
    assert result.ask.expires_at > result.ask.request.requested_at
    assert result.grant is None


@pytest.mark.asyncio
async def test_approved_once_grant_materializes_opaque_lease_and_records_use(ledger) -> None:
    broker = PostgresCredentialBroker(ledger.credentials,
        LayeredSecretSource((EnvironmentSecretSource({"GITHUB_TOKEN": "never-in-model"}),))
    )
    req = request()
    broker.register(request=req, source_name=CredentialName("GITHUB_TOKEN"))
    ask = (await broker.request_access(req)).ask
    assert ask is not None
    grant = await broker.approve(ask.id, req.owner, CredentialGrantMode.ONCE)

    lease = await broker.materialize(grant.id, CredentialSession("session-1"))
    used = await broker.grant(grant.id)

    assert lease.opaque_handle
    assert not hasattr(lease, "secret")
    assert used.status is CredentialGrantStatus.USED
    assert len(used.uses) == 1
    assert "never-in-model" not in repr(lease)


@pytest.mark.asyncio
async def test_revocation_blocks_materialization(ledger) -> None:
    broker = PostgresCredentialBroker(ledger.credentials,
        LayeredSecretSource((EnvironmentSecretSource({"GITHUB_TOKEN": "value"}),))
    )
    req = request(mode=CredentialGrantMode.STANDING)
    broker.register(request=req, source_name=CredentialName("GITHUB_TOKEN"))
    ask = (await broker.request_access(req)).ask
    assert ask is not None
    grant = await broker.approve(ask.id, req.owner, CredentialGrantMode.STANDING)

    assert await broker.revoke(grant.id, req.owner)
    with pytest.raises(PermissionError, match="revoked"):
        await broker.materialize(grant.id, CredentialSession("session-2"))


@pytest.mark.asyncio
async def test_layered_source_falls_through_without_exposing_values() -> None:
    source = LayeredSecretSource(
        (EnvironmentSecretSource({}), EnvironmentSecretSource({"TOKEN": "value"}))
    )

    resolved = await source.get(CredentialName("TOKEN"))

    assert resolved == SecretValue("value")


@pytest.mark.asyncio
async def test_aws_secret_source_applies_prefix() -> None:
    requested: list[str] = []

    class Client:
        async def get_secret(self, name: str) -> str | None:
            requested.append(name)
            return "value"

    value = await AwsSecretsManagerSource(Client(), prefix="chorus/").get(
        CredentialName("github")
    )

    assert value == SecretValue("value")
    assert requested == ["chorus/github"]


@pytest.mark.asyncio
async def test_broker_proxy_injects_secret_and_enforces_host_and_path(ledger) -> None:
    calls: list[tuple[str, str, tuple[CredentialProxyHeader, ...], str | None]] = []

    class Client:
        async def request(
            self,
            method: str,
            url: str,
            headers: tuple[CredentialProxyHeader, ...],
            body: str | None,
        ) -> CredentialProxyResponse:
            calls.append((method, url, headers, body))
            return CredentialProxyResponse(status=200, body="ok")

    broker = PostgresCredentialBroker(ledger.credentials,
        EnvironmentSecretSource({"GITHUB_TOKEN": "never-in-model"}),
        http_client=Client(),
    )
    req = request(mode=CredentialGrantMode.STANDING)
    broker.register(request=req, source_name=CredentialName("GITHUB_TOKEN"))
    ask = (await broker.request_access(req)).ask
    assert ask is not None
    grant = await broker.approve(ask.id, req.owner, CredentialGrantMode.STANDING)
    lease = await broker.materialize(grant.id, CredentialSession("session-3"))

    response = await broker.proxy(
        lease,
        CredentialProxyRequest(
            CredentialHttpMethod.GET,
            "https://api.github.com/repos/acme/app/pulls",
        ),
    )

    assert response.status == 200
    assert calls[0][0] == "GET"
    assert any(getattr(header, "value", "") == "Bearer never-in-model" for header in calls[0][2])
    with pytest.raises(PermissionError, match="host"):
        await broker.proxy(
            lease,
            CredentialProxyRequest(CredentialHttpMethod.GET, "https://evil.example/repos/acme/app"),
        )


@pytest.mark.asyncio
async def test_environment_delivery_injects_only_into_the_sandbox_target(ledger) -> None:
    values: dict[str, str] = {}

    class Target:
        async def set_credential(self, name: str, value: str) -> None:
            values[name] = value

    broker = PostgresCredentialBroker(ledger.credentials,
        EnvironmentSecretSource({"GITHUB_TOKEN": "never-in-model"})
    )
    req = replace(
        request(),
        delivery=CredentialDelivery.ENVIRONMENT,
        environment_key="GITHUB_TOKEN",
        allowed_host=None,
    )
    broker.register(request=req, source_name=CredentialName("GITHUB_TOKEN"))
    ask = (await broker.request_access(req)).ask
    assert ask is not None
    grant = await broker.approve(ask.id, req.owner, CredentialGrantMode.STANDING)
    lease = await broker.materialize(grant.id, CredentialSession("session-4"))

    await broker.inject_environment(lease, Target())

    assert values == {"GITHUB_TOKEN": "never-in-model"}
