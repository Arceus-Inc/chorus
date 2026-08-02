"""TDD coverage for Chorus's opaque credential broker."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

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
    ASK_TTL,
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


@pytest.mark.asyncio
async def test_lease_handle_alone_does_not_authorise_another_session(ledger) -> None:
    """A lease binds one grant to one session — a forged pairing is refused before the secret."""

    class Client:
        async def request(self, method, url, headers, body) -> CredentialProxyResponse:
            raise AssertionError("the proxy must not reach the wire for an invalid lease")

    broker = PostgresCredentialBroker(
        ledger.credentials,
        EnvironmentSecretSource({"GITHUB_TOKEN": "never-in-model"}),
        http_client=Client(),
    )
    req = request(mode=CredentialGrantMode.STANDING)
    broker.register(request=req, source_name=CredentialName("GITHUB_TOKEN"))
    ask = (await broker.request_access(req)).ask
    assert ask is not None
    grant = await broker.approve(ask.id, req.owner, CredentialGrantMode.STANDING)
    lease = await broker.materialize(grant.id, CredentialSession("session-5"))

    for forged in (
        replace(lease, session=CredentialSession("session-6")),
        replace(lease, opaque_handle="lease:guessed"),
    ):
        with pytest.raises(PermissionError, match="lease is invalid"):
            await broker.proxy(
                forged,
                CredentialProxyRequest(
                    CredentialHttpMethod.GET, "https://api.github.com/repos/acme/app/pulls"
                ),
            )


@pytest.mark.asyncio
async def test_revoking_a_grant_kills_leases_already_issued(ledger) -> None:
    """Revocation is checked at use, not just at materialization — an issued lease goes dead."""

    class Client:
        async def request(self, method, url, headers, body) -> CredentialProxyResponse:
            raise AssertionError("a revoked grant must never reach the wire")

    broker = PostgresCredentialBroker(
        ledger.credentials,
        EnvironmentSecretSource({"GITHUB_TOKEN": "never-in-model"}),
        http_client=Client(),
    )
    req = request(mode=CredentialGrantMode.STANDING)
    broker.register(request=req, source_name=CredentialName("GITHUB_TOKEN"))
    ask = (await broker.request_access(req)).ask
    assert ask is not None
    grant = await broker.approve(ask.id, req.owner, CredentialGrantMode.STANDING)
    lease = await broker.materialize(grant.id, CredentialSession("session-7"))

    assert await broker.revoke(grant.id, req.owner)

    with pytest.raises(PermissionError, match="revoked"):
        await broker.proxy(
            lease,
            CredentialProxyRequest(
                CredentialHttpMethod.GET, "https://api.github.com/repos/acme/app/pulls"
            ),
        )


@pytest.mark.asyncio
async def test_only_the_owner_approves_or_revokes(ledger) -> None:
    broker = PostgresCredentialBroker(
        ledger.credentials, EnvironmentSecretSource({"GITHUB_TOKEN": "never-in-model"})
    )
    req = request()
    broker.register(request=req, source_name=CredentialName("GITHUB_TOKEN"))
    ask = (await broker.request_access(req)).ask
    assert ask is not None

    with pytest.raises(PermissionError, match="owner"):
        await broker.approve(ask.id, CredentialOwner("employee:mallory"), CredentialGrantMode.ONCE)

    grant = await broker.approve(ask.id, req.owner, CredentialGrantMode.ONCE)
    with pytest.raises(PermissionError, match="owner"):
        await broker.revoke(grant.id, CredentialOwner("employee:mallory"))


@pytest.mark.asyncio
async def test_an_expired_ask_can_no_longer_be_approved(ledger) -> None:
    now = datetime.now(UTC)
    broker = PostgresCredentialBroker(
        ledger.credentials,
        EnvironmentSecretSource({"GITHUB_TOKEN": "never-in-model"}),
        now=lambda: now,
    )
    req = request()
    broker.register(request=req, source_name=CredentialName("GITHUB_TOKEN"))
    ask = (await broker.request_access(req)).ask
    assert ask is not None

    late = PostgresCredentialBroker(
        ledger.credentials,
        EnvironmentSecretSource({"GITHUB_TOKEN": "never-in-model"}),
        now=lambda: now + ASK_TTL + timedelta(seconds=1),
    )
    with pytest.raises(PermissionError, match="expired"):
        await late.approve(ask.id, req.owner, CredentialGrantMode.ONCE)


@pytest.mark.asyncio
async def test_a_standing_grant_short_circuits_the_next_ask(ledger) -> None:
    broker = PostgresCredentialBroker(
        ledger.credentials, EnvironmentSecretSource({"GITHUB_TOKEN": "never-in-model"})
    )
    req = request(mode=CredentialGrantMode.STANDING)
    broker.register(request=req, source_name=CredentialName("GITHUB_TOKEN"))
    first = (await broker.request_access(req)).ask
    assert first is not None
    await broker.approve(first.id, req.owner, CredentialGrantMode.STANDING)

    again = await broker.request_access(req)

    assert again.status is CredentialRequestStatus.GRANTED
    assert again.grant is not None
    assert again.ask is None


@pytest.mark.asyncio
async def test_tightening_the_registration_binds_a_live_grant(ledger) -> None:
    """Re-registering narrower policy applies to grants already approved — no forward copy."""

    class Client:
        async def request(self, method, url, headers, body) -> CredentialProxyResponse:
            return CredentialProxyResponse(status=200, body="ok")

    broker = PostgresCredentialBroker(
        ledger.credentials,
        EnvironmentSecretSource({"GITHUB_TOKEN": "never-in-model"}),
        http_client=Client(),
    )
    req = request(mode=CredentialGrantMode.STANDING)
    broker.register(request=req, source_name=CredentialName("GITHUB_TOKEN"))
    ask = (await broker.request_access(req)).ask
    assert ask is not None
    grant = await broker.approve(ask.id, req.owner, CredentialGrantMode.STANDING)
    lease = await broker.materialize(grant.id, CredentialSession("session-8"))
    call = CredentialProxyRequest(
        CredentialHttpMethod.GET, "https://api.github.com/repos/acme/app/pulls"
    )
    assert (await broker.proxy(lease, call)).status == 200

    broker.register(
        request=replace(req, allowed_path_prefixes=("/repos/acme/other",)),
        source_name=CredentialName("GITHUB_TOKEN"),
    )

    with pytest.raises(PermissionError, match="path"):
        await broker.proxy(lease, call)
