"""Translation between the dream credential contract and the ledger's credential rows.

The contract (``dream.contracts.credentials``) is the vocabulary the runtime sees: requests,
grants, opaque leases. The ledger speaks rows. Keeping the mapping here is what lets
``CredentialRepo`` stay a plain chorus repo with no dream import, and gives one place to check that
nothing on the way out carries a secret.
"""

from __future__ import annotations

from dream.contracts.credentials import (
    CredentialAsk,
    CredentialAskId,
    CredentialDelivery,
    CredentialGrant,
    CredentialGrantId,
    CredentialGrantMode,
    CredentialGrantStatus,
    CredentialHttpMethod,
    CredentialInjection,
    CredentialLease,
    CredentialName,
    CredentialOwner,
    CredentialRequest,
    CredentialSession,
    CredentialUse,
)

from chorus.ledger import (
    CredentialAsk as AskRow,
)
from chorus.ledger import (
    CredentialDelivery as DeliveryKind,
)
from chorus.ledger import (
    CredentialGrantMode as GrantMode,
)
from chorus.ledger import (
    CredentialGrantView as GrantRow,
)
from chorus.ledger import (
    CredentialLease as LeaseRow,
)
from chorus.ledger import (
    CredentialRegistration as RegistrationRow,
)


def to_registration(request: CredentialRequest, source_name: CredentialName) -> RegistrationRow:
    return RegistrationRow(
        credential=request.credential.value,
        source_name=source_name.value,
        owner=request.owner.value,
        audience=request.audience.value,
        purpose=request.purpose,
        mode=GrantMode(request.mode.value),
        delivery=DeliveryKind(request.delivery.value),
        requested_at=request.requested_at,
        environment_key=request.environment_key,
        allowed_host=request.allowed_host,
        injection_header=request.injection.header,
        injection_scheme=request.injection.scheme,
        allowed_methods=tuple(method.value for method in request.allowed_methods),
        allowed_path_prefixes=request.allowed_path_prefixes,
    )


def to_request(
    registration: RegistrationRow,
    *,
    audience: str | None = None,
    purpose: str | None = None,
    mode: GrantMode | None = None,
) -> CredentialRequest:
    """The registered policy as a contract request, with the grant's own terms layered on.

    A grant records who asked, why, and for how long; everything else — host, methods, paths,
    header injection — is read live from the registration so tightening it binds existing grants.
    """
    return CredentialRequest(
        credential=CredentialName(registration.credential),
        owner=CredentialOwner(registration.owner),
        audience=CredentialOwner(audience or registration.audience),
        purpose=purpose or registration.purpose,
        mode=CredentialGrantMode((mode or registration.mode).value),
        delivery=CredentialDelivery(registration.delivery.value),
        environment_key=registration.environment_key,
        allowed_host=registration.allowed_host,
        injection=CredentialInjection(registration.injection_header, registration.injection_scheme),
        allowed_methods=tuple(
            CredentialHttpMethod(method) for method in registration.allowed_methods
        ),
        allowed_path_prefixes=registration.allowed_path_prefixes,
        requested_at=registration.requested_at,
    )


def to_ask(ask: AskRow, registration: RegistrationRow) -> CredentialAsk:
    return CredentialAsk(
        id=CredentialAskId(ask.id),
        request=to_request(registration, audience=ask.audience, purpose=ask.purpose),
        expires_at=ask.expires_at,
    )


def to_grant(view: GrantRow) -> CredentialGrant:
    grant = view.grant
    return CredentialGrant(
        id=CredentialGrantId(grant.id),
        request=to_request(
            view.registration,
            audience=grant.audience,
            purpose=grant.purpose,
            mode=grant.mode,
        ),
        status=CredentialGrantStatus(grant.status.value),
        granted_at=grant.granted_at,
        expires_at=grant.expires_at,
        uses=tuple(
            CredentialUse(CredentialSession(use.session), use.used_at) for use in grant.uses
        ),
    )


def to_lease(lease: LeaseRow, registration: RegistrationRow) -> CredentialLease:
    return CredentialLease(
        grant=CredentialGrantId(lease.grant_id),
        session=CredentialSession(lease.session),
        delivery=CredentialDelivery(registration.delivery.value),
        opaque_handle=lease.handle,
        env_key=registration.environment_key,
    )


__all__ = ["to_ask", "to_grant", "to_lease", "to_registration", "to_request"]
