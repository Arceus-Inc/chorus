"""Durable credential aggregate persistence."""

from __future__ import annotations

import json
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
    CredentialInjection,
    CredentialLease,
    CredentialName,
    CredentialOwner,
    CredentialRequest,
    CredentialSession,
    CredentialUse,
)

from chorus.ledger.repos._base import LedgerConnection, LedgerRow, from_iso, to_iso


class CredentialRepo:
    """Postgres persistence for credential registrations, asks, grants, leases and usage."""

    def __init__(self, conn: LedgerConnection) -> None:
        self._conn = conn

    def register(self, request: CredentialRequest, source_name: CredentialName) -> None:
        self._conn.execute(
            "INSERT INTO credential_registration (credential, source_name, owner, audience, purpose, mode, delivery, environment_key, allowed_host, injection_header, injection_scheme, allowed_methods, allowed_paths, requested_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (company_id, credential) DO UPDATE SET source_name = EXCLUDED.source_name, owner = EXCLUDED.owner, audience = EXCLUDED.audience, purpose = EXCLUDED.purpose, mode = EXCLUDED.mode, delivery = EXCLUDED.delivery, environment_key = EXCLUDED.environment_key, allowed_host = EXCLUDED.allowed_host, injection_header = EXCLUDED.injection_header, injection_scheme = EXCLUDED.injection_scheme, allowed_methods = EXCLUDED.allowed_methods, allowed_paths = EXCLUDED.allowed_paths, requested_at = EXCLUDED.requested_at",
            (request.credential.value, source_name.value, request.owner.value, request.audience.value, request.purpose, request.mode.value, request.delivery.value, request.environment_key, request.allowed_host, request.injection.header, request.injection.scheme, json.dumps([method.value for method in request.allowed_methods]), json.dumps(request.allowed_path_prefixes), to_iso(request.requested_at)),
        )
        self._conn.commit()

    def registration(self, credential: CredentialName) -> tuple[CredentialRequest, CredentialName]:
        row = self._conn.execute("SELECT * FROM credential_registration WHERE credential = ?", (credential.value,)).fetchone()
        if row is None:
            raise LookupError(f"credential {credential.value!r} is not registered")
        return _request(row), CredentialName(str(row["source_name"]))

    def standing_grant(self, request: CredentialRequest, now: datetime) -> CredentialGrant | None:
        row = self._conn.execute("SELECT g.*, g.mode AS grant_mode, r.* FROM credential_grant g JOIN credential_registration r USING (company_id, credential) WHERE g.credential = ? AND g.audience = ? AND g.mode = ? AND g.status = ? AND (g.expires_at IS NULL OR g.expires_at > ?)", (request.credential.value, request.audience.value, CredentialGrantMode.STANDING.value, CredentialGrantStatus.ACTIVE.value, to_iso(now))).fetchone()
        return self._grant(row) if row is not None else None

    def create_ask(self, request: CredentialRequest, expires_at: datetime) -> CredentialAsk:
        ask = CredentialAsk(CredentialAskId(uuid4().hex), request, expires_at)
        self._conn.execute("INSERT INTO credential_ask (id, credential, audience, purpose, requested_at, expires_at, status) VALUES (?, ?, ?, ?, ?, ?, 'pending')", (ask.id.value, request.credential.value, request.audience.value, request.purpose, to_iso(request.requested_at), to_iso(expires_at)))
        self._conn.commit()
        return ask

    def approve(self, ask: CredentialAskId, owner: CredentialOwner, mode: CredentialGrantMode, now: datetime) -> CredentialGrant:
        row = self._conn.execute("SELECT a.*, r.* FROM credential_ask a JOIN credential_registration r USING (company_id, credential) WHERE a.id = ?", (ask.value,)).fetchone()
        if row is None:
            raise LookupError(f"credential ask {ask.value!r} was not found")
        if str(row["owner"]) != owner.value:
            raise PermissionError("only the credential owner may approve an ask")
        expires_at = from_iso(str(row["expires_at"]))
        if expires_at is None or now >= expires_at:
            raise PermissionError("credential ask expired")
        request = replace(_request(row), mode=mode)
        grant_id = CredentialGrantId(uuid4().hex)
        self._conn.execute("INSERT INTO credential_grant (id, credential, audience, status, mode, purpose, granted_at, expires_at) VALUES (?, ?, ?, 'active', ?, ?, ?, NULL)", (grant_id.value, request.credential.value, request.audience.value, mode.value, request.purpose, to_iso(now)))
        self._conn.execute("UPDATE credential_ask SET status = 'approved', grant_id = ? WHERE id = ?", (grant_id.value, ask.value))
        self._conn.commit()
        return self.grant(grant_id)

    def grant(self, grant: CredentialGrantId) -> CredentialGrant:
        row = self._conn.execute("SELECT g.*, g.mode AS grant_mode, r.* FROM credential_grant g JOIN credential_registration r USING (company_id, credential) WHERE g.id = ?", (grant.value,)).fetchone()
        if row is None:
            raise LookupError(f"credential grant {grant.value!r} was not found")
        return self._grant(row)

    def materialize(self, grant: CredentialGrantId, session: CredentialSession, now: datetime) -> CredentialLease:
        current = self.grant(grant)
        handle = f"lease:{uuid4().hex}"
        self._conn.execute("INSERT INTO credential_lease (handle, grant_id, session, issued_at) VALUES (?, ?, ?, ?)", (handle, grant.value, session.value, to_iso(now)))
        self._conn.execute("INSERT INTO credential_use (grant_id, session, used_at) VALUES (?, ?, ?)", (grant.value, session.value, to_iso(now)))
        if current.request.mode is CredentialGrantMode.ONCE:
            self._conn.execute("UPDATE credential_grant SET status = 'used' WHERE id = ?", (grant.value,))
        self._conn.commit()
        return CredentialLease(grant, session, current.request.delivery, handle, current.request.environment_key)

    def lease_grant(self, lease: CredentialLease) -> CredentialGrant:
        row = self._conn.execute("SELECT grant_id FROM credential_lease WHERE handle = ? AND session = ?", (lease.opaque_handle, lease.session.value)).fetchone()
        if row is None or str(row["grant_id"]) != lease.grant.value:
            raise PermissionError("credential lease is invalid")
        current = self.grant(lease.grant)
        if current.status is not CredentialGrantStatus.ACTIVE:
            raise PermissionError(f"credential grant was {current.status.value}")
        return current

    def revoke(self, grant: CredentialGrantId) -> bool:
        cursor = self._conn.execute("UPDATE credential_grant SET status = 'revoked' WHERE id = ? AND status <> 'revoked'", (grant.value,))
        self._conn.commit()
        return cast(int, cursor.rowcount) == 1

    def _grant(self, row: LedgerRow) -> CredentialGrant:
        uses = self._conn.execute("SELECT session, used_at FROM credential_use WHERE grant_id = ? ORDER BY used_at", (str(row["id"]),)).fetchall()
        return CredentialGrant(CredentialGrantId(str(row["id"])), _request(row), CredentialGrantStatus(str(row["status"])), from_iso(str(row["granted_at"])) or datetime.now(UTC), from_iso(str(row["expires_at"])) if row["expires_at"] else None, tuple(CredentialUse(CredentialSession(str(use["session"])), from_iso(str(use["used_at"])) or datetime.now(UTC)) for use in uses))


def _request(row: LedgerRow) -> CredentialRequest:
    from dream.contracts.credentials import CredentialHttpMethod

    return CredentialRequest(credential=CredentialName(str(row["credential"])), owner=CredentialOwner(str(row["owner"])), audience=CredentialOwner(str(row["audience"])), purpose=str(row["purpose"]), mode=CredentialGrantMode(str(row.get("grant_mode", row["mode"]))), delivery=CredentialDelivery(str(row["delivery"])), environment_key=str(row["environment_key"]) if row["environment_key"] else None, allowed_host=str(row["allowed_host"]) if row["allowed_host"] else None, injection=CredentialInjection(str(row["injection_header"]), str(row["injection_scheme"])), allowed_methods=tuple(CredentialHttpMethod(value) for value in json.loads(str(row["allowed_methods"]))), allowed_path_prefixes=tuple(str(value) for value in json.loads(str(row["allowed_paths"]))), requested_at=from_iso(str(row["requested_at"])) or datetime.now(UTC))


__all__ = ["CredentialRepo"]
