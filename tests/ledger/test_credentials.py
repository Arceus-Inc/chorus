"""CredentialRepo — the credential aggregate's persistence, in ledger row terms only."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from chorus.ledger import (
    CredentialAskStatus,
    CredentialDelivery,
    CredentialGrantMode,
    CredentialGrantStatus,
    CredentialRegistration,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def registration(**overrides: object) -> CredentialRegistration:
    base = CredentialRegistration(
        credential="github",
        source_name="GITHUB_TOKEN",
        owner="org:acme",
        audience="employee:ada",
        purpose="open the release pull request",
        mode=CredentialGrantMode.ONCE,
        delivery=CredentialDelivery.BROKER,
        requested_at=NOW,
        allowed_host="api.github.com",
        allowed_methods=("GET",),
        allowed_path_prefixes=("/repos/acme/app",),
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


def approved_grant(repo, mode: CredentialGrantMode = CredentialGrantMode.ONCE):
    repo.register(registration())
    ask = repo.create_ask(
        credential="github",
        audience="employee:ada",
        purpose="open the release pull request",
        requested_at=NOW,
        expires_at=NOW + timedelta(hours=24),
    )
    return repo.approve(ask, mode, NOW)


def test_registration_round_trips_and_upserts(ledger) -> None:
    repo = ledger.credentials
    repo.register(registration())
    repo.register(registration(allowed_methods=("GET", "POST"), source_name="GITHUB_TOKEN_V2"))

    stored = repo.registration("github")

    assert stored is not None
    assert stored.allowed_methods == ("GET", "POST")
    assert stored.source_name == "GITHUB_TOKEN_V2"
    assert repo.registration("gitlab") is None


def test_approval_mints_one_active_grant_and_closes_the_ask(ledger) -> None:
    repo = ledger.credentials
    view = approved_grant(repo, CredentialGrantMode.STANDING)

    assert view.grant.status is CredentialGrantStatus.ACTIVE
    assert view.grant.mode is CredentialGrantMode.STANDING
    assert view.registration.allowed_host == "api.github.com"
    assert view.grant.granted_at == NOW
    assert view.grant.uses == ()


def test_second_approval_of_the_same_ask_is_refused(ledger) -> None:
    repo = ledger.credentials
    repo.register(registration())
    ask = repo.create_ask(
        credential="github",
        audience="employee:ada",
        purpose="open the release pull request",
        requested_at=NOW,
        expires_at=NOW + timedelta(hours=24),
    )
    repo.approve(ask, CredentialGrantMode.ONCE, NOW)

    with pytest.raises(PermissionError, match="no longer pending"):
        repo.approve(ask, CredentialGrantMode.STANDING, NOW)

    closed = repo.ask(ask.id)
    assert closed is not None
    assert closed.status is CredentialAskStatus.APPROVED
    assert closed.grant_id is not None


def test_materializing_a_once_grant_burns_it_and_records_the_use(ledger) -> None:
    repo = ledger.credentials
    view = approved_grant(repo)

    lease = repo.materialize(view.grant.id, "session-1", NOW)
    after = repo.grant(view.grant.id)

    assert lease.handle.startswith("lease:")
    assert repo.lease(lease.handle) == lease
    assert after is not None
    assert after.grant.status is CredentialGrantStatus.USED
    assert [use.session for use in after.grant.uses] == ["session-1"]


def test_repeat_materialization_in_one_session_refreshes_the_used_at_trail(ledger) -> None:
    repo = ledger.credentials
    view = approved_grant(repo, CredentialGrantMode.STANDING)

    repo.materialize(view.grant.id, "session-1", NOW)
    repo.materialize(view.grant.id, "session-1", NOW + timedelta(minutes=5))
    after = repo.grant(view.grant.id)

    assert after is not None
    assert [(use.session, use.used_at) for use in after.grant.uses] == [
        ("session-1", NOW + timedelta(minutes=5))
    ]


def test_standing_grant_lookup_ignores_burnt_and_revoked_grants(ledger) -> None:
    repo = ledger.credentials
    view = approved_grant(repo, CredentialGrantMode.STANDING)

    assert repo.standing_grant("github", "employee:ada", NOW) is not None
    assert repo.standing_grant("github", "employee:bob", NOW) is None

    assert repo.revoke(view.grant.id) is True
    assert repo.revoke(view.grant.id) is False  # already revoked — nothing left to revoke
    assert repo.standing_grant("github", "employee:ada", NOW) is None


def test_tightening_a_registration_binds_grants_already_approved(ledger) -> None:
    """The grant stores approval terms only, so policy is always read live from the registration."""
    repo = ledger.credentials
    view = approved_grant(repo, CredentialGrantMode.STANDING)

    repo.register(registration(allowed_path_prefixes=("/repos/acme/app/pulls",)))
    after = repo.grant(view.grant.id)

    assert after is not None
    assert after.registration.allowed_path_prefixes == ("/repos/acme/app/pulls",)
    assert after.grant.purpose == view.grant.purpose
