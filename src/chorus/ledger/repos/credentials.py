"""CredentialRepo — durable credential brokerage aggregate (registration / ask / grant / lease / use).

Policy and grant metadata only — plaintext secrets never land in these tables. Materialization
reads an external :class:`~chorus.credentials.SecretSource`. Mirrors the house repo shape
(``ApprovalRepo``, ``ArtifactRepo``): focused methods, multi-line SQL, ``_base`` helpers,
``mint_id`` uuidv7 entity ids.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

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

from chorus.ids import mint_id
from chorus.ledger.repos._base import (
    LedgerConnection,
    LedgerRow,
    dumps,
    from_iso,
    loads_list,
    require_persisted,
    to_iso,
)

# Grant rows join registration for the delivery policy; alias grant.mode so it does not
# collide with registration.mode in the joined mapping.
_GRANT_JOIN = (
    "SELECT g.id, g.status, g.mode AS grant_mode, g.purpose AS grant_purpose, "
    "g.audience AS grant_audience, g.granted_at, g.expires_at, "
    "r.credential, r.source_name, r.owner, r.audience, r.purpose, r.mode, r.delivery, "
    "r.environment_key, r.allowed_host, r.injection_header, r.injection_scheme, "
    "r.allowed_methods, r.allowed_paths, r.requested_at "
    "FROM credential_grant g "
    "JOIN credential_registration r USING (company_id, credential)"
)


class CredentialRepo:
    """Postgres persistence for credential registrations, asks, grants, leases, and usage."""

    def __init__(self, conn: LedgerConnection) -> None:
        self._conn = conn

    def register(self, request: CredentialRequest, source_name: CredentialName) -> None:
        """Upsert the org registration for ``request.credential`` (policy only — no secret)."""
        self._conn.execute(
            "INSERT INTO credential_registration ("
            "credential, source_name, owner, audience, purpose, mode, delivery, "
            "environment_key, allowed_host, injection_header, injection_scheme, "
            "allowed_methods, allowed_paths, requested_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (company_id, credential) DO UPDATE SET "
            "source_name = EXCLUDED.source_name, "
            "owner = EXCLUDED.owner, "
            "audience = EXCLUDED.audience, "
            "purpose = EXCLUDED.purpose, "
            "mode = EXCLUDED.mode, "
            "delivery = EXCLUDED.delivery, "
            "environment_key = EXCLUDED.environment_key, "
            "allowed_host = EXCLUDED.allowed_host, "
            "injection_header = EXCLUDED.injection_header, "
            "injection_scheme = EXCLUDED.injection_scheme, "
            "allowed_methods = EXCLUDED.allowed_methods, "
            "allowed_paths = EXCLUDED.allowed_paths, "
            "requested_at = EXCLUDED.requested_at",
            (
                request.credential.value,
                source_name.value,
                request.owner.value,
                request.audience.value,
                request.purpose,
                request.mode.value,
                request.delivery.value,
                request.environment_key,
                request.allowed_host,
                request.injection.header,
                request.injection.scheme,
                dumps([method.value for method in request.allowed_methods]),
                dumps(list(request.allowed_path_prefixes)),
                to_iso(request.requested_at),
            ),
        )
        self._conn.commit()

    def registration(self, credential: CredentialName) -> tuple[CredentialRequest, CredentialName]:
        row = self._conn.execute(
            "SELECT * FROM credential_registration WHERE credential = ?",
            (credential.value,),
        ).fetchone()
        if row is None:
            raise LookupError(f"credential {credential.value!r} is not registered")
        return _row_to_request(row), CredentialName(str(row["source_name"]))

    def standing_grant(self, request: CredentialRequest, now: datetime) -> CredentialGrant | None:
        """Active standing grant for this credential+audience, if one has not expired."""
        row = self._conn.execute(
            f"{_GRANT_JOIN} "
            "WHERE g.credential = ? AND g.audience = ? AND g.mode = ? AND g.status = ? "
            "AND (g.expires_at IS NULL OR g.expires_at > ?)",
            (
                request.credential.value,
                request.audience.value,
                CredentialGrantMode.STANDING.value,
                CredentialGrantStatus.ACTIVE.value,
                to_iso(now),
            ),
        ).fetchone()
        return self._row_to_grant(row) if row is not None else None

    def create_ask(self, request: CredentialRequest, expires_at: datetime) -> CredentialAsk:
        ask_id = mint_id()
        self._conn.execute(
            "INSERT INTO credential_ask ("
            "id, credential, audience, purpose, requested_at, expires_at, status"
            ") VALUES (?, ?, ?, ?, ?, ?, 'pending')",
            (
                ask_id,
                request.credential.value,
                request.audience.value,
                request.purpose,
                to_iso(request.requested_at),
                to_iso(expires_at),
            ),
        )
        self._conn.commit()
        return CredentialAsk(
            CredentialAskId(ask_id),
            request,
            expires_at,
        )

    def approve(
        self,
        ask: CredentialAskId,
        owner: CredentialOwner,
        mode: CredentialGrantMode,
        now: datetime,
    ) -> CredentialGrant:
        row = self._conn.execute(
            "SELECT a.id AS ask_id, a.expires_at AS ask_expires_at, a.status AS ask_status, "
            "r.* "
            "FROM credential_ask a "
            "JOIN credential_registration r USING (company_id, credential) "
            "WHERE a.id = ?",
            (ask.value,),
        ).fetchone()
        if row is None:
            raise LookupError(f"credential ask {ask.value!r} was not found")
        if str(row["owner"]) != owner.value:
            raise PermissionError("only the credential owner may approve an ask")
        expires_at = from_iso(str(row["ask_expires_at"]))
        if expires_at is None or now >= expires_at:
            raise PermissionError("credential ask expired")

        request = replace(_row_to_request(row), mode=mode)
        grant_id = mint_id()
        self._conn.execute(
            "INSERT INTO credential_grant ("
            "id, credential, audience, status, mode, purpose, granted_at, expires_at"
            ") VALUES (?, ?, ?, 'active', ?, ?, ?, NULL)",
            (
                grant_id,
                request.credential.value,
                request.audience.value,
                mode.value,
                request.purpose,
                to_iso(now),
            ),
        )
        self._conn.execute(
            "UPDATE credential_ask SET status = 'approved', grant_id = ? WHERE id = ?",
            (grant_id, ask.value),
        )
        self._conn.commit()
        return require_persisted(self.grant(CredentialGrantId(grant_id)), grant_id)

    def grant(self, grant: CredentialGrantId) -> CredentialGrant:
        row = self._conn.execute(
            f"{_GRANT_JOIN} WHERE g.id = ?",
            (grant.value,),
        ).fetchone()
        if row is None:
            raise LookupError(f"credential grant {grant.value!r} was not found")
        return self._row_to_grant(row)

    def materialize(
        self,
        grant: CredentialGrantId,
        session: CredentialSession,
        now: datetime,
    ) -> CredentialLease:
        current = self.grant(grant)
        handle = f"lease:{uuid4().hex}"
        self._conn.execute(
            "INSERT INTO credential_lease (handle, grant_id, session, issued_at) "
            "VALUES (?, ?, ?, ?)",
            (handle, grant.value, session.value, to_iso(now)),
        )
        self._conn.execute(
            "INSERT INTO credential_use (grant_id, session, used_at) VALUES (?, ?, ?)",
            (grant.value, session.value, to_iso(now)),
        )
        if current.request.mode is CredentialGrantMode.ONCE:
            self._conn.execute(
                "UPDATE credential_grant SET status = 'used' WHERE id = ?",
                (grant.value,),
            )
        self._conn.commit()
        return CredentialLease(
            grant,
            session,
            current.request.delivery,
            handle,
            current.request.environment_key,
        )

    def lease_grant(self, lease: CredentialLease) -> CredentialGrant:
        row = self._conn.execute(
            "SELECT grant_id FROM credential_lease WHERE handle = ? AND session = ?",
            (lease.opaque_handle, lease.session.value),
        ).fetchone()
        if row is None or str(row["grant_id"]) != lease.grant.value:
            raise PermissionError("credential lease is invalid")
        current = self.grant(lease.grant)
        if current.status is not CredentialGrantStatus.ACTIVE:
            raise PermissionError(f"credential grant was {current.status.value}")
        return current

    def revoke(self, grant: CredentialGrantId) -> bool:
        cursor = self._conn.execute(
            "UPDATE credential_grant SET status = 'revoked' "
            "WHERE id = ? AND status <> 'revoked'",
            (grant.value,),
        )
        self._conn.commit()
        return cast(int, cursor.rowcount) == 1

    def _row_to_grant(self, row: LedgerRow) -> CredentialGrant:
        uses = self._conn.execute(
            "SELECT session, used_at FROM credential_use "
            "WHERE grant_id = ? ORDER BY used_at",
            (str(row["id"]),),
        ).fetchall()
        request = replace(
            _row_to_request(row),
            mode=CredentialGrantMode(str(row["grant_mode"])),
            purpose=str(row.get("grant_purpose", row["purpose"])),
            audience=CredentialOwner(str(row.get("grant_audience", row["audience"]))),
        )
        return CredentialGrant(
            id=CredentialGrantId(str(row["id"])),
            request=request,
            status=CredentialGrantStatus(str(row["status"])),
            granted_at=from_iso(str(row["granted_at"])) or datetime.now(UTC),
            expires_at=from_iso(str(row["expires_at"])) if row["expires_at"] else None,
            uses=tuple(
                CredentialUse(
                    CredentialSession(str(use["session"])),
                    from_iso(str(use["used_at"])) or datetime.now(UTC),
                )
                for use in uses
            ),
        )


def _json_list(value: object) -> list[object]:
    """Decode a jsonb list column whether the driver returned text or a parsed list."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return loads_list(str(value))


def _row_to_request(row: LedgerRow) -> CredentialRequest:
    methods = _json_list(row["allowed_methods"])
    paths = _json_list(row["allowed_paths"])
    return CredentialRequest(
        credential=CredentialName(str(row["credential"])),
        owner=CredentialOwner(str(row["owner"])),
        audience=CredentialOwner(str(row["audience"])),
        purpose=str(row["purpose"]),
        mode=CredentialGrantMode(str(row["mode"])),
        delivery=CredentialDelivery(str(row["delivery"])),
        environment_key=str(row["environment_key"]) if row["environment_key"] else None,
        allowed_host=str(row["allowed_host"]) if row["allowed_host"] else None,
        injection=CredentialInjection(
            str(row["injection_header"]),
            str(row["injection_scheme"]),
        ),
        allowed_methods=tuple(CredentialHttpMethod(str(value)) for value in methods),
        allowed_path_prefixes=tuple(str(value) for value in paths),
        requested_at=from_iso(str(row["requested_at"])) or datetime.now(UTC),
    )


__all__ = ["CredentialRepo"]
