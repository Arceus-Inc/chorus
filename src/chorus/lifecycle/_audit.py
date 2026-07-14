"""Governance audit emission (spec 01 Cluster G ``activity``, spec 08 §5).

The ``activity`` table is the durable, queryable governance trail — distinct from the operational
event stream. :func:`record_activity` is the one writer the runtime calls so every audited transition
(decomposition, recovery, gate, hire/fire, approval) lands one immutable row.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from chorus.ids import mint_id
from chorus.ledger._models import Activity, ActivityVerb

if TYPE_CHECKING:
    from collections.abc import Mapping

    from chorus.ledger import SqliteLedger


def record_activity(
    ledger: SqliteLedger,
    *,
    verb: ActivityVerb,
    subject_id: str,
    subject_kind: str = "task",
    actor_employee_id: str | None = None,
    actor_user_id: str | None = None,
    actor_system_principal_id: str | None = None,
    payload: Mapping[str, Any] | None = None,
) -> None:
    """Append one immutable governance-audit row (spec 08 §5). Kernel actor when ``actor`` is null."""
    ledger.activity.append(
        Activity(
            id=mint_id("act"),
            verb=verb,
            subject_kind=subject_kind,
            subject_id=subject_id,
            actor_employee_id=actor_employee_id,
            actor_user_id=actor_user_id,
            actor_system_principal_id=actor_system_principal_id,
            payload=payload or {},
        )
    )


__all__ = ["record_activity"]
