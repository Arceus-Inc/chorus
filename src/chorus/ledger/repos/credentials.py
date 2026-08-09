"""CredentialRepo — the credential brokerage aggregate (registration / ask / grant / lease / use).

Policy and grant metadata only: plaintext secrets never land in these tables, and materialization
reads them from an external :class:`~chorus.credentials.SecretSource` at call time. Like every other
repo this one speaks :mod:`chorus.ledger._models` rows and nothing else — owner checks, expiry, and
delivery enforcement are the broker's job (:mod:`chorus.credentials`), not the store's.

A grant never copies its registration's policy forward: :meth:`grant` returns a
:class:`CredentialGrantView` joining the two, so tightening a registration applies to grants already
approved against it.
"""

from __future__ import annotations

import secrets
from datetime import datetime
from typing import cast

from chorus.ids import mint_id
from chorus.ledger._models import (
    CredentialAsk,
    CredentialAskStatus,
    CredentialDelivery,
    CredentialGrant,
    CredentialGrantMode,
    CredentialGrantStatus,
    CredentialGrantView,
    CredentialLease,
    CredentialRegistration,
    CredentialUse,
)
from chorus.ledger.repos._base import (
    LedgerConnection,
    LedgerRow,
    dumps,
    from_iso,
    loads_list,
    require_persisted,
    to_iso,
)

_REGISTRATION_COLUMNS = (
    "credential, source_name, owner, audience, purpose, mode, delivery, environment_key, "
    "allowed_host, injection_header, injection_scheme, allowed_methods, allowed_paths, requested_at"
)

# A grant is always read through its registration; alias the columns both tables share so the
# joined mapping stays unambiguous.
_GRANT_JOIN = (
    "SELECT g.id, g.status, g.mode AS grant_mode, g.purpose AS grant_purpose, "
    "g.audience AS grant_audience, g.granted_at, g.expires_at, "
    "r.credential, r.source_name, r.owner, r.audience, r.purpose, r.mode, r.delivery, "
    "r.environment_key, r.allowed_host, r.injection_header, r.injection_scheme, "
    "r.allowed_methods, r.allowed_paths, r.requested_at "
    "FROM credential_grant g JOIN credential_registration r USING (company_id, credential)"
)


class CredentialRepo:
    """Durable registrations, asks, grants, opaque leases, and the used-at trail."""

    def __init__(self, conn: LedgerConnection) -> None:
        self._conn = conn

    def register(self, registration: CredentialRegistration) -> None:
        """Upsert the org policy for ``registration.credential`` (policy only — no secret)."""
        self._conn.execute(
            f"INSERT INTO credential_registration ({_REGISTRATION_COLUMNS}) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (company_id, credential) DO UPDATE SET "
            "source_name = EXCLUDED.source_name, owner = EXCLUDED.owner, "
            "audience = EXCLUDED.audience, purpose = EXCLUDED.purpose, mode = EXCLUDED.mode, "
            "delivery = EXCLUDED.delivery, environment_key = EXCLUDED.environment_key, "
            "allowed_host = EXCLUDED.allowed_host, injection_header = EXCLUDED.injection_header, "
            "injection_scheme = EXCLUDED.injection_scheme, "
            "allowed_methods = EXCLUDED.allowed_methods, allowed_paths = EXCLUDED.allowed_paths, "
            "requested_at = EXCLUDED.requested_at",
            (
                registration.credential,
                registration.source_name,
                registration.owner,
                registration.audience,
                registration.purpose,
                registration.mode.value,
                registration.delivery.value,
                registration.environment_key,
                registration.allowed_host,
                registration.injection_header,
                registration.injection_scheme,
                dumps(list(registration.allowed_methods)),
                dumps(list(registration.allowed_path_prefixes)),
                to_iso(registration.requested_at),
            ),
        )
        self._conn.commit()

    def registration(self, credential: str) -> CredentialRegistration | None:
        row = self._conn.execute(
            f"SELECT {_REGISTRATION_COLUMNS} FROM credential_registration WHERE credential = ?",
            (credential,),
        ).fetchone()
        return _to_registration(row) if row is not None else None

    def standing_grant(
        self, credential: str, audience: str, now: datetime
    ) -> CredentialGrantView | None:
        """The live standing grant for this credential+audience, if one exists and has not expired."""
        row = self._conn.execute(
            f"{_GRANT_JOIN} "
            "WHERE g.credential = ? AND g.audience = ? AND g.mode = ? AND g.status = ? "
            "AND (g.expires_at IS NULL OR g.expires_at > ?)",
            (
                credential,
                audience,
                CredentialGrantMode.STANDING.value,
                CredentialGrantStatus.ACTIVE.value,
                to_iso(now),
            ),
        ).fetchone()
        return self._to_grant_view(row) if row is not None else None

    def create_ask(
        self,
        *,
        credential: str,
        audience: str,
        purpose: str,
        requested_at: datetime,
        expires_at: datetime,
    ) -> CredentialAsk:
        ask_id = mint_id()
        self._conn.execute(
            "INSERT INTO credential_ask "
            "(id, credential, audience, purpose, requested_at, expires_at, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                ask_id,
                credential,
                audience,
                purpose,
                to_iso(requested_at),
                to_iso(expires_at),
                CredentialAskStatus.PENDING.value,
            ),
        )
        self._conn.commit()
        return require_persisted(self.ask(ask_id), ask_id)

    def ask(self, ask_id: str) -> CredentialAsk | None:
        row = self._conn.execute(
            "SELECT id, credential, audience, purpose, requested_at, expires_at, status, grant_id "
            "FROM credential_ask WHERE id = ?",
            (ask_id,),
        ).fetchone()
        return _to_ask(row) if row is not None else None

    def approve(self, ask: CredentialAsk, mode: CredentialGrantMode, now: datetime) -> CredentialGrantView:
        """Open an active grant for a pending ask and mark the ask approved.

        Claiming the ask first makes approval exact-once: a second approval of the same ask finds
        no pending row and raises before anything is written, so it can never mint a second grant.
        """
        claimed = self._conn.execute(
            "UPDATE credential_ask SET status = ? WHERE id = ? AND status = ?",
            (
                CredentialAskStatus.APPROVED.value,
                ask.id,
                CredentialAskStatus.PENDING.value,
            ),
        )
        if cast(int, claimed.rowcount) != 1:
            raise PermissionError(f"credential ask {ask.id!r} is no longer pending")
        grant_id = mint_id()
        self._conn.execute(
            "INSERT INTO credential_grant "
            "(id, credential, audience, status, mode, purpose, granted_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, NULL)",
            (
                grant_id,
                ask.credential,
                ask.audience,
                CredentialGrantStatus.ACTIVE.value,
                mode.value,
                ask.purpose,
                to_iso(now),
            ),
        )
        self._conn.execute(
            "UPDATE credential_ask SET grant_id = ? WHERE id = ?",
            (grant_id, ask.id),
        )
        self._conn.commit()
        return require_persisted(self.grant(grant_id), grant_id)

    def grant(self, grant_id: str) -> CredentialGrantView | None:
        row = self._conn.execute(f"{_GRANT_JOIN} WHERE g.id = ?", (grant_id,)).fetchone()
        return self._to_grant_view(row) if row is not None else None

    def materialize(self, grant_id: str, session: str, now: datetime) -> CredentialLease:
        """Issue an opaque lease for one session and record the use; ``once`` grants burn here.

        The used-at trail keeps one row per grant+session (its primary key), so a session that
        materializes twice refreshes its timestamp rather than failing.
        """
        handle = f"lease:{secrets.token_urlsafe(32)}"
        self._conn.execute(
            "INSERT INTO credential_lease (handle, grant_id, session, issued_at) "
            "VALUES (?, ?, ?, ?)",
            (handle, grant_id, session, to_iso(now)),
        )
        self._conn.execute(
            "INSERT INTO credential_use (grant_id, session, used_at) VALUES (?, ?, ?) "
            "ON CONFLICT (company_id, grant_id, session) DO UPDATE SET used_at = EXCLUDED.used_at",
            (grant_id, session, to_iso(now)),
        )
        self._conn.execute(
            "UPDATE credential_grant SET status = ? WHERE id = ? AND mode = ?",
            (
                CredentialGrantStatus.USED.value,
                grant_id,
                CredentialGrantMode.ONCE.value,
            ),
        )
        self._conn.commit()
        return require_persisted(self.lease(handle), handle)

    def lease(self, handle: str) -> CredentialLease | None:
        row = self._conn.execute(
            "SELECT handle, grant_id, session, issued_at FROM credential_lease WHERE handle = ?",
            (handle,),
        ).fetchone()
        if row is None:
            return None
        return CredentialLease(
            handle=str(row["handle"]),
            grant_id=str(row["grant_id"]),
            session=str(row["session"]),
            issued_at=require_persisted(from_iso(str(row["issued_at"])), handle),
        )

    def revoke(self, grant_id: str) -> bool:
        cursor = self._conn.execute(
            "UPDATE credential_grant SET status = ? WHERE id = ? AND status = ?",
            (
                CredentialGrantStatus.REVOKED.value,
                grant_id,
                CredentialGrantStatus.ACTIVE.value,
            ),
        )
        self._conn.commit()
        return cast(int, cursor.rowcount) == 1

    def uses(self, grant_id: str) -> tuple[CredentialUse, ...]:
        rows = self._conn.execute(
            "SELECT session, used_at FROM credential_use WHERE grant_id = ? ORDER BY used_at",
            (grant_id,),
        ).fetchall()
        return tuple(
            CredentialUse(
                session=str(row["session"]),
                used_at=require_persisted(from_iso(str(row["used_at"])), grant_id),
            )
            for row in rows
        )

    def _to_grant_view(self, row: LedgerRow) -> CredentialGrantView:
        grant_id = str(row["id"])
        grant = CredentialGrant(
            id=grant_id,
            credential=str(row["credential"]),
            audience=str(row["grant_audience"]),
            mode=CredentialGrantMode(str(row["grant_mode"])),
            purpose=str(row["grant_purpose"]),
            granted_at=require_persisted(from_iso(str(row["granted_at"])), grant_id),
            status=CredentialGrantStatus(str(row["status"])),
            expires_at=from_iso(str(row["expires_at"])) if row["expires_at"] else None,
            uses=self.uses(grant_id),
        )
        return CredentialGrantView(grant=grant, registration=_to_registration(row))


def _json_list(value: object) -> list[object]:
    """Decode a jsonb list column whether the driver returned text or an already-parsed list."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return loads_list(str(value))


def _to_registration(row: LedgerRow) -> CredentialRegistration:
    credential = str(row["credential"])
    return CredentialRegistration(
        credential=credential,
        source_name=str(row["source_name"]),
        owner=str(row["owner"]),
        audience=str(row["audience"]),
        purpose=str(row["purpose"]),
        mode=CredentialGrantMode(str(row["mode"])),
        delivery=CredentialDelivery(str(row["delivery"])),
        requested_at=require_persisted(from_iso(str(row["requested_at"])), credential),
        environment_key=str(row["environment_key"]) if row["environment_key"] else None,
        allowed_host=str(row["allowed_host"]) if row["allowed_host"] else None,
        injection_header=str(row["injection_header"]),
        injection_scheme=str(row["injection_scheme"]),
        allowed_methods=tuple(str(value) for value in _json_list(row["allowed_methods"])),
        allowed_path_prefixes=tuple(str(value) for value in _json_list(row["allowed_paths"])),
    )


def _to_ask(row: LedgerRow) -> CredentialAsk:
    ask_id = str(row["id"])
    return CredentialAsk(
        id=ask_id,
        credential=str(row["credential"]),
        audience=str(row["audience"]),
        purpose=str(row["purpose"]),
        requested_at=require_persisted(from_iso(str(row["requested_at"])), ask_id),
        expires_at=require_persisted(from_iso(str(row["expires_at"])), ask_id),
        status=CredentialAskStatus(str(row["status"])),
        grant_id=str(row["grant_id"]) if row["grant_id"] else None,
    )


__all__ = ["CredentialRepo"]
